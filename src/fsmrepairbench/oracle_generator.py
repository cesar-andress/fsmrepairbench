"""Automatic behavioural oracle generation from reference FSMs."""

from __future__ import annotations

import random
import statistics
import zlib
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite, Transition

DepthLevel = Literal["shallow", "medium", "deep", "exhaustive_like"]
ScenarioPolicy = Literal["shortest-path", "depth-forced"]

DEPTH_MAX_STEPS: dict[DepthLevel, int] = {
    "shallow": 5,
    "medium": 12,
    "deep": 25,
    "exhaustive_like": 40,
}

DEPTH_FORCED_TARGETS: dict[DepthLevel, dict[str, int]] = {
    "shallow": {
        "target_mean_steps": 3,
        "target_max_steps": 5,
        "min_extra_scenarios": 0,
    },
    "medium": {
        "target_mean_steps": 8,
        "target_max_steps": 12,
        "min_extra_scenarios": 4,
    },
    "deep": {
        "target_mean_steps": 16,
        "target_max_steps": 25,
        "min_extra_scenarios": 8,
    },
    "exhaustive_like": {
        "target_mean_steps": 30,
        "target_max_steps": 40,
        "min_extra_scenarios": 12,
    },
}


class OracleGeneratorError(ValueError):
    """Raised when oracle generation fails."""


@dataclass(frozen=True)
class OracleCoverageMetrics:
    """Coverage metrics for a generated oracle suite."""

    state_coverage: float
    transition_coverage: float
    event_coverage: float
    covered_states: tuple[str, ...]
    covered_transitions: tuple[str, ...]
    covered_events: tuple[str, ...]
    total_states: int
    total_transitions: int
    total_events: int


@dataclass(frozen=True)
class OracleGenerationResult:
    """Generated oracle suite and coverage summary."""

    suite: OracleSuite
    coverage: OracleCoverageMetrics
    declared_max_depth: int = 0
    mean_scenario_length: float = 0.0
    median_scenario_length: float = 0.0
    max_scenario_length: int = 0
    scenario_policy: ScenarioPolicy = "shortest-path"


def _scenario_length_stats(scenarios: Iterable[OracleScenario]) -> tuple[float, float, int]:
    lengths = [len(scenario.steps) for scenario in scenarios]
    if not lengths:
        return 0.0, 0.0, 0
    return (
        statistics.mean(lengths),
        statistics.median(lengths),
        max(lengths),
    )


def _end_state_after_steps(fsm: FSM, steps: Iterable[OracleStep]) -> str | None:
    current_state = fsm.initial_state
    for step in steps:
        matched: Transition | None = None
        for transition in _outgoing_transitions(fsm, current_state):
            if transition.event != step.event:
                continue
            if step.guard != transition.guard:
                continue
            matched = transition
            break
        if matched is None:
            return None
        current_state = matched.target
    return current_state


def _random_walk_steps(
    fsm: FSM,
    start_state: str,
    num_steps: int,
    *,
    max_total_length: int,
    rng: random.Random,
) -> list[OracleStep]:
    steps: list[OracleStep] = []
    current = start_state
    for _ in range(num_steps):
        if len(steps) >= max_total_length:
            break
        outgoing = _outgoing_transitions(fsm, current)
        if not outgoing:
            break
        transition = rng.choice(outgoing)
        steps.append(_transition_step(transition))
        current = transition.target
    return steps


def _extend_scenario_to_target_length(
    fsm: FSM,
    scenario: OracleScenario,
    *,
    target_length: int,
    max_length: int,
    rng: random.Random,
) -> OracleScenario:
    current_steps = list(scenario.steps)
    if len(current_steps) >= target_length:
        return scenario
    end_state = _end_state_after_steps(fsm, current_steps)
    if end_state is None:
        return scenario
    extra = _random_walk_steps(
        fsm,
        end_state,
        target_length - len(current_steps),
        max_total_length=max(0, max_length - len(current_steps)),
        rng=rng,
    )
    if not extra:
        return scenario
    return OracleScenario(
        id=scenario.id,
        description=scenario.description,
        steps=current_steps + extra,
    )


def _random_walk_scenario(
    fsm: FSM,
    *,
    scenario_id: str,
    target_length: int,
    max_length: int,
    rng: random.Random,
) -> OracleScenario | None:
    steps = _random_walk_steps(
        fsm,
        fsm.initial_state,
        target_length,
        max_total_length=max_length,
        rng=rng,
    )
    if not steps:
        return None
    return OracleScenario(
        id=scenario_id,
        description=f"Random behavioural walk ({len(steps)} steps).",
        steps=steps,
    )


def _depth_forced_seed(fsm: FSM, depth: DepthLevel) -> int:
    return zlib.crc32(f"{fsm.id}:depth-forced:{depth}".encode()) & 0xFFFFFFFF


