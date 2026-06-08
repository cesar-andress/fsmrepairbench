"""Stratified FSM generation aligned with taxonomy cells."""

from __future__ import annotations

import random

from fsmrepairbench.generators.stratified_specs import GenerationCell
from fsmrepairbench.generators.synthetic_factory import (
    SyntheticFactoryError,
    SyntheticGenerationParams,
    generate_synthetic_fsm,
)
from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.taxonomy import (
    ArityClass,
    Completeness,
    Determinism,
    GraphStructure,
    GuardComplexity,
    MachineType,
    SizeClass,
    TimeFeature,
)

SIZE_CLASS_PARAMS: dict[SizeClass, tuple[int, int, int]] = {
    SizeClass.TINY: (3, 2, 1),
    SizeClass.SMALL: (5, 3, 2),
    SizeClass.MEDIUM: (10, 5, 3),
    SizeClass.LARGE: (20, 8, 4),
    SizeClass.VERY_LARGE: (35, 12, 5),
}

ARITY_BRANCHING: dict[ArityClass, int] = {
    ArityClass.LOW: 1,
    ArityClass.MEDIUM: 2,
    ArityClass.HIGH: 4,
    ArityClass.VERY_HIGH: 6,
}


class StratifiedGeneratorError(ValueError):
    """Raised when a stratified FSM cannot be generated."""


def _guard_for_complexity(complexity: GuardComplexity, seed: int, index: int) -> str | None:
    if complexity is GuardComplexity.NONE:
        return None
    if complexity is GuardComplexity.SIMPLE:
        return f"x_{seed}_{index} > 0"
    if complexity is GuardComplexity.COMPOUND:
        return f"x_{seed}_{index} > 0 and y_{seed}_{index} < 10"
    return f"(x_{seed}_{index} > 0) and (y_{seed}_{index} < 10 or z_{seed}_{index} == 1)"


def _apply_machine_type(fsm: FSM, machine_type: MachineType, seed: int) -> FSM:
    updated = fsm.model_copy(deep=True)
    if machine_type in {MachineType.EFSM, MachineType.TIMED_EFSM}:
        updated.variables = {"x": "int", "y": "int"}

    if machine_type in {MachineType.MOORE, MachineType.MEALY}:
        for index, state in enumerate(updated.states):
            if machine_type is MachineType.MOORE:
                updated.states[index] = state.model_copy(
                    update={"state_output": f"out_{seed}_{index}"}
                )

    transitions: list[Transition] = []
    for index, transition in enumerate(updated.transitions):
        payload: dict[str, object] = {}
        if machine_type is MachineType.MEALY:
            payload["output"] = f"out_{seed}_{index}"
        if machine_type in {MachineType.TIMED_FSM, MachineType.TIMED_EFSM}:
            payload["timeout"] = float(1 + index)
        transitions.append(transition.model_copy(update=payload))
    updated.transitions = transitions
    return updated


def _apply_time_features(fsm: FSM, time_features: list[TimeFeature], seed: int) -> FSM:
    updated = fsm.model_copy(deep=True)
    if TimeFeature.NONE in time_features and len(time_features) == 1:
        return updated

    transitions: list[Transition] = []
    for index, transition in enumerate(updated.transitions):
        payload: dict[str, object] = {}
        if TimeFeature.TIMEOUT in time_features or TimeFeature.TIMED_GUARD_AND_TIMEOUT in time_features:
            payload["timeout"] = float(index + 1)
        if TimeFeature.OUTPUT_DELAY in time_features:
            payload["delay"] = float(index) * 0.5
        guard = transition.guard
        if TimeFeature.TIMED_GUARD in time_features or TimeFeature.TIMED_GUARD_AND_TIMEOUT in time_features:
            guard = f"t > {index + seed}"
        transitions.append(transition.model_copy(update={**payload, "guard": guard}))
    updated.transitions = transitions
    return updated


def _apply_guard_complexity(fsm: FSM, complexity: GuardComplexity, seed: int) -> FSM:
    transitions = []
    for index, transition in enumerate(fsm.transitions):
        guard = _guard_for_complexity(complexity, seed, index)
        transitions.append(transition.model_copy(update={"guard": guard}))
    return fsm.model_copy(update={"transitions": transitions})


def _apply_graph_structure(fsm: FSM, structures: list[GraphStructure], seed: int) -> FSM:
    if GraphStructure.HUB_AND_SPOKE in structures and len(fsm.states) > 2:
        hub = fsm.initial_state
        rng = random.Random(seed)
        transitions = [
            Transition(
                id=f"t{seed}_hub_{index}",
                source=hub,
                event=rng.choice(fsm.events),
                target=state.id,
                guard=None,
            )
            for index, state in enumerate(fsm.states[1:], start=1)
        ]
        return fsm.model_copy(update={"transitions": transitions})

    if GraphStructure.ACYCLIC in structures:
        transitions = []
        state_ids = [state.id for state in fsm.states]
        for index, transition in enumerate(fsm.transitions):
            source_index = state_ids.index(transition.source)
            target_index = state_ids.index(transition.target)
            if target_index < source_index:
                target = state_ids[min(source_index + 1, len(state_ids) - 1)]
                transition = transition.model_copy(update={"target": target})
            transitions.append(transition)
        return fsm.model_copy(update={"transitions": transitions})

    if GraphStructure.CYCLIC in structures and fsm.transitions:
        first = fsm.transitions[0]
        back_edge = first.model_copy(
            update={
                "id": f"t{seed}_cycle",
                "source": fsm.states[-1].id,
                "target": fsm.initial_state,
                "event": first.event,
            }
        )
        return fsm.model_copy(update={"transitions": [*fsm.transitions, back_edge]})

    return fsm


def _apply_completeness(fsm: FSM, completeness: Completeness, seed: int) -> FSM:
    if completeness is Completeness.COMPLETE:
        return fsm
    if len(fsm.transitions) <= 1:
        return fsm
    rng = random.Random(seed)
    drop_index = rng.randrange(len(fsm.transitions))
    transitions = [transition for index, transition in enumerate(fsm.transitions) if index != drop_index]
    return fsm.model_copy(update={"transitions": transitions})


def generate_reference_fsm_for_cell(cell: GenerationCell, seed: int) -> FSM:
    """Generate a reference FSM matching the requested taxonomy cell."""
    num_states, num_events, _ = SIZE_CLASS_PARAMS[cell.size_class]
    branching = ARITY_BRANCHING[cell.arity_class]
    params = SyntheticGenerationParams(
        num_states=num_states,
        num_events=num_events,
        branching_factor=branching,
        deterministic=cell.determinism is Determinism.DETERMINISTIC,
        allow_dead_states=cell.completeness is Completeness.PARTIAL,
        seed=seed,
        complexity=None,
    )
    try:
        fsm = generate_synthetic_fsm(params)
    except SyntheticFactoryError as exc:
        msg = f"Could not generate base FSM for cell: {exc}"
        raise StratifiedGeneratorError(msg) from exc

    fsm = _apply_graph_structure(fsm, cell.graph_structure, seed)
    fsm = _apply_guard_complexity(fsm, cell.guard_complexity, seed)
    fsm = _apply_time_features(fsm, cell.time_features, seed)
    fsm = _apply_machine_type(fsm, cell.machine_type, seed)
    fsm = _apply_completeness(fsm, cell.completeness, seed)
    return fsm
