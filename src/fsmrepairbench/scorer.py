"""Scoring helpers for repair evaluation."""

from __future__ import annotations

from fsmrepairbench.models import FSM, OracleSuite, RepairResult, ScoreResult
from fsmrepairbench.oracle import execute_scenario


def score_oracle_suite(fsm: FSM, suite: OracleSuite) -> ScoreResult:
    """Score *fsm* against all scenarios in *suite*."""
    scenario_results = [execute_scenario(fsm, scenario) for scenario in suite.scenarios]

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