def generate_depth_forced_oracle_suite(
    fsm: FSM,
    *,
    depth: DepthLevel = "medium",
) -> OracleGenerationResult:
    """Generate oracle suites whose executed walk lengths reflect depth presets."""
    if depth not in DEPTH_FORCED_TARGETS:
        msg = f"Depth-forced generation does not support depth '{depth}'"
        raise OracleGeneratorError(msg)

    config = DEPTH_FORCED_TARGETS[depth]
    declared_max_depth = DEPTH_MAX_STEPS[depth]
    target_mean = int(config["target_mean_steps"])
    target_max = int(config["target_max_steps"])
    min_extra = int(config["min_extra_scenarios"])

    base = generate_oracle_suite(fsm, depth=depth)
    rng = random.Random(_depth_forced_seed(fsm, depth))
    extended: list[OracleScenario] = []
    for index, scenario in enumerate(base.suite.scenarios):
        per_scenario_target = min(
            target_max,
            max(target_mean, target_mean + (index % 3)),
        )
        extended.append(
            _extend_scenario_to_target_length(
                fsm,
                scenario,
                target_length=per_scenario_target,
                max_length=target_max,
                rng=rng,
            )
        )

    extra_index = 0
    while len(extended) < len(base.suite.scenarios) + min_extra:
        scenario = _random_walk_scenario(
            fsm,
            scenario_id=f"depth_forced_walk_{extra_index}",
            target_length=target_max,
            max_length=target_max,
            rng=rng,
        )
        if scenario is None:
            break
        extended.append(scenario)
        extra_index += 1

    _, _, observed_max = _scenario_length_stats(extended)
    attempt = 0
    while observed_max < target_mean and attempt < min_extra + 4:
        scenario = _random_walk_scenario(
            fsm,
            scenario_id=f"depth_forced_boost_{attempt}",
            target_length=target_max,
            max_length=target_max,
            rng=rng,
        )
        if scenario is None:
            break
        extended.append(scenario)
        _, _, observed_max = _scenario_length_stats(extended)
        attempt += 1

    scenarios = _dedupe_scenarios(extended)
    if not scenarios:
        msg = "Could not generate any depth-forced oracle scenarios for the FSM"
        raise OracleGeneratorError(msg)

    suite = OracleSuite(
        id=f"{fsm.id}_oracles_depth_forced_{depth}",
        fsm_id=fsm.id,
        scenarios=scenarios,
    )
    final_coverage = compute_coverage(fsm, suite)
    mean_len, median_len, max_len = _scenario_length_stats(scenarios)
    return OracleGenerationResult(
        suite=suite,
        coverage=final_coverage,
        declared_max_depth=declared_max_depth,
        mean_scenario_length=mean_len,
        median_scenario_length=median_len,
        max_scenario_length=max_len,
        scenario_policy="depth-forced",
    )


def reachable_state_ids(fsm: FSM) -> set[str]:
    """Return states reachable from the FSM initial state."""
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


def _outgoing_transitions(fsm: FSM, state_id: str) -> list[Transition]:
    return [transition for transition in fsm.transitions if transition.source == state_id]


def _transition_step(transition: Transition) -> OracleStep:
    return OracleStep(
        event=transition.event,
        guard=transition.guard,
        expected_state=transition.target,
    )


def find_path_to_state(fsm: FSM, target_state: str, *, max_depth: int) -> list[OracleStep] | None:
    """Find a shortest step sequence from initial state to *target_state*."""
    if fsm.initial_state == target_state:
        return []

    visited: set[str] = {fsm.initial_state}
    queue: deque[tuple[str, list[OracleStep]]] = deque([(fsm.initial_state, [])])

    while queue:
        current_state, steps = queue.popleft()
        if len(steps) >= max_depth:
            continue

        for transition in _outgoing_transitions(fsm, current_state):
            next_steps = steps + [_transition_step(transition)]
            next_state = transition.target
            if next_state == target_state:
                return next_steps
            if next_state in visited:
                continue
            if len(next_steps) >= max_depth:
                continue
            visited.add(next_state)
            queue.append((next_state, next_steps))

    return None


def _reachable_transitions(fsm: FSM) -> list[Transition]:
    reachable = reachable_state_ids(fsm)
    return [transition for transition in fsm.transitions if transition.source in reachable]


def _scenario_for_transition(
    fsm: FSM,
    transition: Transition,
    *,
    max_depth: int,
) -> OracleScenario | None:
    prefix = find_path_to_state(fsm, transition.source, max_depth=max_depth)
    if prefix is None:
        return None

    steps = prefix + [_transition_step(transition)]
    return OracleScenario(
        id=f"cover_transition_{transition.id}",
        description=(
            f"Covers transition '{transition.id}' "
            f"({transition.source} --{transition.event}--> {transition.target})."
        ),
        steps=steps,
    )


def _scenario_for_state(fsm: FSM, state_id: str, *, max_depth: int) -> OracleScenario | None:
    steps = find_path_to_state(fsm, state_id, max_depth=max_depth)
    if steps is None:
        return None
    return OracleScenario(
        id=f"cover_state_{state_id}",
        description=f"Reaches state '{state_id}'.",
        steps=steps,
    )


