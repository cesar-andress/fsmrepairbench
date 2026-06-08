"""Synthetic FSM factory with controllable complexity."""

from __future__ import annotations

import random
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.validators import validate_fsm

ComplexityLevel = Literal["small", "medium", "large", "very_large"]

COMPLEXITY_PRESETS: dict[ComplexityLevel, dict[str, int]] = {
    "small": {
        "num_states": 5,
        "num_events": 3,
        "branching_factor": 2,
    },
    "medium": {
        "num_states": 10,
        "num_events": 5,
        "branching_factor": 3,
    },
    "large": {
        "num_states": 20,
        "num_events": 10,
        "branching_factor": 4,
    },
    "very_large": {
        "num_states": 50,
        "num_events": 15,
        "branching_factor": 5,
    },
}


class SyntheticFactoryError(ValueError):
    """Raised when synthetic FSM generation fails."""


@dataclass(frozen=True)
class SyntheticGenerationParams:
    """Parameters controlling synthetic FSM generation."""

    num_states: int
    num_events: int
    branching_factor: int = 2
    deterministic: bool = True
    allow_dead_states: bool = False
    seed: int = 0
    complexity: ComplexityLevel | None = None

    def __post_init__(self) -> None:
        if self.num_states < 1:
            raise SyntheticFactoryError("num_states must be at least 1")
        if self.num_events < 1:
            raise SyntheticFactoryError("num_events must be at least 1")
        if self.branching_factor < 1:
            raise SyntheticFactoryError("branching_factor must be at least 1")


def params_from_complexity(
    complexity: ComplexityLevel,
    *,
    seed: int = 0,
    deterministic: bool = True,
    allow_dead_states: bool = False,
    branching_factor: int | None = None,
    num_states: int | None = None,
    num_events: int | None = None,
) -> SyntheticGenerationParams:
    """Build generation params from a named complexity preset."""
    preset = COMPLEXITY_PRESETS[complexity]
    return SyntheticGenerationParams(
        num_states=num_states or preset["num_states"],
        num_events=num_events or preset["num_events"],
        branching_factor=branching_factor or preset["branching_factor"],
        deterministic=deterministic,
        allow_dead_states=allow_dead_states,
        seed=seed,
        complexity=complexity,
    )


def reachable_state_ids(fsm: FSM) -> set[str]:
    """Return states reachable from the initial state."""
    graph: dict[str, list[str]] = {state.id: [] for state in fsm.states}
    for transition in fsm.transitions:
        graph[transition.source].append(transition.target)

    seen: set[str] = set()
    queue: deque[str] = deque([fsm.initial_state])
    while queue:
        current = queue.popleft()
        if current in seen:
            continue
        seen.add(current)
        queue.extend(graph[current])
    return seen


def generate_synthetic_fsm(params: SyntheticGenerationParams) -> FSM:
    """Generate a synthetic FSM from *params*."""
    rng = random.Random(params.seed)
    state_ids = [f"s{params.seed}_{index}" for index in range(params.num_states)]
    event_ids = [f"e{params.seed}_{index}" for index in range(params.num_events)]
    initial_state = state_ids[0]

    if params.allow_dead_states and params.num_states > 1:
        reachable_count = rng.randint(max(1, params.num_states // 2), params.num_states)
    else:
        reachable_count = params.num_states

    reachable_states_list = state_ids[:reachable_count]
    transitions: list[Transition] = []
    transition_counter = 0
    used_triples: set[tuple[str, str, str | None]] = set()
    outgoing_counts: dict[str, int] = dict.fromkeys(reachable_states_list, 0)

    def try_add_transition(source: str, target: str, event: str) -> bool:
        nonlocal transition_counter
        guard: str | None = None
        triple = (source, event, guard)

        if params.deterministic:
            suffix = 0
            while triple in used_triples:
                suffix += 1
                guard = f"g{params.seed}_{transition_counter}_{suffix}"
                triple = (source, event, guard)
                if suffix > params.num_states * params.num_events:
                    return False
            used_triples.add(triple)

        transition_counter += 1
        transitions.append(
            Transition(
                id=f"t{params.seed}_{transition_counter}",
                source=source,
                event=event,
                target=target,
                guard=guard,
                action=f"act{params.seed}_{transition_counter}",
            )
        )
        outgoing_counts[source] += 1
        return True

    for index in range(1, reachable_count):
        parent = reachable_states_list[rng.randrange(index)]
        event = rng.choice(event_ids)
        try_add_transition(parent, reachable_states_list[index], event)

    for source in reachable_states_list:
        attempts = 0
        max_attempts = params.branching_factor * max(2, params.num_events)
        while outgoing_counts[source] < params.branching_factor and attempts < max_attempts:
            attempts += 1
            target = rng.choice(reachable_states_list)
            event = rng.choice(event_ids)
            if params.deterministic:
                if (source, event, None) in used_triples:
                    guard_exists = any(
                        triple[0] == source and triple[1] == event for triple in used_triples
                    )
                    if guard_exists and outgoing_counts[source] >= len(event_ids):
                        break
            try_add_transition(source, target, event)

    complexity_label = params.complexity or "custom"
    fsm = FSM(
        id=f"synthetic_{params.seed}_{params.num_states}_{params.num_events}",
        name=f"Synthetic FSM ({complexity_label})",
        description=(
            f"Synthetic FSM generated with seed={params.seed}, "
            f"states={params.num_states}, events={params.num_events}, "
            f"branching_factor={params.branching_factor}, "
            f"deterministic={params.deterministic}, "
            f"allow_dead_states={params.allow_dead_states}"
        ),
        states=[State(id=state_id) for state_id in state_ids],
        initial_state=initial_state,
        events=event_ids,
        transitions=transitions,
    )

    errors = validate_fsm(fsm, allow_nondeterminism=not params.deterministic)
    if errors:
        msg = f"Generated invalid FSM: {errors[0]}"
        raise SyntheticFactoryError(msg)

    assert_reachability_requirements(fsm, allow_dead_states=params.allow_dead_states)
    return fsm


def export_fsm_json(fsm: FSM, path: Path) -> None:
    """Write *fsm* to *path* in benchmark JSON format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fsm.model_dump_json(indent=2) + "\n", encoding="utf-8")


def assert_reachability_requirements(fsm: FSM, *, allow_dead_states: bool) -> None:
    """Validate reachability constraints for a generated FSM."""
    reachable = reachable_state_ids(fsm)
    if fsm.initial_state not in reachable:
        msg = "Initial state must be reachable from itself"
        raise SyntheticFactoryError(msg)

    dead_states = [state.id for state in fsm.states if state.id not in reachable]
    if not allow_dead_states and dead_states:
        msg = f"Unexpected dead states: {dead_states}"
        raise SyntheticFactoryError(msg)

    for transition in fsm.transitions:
        if transition.source in reachable and transition.target not in reachable:
            msg = (
                f"Reachable state '{transition.source}' has transition to dead state "
                f"'{transition.target}'"
            )
            raise SyntheticFactoryError(msg)


def complexity_presets() -> dict[ComplexityLevel, dict[str, int]]:
    """Return available complexity presets."""
    return COMPLEXITY_PRESETS
