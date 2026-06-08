"""Specification-based coverage metrics for FSM oracle suites."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from itertools import combinations

from fsmrepairbench.models import FSM, OracleSuite, Transition
from fsmrepairbench.oracle import trace_scenario_transitions
from fsmrepairbench.taxonomy import MachineType, infer_machine_type

SPEC_COVERAGE_CSV_COLUMNS: tuple[str, ...] = (
    "metric",
    "covered",
    "total",
    "coverage",
    "machine_type",
)


@dataclass(frozen=True)
class TransitionSequenceCoverage:
    """Coverage of transition sequences up to a fixed length."""

    max_length: int
    covered_sequences: tuple[tuple[str, ...], ...]
    total_sequences: int
    coverage: float


@dataclass(frozen=True)
class SpecCoverageReport:
    """Specification-based coverage summary for an FSM and oracle suite."""

    machine_type: MachineType
    transition_coverage: float
    transition_pair_coverage: float
    sequence_coverage: float
    covered_transitions: tuple[str, ...]
    covered_transition_pairs: tuple[tuple[str, str], ...]
    covered_sequences: tuple[tuple[str, ...], ...]
    total_transitions: int
    total_transition_pairs: int
    total_sequences: int
    efsm_guard_transition_coverage: float | None
    timed_transition_coverage: float | None
    max_sequence_length: int


def _all_transition_ids(fsm: FSM) -> tuple[str, ...]:
    return tuple(transition.id for transition in fsm.transitions)


def _all_transition_pairs(transition_ids: Iterable[str]) -> set[tuple[str, str]]:
    ordered = tuple(transition_ids)
    return {(left, right) for left, right in combinations(ordered, 2)}


def _is_efsm_transition(transition: Transition, fsm: FSM) -> bool:
    return bool(transition.guard) or bool(fsm.variables)


def _is_timed_transition(transition: Transition) -> bool:
    return transition.timeout is not None or transition.delay is not None


def _collect_executed_paths(suite: OracleSuite, fsm: FSM) -> list[list[str]]:
    return [trace_scenario_transitions(fsm, scenario) for scenario in suite.scenarios]


def _sequence_set(paths: Iterable[list[str]], *, max_length: int) -> set[tuple[str, ...]]:
    sequences: set[tuple[str, ...]] = set()
    for path in paths:
        for length in range(1, min(max_length, len(path)) + 1):
            for start in range(len(path) - length + 1):
                sequences.add(tuple(path[start : start + length]))
    return sequences


def _all_feasible_sequences(fsm: FSM, *, max_length: int) -> set[tuple[str, ...]]:
    """Collect contiguous transition-id sequences along feasible paths."""
    from collections import deque

    sequences: set[tuple[str, ...]] = set()
    queue: deque[tuple[str, tuple[str, ...]]] = deque([(fsm.initial_state, ())])

    while queue:
        state, path = queue.popleft()
        if path:
            sequences.add(path)
        if len(path) >= max_length:
            continue
        for transition in fsm.transitions:
            if transition.source != state:
                continue
            next_path = path + (transition.id,)
            sequences.add(next_path)
            queue.append((transition.target, next_path))

    return sequences


def compute_spec_coverage(
    fsm: FSM,
    suite: OracleSuite,
    *,
    max_sequence_length: int = 3,
) -> SpecCoverageReport:
    """Compute transition, pair, and sequence coverage exercised by *suite*."""
    if max_sequence_length < 1:
        msg = "max_sequence_length must be at least 1"
        raise ValueError(msg)

    machine_type = infer_machine_type(fsm)
    transition_ids = _all_transition_ids(fsm)
    transition_lookup = {transition.id: transition for transition in fsm.transitions}
    paths = _collect_executed_paths(suite, fsm)

    covered_transitions: set[str] = set()
    covered_pairs: set[tuple[str, str]] = set()
    for path in paths:
        covered_transitions.update(path)
        for left, right in zip(path, path[1:], strict=False):
            covered_pairs.add((left, right))

    covered_sequences = _sequence_set(paths, max_length=max_sequence_length)
    total_sequences = _all_feasible_sequences(fsm, max_length=max_sequence_length)
    total_pairs = _all_transition_pairs(transition_ids)

    efsm_ids = {
        transition.id
        for transition in fsm.transitions
        if _is_efsm_transition(transition, fsm)
    }
    timed_ids = {transition.id for transition in fsm.transitions if _is_timed_transition(transition)}

    efsm_coverage: float | None = None
    if efsm_ids:
        efsm_coverage = len(covered_transitions & efsm_ids) / len(efsm_ids)

    timed_coverage: float | None = None
    if timed_ids:
        timed_coverage = len(covered_transitions & timed_ids) / len(timed_ids)

    total_transitions = len(transition_ids)
    transition_coverage = (
        len(covered_transitions) / total_transitions if total_transitions else 0.0
    )
    transition_pair_coverage = len(covered_pairs) / len(total_pairs) if total_pairs else 0.0
    sequence_coverage = len(covered_sequences) / len(total_sequences) if total_sequences else 0.0

    _ = transition_lookup
    return SpecCoverageReport(
        machine_type=machine_type,
        transition_coverage=transition_coverage,
        transition_pair_coverage=transition_pair_coverage,
        sequence_coverage=sequence_coverage,
        covered_transitions=tuple(sorted(covered_transitions)),
        covered_transition_pairs=tuple(sorted(covered_pairs)),
        covered_sequences=tuple(sorted(covered_sequences)),
        total_transitions=total_transitions,
        total_transition_pairs=len(total_pairs),
        total_sequences=len(total_sequences),
        efsm_guard_transition_coverage=efsm_coverage,
        timed_transition_coverage=timed_coverage,
        max_sequence_length=max_sequence_length,
    )


def spec_coverage_to_json_dict(report: SpecCoverageReport) -> dict[str, object]:
    """Convert a report to a JSON-serialisable mapping."""
    return {
        "machine_type": report.machine_type.value,
        "transition_coverage": report.transition_coverage,
        "transition_pair_coverage": report.transition_pair_coverage,
        "sequence_coverage": report.sequence_coverage,
        "covered_transitions": list(report.covered_transitions),
        "covered_transition_pairs": [list(pair) for pair in report.covered_transition_pairs],
        "covered_sequences": [list(sequence) for sequence in report.covered_sequences],
        "total_transitions": report.total_transitions,
        "total_transition_pairs": report.total_transition_pairs,
        "total_sequences": report.total_sequences,
        "efsm_guard_transition_coverage": report.efsm_guard_transition_coverage,
        "timed_transition_coverage": report.timed_transition_coverage,
        "max_sequence_length": report.max_sequence_length,
    }


def spec_coverage_to_csv_rows(report: SpecCoverageReport) -> list[dict[str, object]]:
    """Flatten a report into CSV rows."""
    rows: list[dict[str, object]] = [
        {
            "metric": "transition",
            "covered": len(report.covered_transitions),
            "total": report.total_transitions,
            "coverage": f"{report.transition_coverage:.6f}",
            "machine_type": report.machine_type.value,
        },
        {
            "metric": "transition_pair",
            "covered": len(report.covered_transition_pairs),
            "total": report.total_transition_pairs,
            "coverage": f"{report.transition_pair_coverage:.6f}",
            "machine_type": report.machine_type.value,
        },
        {
            "metric": "sequence",
            "covered": len(report.covered_sequences),
            "total": report.total_sequences,
            "coverage": f"{report.sequence_coverage:.6f}",
            "machine_type": report.machine_type.value,
        },
    ]
    if report.efsm_guard_transition_coverage is not None:
        rows.append(
            {
                "metric": "efsm_guard_transition",
                "covered": len(report.covered_transitions),
                "total": report.total_transitions,
                "coverage": f"{report.efsm_guard_transition_coverage:.6f}",
                "machine_type": report.machine_type.value,
            }
        )
    if report.timed_transition_coverage is not None:
        rows.append(
            {
                "metric": "timed_transition",
                "covered": len(report.covered_transitions),
                "total": report.total_transitions,
                "coverage": f"{report.timed_transition_coverage:.6f}",
                "machine_type": report.machine_type.value,
            }
        )
    return rows