def _scenario_for_event(fsm: FSM, event: str, *, max_depth: int) -> OracleScenario | None:
    for transition in _reachable_transitions(fsm):
        if transition.event != event:
            continue
        scenario = _scenario_for_transition(fsm, transition, max_depth=max_depth)
        if scenario is None:
            continue
        return OracleScenario(
            id=f"cover_event_{event}",
            description=f"Covers event '{event}' via transition '{transition.id}'.",
            steps=scenario.steps,
        )
    return None


def _dedupe_scenarios(scenarios: Iterable[OracleScenario]) -> list[OracleScenario]:
    seen: set[tuple[tuple[str | None, str, str | None], ...]] = set()
    unique: list[OracleScenario] = []
    for scenario in scenarios:
        key = tuple(
            (step.guard, step.event, step.expected_state) for step in scenario.steps
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(scenario)
    return unique


def compute_coverage(fsm: FSM, suite: OracleSuite) -> OracleCoverageMetrics:
    """Compute state, transition, and event coverage for *suite* over *fsm*."""
    reachable = reachable_state_ids(fsm)
    reachable_transitions = _reachable_transitions(fsm)
    reachable_events = {transition.event for transition in reachable_transitions}
    if not reachable_events:
        reachable_events = set(fsm.events)

    covered_states: set[str] = {fsm.initial_state}
    covered_transitions: set[str] = set()
    covered_events: set[str] = set()

    for scenario in suite.scenarios:
        current_state = fsm.initial_state
        for step in scenario.steps:
            covered_events.add(step.event)
            matched: Transition | None = None
            for transition in _outgoing_transitions(fsm, current_state):
                if transition.event != step.event:
                    continue
                if step.guard != transition.guard:
                    continue
                matched = transition
                break
            if matched is None:
                break
            covered_transitions.add(matched.id)
            current_state = matched.target
            covered_states.add(current_state)

    state_total = len(reachable) or 1
    transition_total = len(reachable_transitions) or 1
    event_total = len(reachable_events) or 1

    return OracleCoverageMetrics(
        state_coverage=len(covered_states & reachable) / state_total,
        transition_coverage=len(covered_transitions) / transition_total,
        event_coverage=len(covered_events & reachable_events) / event_total,
        covered_states=tuple(sorted(covered_states & reachable)),
        covered_transitions=tuple(sorted(covered_transitions)),
        covered_events=tuple(sorted(covered_events & reachable_events)),
        total_states=state_total,
        total_transitions=transition_total,
        total_events=event_total,
    )


def generate_oracle_suite(
    fsm: FSM,
    *,
    depth: DepthLevel = "medium",
    policy: ScenarioPolicy = "shortest-path",
) -> OracleGenerationResult:
    """Generate an oracle suite by traversing paths in *fsm*."""
    if policy == "depth-forced":
        return generate_depth_forced_oracle_suite(fsm, depth=depth)

    max_depth = DEPTH_MAX_STEPS[depth]
    scenarios: list[OracleScenario] = []

    for transition in _reachable_transitions(fsm):
        scenario = _scenario_for_transition(fsm, transition, max_depth=max_depth)
        if scenario is not None:
            scenarios.append(scenario)

    coverage = compute_coverage(fsm, OracleSuite(id="temp", scenarios=scenarios))
    reachable = reachable_state_ids(fsm)
    reachable_events = {transition.event for transition in _reachable_transitions(fsm)}

    missing_states = reachable - set(coverage.covered_states)
    for state_id in sorted(missing_states):
        scenario = _scenario_for_state(fsm, state_id, max_depth=max_depth)
        if scenario is not None:
            scenarios.append(scenario)

    coverage = compute_coverage(fsm, OracleSuite(id="temp", scenarios=scenarios))
    missing_events = reachable_events - set(coverage.covered_events)
    for event in sorted(missing_events):
        scenario = _scenario_for_event(fsm, event, max_depth=max_depth)
        if scenario is not None:
            scenarios.append(scenario)

    scenarios = _dedupe_scenarios(scenarios)
    if not scenarios:
        msg = "Could not generate any oracle scenarios for the FSM"
        raise OracleGeneratorError(msg)

    suite = OracleSuite(
        id=f"{fsm.id}_oracles",
        fsm_id=fsm.id,
        scenarios=scenarios,
    )
    final_coverage = compute_coverage(fsm, suite)
    mean_len, median_len, max_len = _scenario_length_stats(scenarios)
    return OracleGenerationResult(
        suite=suite,
        coverage=final_coverage,
        declared_max_depth=max_depth,
        mean_scenario_length=mean_len,
        median_scenario_length=median_len,
        max_scenario_length=max_len,
        scenario_policy="shortest-path",
    )


def export_oracle_json(suite: OracleSuite, path: Path) -> None:
    """Write *suite* to *path* in benchmark JSON format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(suite.model_dump_json(indent=2) + "\n", encoding="utf-8")
