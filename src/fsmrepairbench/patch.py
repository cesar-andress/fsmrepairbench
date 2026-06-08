"""FSM repair patch metamodel and application."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from fsmrepairbench.models import FSM, Transition
from fsmrepairbench.validators import load_model, validate_fsm

PatchOpName = Literal[
    "add_transition",
    "remove_transition",
    "replace_transition_source",
    "replace_transition_target",
    "replace_transition_event",
    "replace_initial_state",
    "replace_guard",
    "replace_action",
]


class AddTransitionOperation(BaseModel):
    """Add a new transition to an FSM."""

    op: Literal["add_transition"] = "add_transition"
    id: str
    source: str
    event: str
    target: str
    guard: str | None = None
    action: str | None = None
    requirements: list[str] = Field(default_factory=list)


class RemoveTransitionOperation(BaseModel):
    """Remove an existing transition."""

    op: Literal["remove_transition"] = "remove_transition"
    transition_id: str


class ReplaceTransitionSourceOperation(BaseModel):
    """Replace the source state of a transition."""

    op: Literal["replace_transition_source"] = "replace_transition_source"
    transition_id: str
    source: str


class ReplaceTransitionTargetOperation(BaseModel):
    """Replace the target state of a transition."""

    op: Literal["replace_transition_target"] = "replace_transition_target"
    transition_id: str
    target: str


class ReplaceTransitionEventOperation(BaseModel):
    """Replace the event of a transition."""

    op: Literal["replace_transition_event"] = "replace_transition_event"
    transition_id: str
    event: str


class ReplaceInitialStateOperation(BaseModel):
    """Replace the initial state."""

    op: Literal["replace_initial_state"] = "replace_initial_state"
    initial_state: str


class ReplaceGuardOperation(BaseModel):
    """Replace the guard of a transition."""

    op: Literal["replace_guard"] = "replace_guard"
    transition_id: str
    guard: str | None = None


class ReplaceActionOperation(BaseModel):
    """Replace the action of a transition."""

    op: Literal["replace_action"] = "replace_action"
    transition_id: str
    action: str | None = None


PatchOperation = Annotated[
    AddTransitionOperation
    | RemoveTransitionOperation
    | ReplaceTransitionSourceOperation
    | ReplaceTransitionTargetOperation
    | ReplaceTransitionEventOperation
    | ReplaceInitialStateOperation
    | ReplaceGuardOperation
    | ReplaceActionOperation,
    Field(discriminator="op"),
]


class FSMPatch(BaseModel):
    """Patch describing repair operations for an FSM."""

    patch_id: str
    target_fsm_id: str
    operations: list[PatchOperation] = Field(default_factory=list)


class PatchError(ValueError):
    """Raised when a patch cannot be applied."""


def load_patch_json(path: Path) -> FSMPatch:
    """Load an FSM patch from a JSON file."""
    return load_model(path, FSMPatch)


def _state_ids(fsm: FSM) -> set[str]:
    return {state.id for state in fsm.states}


def _transition_index(fsm: FSM) -> dict[str, int]:
    return {transition.id: index for index, transition in enumerate(fsm.transitions)}


def _require_transition(fsm: FSM, transition_id: str) -> int:
    index = _transition_index(fsm).get(transition_id)
    if index is None:
        msg = f"Unknown transition id: '{transition_id}'"
        raise PatchError(msg)
    return index


def _validate_added_transition(fsm: FSM, operation: AddTransitionOperation) -> list[str]:
    errors: list[str] = []
    state_ids = _state_ids(fsm)
    if operation.id in _transition_index(fsm):
        errors.append(f"Transition id '{operation.id}' already exists")
    if operation.source not in state_ids:
        errors.append(
            f"add_transition '{operation.id}': source '{operation.source}' "
            "is not a defined state"
        )
    if operation.target not in state_ids:
        errors.append(
            f"add_transition '{operation.id}': target '{operation.target}' "
            "is not a defined state"
        )
    if operation.event not in set(fsm.events):
        errors.append(
            f"add_transition '{operation.id}': event '{operation.event}' "
            "is not defined in events"
        )
    return errors


def apply_patch(fsm: FSM, patch: FSMPatch) -> FSM:
    """Apply *patch* to *fsm* and return the patched FSM."""
    result = fsm.model_copy(deep=True)

    for operation in patch.operations:
        if isinstance(operation, AddTransitionOperation):
            errors = _validate_added_transition(result, operation)
            if errors:
                raise PatchError(errors[0])
            result.transitions.append(
                Transition(
                    id=operation.id,
                    source=operation.source,
                    event=operation.event,
                    target=operation.target,
                    guard=operation.guard,
                    action=operation.action,
                    requirements=operation.requirements,
                )
            )
            continue

        if isinstance(operation, RemoveTransitionOperation):
            index = _require_transition(result, operation.transition_id)
            result.transitions.pop(index)
            continue

        if isinstance(operation, ReplaceTransitionSourceOperation):
            index = _require_transition(result, operation.transition_id)
            transition = result.transitions[index]
            result.transitions[index] = transition.model_copy(update={"source": operation.source})
            continue

        if isinstance(operation, ReplaceTransitionTargetOperation):
            index = _require_transition(result, operation.transition_id)
            transition = result.transitions[index]
            result.transitions[index] = transition.model_copy(update={"target": operation.target})
            continue

        if isinstance(operation, ReplaceTransitionEventOperation):
            index = _require_transition(result, operation.transition_id)
            transition = result.transitions[index]
            result.transitions[index] = transition.model_copy(update={"event": operation.event})
            continue

        if isinstance(operation, ReplaceInitialStateOperation):
            result.initial_state = operation.initial_state
            continue

        if isinstance(operation, ReplaceGuardOperation):
            index = _require_transition(result, operation.transition_id)
            transition = result.transitions[index]
            result.transitions[index] = transition.model_copy(update={"guard": operation.guard})
            continue

        if isinstance(operation, ReplaceActionOperation):
            index = _require_transition(result, operation.transition_id)
            transition = result.transitions[index]
            result.transitions[index] = transition.model_copy(
                update={"action": operation.action}
            )
            continue

        msg = f"Unsupported patch operation: {operation!r}"
        raise PatchError(msg)

    return result


def validate_patch(
    fsm: FSM,
    patch: FSMPatch,
    *,
    allow_nondeterminism: bool = False,
) -> list[str]:
    """Return validation errors for applying *patch* to *fsm*."""
    if patch.target_fsm_id != fsm.id:
        return [
            f"Patch target_fsm_id '{patch.target_fsm_id}' does not match FSM id '{fsm.id}'"
        ]

    try:
        patched = apply_patch(fsm, patch)
    except PatchError as exc:
        return [str(exc)]

    return validate_fsm(patched, allow_nondeterminism=allow_nondeterminism)
