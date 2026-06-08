"""Tests for FSM mutation operators."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.models import FSM
from fsmrepairbench.mutators import (
    MUTATION_OPERATORS,
    MutatorError,
    describe_mutator_registry,
    mutate,
)
from fsmrepairbench.validators import is_valid_fsm, load_fsm, validate_fsm

FIXTURES = Path(__file__).parent / "fixtures"
REFERENCE = load_fsm(FIXTURES / "valid_fsm.json")
SEED = 42


@pytest.fixture
def reference() -> FSM:
    return REFERENCE.model_copy(deep=True)


@pytest.mark.parametrize("operator", MUTATION_OPERATORS)
def test_each_operator_produces_faulty_fsm(reference: FSM, operator: str) -> None:
    faulty, metadata = mutate(reference, operator, SEED)

    assert faulty.id == f"{reference.id}__faulty__{operator}__{SEED}"
    assert faulty.id != reference.id
    assert metadata.bug_id == f"{reference.id}__{operator}__{SEED}"
    assert metadata.reference_fsm_id == reference.id
    assert metadata.faulty_fsm_id == faulty.id
    assert faulty.reference_fsm_id == reference.id
    assert faulty.parent_fsm_id == reference.id
    assert metadata.mutation_operator == operator
    assert metadata.seed == SEED
    assert metadata.description


@pytest.mark.parametrize("operator", MUTATION_OPERATORS)
def test_mutation_is_deterministic(reference: FSM, operator: str) -> None:
    first_fsm, first_meta = mutate(reference, operator, SEED)
    second_fsm, second_meta = mutate(reference, operator, SEED)

    assert first_fsm.model_dump() == second_fsm.model_dump()
    assert first_meta.model_dump() == second_meta.model_dump()


def test_registry_lists_all_operators() -> None:
    assert describe_mutator_registry() == list(MUTATION_OPERATORS)


def test_unknown_operator_raises(reference: FSM) -> None:
    with pytest.raises(MutatorError, match="Unknown mutation operator"):
        mutate(reference, "unknown_operator", SEED)


def test_missing_transition_removes_transition(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "missing_transition", SEED)

    assert len(faulty.transitions) == len(reference.transitions) - 1
    assert metadata.changed_transition_id is not None
    remaining_ids = {transition.id for transition in faulty.transitions}
    assert metadata.changed_transition_id not in remaining_ids
    assert is_valid_fsm(faulty)


def test_wrong_target_changes_target_only(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "wrong_target", SEED)
    changed_id = metadata.changed_transition_id
    assert changed_id is not None

    reference_transition = next(
        transition for transition in reference.transitions if transition.id == changed_id
    )
    faulty_transition = next(
        transition for transition in faulty.transitions if transition.id == changed_id
    )

    assert faulty_transition.source == reference_transition.source
    assert faulty_transition.event == reference_transition.event
    assert faulty_transition.target != reference_transition.target
    assert faulty_transition.target in {state.id for state in reference.states}


def test_wrong_source_changes_source_only(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "wrong_source", SEED)
    changed_id = metadata.changed_transition_id
    assert changed_id is not None

    reference_transition = next(
        transition for transition in reference.transitions if transition.id == changed_id
    )
    faulty_transition = next(
        transition for transition in faulty.transitions if transition.id == changed_id
    )

    assert faulty_transition.target == reference_transition.target
    assert faulty_transition.event == reference_transition.event
    assert faulty_transition.source != reference_transition.source
    assert faulty_transition.source in {state.id for state in reference.states}


def test_wrong_event_changes_event_only(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "wrong_event", SEED)
    changed_id = metadata.changed_transition_id
    assert changed_id is not None

    reference_transition = next(
        transition for transition in reference.transitions if transition.id == changed_id
    )
    faulty_transition = next(
        transition for transition in faulty.transitions if transition.id == changed_id
    )

    assert faulty_transition.source == reference_transition.source
    assert faulty_transition.target == reference_transition.target
    assert faulty_transition.event != reference_transition.event
    assert faulty_transition.event in reference.events


def test_wrong_initial_state_changes_initial_state(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "wrong_initial_state", SEED)

    assert faulty.initial_state != reference.initial_state
    assert faulty.initial_state in {state.id for state in reference.states}
    assert metadata.changed_transition_id is None
    assert len(faulty.transitions) == len(reference.transitions)


def test_duplicate_transition_adds_nondeterministic_copy(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "duplicate_transition", SEED)

    assert len(faulty.transitions) == len(reference.transitions) + 1
    assert metadata.changed_transition_id is not None

    original = next(
        transition
        for transition in reference.transitions
        if transition.id == metadata.changed_transition_id
    )
    duplicates = [
        transition
        for transition in faulty.transitions
        if transition.source == original.source
        and transition.event == original.event
        and transition.guard == original.guard
    ]
    assert len(duplicates) == 2
    assert not is_valid_fsm(faulty)
    assert validate_fsm(faulty)


def test_dead_state_intro_adds_unreachable_state(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "dead_state_intro", SEED)

    assert len(faulty.states) == len(reference.states) + 1
    assert metadata.changed_transition_id is None

    new_states = {state.id for state in faulty.states} - {state.id for state in reference.states}
    assert len(new_states) == 1
    dead_state = new_states.pop()
    assert dead_state.startswith("dead_")
    assert is_valid_fsm(faulty)


def test_guard_flip_with_existing_guard(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "guard_flip", 7)
    changed_id = metadata.changed_transition_id
    assert changed_id is not None

    reference_transition = next(
        transition for transition in reference.transitions if transition.id == changed_id
    )
    faulty_transition = next(
        transition for transition in faulty.transitions if transition.id == changed_id
    )

    if reference_transition.guard is not None:
        assert faulty_transition.guard == f"not_{reference_transition.guard}"
    else:
        assert faulty_transition.guard == "unexpected_guard"


def test_action_corruption_with_existing_action(reference: FSM) -> None:
    faulty, metadata = mutate(reference, "action_corruption", 7)
    changed_id = metadata.changed_transition_id
    assert changed_id is not None

    reference_transition = next(
        transition for transition in reference.transitions if transition.id == changed_id
    )
    faulty_transition = next(
        transition for transition in faulty.transitions if transition.id == changed_id
    )

    if reference_transition.action is not None:
        assert faulty_transition.action == f"wrong_{reference_transition.action}"
    else:
        assert faulty_transition.action == "wrong_action"


def test_guard_flip_without_guard_on_selected_transition() -> None:
    fsm = FSM.model_validate(
        {
            "id": "guardless",
            "name": "Guardless",
            "states": [{"id": "a"}, {"id": "b"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "only", "source": "a", "event": "go", "target": "b"},
            ],
        }
    )
    faulty, metadata = mutate(fsm, "guard_flip", 1)
    transition = faulty.transitions[0]
    assert transition.guard == "unexpected_guard"
    assert metadata.changed_transition_id == "only"


def test_action_corruption_without_action_on_selected_transition() -> None:
    fsm = FSM.model_validate(
        {
            "id": "actionless",
            "name": "Actionless",
            "states": [{"id": "a"}, {"id": "b"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [
                {"id": "only", "source": "a", "event": "go", "target": "b"},
            ],
        }
    )
    faulty, metadata = mutate(fsm, "action_corruption", 1)
    transition = faulty.transitions[0]
    assert transition.action == "wrong_action"
    assert metadata.changed_transition_id == "only"


def test_missing_transition_requires_transition() -> None:
    fsm = FSM.model_validate(
        {
            "id": "empty",
            "name": "Empty",
            "states": [{"id": "a"}],
            "initial_state": "a",
            "events": ["go"],
            "transitions": [],
        }
    )
    with pytest.raises(MutatorError, match="missing_transition requires"):
        mutate(fsm, "missing_transition", SEED)
