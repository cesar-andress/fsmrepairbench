"""Load and validate FSM and oracle JSON documents."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

from fsmrepairbench.models import FSM, OracleSuite

ModelT = TypeVar("ModelT", bound=BaseModel)


def load_json(path: Path) -> object:
    """Read and parse a JSON file."""
    text = path.read_text(encoding="utf-8")
    return json.loads(text)


def load_model(path: Path, model: type[ModelT]) -> ModelT:
    """Load JSON from *path* and validate it against *model*."""
    data = load_json(path)
    return model.model_validate(data)


def load_fsm_json(path: Path) -> FSM:
    """Load an FSM definition from a JSON file."""
    return load_model(path, FSM)


def load_fsm(path: Path) -> FSM:
    """Alias for :func:`load_fsm_json`."""
    return load_fsm_json(path)


def validate_fsm(fsm: FSM, *, allow_nondeterminism: bool = False) -> list[str]:
    """Return semantic validation errors for *fsm* (empty list if valid)."""
    errors: list[str] = []

    state_ids = [state.id for state in fsm.states]
    state_id_set = set(state_ids)

    duplicate_state_ids = sorted(
        state_id for state_id, count in Counter(state_ids).items() if count > 1
    )
    for state_id in duplicate_state_ids:
        errors.append(f"Duplicate state id: '{state_id}'")

    if fsm.initial_state not in state_id_set:
        errors.append(
            f"initial_state '{fsm.initial_state}' is not defined in states"
        )

    event_set = set(fsm.events)

    transition_ids = [transition.id for transition in fsm.transitions]
    duplicate_transition_ids = sorted(
        transition_id
        for transition_id, count in Counter(transition_ids).items()
        if count > 1
    )
    for transition_id in duplicate_transition_ids:
        errors.append(f"Duplicate transition id: '{transition_id}'")

    triples: dict[tuple[str, str, str | None], str] = {}
    for transition in fsm.transitions:
        if transition.source not in state_id_set:
            errors.append(
                f"Transition '{transition.id}': source '{transition.source}' "
                "is not a defined state"
            )
        if transition.target not in state_id_set:
            errors.append(
                f"Transition '{transition.id}': target '{transition.target}' "
                "is not a defined state"
            )
        if transition.event not in event_set:
            errors.append(
                f"Transition '{transition.id}': event '{transition.event}' "
                "is not defined in events"
            )

        if allow_nondeterminism:
            continue

        triple = (transition.source, transition.event, transition.guard)
        if triple in triples:
            errors.append(
                "Non-deterministic FSM: duplicate (source, event, guard) "
                f"{triple} in transitions '{triples[triple]}' and '{transition.id}'"
            )
        else:
            triples[triple] = transition.id

    return errors


def is_valid_fsm(fsm: FSM) -> bool:
    """Return ``True`` when *fsm* passes semantic validation."""
    return not validate_fsm(fsm)


def load_oracle_suite(path: Path) -> OracleSuite:
    """Load and validate an oracle suite from JSON."""
    return load_model(path, OracleSuite)


def validate_fsm_document(path: Path) -> tuple[bool, str, FSM | None]:
    """Validate an FSM JSON file, returning success flag, message, and model."""
    try:
        fsm = load_fsm_json(path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Failed to read JSON: {exc}", None
    except ValidationError as exc:
        return False, f"Invalid FSM schema: {exc}", None

    errors = validate_fsm(fsm)
    if errors:
        return False, errors[0], None

    return True, f"Valid FSM '{fsm.name}' with {len(fsm.states)} states", fsm


def validate_oracle_document(path: Path) -> tuple[bool, str, OracleSuite | None]:
    """Validate an oracle suite JSON file, returning success flag, message, and model."""
    try:
        suite = load_oracle_suite(path)
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"Failed to read JSON: {exc}", None
    except ValidationError as exc:
        return False, f"Invalid oracle schema: {exc}", None

    scenario_count = len(suite.scenarios)
    return True, f"Valid oracle suite '{suite.id}' with {scenario_count} scenarios", suite
