"""Specification-based coverage criteria for FSM oracle suites."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.models import FSM, OracleScenario, OracleSuite, Transition
from fsmrepairbench.oracle import trace_scenario_transitions
from fsmrepairbench.oracle_generator import reachable_state_ids
from fsmrepairbench.taxonomy import MachineType, infer_machine_type


@dataclass(frozen=True)
class CoverageCriterion:
    """One specification-based coverage criterion."""

    name: str
    covered: int
    total: int
    coverage: float
    covered_items: tuple[str, ...]


@dataclass(frozen=True)
class CoverageReport:
    """Coverage report for an FSM evaluated against an oracle suite."""

    fsm_id: str
    oracle_suite_id: str
    machine_type: MachineType
    sequence_depth: int
    state: CoverageCriterion
    transition: CoverageCriterion
    transition_pair: CoverageCriterion
    transition_sequence: CoverageCriterion
    guard: CoverageCriterion | None
    timeout: CoverageCriterion | None


def _ratio(covered: int, total: int) -> float:
    if total <= 0:
        return 1.0
    return covered / total


def _reachable_transitions(fsm: FSM) -> list[Transition]:
    reachable = reachable_state_ids(fsm)
    return [transition for transition in fsm.transitions if transition.source in reachable]


def _trace_scenario_states(fsm: FSM, scenario: OracleScenario) -> list[str]:
    states = [fsm.initial_state]
    current_state = fsm.initial_state
    for step in scenario.steps:
        matched: Transition | None = None
        for transition in fsm.transitions:
            if transition.source != current_state:
                continue
            if transition.event != step.event:
                continue
            if step.guard != transition.guard:
                continue
            matched = transition
            break
        if matched is None:
            break
        current_state = matched.target
        states.append(current_state)
        if current_state != step.expected_state:
            break
    return states


def _collect_transition_paths(suite: OracleSuite, fsm: FSM) -> list[list[str]]:
    return [trace_scenario_transitions(fsm, scenario) for scenario in suite.scenarios]


def _adjacent_pairs(path: Iterable[str]) -> set[tuple[str, str]]:
    ordered = list(path)
    return {(left, right) for left, right in zip(ordered, ordered[1:], strict=False)}


def _sequence_set(paths: Iterable[list[str]], *, max_length: int) -> set[tuple[str, ...]]:
    sequences: set[tuple[str, ...]] = set()
    for path in paths:
        for length in range(1, min(max_length, len(path)) + 1):
            for start in range(len(path) - length + 1):
                sequences.add(tuple(path[start : start + length]))
    return sequences


def _all_feasible_sequences(fsm: FSM, *, max_length: int) -> set[tuple[str, ...]]:
    sequences: set[tuple[str, ...]] = set()
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(fsm.initial_state, ())])

    while queue:
        state, path = queue.popleft()
        if path:
            sequences.add(path)
        if len(path) >= max_length:
            continue
        for transition in _reachable_transitions(fsm):
            if transition.source != state:
                continue
            next_path = path + (transition.id,)
            sequences.add(next_path)
            queue.append((transition.target, next_path))

    return sequences


def _all_feasible_adjacent_pairs(fsm: FSM, *, max_length: int) -> set[tuple[str, str]]:
    pairs: set[tuple[str, str]] = set()
    for sequence in _all_feasible_sequences(fsm, max_length=max_length):
        pairs.update(_adjacent_pairs(sequence))
    return pairs


def _guarded_transitions(fsm: FSM) -> list[Transition]:
    return [
        transition
        for transition in _reachable_transitions(fsm)
        if transition.guard is not None and transition.guard.strip()
    ]


def _timed_transitions(fsm: FSM) -> list[Transition]:
    return [
        transition
        for transition in _reachable_transitions(fsm)
        if transition.timeout is not None
    ]


def compute_coverage_report(
    fsm: FSM,
    suite: OracleSuite,
    *,
    sequence_depth: int = 3,
) -> CoverageReport:
    """Compute specification-based coverage criteria for *suite* over *fsm*."""
    if sequence_depth < 1:
        msg = "sequence_depth must be at least 1"
        raise ValueError(msg)

    reachable_states = reachable_state_ids(fsm)
    reachable_transition_ids = {transition.id for transition in _reachable_transitions(fsm)}
    paths = _collect_transition_paths(suite, fsm)

    covered_states: set[str] = set()
    for scenario in suite.scenarios:
        covered_states.update(_trace_scenario_states(fsm, scenario))
    covered_states &= reachable_states

    covered_transitions: set[str] = set()
    covered_pairs: set[tuple[str, str]] = set()
    for path in paths:
        covered_transitions.update(path)
        covered_pairs.update(_adjacent_pairs(path))
    covered_transitions &= reachable_transition_ids

    covered_sequences = _sequence_set(paths, max_length=sequence_depth)
    total_sequences = _all_feasible_sequences(fsm, max_length=sequence_depth)
    covered_sequences &= total_sequences
    total_pairs = _all_feasible_adjacent_pairs(fsm, max_length=sequence_depth)
    covered_pairs &= total_pairs

    guarded = _guarded_transitions(fsm)
    guarded_ids = {transition.id for transition in guarded}
    covered_guard_ids = covered_transitions & guarded_ids
    guard_criterion: CoverageCriterion | None = None
    if guarded_ids:
        guard_criterion = CoverageCriterion(
            name="guard",
            covered=len(covered_guard_ids),
            total=len(guarded_ids),
            coverage=_ratio(len(covered_guard_ids), len(guarded_ids)),
            covered_items=tuple(sorted(covered_guard_ids)),
        )

    timed = _timed_transitions(fsm)
    timed_ids = {transition.id for transition in timed}
    covered_timed_ids = covered_transitions & timed_ids
    timeout_criterion: CoverageCriterion | None = None
    if timed_ids:
        timeout_criterion = CoverageCriterion(
            name="timeout",
            covered=len(covered_timed_ids),
            total=len(timed_ids),
            coverage=_ratio(len(covered_timed_ids), len(timed_ids)),
            covered_items=tuple(sorted(covered_timed_ids)),
        )

    return CoverageReport(
        fsm_id=fsm.id,
        oracle_suite_id=suite.id,
        machine_type=infer_machine_type(fsm),
        sequence_depth=sequence_depth,
        state=CoverageCriterion(
            name="state",
            covered=len(covered_states),
            total=len(reachable_states),
            coverage=_ratio(len(covered_states), len(reachable_states)),
            covered_items=tuple(sorted(covered_states)),
        ),
        transition=CoverageCriterion(
            name="transition",
            covered=len(covered_transitions),
            total=len(reachable_transition_ids),
            coverage=_ratio(len(covered_transitions), len(reachable_transition_ids)),
            covered_items=tuple(sorted(covered_transitions)),
        ),
        transition_pair=CoverageCriterion(
            name="transition_pair",
            covered=len(covered_pairs),
            total=len(total_pairs),
            coverage=_ratio(len(covered_pairs), len(total_pairs)),
            covered_items=tuple(
                sorted(f"{left}->{right}" for left, right in covered_pairs)
            ),
        ),
        transition_sequence=CoverageCriterion(
            name="transition_sequence",
            covered=len(covered_sequences),
            total=len(total_sequences),
            coverage=_ratio(len(covered_sequences), len(total_sequences)),
            covered_items=tuple("->".join(sequence) for sequence in sorted(covered_sequences)),
        ),
        guard=guard_criterion,
        timeout=timeout_criterion,
    )


def _criterion_to_dict(criterion: CoverageCriterion) -> dict[str, object]:
    return {
        "name": criterion.name,
        "covered": criterion.covered,
        "total": criterion.total,
        "coverage": criterion.coverage,
        "covered_items": list(criterion.covered_items),
    }


def coverage_report_to_dict(report: CoverageReport) -> dict[str, object]:
    """Convert a coverage report to a JSON-serialisable mapping."""
    criteria: dict[str, object] = {
        "state": _criterion_to_dict(report.state),
        "transition": _criterion_to_dict(report.transition),
        "transition_pair": _criterion_to_dict(report.transition_pair),
        "transition_sequence": _criterion_to_dict(report.transition_sequence),
    }
    if report.guard is not None:
        criteria["guard"] = _criterion_to_dict(report.guard)
    if report.timeout is not None:
        criteria["timeout"] = _criterion_to_dict(report.timeout)

    return {
        "fsm_id": report.fsm_id,
        "oracle_suite_id": report.oracle_suite_id,
        "machine_type": report.machine_type.value,
        "sequence_depth": report.sequence_depth,
        "criteria": criteria,
    }


def write_coverage_json(path: Path, report: CoverageReport) -> None:
    """Write *report* as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(coverage_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
