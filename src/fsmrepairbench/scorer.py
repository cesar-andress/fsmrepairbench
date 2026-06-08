"""Scoring helpers for repair evaluation."""

from __future__ import annotations

import csv
from pathlib import Path

from fsmrepairbench.models import FSM, OracleSuite, RepairResult, ScenarioResult, ScoreResult
from fsmrepairbench.oracle import execute_scenario

SCORE_CSV_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "oracle_suite_id",
    "scenario_id",
    "passed",
    "passed_steps",
    "total_steps",
    "bpr",
)


def scenario_bpr(scenario: ScenarioResult) -> float:
    """Return the behavioural pass rate for a single scenario."""
    if scenario.total_steps == 0:
        return 0.0
    return scenario.passed_steps / scenario.total_steps


def write_score_json(path: Path, result: ScoreResult) -> None:
    """Write the full score result as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")


def write_score_csv(
    path: Path,
    *,
    fsm_id: str,
    oracle_suite_id: str,
    result: ScoreResult,
) -> None:
    """Write scenario-level score rows as CSV to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SCORE_CSV_COLUMNS))
        writer.writeheader()
        for scenario in result.scenarios:
            writer.writerow(
                {
                    "fsm_id": fsm_id,
                    "oracle_suite_id": oracle_suite_id,
                    "scenario_id": scenario.scenario_id,
                    "passed": scenario.passed,
                    "passed_steps": scenario.passed_steps,
                    "total_steps": scenario.total_steps,
                    "bpr": f"{scenario_bpr(scenario):.6f}",
                }
            )


def score_oracle_suite(fsm: FSM, suite: OracleSuite) -> ScoreResult:
    """Score *fsm* against all scenarios in *suite*."""
    semantics_mode = suite.semantics_mode or fsm.semantics_mode
    scenario_results = [
        execute_scenario(fsm, scenario, semantics_mode=semantics_mode)
        for scenario in suite.scenarios
    ]

    passed_steps = sum(result.passed_steps for result in scenario_results)
    total_steps = sum(result.total_steps for result in scenario_results)
    passed_scenarios = sum(1 for result in scenario_results if result.passed)
    total_scenarios = len(scenario_results)
    bpr = passed_steps / total_steps if total_steps else 0.0

    return ScoreResult(
        bpr=bpr,
        passed_steps=passed_steps,
        total_steps=total_steps,
        passed_scenarios=passed_scenarios,
        total_scenarios=total_scenarios,
        scenarios=scenario_results,
    )


def score_repair(
    *,
    bug_id: str,
    candidate: FSM,
    reference: FSM,
    oracle: OracleSuite,
) -> RepairResult:
    """Score a candidate repair using behavioural oracle execution."""
    _ = reference
    score = score_oracle_suite(candidate, oracle)
    return RepairResult(
        bug_id=bug_id,
        passed=score.bpr == 1.0,
        score=score.bpr,
        details={
            "passed_steps": score.passed_steps,
            "total_steps": score.total_steps,
            "passed_scenarios": score.passed_scenarios,
            "total_scenarios": score.total_scenarios,
        },
    )
