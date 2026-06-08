"""Backward-compatible wrappers for specification-based coverage."""

from __future__ import annotations

from fsmrepairbench.coverage import (
    CoverageReport,
    compute_coverage_report,
    coverage_report_to_dict,
    write_coverage_json,
)
from fsmrepairbench.models import FSM, OracleSuite
from fsmrepairbench.taxonomy import MachineType

SPEC_COVERAGE_CSV_COLUMNS: tuple[str, ...] = (
    "metric",
    "covered",
    "total",
    "coverage",
    "machine_type",
)


class SpecCoverageReport:
    """Legacy report shape used by earlier SOTA integration code."""

    def __init__(self, report: CoverageReport) -> None:
        self._report = report

    @property
    def machine_type(self) -> MachineType:
        return self._report.machine_type

    @property
    def transition_coverage(self) -> float:
        return self._report.transition.coverage

    @property
    def transition_pair_coverage(self) -> float:
        return self._report.transition_pair.coverage

    @property
    def sequence_coverage(self) -> float:
        return self._report.transition_sequence.coverage

    @property
    def covered_transitions(self) -> tuple[str, ...]:
        return self._report.transition.covered_items

    @property
    def covered_transition_pairs(self) -> tuple[tuple[str, str], ...]:
        pairs: list[tuple[str, str]] = []
        for item in self._report.transition_pair.covered_items:
            left, right = item.split("->", maxsplit=1)
            pairs.append((left, right))
        return tuple(pairs)

    @property
    def covered_sequences(self) -> tuple[tuple[str, ...], ...]:
        return tuple(
            tuple(part for part in item.split("->"))
            for item in self._report.transition_sequence.covered_items
        )

    @property
    def total_transitions(self) -> int:
        return self._report.transition.total

    @property
    def total_transition_pairs(self) -> int:
        return self._report.transition_pair.total

    @property
    def total_sequences(self) -> int:
        return self._report.transition_sequence.total

    @property
    def efsm_guard_transition_coverage(self) -> float | None:
        if self._report.guard is None:
            return None
        return self._report.guard.coverage

    @property
    def timed_transition_coverage(self) -> float | None:
        if self._report.timeout is None:
            return None
        return self._report.timeout.coverage

    @property
    def max_sequence_length(self) -> int:
        return self._report.sequence_depth


def compute_spec_coverage(
    fsm: FSM,
    suite: OracleSuite,
    *,
    max_sequence_length: int = 3,
) -> SpecCoverageReport:
    """Compute specification-based coverage using the canonical coverage module."""
    report = compute_coverage_report(fsm, suite, sequence_depth=max_sequence_length)
    return SpecCoverageReport(report)


def spec_coverage_to_json_dict(report: SpecCoverageReport) -> dict[str, object]:
    """Convert a legacy report wrapper to JSON."""
    payload = coverage_report_to_dict(report._report)
    payload["state_coverage"] = report._report.state.coverage
    payload["transition_coverage"] = report.transition_coverage
    payload["transition_pair_coverage"] = report.transition_pair_coverage
    payload["sequence_coverage"] = report.sequence_coverage
    payload["efsm_guard_transition_coverage"] = report.efsm_guard_transition_coverage
    payload["timed_transition_coverage"] = report.timed_transition_coverage
    payload["max_sequence_length"] = report.max_sequence_length
    return payload


def spec_coverage_to_csv_rows(report: SpecCoverageReport) -> list[dict[str, object]]:
    """Flatten a legacy report wrapper into CSV rows."""
    rows: list[dict[str, object]] = []
    for criterion in (
        report._report.state,
        report._report.transition,
        report._report.transition_pair,
        report._report.transition_sequence,
    ):
        rows.append(
            {
                "metric": criterion.name,
                "covered": criterion.covered,
                "total": criterion.total,
                "coverage": f"{criterion.coverage:.6f}",
                "machine_type": report.machine_type.value,
            }
        )
    if report._report.guard is not None:
        rows.append(
            {
                "metric": "guard",
                "covered": report._report.guard.covered,
                "total": report._report.guard.total,
                "coverage": f"{report._report.guard.coverage:.6f}",
                "machine_type": report.machine_type.value,
            }
        )
    if report._report.timeout is not None:
        rows.append(
            {
                "metric": "timeout",
                "covered": report._report.timeout.covered,
                "total": report._report.timeout.total,
                "coverage": f"{report._report.timeout.coverage:.6f}",
                "machine_type": report.machine_type.value,
            }
        )
    return rows


__all__ = [
    "SPEC_COVERAGE_CSV_COLUMNS",
    "SpecCoverageReport",
    "compute_spec_coverage",
    "spec_coverage_to_csv_rows",
    "spec_coverage_to_json_dict",
    "write_coverage_json",
]
