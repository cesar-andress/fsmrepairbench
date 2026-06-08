"""Tests for advanced FSM semantics and structural feature inference."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.semantics import (
    infer_structural_features,
    validate_semantics,
    write_semantics_report_json,
)
from fsmrepairbench.taxonomy import MachineType, compute_case_features, infer_machine_type
from fsmrepairbench.taxonomy import BugType
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _probabilistic_fsm() -> FSM:
    return FSM.model_validate(
        {
            "id": "prob_gate",
            "name": "Probabilistic Gate",
            "states": [{"id": "s0"}, {"id": "s1"}, {"id": "s2"}],
            "initial_state": "s0",
            "events": ["go"],
            "semantics_mode": "probabilistic_threshold",
            "transitions": [
                {
                    "id": "t0",
                    "source": "s0",
                    "event": "go",
                    "target": "s1",
                    "probability": 0.7,
                },
                {
                    "id": "t1",
                    "source": "s0",
                    "event": "go",
                    "target": "s2",
                    "probability": 0.3,
                },
            ],
        }
    )


def _nondeterministic_fsm() -> FSM:
    return FSM.model_validate(
        {
            "id": "nd_toggle",
            "name": "Nondeterministic Toggle",
            "states": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
            "initial_state": "a",
            "events": ["step"],
            "semantics_mode": "nondeterministic_accepting",
            "transitions": [
                {"id": "t_ab", "source": "a", "event": "step", "target": "b", "is_nondeterministic": True},
                {"id": "t_ac", "source": "a", "event": "step", "target": "c", "is_nondeterministic": True},
                {"id": "t_bc", "source": "b", "event": "step", "target": "c"},
            ],
        }
    )


def _refusal_fsm() -> FSM:
    return FSM.model_validate(
        {
            "id": "refusal_fsm",
            "name": "Refusal FSM",
            "states": [{"id": "idle", "refusal": True}, {"id": "busy"}],
            "initial_state": "idle",
            "events": ["request", "$refusal"],
            "semantics_mode": "refusal_aware",
            "transitions": [
                {
                    "id": "t_req",
                    "source": "idle",
                    "event": "request",
                    "target": "busy",
                },
                {
                    "id": "t_ref",
                    "source": "idle",
                    "event": "$refusal",
                    "target": "idle",
                    "refusal": True,
                },
            ],
        }
    )


def _timed_discrete_fsm() -> FSM:
    return FSM.model_validate(
        {
            "id": "timed_discrete",
            "name": "Timed Discrete",
            "states": [{"id": "s0"}, {"id": "s1"}],
            "initial_state": "s0",
            "events": ["tick"],
            "discrete_time_step": 1.0,
            "semantics_mode": "timed_discrete",
            "transitions": [
                {
                    "id": "t0",
                    "source": "s0",
                    "event": "tick",
                    "target": "s1",
                    "discrete_time": 1,
                    "timeout": 2.0,
                }
            ],
        }
    )


def test_infer_structural_features_for_probabilistic_fsm() -> None:
    features = infer_structural_features(_probabilistic_fsm())
    assert features.has_probabilities
    assert not features.has_nondeterminism
    assert infer_machine_type(_probabilistic_fsm()) is MachineType.PROBABILISTIC_FSM


def test_infer_structural_features_for_nondeterministic_fsm() -> None:
    features = infer_structural_features(_nondeterministic_fsm())
    assert features.has_nondeterminism
    assert infer_machine_type(_nondeterministic_fsm()) is MachineType.NONDETERMINISTIC_FSM


def test_validate_probabilistic_threshold_requires_probability_sum() -> None:
    valid = validate_semantics(_probabilistic_fsm(), mode="probabilistic_threshold")
    assert valid.valid

    broken = _probabilistic_fsm().model_copy(deep=True)
    broken.transitions[1].probability = 0.5
    report = validate_semantics(broken, mode="probabilistic_threshold")
    assert not report.valid
    assert any(issue.code == "probability_sum" for issue in report.issues)


def test_validate_refusal_aware_requires_refusal_markers() -> None:
    assert validate_semantics(_refusal_fsm(), mode="refusal_aware").valid
    plain = load_fsm(FIXTURES / "simple_fsm.json")
    assert not validate_semantics(plain, mode="refusal_aware").valid


def test_validate_timed_discrete_mode() -> None:
    assert validate_semantics(_timed_discrete_fsm(), mode="timed_discrete").valid


def test_validate_deterministic_rejects_duplicate_transitions() -> None:
    fsm = _nondeterministic_fsm()
    report = validate_semantics(fsm, mode="deterministic")
    assert not report.valid


def test_nondeterministic_oracle_execution_with_accepting_states() -> None:
    fsm = _nondeterministic_fsm()
    scenario = OracleScenario(
        id="accept_b_or_c",
        steps=[
            OracleStep(event="step", expected_state="b", accepting_states=["b", "c"]),
            OracleStep(event="step", expected_state="c"),
        ],
    )
    result = execute_scenario(fsm, scenario, semantics_mode="nondeterministic_accepting")
    assert result.passed


def test_probabilistic_oracle_execution_uses_threshold() -> None:
    fsm = _probabilistic_fsm()
    suite = OracleSuite(
        id="prob_oracle",
        fsm_id=fsm.id,
        semantics_mode="probabilistic_threshold",
        probability_threshold=0.5,
        scenarios=[
            OracleScenario(
                id="high_prob_path",
                steps=[
                    OracleStep(
                        event="go",
                        expected_state="s1",
                        probability_threshold=0.5,
                    )
                ],
            )
        ],
    )
    score = score_oracle_suite(fsm, suite)
    assert score.bpr == 1.0


def test_compute_case_features_includes_semantics_flags() -> None:
    features = compute_case_features(
        _probabilistic_fsm(),
        None,
        BugType.MISSING_TRANSITION,
        seed=1,
        case_id="case_prob",
    )
    assert features.has_probabilities
    assert features.cycle_count is not None
    assert features.strongly_connected_component_count is not None
    assert "probability" in {item.value for item in features.semantics_features}


def test_cli_validate_semantics(tmp_path: Path) -> None:
    fsm_path = tmp_path / "prob.json"
    fsm_path.write_text(_probabilistic_fsm().model_dump_json(indent=2) + "\n", encoding="utf-8")
    out_path = tmp_path / "report.json"

    result = runner.invoke(
        app,
        [
            "validate-semantics",
            str(fsm_path),
            "--mode",
            "probabilistic_threshold",
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["valid"] is True
    assert payload["structural_features"]["has_probabilities"] is True


def test_write_semantics_report_json(tmp_path: Path) -> None:
    report = validate_semantics(_refusal_fsm(), mode="refusal_aware")
    path = tmp_path / "semantics.json"
    write_semantics_report_json(path, report)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["mode"] == "refusal_aware"
