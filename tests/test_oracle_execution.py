"""Tests for oracle execution and scoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.models import OracleScenario, OracleStep
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"


def test_execute_simple_scenario_passes() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    result = execute_scenario(fsm, suite.scenarios[0])
    assert result.passed is True
    assert result.passed_steps == 1
    assert result.total_steps == 1
    assert result.steps[0].actual_state == "on"


def test_execute_simple_scenario_two_steps() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    result = execute_scenario(fsm, suite.scenarios[1])
    assert result.passed is True
    assert result.passed_steps == 2
    assert [step.actual_state for step in result.steps] == ["on", "off"]


def test_execute_scenario_fails_on_missing_transition() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    scenario = OracleScenario(
        id="impossible",
        steps=[OracleStep(event="missing_event", expected_state="on")],
    )

    result = execute_scenario(fsm, scenario)
    assert result.passed is False
    assert result.passed_steps == 0
    assert result.steps[0].failure_reason == "no_matching_transition"
    assert result.steps[0].actual_state == "off"


def test_execute_scenario_fails_on_wrong_expected_state() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    scenario = OracleScenario(
        id="wrong_expectation",
        steps=[OracleStep(event="toggle", expected_state="off")],
    )

    result = execute_scenario(fsm, scenario)
    assert result.passed is False
    assert result.passed_steps == 0
    assert result.steps[0].failure_reason == "unexpected_state"
    assert result.steps[0].actual_state == "on"


def test_guarded_transition_requires_matching_guard() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    scenario = OracleScenario(
        id="wrong_guard",
        steps=[
            OracleStep(
                event="car_arrives",
                guard="ticket_valid",
                expected_state="closed",
            )
        ],
    )

    result = execute_scenario(fsm, scenario)
    assert result.passed is False
    assert result.steps[0].failure_reason == "unexpected_state"
    assert result.steps[0].actual_state == "open"


def test_guarded_transition_without_guard_does_not_match() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    scenario = OracleScenario(
        id="missing_guard",
        steps=[OracleStep(event="car_arrives", expected_state="closed")],
    )

    result = execute_scenario(fsm, scenario)
    assert result.passed is False
    assert result.steps[0].failure_reason == "no_matching_transition"


def test_score_oracle_suite_full_pass() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")

    result = score_oracle_suite(fsm, suite)
    assert result.bpr == 1.0
    assert result.passed_steps == 4
    assert result.total_steps == 4
    assert result.passed_scenarios == 3
    assert result.total_scenarios == 3


def test_score_oracle_suite_partial_pass() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    broken = fsm.model_copy(
        update={
            "transitions": [
                transition
                for transition in fsm.transitions
                if transition.id != "t2"
            ]
        }
    )
    result = score_oracle_suite(broken, suite)
    assert result.bpr == pytest.approx(2 / 3)
    assert result.passed_steps == 2
    assert result.total_steps == 3
    assert result.passed_scenarios == 1
    assert result.scenarios[0].passed is True
    assert result.scenarios[1].passed is False
    assert result.scenarios[1].steps[1].failure_reason == "no_matching_transition"
