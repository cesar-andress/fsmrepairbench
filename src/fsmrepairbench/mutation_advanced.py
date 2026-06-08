"""Advanced mutation operators inspired by historical OO testing tools."""

from __future__ import annotations

import random
from collections.abc import Callable
from typing import Literal

from fsmrepairbench.models import BugMetadata, FSM, Transition
from fsmrepairbench.mutators import (
    MutatorError,
    _build_metadata,
    _clone_fsm,
    _pick_index,
    _pick_transition,
)

MutationComplexity = Literal["simple", "complex"]
MutationScope = Literal["intra_class", "inter_class"]
MutationMode = Literal["selective", "full"]
MutationFn = Callable[[FSM, random.Random, int], tuple[FSM, BugMetadata]]

ADVANCED_MUTATION_OPERATORS: tuple[str, ...] = (
    "variable_intra_class",
    "guard_inter_class",
    "action_full_mutation",
    "timed_selective_mutation",
)

SIMPLE_MUTATION_OPERATORS: frozenset[str] = frozenset(
    {
        "missing_transition",
        "wrong_target",
        "wrong_source",
        "wrong_event",
        "wrong_initial_state",
        "duplicate_transition",
        "dead_state_intro",
        "unreachable_state_intro",
    }
)

COMPLEX_MUTATION_OPERATORS: frozenset[str] = frozenset(
    {
        "guard_flip",
        "guard_weaken",
        "guard_strengthen",
        "action_corruption",
        "timeout_corruption",
        "delay_corruption",
        "nondeterminism_intro",
        *ADVANCED_MUTATION_OPERATORS,
    }
)


def classify_mutation_complexity(operator: str) -> MutationComplexity:
    """Return whether *operator* is a simple or complex mutation."""
    if operator in SIMPLE_MUTATION_OPERATORS:
        return "simple"
    return "complex"


def _advanced_metadata(
    *,
    reference: FSM,
    operator: str,
    seed: int,
    description: str,
    changed_transition_id: str | None,
    complexity: MutationComplexity,
    scope: MutationScope,
    mode: MutationMode,
) -> BugMetadata:
    metadata = _build_metadata(
        reference=reference,
        operator=operator,
        seed=seed,
        description=description,
        changed_transition_id=changed_transition_id,
    )
    return metadata.model_copy(
        update={
            "mutation_complexity": complexity,
            "mutation_scope": scope,
            "mutation_mode": mode,
        }
    )


def _mutate_variable_intra_class(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    if not reference.variables:
        raise MutatorError("variable_intra_class requires at least one FSM variable")

    faulty = _clone_fsm(reference, "variable_intra_class", seed)
    keys = list(faulty.variables)
    key = rng.choice(keys)
    faulty.variables[key] = f"mutated_{faulty.variables[key]}_{seed}"
    metadata = _advanced_metadata(
        reference=reference,
        operator="variable_intra_class",
        seed=seed,
        description=f"Intra-class variable mutation on '{key}'",
        changed_transition_id=None,
        complexity="complex",
        scope="intra_class",
        mode="selective",
    )
    return faulty, metadata


def _mutate_guard_inter_class(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    guarded = [transition for transition in reference.transitions if transition.guard]
    if len(guarded) < 2:
        raise MutatorError("guard_inter_class requires at least two guarded transitions")

    left_index, left = _pick_transition(reference, rng)
    right_index = _pick_index(rng, len(reference.transitions))
    while right_index == left_index:
        right_index = _pick_index(rng, len(reference.transitions))
    right = reference.transitions[right_index]

    faulty = _clone_fsm(reference, "guard_inter_class", seed)
    faulty.transitions[left_index] = left.model_copy(update={"guard": right.guard})
    metadata = _advanced_metadata(
        reference=reference,
        operator="guard_inter_class",
        seed=seed,
        description=(
            f"Inter-class guard swap from '{right.id}' onto transition '{left.id}'"
        ),
        changed_transition_id=left.id,
        complexity="complex",
        scope="inter_class",
        mode="selective",
    )
    return faulty, metadata


def _mutate_action_full_mutation(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    if not reference.transitions:
        raise MutatorError("action_full_mutation requires at least one transition")

    faulty = _clone_fsm(reference, "action_full_mutation", seed)
    updated: list[Transition] = []
    for transition in faulty.transitions:
        action = transition.action or "noop"
        updated.append(
            transition.model_copy(update={"action": f"full_mut_{action}_{seed}"})
        )
    faulty.transitions = updated
    metadata = _advanced_metadata(
        reference=reference,
        operator="action_full_mutation",
        seed=seed,
        description="Full mutation of all transition actions",
        changed_transition_id=None,
        complexity="complex",
        scope="intra_class",
        mode="full",
    )
    return faulty, metadata


def _mutate_timed_selective_mutation(
    reference: FSM,
    rng: random.Random,
    seed: int,
) -> tuple[FSM, BugMetadata]:
    timed_indices = [
        index
        for index, transition in enumerate(reference.transitions)
        if transition.timeout is not None or transition.delay is not None
    ]
    if not timed_indices:
        raise MutatorError("timed_selective_mutation requires timed transitions")

    index = rng.choice(timed_indices)
    transition = reference.transitions[index]
    faulty = _clone_fsm(reference, "timed_selective_mutation", seed)
    faulty.transitions[index] = transition.model_copy(
        update={
            "timeout": (transition.timeout or 1.0) + 1.0,
            "delay": (transition.delay or 0.0) + 0.5,
        }
    )
    metadata = _advanced_metadata(
        reference=reference,
        operator="timed_selective_mutation",
        seed=seed,
        description=f"Selective timed mutation on transition '{transition.id}'",
        changed_transition_id=transition.id,
        complexity="complex",
        scope="intra_class",
        mode="selective",
    )
    return faulty, metadata


ADVANCED_OPERATOR_IMPL: dict[str, MutationFn] = {
    "variable_intra_class": _mutate_variable_intra_class,
    "guard_inter_class": _mutate_guard_inter_class,
    "action_full_mutation": _mutate_action_full_mutation,
    "timed_selective_mutation": _mutate_timed_selective_mutation,
}


def describe_advanced_mutator_registry() -> list[str]:
    """Return advanced mutation operator identifiers."""
    return list(ADVANCED_MUTATION_OPERATORS)
