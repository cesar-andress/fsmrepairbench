"""Alternative ground-truth definitions for RQ3 transition-level localization edge cases."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.localization_campaign import (
    CaseLocalizationResult,
    ranked_transition_ids,
    transition_localization_metrics,
)
from fsmrepairbench.models import BugMetadata, FSM, Transition
from fsmrepairbench.smoke_test_pipeline import infer_injected_fault_elements
from fsmrepairbench.validators import load_fsm_json

AlternativeGtMode = Literal[
    "primary",
    "deleted_transition_proxy",
    "initial_state_outgoing",
]

OPERATORS_WITH_ALTERNATIVE_GT: frozenset[str] = frozenset(
    {"missing_transition", "wrong_initial_state"}
)


@dataclass(frozen=True)
class AlternativeGtEvaluation:
    """Localization outcome under one ground-truth definition."""

    gt_mode: AlternativeGtMode
    gt_targets: tuple[str, ...]
    rank_of_target: int | None
    reciprocal_rank: float
    top1_hit: bool
    top3_hit: bool
    top5_hit: bool

    def to_dict(self) -> dict[str, str | int | float | bool]:
        return {
            "alternative_gt_mode": self.gt_mode,
            "alternative_gt_targets": ";".join(self.gt_targets),
            "alternative_rank_of_target": self.rank_of_target if self.rank_of_target is not None else "",
            "alternative_reciprocal_rank": round(self.reciprocal_rank, 6),
            "alternative_top1_hit": self.top1_hit,
            "alternative_top3_hit": self.top3_hit,
            "alternative_top5_hit": self.top5_hit,
        }


def _transition_by_id(fsm: FSM, transition_id: str) -> Transition | None:
    for transition in fsm.transitions:
        if transition.id == transition_id:
            return transition
    return None


def _dedupe_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def resolve_deleted_transition_proxy_targets(
    *,
    deleted_transition_id: str,
    reference: FSM,
    faulty: FSM,
) -> list[str]:
    """Proxy GT for ``missing_transition``: rankable transitions near the deletion site."""
    faulty_ids = {transition.id for transition in faulty.transitions}
    proxies: list[str] = []

    deleted = _transition_by_id(reference, deleted_transition_id)
    if deleted is not None:
        for transition in faulty.transitions:
            if transition.source == deleted.source and transition.event == deleted.event:
                proxies.append(transition.id)
            if transition.target == deleted.source:
                proxies.append(transition.id)
            if transition.source == deleted.target:
                proxies.append(transition.id)

    for element_type, element_id in infer_injected_fault_elements(reference, faulty):
        if element_type == "transition" and element_id in faulty_ids:
            proxies.append(element_id)

    return _dedupe_preserve_order(proxies)


def resolve_initial_state_outgoing_targets(*, faulty: FSM) -> list[str]:
    """Proxy GT for ``wrong_initial_state``: outgoing transitions from the faulty initial state."""
    return _dedupe_preserve_order(
        [
            transition.id
            for transition in faulty.transitions
            if transition.source == faulty.initial_state
        ]
    )


def resolve_alternative_gt_targets(
    *,
    mutation_operator: str,
    changed_transition_id: str | None,
    reference: FSM,
    faulty: FSM,
) -> tuple[AlternativeGtMode, tuple[str, ...]]:
    """Return alternative GT mode and target transition IDs when applicable."""
    if mutation_operator == "missing_transition":
        deleted_id = (changed_transition_id or "").strip()
        if not deleted_id:
            return "primary", ()
        proxies = resolve_deleted_transition_proxy_targets(
            deleted_transition_id=deleted_id,
            reference=reference,
            faulty=faulty,
        )
        return "deleted_transition_proxy", tuple(proxies)

    if mutation_operator == "wrong_initial_state":
        outgoing = resolve_initial_state_outgoing_targets(faulty=faulty)
        return "initial_state_outgoing", tuple(outgoing)

    primary = (changed_transition_id or "").strip()
    return "primary", ((primary,) if primary else ())


def multi_target_localization_metrics(
    targets: list[str],
    ranked_transition_ids: list[str],
) -> tuple[int | None, float, bool, bool, bool]:
    """Compute best-rank top-k metrics when any *targets* appear in the ranking."""
    ranks = [
        ranked_transition_ids.index(target) + 1
        for target in targets
        if target and target in ranked_transition_ids
    ]
    if not ranks:
        return None, 0.0, False, False, False
    best_rank = min(ranks)
    reciprocal = 1.0 / best_rank
    return (
        best_rank,
        reciprocal,
        best_rank == 1,
        best_rank <= 3,
        best_rank <= 5,
    )


def evaluate_alternative_gt(
    *,
    mutation_operator: str,
    changed_transition_id: str,
    ranked_transition_ids: list[str],
    reference: FSM,
    faulty: FSM,
) -> AlternativeGtEvaluation:
    """Evaluate localization under primary or operator-specific alternative GT."""
    gt_mode, gt_targets = resolve_alternative_gt_targets(
        mutation_operator=mutation_operator,
        changed_transition_id=changed_transition_id or None,
        reference=reference,
        faulty=faulty,
    )
    if gt_mode == "primary":
        rank, reciprocal, top1, top3, top5 = transition_localization_metrics(
            changed_transition_id,
            ranked_transition_ids,
        )
    else:
        rank, reciprocal, top1, top3, top5 = multi_target_localization_metrics(
            list(gt_targets),
            ranked_transition_ids,
        )
    return AlternativeGtEvaluation(
        gt_mode=gt_mode,
        gt_targets=gt_targets,
        rank_of_target=rank,
        reciprocal_rank=reciprocal,
        top1_hit=top1,
        top3_hit=top3,
        top5_hit=top5,
    )


def load_case_fsms(case_dir: Path) -> tuple[FSM, FSM] | None:
    """Load reference and faulty FSMs for one benchmark case directory."""
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    if reference_path is None or faulty_path is None:
        return None
    if not reference_path.is_file() or not faulty_path.is_file():
        return None
    return load_fsm_json(reference_path), load_fsm_json(faulty_path)


def ranked_transitions_for_case(case_dir: Path) -> list[str]:
    """Re-run Ochiai localization and return ranked transition IDs for one case."""
    from fsmrepairbench.localization_campaign import ochiai_ranked_transition_ids

    return ochiai_ranked_transition_ids(case_dir) or []


def enrich_case_with_alternative_gt(
    case_dir: Path,
    case: CaseLocalizationResult,
) -> AlternativeGtEvaluation | None:
    """Compute alternative-GT metrics for one localized case."""
    if not case.localized:
        return None

    fsms = load_case_fsms(case_dir)
    if fsms is None:
        return None
    reference, faulty = fsms
    metadata_path = case_dir / "bug_metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = BugMetadata.model_validate(
        __import__("json").loads(metadata_path.read_text(encoding="utf-8"))
    )
    ranked_ids = ranked_transitions_for_case(case_dir)
    if not ranked_ids:
        return None

    return evaluate_alternative_gt(
        mutation_operator=metadata.mutation_operator,
        changed_transition_id=case.changed_transition_id,
        ranked_transition_ids=ranked_ids,
        reference=reference,
        faulty=faulty,
    )
