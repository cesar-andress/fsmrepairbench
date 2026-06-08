"""FSM mutation helpers for generating benchmark instances."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import TypeVar

from fsmrepairbench.models import FSM, BugMetadata, State, Transition

MutationFn = Callable[[FSM, random.Random, int], tuple[FSM, BugMetadata]]

MUTATION_OPERATORS: tuple[str, ...] = (
    "missing_transition",
    "wrong_target",
    "wrong_source",
    "wrong_event",
    "wrong_initial_state",
    "duplicate_transition",
    "dead_state_intro",
    "guard_flip",
    "guard_weaken",
    "guard_strengthen",
    "action_corruption",
    "timeout_corruption",
    "delay_corruption",
    "nondeterminism_intro",
    "unreachable_state_intro",
)

T = TypeVar("T")


class MutatorError(ValueError):
    """Raised when a mutation operator cannot be applied."""


def describe_mutator_registry() -> list[str]:
    """Return registered mutator identifiers."""
    return list(MUTATION_OPERATORS)


def _bug_id(reference_fsm_id: str, operator: str, seed: int) -> str:
    return f"{reference_fsm_id}__{operator}__{seed}"


def _faulty_fsm_id(reference_fsm_id: str, operator: str, seed: int) -> str:
    return f"{reference_fsm_id}__faulty__{operator}__{seed}"


def _pick_index(rng: random.Random, size: int) -> int:
    if size <= 0:
        raise MutatorError("Cannot pick from an empty collection")
    return rng.randrange(size)


def _pick_other(rng: random.Random, options: list[T], current: T) -> T:
    alternatives = [option for option in options if option != current]
    if not alternatives:
        raise MutatorError(f"No alternative value available besides {current!r}")
    return rng.choice(alternatives)


def _pick_transition(fsm: FSM, rng: random.Random) -> tuple[int, Transition]:
    index = _pick_index(rng, len(fsm.transitions))
    return index, fsm.transitions[index]


def _state_ids(fsm: FSM) -> list[str]:
    return [state.id for state in fsm.states]


def _clone_fsm(reference: FSM, operator: str, seed: int) -> FSM:
    faulty = reference.model_copy(deep=True)
    faulty.id = _faulty_fsm_id(reference.id, operator, seed)
    faulty.name = f"{reference.name} (faulty: {operator})"
    faulty.reference_fsm_id = reference.id
    faulty.parent_fsm_id = reference.id
    return faulty


def _build_metadata(
    *,
    reference: FSM,
    operator: str,
    seed: int,
    description: str,
    changed_transition_id: str | None,
) -> BugMetadata:
    return BugMetadata(
        bug_id=_bug_id(reference.id, operator, seed),
        reference_fsm_id=reference.id,
        faulty_fsm_id=_faulty_fsm_id(reference.id, operator, seed),
        mutation_operator=operator,
        changed_transition_id=changed_transition_id,
        description=description,
        seed=seed,
    )


def _mutate_missing_transition(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    faulty = _clone_fsm(reference, "missing_transition", seed)
    removed = faulty.transitions.pop(index)
    metadata = _build_metadata(
        reference=reference,
        operator="missing_transition",
        seed=seed,
        description=f"Removed transition '{removed.id}'",
        changed_transition_id=removed.id,
    )
    return faulty, metadata


def _mutate_wrong_target(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    new_target = _pick_other(rng, _state_ids(reference), transition.target)
    faulty = _clone_fsm(reference, "wrong_target", seed)
    updated = faulty.transitions[index].model_copy(update={"target": new_target})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="wrong_target",
        seed=seed,
        description=(
            f"Changed target of transition '{transition.id}' "
            f"from '{transition.target}' to '{new_target}'"
        ),
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_wrong_source(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    new_source = _pick_other(rng, _state_ids(reference), transition.source)
    faulty = _clone_fsm(reference, "wrong_source", seed)
    updated = faulty.transitions[index].model_copy(update={"source": new_source})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="wrong_source",
        seed=seed,
        description=(
            f"Changed source of transition '{transition.id}' "
            f"from '{transition.source}' to '{new_source}'"
        ),
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_wrong_event(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    if len(reference.events) < 2:
        raise MutatorError("wrong_event requires at least two events")
    index, transition = _pick_transition(reference, rng)
    new_event = _pick_other(rng, reference.events, transition.event)
    faulty = _clone_fsm(reference, "wrong_event", seed)
    updated = faulty.transitions[index].model_copy(update={"event": new_event})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="wrong_event",
        seed=seed,
        description=(
            f"Changed event of transition '{transition.id}' "
            f"from '{transition.event}' to '{new_event}'"
        ),
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_wrong_initial_state(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    if len(reference.states) < 2:
        raise MutatorError("wrong_initial_state requires at least two states")
    new_initial = _pick_other(rng, _state_ids(reference), reference.initial_state)
    faulty = _clone_fsm(reference, "wrong_initial_state", seed)
    faulty.initial_state = new_initial
    metadata = _build_metadata(
        reference=reference,
        operator="wrong_initial_state",
        seed=seed,
        description=(
            f"Changed initial_state from '{reference.initial_state}' to '{new_initial}'"
        ),
        changed_transition_id=None,
    )
    return faulty, metadata


def _mutate_duplicate_transition(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    _, transition = _pick_transition(reference, rng)
    duplicate_id = f"{transition.id}__dup__{seed}"
    duplicate = transition.model_copy(update={"id": duplicate_id})
    faulty = _clone_fsm(reference, "duplicate_transition", seed)
    faulty.transitions.append(duplicate)
    metadata = _build_metadata(
        reference=reference,
        operator="duplicate_transition",
        seed=seed,
        description=f"Duplicated transition '{transition.id}' as '{duplicate_id}'",
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_dead_state_intro(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    _ = rng
    state_id = f"dead_{seed}"
    existing = set(_state_ids(reference))
    suffix = 0
    while state_id in existing:
        suffix += 1
        state_id = f"dead_{seed}_{suffix}"
    faulty = _clone_fsm(reference, "dead_state_intro", seed)
    faulty.states.append(State(id=state_id))
    metadata = _build_metadata(
        reference=reference,
        operator="dead_state_intro",
        seed=seed,
        description=f"Added unreachable state '{state_id}'",
        changed_transition_id=None,
    )
    return faulty, metadata


def _mutate_guard_flip(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    if transition.guard is None:
        new_guard = "unexpected_guard"
        description = f"Added guard '{new_guard}' to transition '{transition.id}'"
    else:
        new_guard = f"not_{transition.guard}"
        description = (
            f"Changed guard of transition '{transition.id}' "
            f"from '{transition.guard}' to '{new_guard}'"
        )
    faulty = _clone_fsm(reference, "guard_flip", seed)
    updated = faulty.transitions[index].model_copy(update={"guard": new_guard})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="guard_flip",
        seed=seed,
        description=description,
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_action_corruption(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    if transition.action is None:
        new_action = "wrong_action"
        description = f"Added action '{new_action}' to transition '{transition.id}'"
    else:
        new_action = f"wrong_{transition.action}"
        description = (
            f"Changed action of transition '{transition.id}' "
            f"from '{transition.action}' to '{new_action}'"
        )
    faulty = _clone_fsm(reference, "action_corruption", seed)
    updated = faulty.transitions[index].model_copy(update={"action": new_action})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="action_corruption",
        seed=seed,
        description=description,
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_guard_weaken(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    new_guard = "true"
    faulty = _clone_fsm(reference, "guard_weaken", seed)
    updated = faulty.transitions[index].model_copy(update={"guard": new_guard})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="guard_weaken",
        seed=seed,
        description=f"Weakened guard on transition '{transition.id}' to '{new_guard}'",
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_guard_strengthen(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    new_guard = transition.guard or "cond"
    new_guard = f"({new_guard}) and strict_check"
    faulty = _clone_fsm(reference, "guard_strengthen", seed)
    updated = faulty.transitions[index].model_copy(update={"guard": new_guard})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="guard_strengthen",
        seed=seed,
        description=f"Strengthened guard on transition '{transition.id}'",
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_timeout_corruption(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    new_timeout = (transition.timeout or 1.0) * 2.0
    faulty = _clone_fsm(reference, "timeout_corruption", seed)
    updated = faulty.transitions[index].model_copy(update={"timeout": new_timeout})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="timeout_corruption",
        seed=seed,
        description=f"Corrupted timeout on transition '{transition.id}' to {new_timeout}",
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_delay_corruption(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    new_delay = (transition.delay or 0.5) + 1.0
    faulty = _clone_fsm(reference, "delay_corruption", seed)
    updated = faulty.transitions[index].model_copy(update={"delay": new_delay})
    faulty.transitions[index] = updated
    metadata = _build_metadata(
        reference=reference,
        operator="delay_corruption",
        seed=seed,
        description=f"Corrupted delay on transition '{transition.id}' to {new_delay}",
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_nondeterminism_intro(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    index, transition = _pick_transition(reference, rng)
    alternate_target = _pick_other(rng, _state_ids(reference), transition.target)
    faulty = _clone_fsm(reference, "nondeterminism_intro", seed)
    duplicate = transition.model_copy(
        update={
            "id": f"{transition.id}__nd__{seed}",
            "target": alternate_target,
            "guard": transition.guard,
        }
    )
    faulty.transitions.append(duplicate)
    metadata = _build_metadata(
        reference=reference,
        operator="nondeterminism_intro",
        seed=seed,
        description=(
            f"Added nondeterministic duplicate for event '{transition.event}' "
            f"from '{transition.source}'"
        ),
        changed_transition_id=transition.id,
    )
    return faulty, metadata


def _mutate_unreachable_state_intro(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    _ = rng
    state_id = f"unreachable_{seed}"
    existing = set(_state_ids(reference))
    suffix = 0
    while state_id in existing:
        suffix += 1
        state_id = f"unreachable_{seed}_{suffix}"
    faulty = _clone_fsm(reference, "unreachable_state_intro", seed)
    faulty.states.append(State(id=state_id))
    metadata = _build_metadata(
        reference=reference,
        operator="unreachable_state_intro",
        seed=seed,
        description=f"Added unreachable state '{state_id}'",
        changed_transition_id=None,
    )
    return faulty, metadata


_OPERATOR_IMPL: dict[str, MutationFn] = {
    "missing_transition": _mutate_missing_transition,
    "wrong_target": _mutate_wrong_target,
    "wrong_source": _mutate_wrong_source,
    "wrong_event": _mutate_wrong_event,
    "wrong_initial_state": _mutate_wrong_initial_state,
    "duplicate_transition": _mutate_duplicate_transition,
    "dead_state_intro": _mutate_dead_state_intro,
    "guard_flip": _mutate_guard_flip,
    "guard_weaken": _mutate_guard_weaken,
    "guard_strengthen": _mutate_guard_strengthen,
    "action_corruption": _mutate_action_corruption,
    "timeout_corruption": _mutate_timeout_corruption,
    "delay_corruption": _mutate_delay_corruption,
    "nondeterminism_intro": _mutate_nondeterminism_intro,
    "unreachable_state_intro": _mutate_unreachable_state_intro,
}


def mutate(reference: FSM, operator: str, seed: int) -> tuple[FSM, BugMetadata]:
    """Apply *operator* to *reference* using deterministic *seed*."""
    if operator not in _OPERATOR_IMPL:
        known = ", ".join(MUTATION_OPERATORS)
        raise MutatorError(f"Unknown mutation operator '{operator}'. Known: {known}")

    if operator == "missing_transition" and not reference.transitions:
        raise MutatorError("missing_transition requires at least one transition")
    if operator in {
        "wrong_target",
        "wrong_source",
        "wrong_event",
        "duplicate_transition",
        "guard_flip",
        "guard_weaken",
        "guard_strengthen",
        "action_corruption",
        "timeout_corruption",
        "delay_corruption",
        "nondeterminism_intro",
    } and not reference.transitions:
        raise MutatorError(f"{operator} requires at least one transition")

    rng = random.Random(seed)
    return _OPERATOR_IMPL[operator](reference, rng, seed)


def apply_mutation(reference: FSM, metadata: BugMetadata) -> tuple[FSM, BugMetadata]:
    """Reproduce a mutation described by *metadata*."""
    faulty, reproduced = mutate(reference, metadata.mutation_operator, metadata.seed)
    if reproduced.bug_id != metadata.bug_id:
        raise MutatorError("Reproduced mutation metadata does not match requested bug_id")
    return faulty, reproduced
