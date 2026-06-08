"""Semantics validation and structural feature inference for advanced FSM families."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.difficulty import (
    compute_cycle_count,
    compute_strongly_connected_components,
    reachable_state_ids,
)
from fsmrepairbench.models import FSM, OracleSemanticsMode, OracleSuite, QUIESCENCE_EVENTS, REFUSAL_EVENTS

SemanticsMode = OracleSemanticsMode

SUPPORTED_SEMANTICS_MODES: tuple[SemanticsMode, ...] = (
    "deterministic",
    "nondeterministic_accepting",
    "probabilistic_threshold",
    "refusal_aware",
    "timed_discrete",
)

PROBABILITY_SUM_EPSILON = 1e-6


class SemanticsError(ValueError):
    """Raised when semantics validation fails."""


@dataclass(frozen=True)
class StructuralFeatures:
    """Inferred structural features for benchmark slicing."""

    has_nondeterminism: bool
    has_probabilities: bool
    has_cycles: bool
    has_refusals: bool
    has_discrete_time: bool
    cycle_count: int
    strongly_connected_component_count: int

    def to_dict(self) -> dict[str, bool | int]:
        return {
            "has_nondeterminism": self.has_nondeterminism,
            "has_probabilities": self.has_probabilities,
            "has_cycles": self.has_cycles,
            "has_refusals": self.has_refusals,
            "has_discrete_time": self.has_discrete_time,
            "cycle_count": self.cycle_count,
            "strongly_connected_component_count": self.strongly_connected_component_count,
        }


@dataclass(frozen=True)
class SemanticsIssue:
    """One semantics validation issue."""

    code: str
    message: str
    severity: Literal["error", "warning"] = "error"


@dataclass(frozen=True)
class SemanticsValidationReport:
    """Result of validating an FSM against a semantics mode."""

    fsm_id: str
    mode: SemanticsMode
    valid: bool
    structural_features: StructuralFeatures
    issues: tuple[SemanticsIssue, ...]
    rationale: str


def _transition_triple(transition) -> tuple[str, str, str | None]:
    return (transition.source, transition.event, transition.guard)


def _is_refusal_transition(transition) -> bool:
    return bool(
        transition.refusal
        or transition.event in REFUSAL_EVENTS
    )


def _is_quiescence_transition(transition) -> bool:
    return bool(
        transition.quiescence
        or transition.event in QUIESCENCE_EVENTS
    )


def _state_by_id(fsm: FSM) -> dict[str, object]:
    return {state.id: state for state in fsm.states}


def infer_structural_features(fsm: FSM) -> StructuralFeatures:
    """Infer nondeterministic, probabilistic, cyclic, refusal, and timed features."""
    reachable = reachable_state_ids(fsm)
    components = compute_strongly_connected_components(fsm, reachable)
    cycle_count = compute_cycle_count(fsm, reachable, components)
    scc_count = len(components)

    triples: dict[tuple[str, str, str | None], list[str]] = {}
    has_probabilities = False
    has_refusals = False
    has_discrete_time = fsm.discrete_time_step is not None

    states = _state_by_id(fsm)
    for state in fsm.states:
        if state.refusal or state.quiescence:
            has_refusals = True

    for transition in fsm.transitions:
        if transition.source not in reachable:
            continue
        triple = _transition_triple(transition)
        triples.setdefault(triple, []).append(transition.target)
        if transition.probability is not None:
            has_probabilities = True
        if transition.is_nondeterministic:
            pass
        if _is_refusal_transition(transition) or _is_quiescence_transition(transition):
            has_refusals = True
        if transition.discrete_time is not None:
            has_discrete_time = True
        target_state = states.get(transition.target)
        if target_state is not None and (target_state.refusal or target_state.quiescence):
            has_refusals = True

    duplicate_targets = False
    for triple, targets in triples.items():
        if len(set(targets)) <= 1:
            continue
        group = [
            transition
            for transition in fsm.transitions
            if transition.source in reachable and _transition_triple(transition) == triple
        ]
        probabilities = [transition.probability for transition in group]
        if all(probability is not None for probability in probabilities) and math.isclose(
            sum(probabilities),
            1.0,
            abs_tol=PROBABILITY_SUM_EPSILON,
        ):
            continue
        duplicate_targets = True
        break

    has_nondeterminism = duplicate_targets or any(
        transition.is_nondeterministic for transition in fsm.transitions
    )

    if fsm.cyclic_metadata is not None:
        cycle_count = fsm.cyclic_metadata.cycle_count
        scc_count = fsm.cyclic_metadata.strongly_connected_component_count

    return StructuralFeatures(
        has_nondeterminism=has_nondeterminism,
        has_probabilities=has_probabilities,
        has_cycles=cycle_count > 0,
        has_refusals=has_refusals,
        has_discrete_time=has_discrete_time,
        cycle_count=cycle_count,
        strongly_connected_component_count=scc_count,
    )


def _group_probabilities(fsm: FSM, reachable: set[str]) -> dict[tuple[str, str, str | None], list[float]]:
    groups: dict[tuple[str, str, str | None], list[float]] = {}
    for transition in fsm.transitions:
        if transition.source not in reachable:
            continue
        if transition.probability is None:
            continue
        key = _transition_triple(transition)
        groups.setdefault(key, []).append(transition.probability)
    return groups


def _validate_deterministic(fsm: FSM, reachable: set[str]) -> list[SemanticsIssue]:
    issues: list[SemanticsIssue] = []
    triples: dict[tuple[str, str, str | None], str] = {}
    for transition in fsm.transitions:
        if transition.source not in reachable:
            continue
        triple = _transition_triple(transition)
        if triple in triples:
            issues.append(
                SemanticsIssue(
                    code="duplicate_transition",
                    message=(
                        "Deterministic semantics forbid duplicate "
                        f"(source, event, guard) {triple}"
                    ),
                )
            )
        else:
            triples[triple] = transition.id
        if transition.is_nondeterministic:
            issues.append(
                SemanticsIssue(
                    code="nondeterministic_marker",
                    message=(
                        f"Transition '{transition.id}' is marked nondeterministic "
                        "under deterministic semantics"
                    ),
                )
            )
        if transition.probability is not None:
            issues.append(
                SemanticsIssue(
                    code="unexpected_probability",
                    message=(
                        f"Transition '{transition.id}' defines probability "
                        "under deterministic semantics"
                    ),
                    severity="warning",
                )
            )
    return issues


def _validate_nondeterministic_accepting(fsm: FSM, reachable: set[str]) -> list[SemanticsIssue]:
    issues: list[SemanticsIssue] = []
    features = infer_structural_features(fsm)
    if not features.has_nondeterminism:
        issues.append(
            SemanticsIssue(
                code="missing_nondeterminism",
                message="Nondeterministic-accepting semantics require ambiguous transitions",
            )
        )
    for transition in fsm.transitions:
        if transition.source in reachable and transition.probability is not None:
            issues.append(
                SemanticsIssue(
                    code="probability_with_nondeterminism",
                    message=(
                        f"Transition '{transition.id}' mixes probability with "
                        "nondeterministic-accepting semantics"
                    ),
                    severity="warning",
                )
            )
    return issues


def _validate_probabilistic_threshold(fsm: FSM, reachable: set[str]) -> list[SemanticsIssue]:
    issues: list[SemanticsIssue] = []
    features = infer_structural_features(fsm)
    if not features.has_probabilities:
        issues.append(
            SemanticsIssue(
                code="missing_probabilities",
                message="Probabilistic-threshold semantics require transition probabilities",
            )
        )

    groups = _group_probabilities(fsm, reachable)
    if not groups:
        return issues

    by_state_event: dict[tuple[str, str], list[tuple[str | None, float]]] = {}
    for transition in fsm.transitions:
        if transition.source not in reachable or transition.probability is None:
            continue
        bucket = by_state_event.setdefault((transition.source, transition.event), [])
        bucket.append((transition.guard, transition.probability))

    for (source, event), entries in by_state_event.items():
        total = sum(probability for _, probability in entries)
        if not math.isclose(total, 1.0, abs_tol=PROBABILITY_SUM_EPSILON):
            issues.append(
                SemanticsIssue(
                    code="probability_sum",
                    message=(
                        f"Outgoing probabilities for ({source}, {event}) "
                        f"sum to {total:.6f}, expected 1.0"
                    ),
                )
            )
        for guard, probability in entries:
            if probability < 0.0 or probability > 1.0:
                issues.append(
                    SemanticsIssue(
                        code="probability_range",
                        message=(
                            f"Invalid probability {probability} for ({source}, {event}, {guard})"
                        ),
                    )
                )
    return issues


def _validate_refusal_aware(fsm: FSM, reachable: set[str]) -> list[SemanticsIssue]:
    issues: list[SemanticsIssue] = []
    features = infer_structural_features(fsm)
    if not features.has_refusals:
        issues.append(
            SemanticsIssue(
                code="missing_refusal_features",
                message=(
                    "Refusal-aware semantics require refusal or quiescence markers "
                    "on states, transitions, or special events"
                ),
            )
        )
    for transition in fsm.transitions:
        if transition.source not in reachable:
            continue
        if transition.refusal and transition.quiescence:
            issues.append(
                SemanticsIssue(
                    code="conflicting_markers",
                    message=(
                        f"Transition '{transition.id}' cannot be both refusal and quiescence"
                    ),
                )
            )
    return issues


def _validate_timed_discrete(fsm: FSM, reachable: set[str]) -> list[SemanticsIssue]:
    issues: list[SemanticsIssue] = []
    features = infer_structural_features(fsm)
    if not features.has_discrete_time:
        issues.append(
            SemanticsIssue(
                code="missing_discrete_time",
                message=(
                    "Timed-discrete semantics require FSM.discrete_time_step or "
                    "transition.discrete_time markers"
                ),
            )
        )

    seen_steps: set[int] = set()
    for transition in fsm.transitions:
        if transition.source not in reachable or transition.discrete_time is None:
            continue
        if transition.discrete_time in seen_steps:
            issues.append(
                SemanticsIssue(
                    code="duplicate_discrete_time",
                    message=(
                        f"Duplicate discrete time step {transition.discrete_time} "
                        f"on transition '{transition.id}'"
                    ),
                    severity="warning",
                )
            )
        seen_steps.add(transition.discrete_time)
        if transition.timeout is not None and fsm.discrete_time_step is not None:
            if transition.timeout % fsm.discrete_time_step != 0:
                issues.append(
                    SemanticsIssue(
                        code="timeout_step_mismatch",
                        message=(
                            f"Transition '{transition.id}' timeout is not aligned "
                            "with discrete_time_step"
                        ),
                        severity="warning",
                    )
                )
    return issues


def _validate_oracle_for_mode(fsm: FSM, suite: OracleSuite, mode: SemanticsMode) -> list[SemanticsIssue]:
    issues: list[SemanticsIssue] = []
    if suite.semantics_mode is not None and suite.semantics_mode != mode:
        issues.append(
            SemanticsIssue(
                code="oracle_mode_mismatch",
                message=(
                    f"Oracle semantics_mode '{suite.semantics_mode}' "
                    f"does not match requested mode '{mode}'"
                ),
                severity="warning",
            )
        )

    for scenario in suite.scenarios:
        for step_index, step in enumerate(scenario.steps):
            if mode == "nondeterministic_accepting" and step.accepting_states:
                if step.expected_state not in step.accepting_states:
                    issues.append(
                        SemanticsIssue(
                            code="accepting_states",
                            message=(
                                f"Scenario '{scenario.id}' step {step_index}: expected_state "
                                "must belong to accepting_states"
                            ),
                        )
                    )
            if mode == "probabilistic_threshold":
                threshold = step.probability_threshold or suite.probability_threshold
                if threshold is None:
                    issues.append(
                        SemanticsIssue(
                            code="missing_probability_threshold",
                            message=(
                                f"Scenario '{scenario.id}' step {step_index} requires "
                                "probability_threshold under probabilistic semantics"
                            ),
                            severity="warning",
                        )
                    )
            if mode == "refusal_aware":
                if step.refusal_expected and step.quiescence_expected:
                    issues.append(
                        SemanticsIssue(
                            code="refusal_quiescence_conflict",
                            message=(
                                f"Scenario '{scenario.id}' step {step_index} cannot expect "
                                "both refusal and quiescence"
                            ),
                        )
                    )
            if mode == "timed_discrete" and step.discrete_time is None:
                issues.append(
                    SemanticsIssue(
                        code="missing_step_discrete_time",
                        message=(
                            f"Scenario '{scenario.id}' step {step_index} requires discrete_time"
                        ),
                        severity="warning",
                    )
                )
    return issues


def validate_semantics(
    fsm: FSM,
    *,
    mode: SemanticsMode,
    oracle_suite: OracleSuite | None = None,
) -> SemanticsValidationReport:
    """Validate *fsm* (and optional *oracle_suite*) against *mode*."""
    if mode not in SUPPORTED_SEMANTICS_MODES:
        msg = f"Unknown semantics mode '{mode}'. Supported: {', '.join(SUPPORTED_SEMANTICS_MODES)}"
        raise SemanticsError(msg)

    reachable = reachable_state_ids(fsm)
    structural_features = infer_structural_features(fsm)
    issues: list[SemanticsIssue] = []

    if mode == "deterministic":
        issues.extend(_validate_deterministic(fsm, reachable))
    elif mode == "nondeterministic_accepting":
        issues.extend(_validate_nondeterministic_accepting(fsm, reachable))
    elif mode == "probabilistic_threshold":
        issues.extend(_validate_probabilistic_threshold(fsm, reachable))
    elif mode == "refusal_aware":
        issues.extend(_validate_refusal_aware(fsm, reachable))
    elif mode == "timed_discrete":
        issues.extend(_validate_timed_discrete(fsm, reachable))

    if oracle_suite is not None:
        issues.extend(_validate_oracle_for_mode(fsm, oracle_suite, mode))

    errors = [issue for issue in issues if issue.severity == "error"]
    valid = not errors
    if valid:
        rationale = f"FSM '{fsm.id}' satisfies {mode} semantics."
    else:
        rationale = "; ".join(issue.message for issue in errors)

    return SemanticsValidationReport(
        fsm_id=fsm.id,
        mode=mode,
        valid=valid,
        structural_features=structural_features,
        issues=tuple(issues),
        rationale=rationale,
    )


def semantics_report_to_dict(report: SemanticsValidationReport) -> dict[str, object]:
    """Convert a semantics validation report to JSON-serialisable data."""
    return {
        "fsm_id": report.fsm_id,
        "mode": report.mode,
        "valid": report.valid,
        "structural_features": report.structural_features.to_dict(),
        "issues": [
            {
                "code": issue.code,
                "message": issue.message,
                "severity": issue.severity,
            }
            for issue in report.issues
        ],
        "rationale": report.rationale,
    }


def write_semantics_report_json(path: Path, report: SemanticsValidationReport) -> None:
    """Write a semantics validation report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(semantics_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def enrich_cyclic_metadata(fsm: FSM) -> FSM:
    """Attach inferred cyclic metadata to *fsm* when absent."""
    if fsm.cyclic_metadata is not None:
        return fsm
    features = infer_structural_features(fsm)
    return fsm.model_copy(
        update={
            "cyclic_metadata": {
                "cycle_count": features.cycle_count,
                "strongly_connected_component_count": features.strongly_connected_component_count,
                "is_cyclic": features.has_cycles,
            }
        }
    )
