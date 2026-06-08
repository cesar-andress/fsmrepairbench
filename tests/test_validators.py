"""Tests for FSMRepairBench."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fsmrepairbench.models import FSM, BugMetadata, RepairResult
from fsmrepairbench.oracle import count_steps, scenario_names
from fsmrepairbench.scorer import score_repair
from fsmrepairbench.validators import (
    is_valid_fsm,
    load_fsm,
    load_fsm_json,
    load_oracle_suite,
    validate_fsm,
    validate_fsm_document,
    validate_oracle_document,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_valid_fsm() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    assert fsm.id == "parking_gate_001"
    assert fsm.name == "Parking Gate"
    assert fsm.initial_state == "closed"
    assert len(fsm.states) == 2
    assert len(fsm.transitions) == 3
    assert is_valid_fsm(fsm)


def test_load_fsm_json_alias() -> None:
    assert load_fsm_json(FIXTURES / "valid_fsm.json").id == "parking_gate_001"


def test_load_valid_oracle() -> None:
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    assert suite.id == "parking_gate_oracles"
    assert suite.fsm_id == "parking_gate_001"
    assert len(suite.scenarios) == 3
    assert suite.scenarios[0].id == "invalid_ticket_stays_closed"


def test_validate_fsm_document_rejects_invalid_structure() -> None:
    ok, message, model = validate_fsm_document(FIXTURES / "invalid_fsm.json")
    assert ok is False
    assert model is None
    assert "initial_state" in message


def test_validate_oracle_document_accepts_fixture() -> None:
    ok, message, model = validate_oracle_document(FIXTURES / "valid_oracle.json")
    assert ok is True
    assert model is not None
    assert "parking_gate_oracles" in message


def test_fsm_rejects_unknown_transition_state() -> None:
    fsm = FSM.model_validate(
        {
            "id": "bad",
            "name": "bad",
            "states": [{"id": "a"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [{"id": "t1", "source": "a", "target": "missing", "event": "go"}],
        }
    )
    errors = validate_fsm(fsm)
    assert any("target 'missing'" in error for error in errors)


def test_oracle_helpers() -> None:
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    assert count_steps(suite) == 4
    assert scenario_names(suite) == [
        "invalid_ticket_stays_closed",
        "valid_ticket_opens_gate",
        "open_then_timeout_closes",
    ]


def test_repair_result_bounds() -> None:
    with pytest.raises(ValidationError):
        RepairResult(bug_id="b1", passed=True, score=1.5)


def test_score_repair_uses_oracle_suite() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    bug = BugMetadata(
        bug_id="parking_gate_001__wrong_target__1",
        reference_fsm_id="parking_gate_001",
        faulty_fsm_id="parking_gate_001__faulty__wrong_target__1",
        mutation_operator="wrong_target",
        description="test",
        seed=1,
    )
    result = score_repair(
        bug_id=bug.bug_id,
        candidate=fsm,
        reference=fsm,
        oracle=suite,
    )
    assert result.passed is True
    assert result.score == 1.0
