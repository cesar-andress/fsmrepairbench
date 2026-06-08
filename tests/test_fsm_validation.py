"""Tests for FSM JSON schema and semantic validation."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from fsmrepairbench.models import FSM, Transition
from fsmrepairbench.validators import (
    is_valid_fsm,
    load_fsm_json,
    validate_fsm,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_valid_fsm_json() -> None:
    fsm = load_fsm_json(FIXTURES / "valid_fsm.json")
    assert fsm.id == "parking_gate_001"
    assert fsm.name == "Parking Gate"
    assert fsm.initial_state == "closed"
    assert fsm.events == ["car_arrives", "ticket_valid", "timeout"]
    assert len(fsm.states) == 2
    assert len(fsm.transitions) == 3


def test_is_valid_fsm_accepts_fixture() -> None:
    fsm = load_fsm_json(FIXTURES / "valid_fsm.json")
    assert is_valid_fsm(fsm)
    assert validate_fsm(fsm) == []


def test_transition_defaults() -> None:
    transition = Transition.model_validate(
        {
            "id": "t1",
            "source": "closed",
            "event": "car_arrives",
            "target": "open",
        }
    )
    assert transition.guard is None
    assert transition.action is None
    assert transition.requirements == []


def test_invalid_initial_state() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}],
            "initial_state": "missing",
            "events": [],
            "transitions": [],
        }
    )
    errors = validate_fsm(fsm)
    assert any("initial_state" in error for error in errors)
    assert not is_valid_fsm(fsm)


def test_invalid_transition_source_and_target() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}, {"id": "b"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "t1", "source": "a", "event": "go", "target": "missing"},
                {"id": "t2", "source": "missing", "event": "go", "target": "b"},
            ],
        }
    )
    errors = validate_fsm(fsm)
    assert any("source 'missing'" in error for error in errors)
    assert any("target 'missing'" in error for error in errors)


def test_invalid_transition_event() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}],
            "initial_state": "a",
            "events": ["allowed"],
            "transitions": [
                {"id": "t1", "source": "a", "event": "forbidden", "target": "a"},
            ],
        }
    )
    errors = validate_fsm(fsm)
    assert any("event 'forbidden'" in error for error in errors)


def test_duplicate_state_ids() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}, {"id": "a"}],
            "initial_state": "a",
            "events": [],
            "transitions": [],
        }
    )
    errors = validate_fsm(fsm)
    assert any("Duplicate state id: 'a'" in error for error in errors)


def test_duplicate_transition_ids() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "t1", "source": "a", "event": "go", "target": "a", "guard": "g1"},
                {"id": "t1", "source": "a", "event": "go", "target": "a", "guard": "g2"},
            ],
        }
    )
    errors = validate_fsm(fsm)
    assert any("Duplicate transition id: 't1'" in error for error in errors)


def test_non_deterministic_duplicate_triple() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}, {"id": "b"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "t1", "source": "a", "event": "go", "target": "a", "guard": "same"},
                {"id": "t2", "source": "a", "event": "go", "target": "b", "guard": "same"},
            ],
        }
    )
    errors = validate_fsm(fsm)
    assert any("Non-deterministic FSM" in error for error in errors)


def test_same_source_event_allowed_with_different_guards() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}, {"id": "b"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "t1", "source": "a", "event": "go", "target": "a", "guard": "g1"},
                {"id": "t2", "source": "a", "event": "go", "target": "b", "guard": "g2"},
            ],
        }
    )
    assert is_valid_fsm(fsm)


def test_duplicate_triple_with_missing_guard() -> None:
    fsm = FSM.model_validate(
        {
            "id": "x",
            "name": "X",
            "states": [{"id": "a"}, {"id": "b"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "t1", "source": "a", "event": "go", "target": "a"},
                {"id": "t2", "source": "a", "event": "go", "target": "b"},
            ],
        }
    )
    errors = validate_fsm(fsm)
    assert any("Non-deterministic FSM" in error for error in errors)


def test_invalid_fsm_fixture_rejected_by_document_validator() -> None:
    from fsmrepairbench.validators import validate_fsm_document

    ok, message, model = validate_fsm_document(FIXTURES / "invalid_fsm.json")
    assert ok is False
    assert model is None
    assert "initial_state" in message


def test_load_fsm_json_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        FSM.model_validate({"name": "incomplete"})
