"""Coupling-effect tracking for simple vs complex mutation faults."""

from __future__ import annotations

from dataclasses import dataclass

from fsmrepairbench.models import BugMetadata, FSM, OracleScenario, OracleSuite
from fsmrepairbench.mutation_advanced import (
    classify_mutation_complexity,
)
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.scorer import score_oracle_suite

COUPLING_CSV_COLUMNS: tuple[str, ...] = (
    "mutation_operator",
    "mutation_complexity",
    "mutation_scope",
    "mutation_mode",
    "reference_bpr",
    "faulty_bpr",
    "fault_detectable",
    "complex_fault_coverage",
    "simple_fault_proxy_coverage",
)


@dataclass(frozen=True)
class CouplingReport:
    """Coupling metrics linking mutation complexity and oracle sensitivity."""

    mutation_operator: str
    mutation_complexity: str
    mutation_scope: str | None
    mutation_mode: str | None
    reference_bpr: float
    faulty_bpr: float
    fault_detectable: bool
    complex_fault_coverage: float
    simple_fault_proxy_coverage: float


def _is_simple_proxy_scenario(scenario: OracleScenario) -> bool:
    return len(scenario.steps) <= 1


def track_coupling_effect(
    reference: FSM,
    faulty: FSM,
    suite: OracleSuite,
    metadata: BugMetadata,
) -> CouplingReport:
    """Measure how well the oracle suite exposes a mutation fault."""
    reference_score = score_oracle_suite(reference, suite)
    faulty_score = score_oracle_suite(faulty, suite)

    failing_scenarios = [
        scenario
        for scenario in suite.scenarios
        if execute_scenario(reference, scenario).passed
        and not execute_scenario(faulty, scenario).passed
    ]
    passing_on_reference = [
        scenario
        for scenario in suite.scenarios
        if execute_scenario(reference, scenario).passed
    ]
    complex_fault_coverage = (
        len(failing_scenarios) / len(passing_on_reference)
        if passing_on_reference
        else 0.0
    )

    simple_proxies = [
        scenario
        for scenario in passing_on_reference
        if _is_simple_proxy_scenario(scenario)
    ]
    simple_failures = [
        scenario
        for scenario in simple_proxies
        if not execute_scenario(faulty, scenario).passed
    ]
    simple_fault_proxy_coverage = (
        len(simple_failures) / len(simple_proxies) if simple_proxies else 0.0
    )

    complexity = metadata.mutation_complexity or classify_mutation_complexity(
        metadata.mutation_operator
    )
    fault_detectable = faulty_score.bpr < reference_score.bpr

    return CouplingReport(
        mutation_operator=metadata.mutation_operator,
        mutation_complexity=complexity,
        mutation_scope=metadata.mutation_scope,
        mutation_mode=metadata.mutation_mode,
        reference_bpr=reference_score.bpr,
        faulty_bpr=faulty_score.bpr,
        fault_detectable=fault_detectable,
        complex_fault_coverage=complex_fault_coverage,
        simple_fault_proxy_coverage=simple_fault_proxy_coverage,
    )


def coupling_report_to_json_dict(report: CouplingReport) -> dict[str, object]:
    """Convert a coupling report to JSON."""
    return {
        "mutation_operator": report.mutation_operator,
        "mutation_complexity": report.mutation_complexity,
        "mutation_scope": report.mutation_scope,
        "mutation_mode": report.mutation_mode,
        "reference_bpr": report.reference_bpr,
        "faulty_bpr": report.faulty_bpr,
        "fault_detectable": report.fault_detectable,
        "complex_fault_coverage": report.complex_fault_coverage,
        "simple_fault_proxy_coverage": report.simple_fault_proxy_coverage,
    }


def coupling_report_to_csv_rows(report: CouplingReport) -> list[dict[str, object]]:
    """Flatten a coupling report to CSV rows."""
    return [
        {
            "mutation_operator": report.mutation_operator,
            "mutation_complexity": report.mutation_complexity,
            "mutation_scope": report.mutation_scope or "",
            "mutation_mode": report.mutation_mode or "",
            "reference_bpr": f"{report.reference_bpr:.6f}",
            "faulty_bpr": f"{report.faulty_bpr:.6f}",
            "fault_detectable": report.fault_detectable,
            "complex_fault_coverage": f"{report.complex_fault_coverage:.6f}",
            "simple_fault_proxy_coverage": f"{report.simple_fault_proxy_coverage:.6f}",
        }
    ]
