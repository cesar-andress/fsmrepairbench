"""Partition and participation metrics shared by extension studies."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.dataset_builder import load_dataset_cases, resolve_coupling_case_file
from fsmrepairbench.localization_localizability_audit import classify_ground_truth_localizability
from fsmrepairbench.models import BugMetadata, FSM
from fsmrepairbench.oracle_surface import (
    OracleSurfaceProfile,
    PROGRESSIVE_SURFACE_ORDER,
    SURFACE_PROFILES,
    case_detected,
    case_saturated,
    execute_scenario_with_surface,
    score_oracle_suite_with_surface,
)
from fsmrepairbench.sbfl_coefficient_comparison import target_transition_spectrum_counts
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite


@dataclass(frozen=True)
class CohortPartitionMetrics:
    case_count: int
    detection_rate: float
    saturation_rate: float
    detectable_count: int
    saturated_count: int
    structural_gt_count: int
    spectrally_participating_count: int
    spectrally_absent_count: int
    participation_rate: float


@dataclass(frozen=True)
class RepairPartitionMetrics:
    cohort_wide_crr: float
    detectable_only_crr: float
    saturation_inflation_pp: float
    detectable_count: int
    cohort_count: int


@dataclass(frozen=True)
class SurfaceLevelMetrics:
    surface_id: str
    surface_label: str
    visible_fields: str
    partition: CohortPartitionMetrics
    repair: RepairPartitionMetrics | None = None


def _load_bug_metadata(case_dir: Path) -> BugMetadata | None:
    path = case_dir / "bug_metadata.json"
    if not path.is_file():
        return None
    return BugMetadata.model_validate(json.loads(path.read_text(encoding="utf-8")))


def _structural_gt_count(dataset_dir: Path, detectable_case_ids: set[str]) -> tuple[int, int, int]:
    participating = 0
    absent = 0
    structural = 0
    for case_id in sorted(detectable_case_ids):
        case_dir = dataset_dir / "cases" / case_id
        metadata = _load_bug_metadata(case_dir)
        if metadata is None:
            continue
        faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
        transition_ids: frozenset[str] = frozenset()
        if faulty_path is not None and faulty_path.is_file():
            faulty = load_fsm_json(faulty_path)
            transition_ids = frozenset(transition.id for transition in faulty.transitions)
        _, localizable, _ = classify_ground_truth_localizability(
            mutation_operator=metadata.mutation_operator,
            changed_transition_id=metadata.changed_transition_id,
            faulty_transition_ids=transition_ids,
        )
        if not localizable:
            continue
        structural += 1
        target = (metadata.changed_transition_id or "").strip()
        ef, ep = target_transition_spectrum_counts(case_dir, target=target)
        if ef + ep > 0:
            participating += 1
        else:
            absent += 1
    return structural, participating, absent


def compute_partition_metrics_from_index(dataset_dir: Path) -> CohortPartitionMetrics:
    """Compute published-oracle partition metrics from a built dataset index."""
    cases = load_dataset_cases(dataset_dir)
    total = len(cases)
    detectable_ids: set[str] = set()
    saturated = 0
    for case in cases:
        if case_saturated(case.faulty_bpr):
            saturated += 1
        if case_detected(case.reference_bpr, case.faulty_bpr):
            detectable_ids.add(case.case_id)
    structural, participating, absent = _structural_gt_count(dataset_dir, detectable_ids)
    participation_rate = participating / structural if structural else 0.0
    return CohortPartitionMetrics(
        case_count=total,
        detection_rate=round(len(detectable_ids) / total, 6) if total else 0.0,
        saturation_rate=round(saturated / total, 6) if total else 0.0,
        detectable_count=len(detectable_ids),
        saturated_count=saturated,
        structural_gt_count=structural,
        spectrally_participating_count=participating,
        spectrally_absent_count=absent,
        participation_rate=round(participation_rate, 6),
    )


def compute_partition_metrics_for_surface(
    dataset_dir: Path,
    case_ids: list[str],
    profile: OracleSurfaceProfile,
) -> CohortPartitionMetrics:
    """Rescore *case_ids* under *profile* and return partition metrics."""
    cases_root = dataset_dir / "cases"
    detectable_ids: set[str] = set()
    saturated = 0
    total = len(case_ids)
    for case_id in case_ids:
        case_dir = cases_root / case_id
        reference = load_fsm_json(case_dir / "reference_fsm.json")
        faulty = load_fsm_json(case_dir / "faulty_fsm.json")
        oracle = load_oracle_suite(case_dir / "oracle_suite.json")
        reference_bpr = score_oracle_suite_with_surface(
            reference,
            oracle,
            reference=reference,
            profile=profile,
        ).bpr
        faulty_bpr = score_oracle_suite_with_surface(
            faulty,
            oracle,
            reference=reference,
            profile=profile,
        ).bpr
        if case_saturated(faulty_bpr):
            saturated += 1
        if case_detected(reference_bpr, faulty_bpr):
            detectable_ids.add(case_id)
    structural, participating, absent = _structural_gt_count(dataset_dir, detectable_ids)
    participation_rate = participating / structural if structural else 0.0
    return CohortPartitionMetrics(
        case_count=total,
        detection_rate=round(len(detectable_ids) / total, 6) if total else 0.0,
        saturation_rate=round(saturated / total, 6) if total else 0.0,
        detectable_count=len(detectable_ids),
        saturated_count=saturated,
        structural_gt_count=structural,
        spectrally_participating_count=participating,
        spectrally_absent_count=absent,
        participation_rate=round(participation_rate, 6),
    )


def collect_surface_spectra_participation(
    case_dir: Path,
    *,
    reference: FSM,
    profile: OracleSurfaceProfile,
    target: str,
) -> tuple[int, int]:
    """Count failing/passing scenario covers for *target* under a surface-aware pass rule."""
    from fsmrepairbench.oracle import trace_scenario_transitions

    faulty = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle = load_oracle_suite(case_dir / "oracle_suite.json")
    semantics_mode = oracle.semantics_mode or faulty.semantics_mode
    ef = 0
    ep = 0
    for scenario in oracle.scenarios:
        passed, _, _ = execute_scenario_with_surface(
            faulty,
            scenario,
            reference=reference,
            profile=profile,
            semantics_mode=semantics_mode,
        )
        if target not in trace_scenario_transitions(faulty, scenario, semantics_mode=semantics_mode):
            continue
        if passed:
            ep += 1
        else:
            ef += 1
    return ef, ep


def compute_surface_participation_metrics(
    dataset_dir: Path,
    case_ids: list[str],
    profile: OracleSurfaceProfile,
) -> tuple[int, int, int, float]:
    """Return structural GT, participating, absent counts under surface-aware spectra."""
    participating = 0
    absent = 0
    structural = 0
    cases_root = dataset_dir / "cases"
    for case_id in case_ids:
        case_dir = cases_root / case_id
        metadata = _load_bug_metadata(case_dir)
        if metadata is None:
            continue
        reference = load_fsm_json(case_dir / "reference_fsm.json")
        faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
        transition_ids: frozenset[str] = frozenset()
        if faulty_path is not None and faulty_path.is_file():
            faulty = load_fsm_json(faulty_path)
            transition_ids = frozenset(transition.id for transition in faulty.transitions)
        _, localizable, _ = classify_ground_truth_localizability(
            mutation_operator=metadata.mutation_operator,
            changed_transition_id=metadata.changed_transition_id,
            faulty_transition_ids=transition_ids,
        )
        if not localizable:
            continue
        structural += 1
        target = (metadata.changed_transition_id or "").strip()
        ef, ep = collect_surface_spectra_participation(
            case_dir,
            reference=reference,
            profile=profile,
            target=target,
        )
        if ef + ep > 0:
            participating += 1
        else:
            absent += 1
    rate = participating / structural if structural else 0.0
    return structural, participating, absent, rate


def compute_repair_metrics_for_surface(
    dataset_dir: Path,
    case_ids: list[str],
    profile: OracleSurfaceProfile,
    patched_by_case: dict[str, FSM],
) -> RepairPartitionMetrics:
    """Rescore random-baseline patches under *profile*."""
    cases_root = dataset_dir / "cases"
    cohort_complete = 0
    detectable_complete = 0
    detectable = 0
    for case_id in case_ids:
        if case_id not in patched_by_case:
            continue
        case_dir = cases_root / case_id
        reference = load_fsm_json(case_dir / "reference_fsm.json")
        faulty = load_fsm_json(case_dir / "faulty_fsm.json")
        oracle = load_oracle_suite(case_dir / "oracle_suite.json")
        patched = patched_by_case[case_id]
        initial_bpr = score_oracle_suite_with_surface(
            faulty,
            oracle,
            reference=reference,
            profile=profile,
        ).bpr
        final_bpr = score_oracle_suite_with_surface(
            patched,
            oracle,
            reference=reference,
            profile=profile,
        ).bpr
        if final_bpr >= 1.0 - 1e-9:
            cohort_complete += 1
        if case_detected(
            score_oracle_suite_with_surface(reference, oracle, reference=reference, profile=profile).bpr,
            initial_bpr,
        ):
            detectable += 1
            if final_bpr >= 1.0 - 1e-9:
                detectable_complete += 1
    cohort_count = len(case_ids)
    cohort_wide = cohort_complete / cohort_count if cohort_count else 0.0
    detectable_only = detectable_complete / detectable if detectable else 0.0
    inflation = (cohort_wide - detectable_only) * 100.0
    return RepairPartitionMetrics(
        cohort_wide_crr=round(cohort_wide, 6),
        detectable_only_crr=round(detectable_only, 6),
        saturation_inflation_pp=round(inflation, 6),
        detectable_count=detectable,
        cohort_count=cohort_count,
    )


def progressive_surface_ids() -> tuple[str, ...]:
    return tuple(surface.value for surface in PROGRESSIVE_SURFACE_ORDER)


def surface_profile_for(surface_id: str) -> OracleSurfaceProfile:
    for surface in PROGRESSIVE_SURFACE_ORDER:
        if surface.value == surface_id:
            return SURFACE_PROFILES[surface]
    msg = f"Unknown surface id: {surface_id}"
    raise ValueError(msg)
