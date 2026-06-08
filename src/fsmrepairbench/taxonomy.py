"""Literature-informed taxonomy and feature inference for benchmark cases."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field

from fsmrepairbench.difficulty import (
    compute_cycle_count,
    compute_difficulty_metrics,
    compute_strongly_connected_components,
    reachable_state_ids,
)
from fsmrepairbench.models import FSM, OracleSuite
from fsmrepairbench.semantics import infer_structural_features


class MachineType(StrEnum):
    PLAIN_FSM = "plain_fsm"
    MEALY = "mealy"
    MOORE = "moore"
    EFSM = "efsm"
    TIMED_FSM = "timed_fsm"
    TIMED_EFSM = "timed_efsm"
    PROBABILISTIC_FSM = "probabilistic_fsm"
    NONDETERMINISTIC_FSM = "nondeterministic_fsm"


class Determinism(StrEnum):
    DETERMINISTIC = "deterministic"
    NONDETERMINISTIC = "nondeterministic"


class Completeness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class ArityClass(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


class SizeClass(StrEnum):
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    VERY_LARGE = "very_large"


class GuardComplexity(StrEnum):
    NONE = "none"
    SIMPLE = "simple"
    COMPOUND = "compound"
    NESTED = "nested"


class TimeFeature(StrEnum):
    NONE = "none"
    TIMEOUT = "timeout"
    TIMED_GUARD = "timed_guard"
    OUTPUT_DELAY = "output_delay"
    TIMED_GUARD_AND_TIMEOUT = "timed_guard_and_timeout"


class GraphStructure(StrEnum):
    ACYCLIC = "acyclic"
    CYCLIC = "cyclic"
    STRONGLY_CONNECTED = "strongly_connected"
    SPARSE = "sparse"
    DENSE = "dense"
    HUB_AND_SPOKE = "hub_and_spoke"
    LAYERED = "layered"


class SemanticsFeature(StrEnum):
    NONDETERMINISM = "nondeterminism"
    PROBABILITY = "probability"
    REFUSAL = "refusal"
    QUIESCENCE = "quiescence"
    DISCRETE_TIME = "discrete_time"
    CYCLES = "cycles"


class OracleDepth(StrEnum):
    SHALLOW = "shallow"
    MEDIUM = "medium"
    DEEP = "deep"
    EXHAUSTIVE_LIKE = "exhaustive_like"


class BugType(StrEnum):
    MISSING_TRANSITION = "missing_transition"
    WRONG_TARGET = "wrong_target"
    WRONG_SOURCE = "wrong_source"
    WRONG_EVENT = "wrong_event"
    WRONG_INITIAL_STATE = "wrong_initial_state"
    DUPLICATE_TRANSITION = "duplicate_transition"
    DEAD_STATE_INTRO = "dead_state_intro"
    GUARD_FLIP = "guard_flip"
    GUARD_WEAKEN = "guard_weaken"
    GUARD_STRENGTHEN = "guard_strengthen"
    ACTION_CORRUPTION = "action_corruption"
    TIMEOUT_CORRUPTION = "timeout_corruption"
    DELAY_CORRUPTION = "delay_corruption"
    NONDETERMINISM_INTRO = "nondeterminism_intro"
    UNREACHABLE_STATE_INTRO = "unreachable_state_intro"


class CaseFeatures(BaseModel):
    """Machine-readable taxonomic features for one benchmark case."""

    case_id: str
    machine_type: MachineType
    determinism: Determinism
    completeness: Completeness
    arity_class: ArityClass
    size_class: SizeClass
    guard_complexity: GuardComplexity
    time_features: list[TimeFeature]
    graph_structure: list[GraphStructure]
    oracle_depth: OracleDepth
    bug_type: BugType
    num_states: int
    num_events: int
    num_transitions: int
    avg_out_degree: float
    max_out_degree: int
    num_guards: int
    num_timed_guards: int
    num_timeouts: int
    num_cycles: int | None
    scc_count: int | None
    has_nondeterminism: bool = False
    has_probabilities: bool = False
    has_cycles: bool = False
    has_refusals: bool = False
    has_discrete_time: bool = False
    cycle_count: int | None = None
    strongly_connected_component_count: int | None = None
    semantics_features: list[SemanticsFeature] = Field(default_factory=list)
    seed: int


def bug_type_to_operator(bug_type: BugType) -> str:
    """Return the mutation operator name for *bug_type*."""
    return bug_type.value


def infer_size_class(num_states: int) -> SizeClass:
    """Map a state count to a size class."""
    if num_states <= 3:
        return SizeClass.TINY
    if num_states <= 7:
        return SizeClass.SMALL
    if num_states <= 15:
        return SizeClass.MEDIUM
    if num_states <= 30:
        return SizeClass.LARGE
    return SizeClass.VERY_LARGE


def infer_arity_class(avg_out_degree: float, max_out_degree: int) -> ArityClass:
    """Map branching statistics to an arity class."""
    if avg_out_degree <= 1.5 and max_out_degree <= 2:
        return ArityClass.LOW
    if avg_out_degree <= 3.0 and max_out_degree <= 4:
        return ArityClass.MEDIUM
    if avg_out_degree <= 5.0 and max_out_degree <= 8:
        return ArityClass.HIGH
    return ArityClass.VERY_HIGH


def _outgoing_counts(fsm: FSM, reachable: set[str]) -> dict[str, int]:
    counts: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable:
            counts[transition.source] += 1
    return counts


def infer_determinism(fsm: FSM) -> Determinism:
    """Detect whether *fsm* is deterministic on (source, event, guard) triples."""
    reachable = reachable_state_ids(fsm)
    seen: set[tuple[str, str, str | None]] = set()
    for transition in fsm.transitions:
        if transition.source not in reachable:
            continue
        triple = (transition.source, transition.event, transition.guard)
        if triple in seen:
            return Determinism.NONDETERMINISTIC
        seen.add(triple)
    return Determinism.DETERMINISTIC


def infer_completeness(fsm: FSM) -> Completeness:
    """Detect whether all reachable state/event pairs have at least one transition."""
    reachable = reachable_state_ids(fsm)
    if not reachable or not fsm.events:
        return Completeness.PARTIAL

    covered: set[tuple[str, str]] = set()
    for transition in fsm.transitions:
        if transition.source in reachable:
            covered.add((transition.source, transition.event))

    expected = len(reachable) * len(fsm.events)
    return Completeness.COMPLETE if len(covered) >= expected else Completeness.PARTIAL


def _guard_text(transition) -> str:
    return transition.guard or ""


def infer_guard_complexity(fsm: FSM) -> GuardComplexity:
    """Classify guard expressions in *fsm*."""
    guards = [_guard_text(transition) for transition in fsm.transitions if transition.guard]
    if not guards:
        return GuardComplexity.NONE

    has_nested = any("(" in guard and ")" in guard for guard in guards)
    has_compound = any(
        token in guard.lower() for guard in guards for token in (" and ", " or ", "&&", "||")
    )
    if has_nested:
        return GuardComplexity.NESTED
    if has_compound:
        return GuardComplexity.COMPOUND
    return GuardComplexity.SIMPLE


def infer_time_features(fsm: FSM) -> list[TimeFeature]:
    """Detect timed features present in *fsm*."""
    features: list[TimeFeature] = []
    has_timeout = any(transition.timeout is not None for transition in fsm.transitions)
    has_delay = any(transition.delay is not None for transition in fsm.transitions)
    has_timed_guard = any(
        transition.guard and any(token in transition.guard.lower() for token in ("time", "t >", "t <"))
        for transition in fsm.transitions
    )

    if not has_timeout and not has_delay and not has_timed_guard:
        return [TimeFeature.NONE]
    if has_timed_guard and has_timeout:
        features.append(TimeFeature.TIMED_GUARD_AND_TIMEOUT)
    if has_timeout:
        features.append(TimeFeature.TIMEOUT)
    if has_timed_guard:
        features.append(TimeFeature.TIMED_GUARD)
    if has_delay:
        features.append(TimeFeature.OUTPUT_DELAY)
    return features or [TimeFeature.NONE]


def infer_graph_structure(fsm: FSM) -> list[GraphStructure]:
    """Infer coarse graph-structure tags for *fsm*."""
    reachable = reachable_state_ids(fsm)
    if not reachable:
        return [GraphStructure.SPARSE]

    outgoing = _outgoing_counts(fsm, reachable)
    avg_out = sum(outgoing.values()) / len(outgoing)
    max_out = max(outgoing.values()) if outgoing else 0
    components = compute_strongly_connected_components(fsm, reachable)
    cycles = compute_cycle_count(fsm, reachable, components)

    tags: list[GraphStructure] = []
    if cycles == 0:
        tags.append(GraphStructure.ACYCLIC)
    else:
        tags.append(GraphStructure.CYCLIC)
    if len(components) == 1 and len(reachable) > 1:
        tags.append(GraphStructure.STRONGLY_CONNECTED)
    if avg_out <= 1.5:
        tags.append(GraphStructure.SPARSE)
    elif avg_out >= 4.0:
        tags.append(GraphStructure.DENSE)

    hub_state = fsm.initial_state
    hub_edges = outgoing.get(hub_state, 0)
    if hub_edges >= max(2, len(reachable) - 1):
        tags.append(GraphStructure.HUB_AND_SPOKE)

    if _looks_layered(fsm, reachable):
        tags.append(GraphStructure.LAYERED)

    return tags or [GraphStructure.SPARSE]


def _looks_layered(fsm: FSM, reachable: set[str]) -> bool:
    """Return whether reachable states appear arranged in forward layers."""
    index_map = {state.id: index for index, state in enumerate(fsm.states)}
    forward = 0
    total = 0
    for transition in fsm.transitions:
        if transition.source not in reachable or transition.target not in reachable:
            continue
        total += 1
        if index_map.get(transition.target, 0) >= index_map.get(transition.source, 0):
            forward += 1
    return total > 0 and forward / total >= 0.8


def infer_machine_type(fsm: FSM) -> MachineType:
    """Infer the machine family from optional schema fields."""
    structural = infer_structural_features(fsm)
    if structural.has_probabilities:
        return MachineType.PROBABILISTIC_FSM
    if structural.has_nondeterminism:
        return MachineType.NONDETERMINISTIC_FSM

    has_timeout = any(transition.timeout is not None for transition in fsm.transitions)
    has_delay = any(transition.delay is not None for transition in fsm.transitions)
    has_variables = bool(fsm.variables)
    has_mealy_output = any(transition.output for transition in fsm.transitions)
    has_moore_output = any(state.state_output for state in fsm.states)

    if has_variables and (has_timeout or has_delay):
        return MachineType.TIMED_EFSM
    if has_timeout or has_delay:
        return MachineType.TIMED_FSM
    if has_variables:
        return MachineType.EFSM
    if has_moore_output:
        return MachineType.MOORE
    if has_mealy_output:
        return MachineType.MEALY
    return MachineType.PLAIN_FSM


def infer_oracle_depth(oracle_suite: OracleSuite | None) -> OracleDepth:
    """Estimate oracle depth from scenario length."""
    if oracle_suite is None or not oracle_suite.scenarios:
        return OracleDepth.SHALLOW

    max_steps = max(len(scenario.steps) for scenario in oracle_suite.scenarios)
    scenario_count = len(oracle_suite.scenarios)
    if max_steps <= 5 and scenario_count <= 6:
        return OracleDepth.SHALLOW
    if max_steps <= 12 and scenario_count <= 20:
        return OracleDepth.MEDIUM
    if max_steps <= 25:
        return OracleDepth.DEEP
    return OracleDepth.EXHAUSTIVE_LIKE


def infer_semantics_features(fsm: FSM) -> list[SemanticsFeature]:
    """Infer semantics-oriented taxonomy tags for benchmark slicing."""
    structural = infer_structural_features(fsm)
    tags: list[SemanticsFeature] = []
    if structural.has_nondeterminism:
        tags.append(SemanticsFeature.NONDETERMINISM)
    if structural.has_probabilities:
        tags.append(SemanticsFeature.PROBABILITY)
    if structural.has_refusals:
        tags.append(SemanticsFeature.REFUSAL)
    if structural.has_discrete_time:
        tags.append(SemanticsFeature.DISCRETE_TIME)
    if structural.has_cycles:
        tags.append(SemanticsFeature.CYCLES)
    if any(state.quiescence for state in fsm.states) or any(
        transition.quiescence for transition in fsm.transitions
    ):
        tags.append(SemanticsFeature.QUIESCENCE)
    return tags


def compute_case_features(
    fsm: FSM,
    oracle_suite: OracleSuite | None,
    bug_type: BugType,
    seed: int,
    *,
    case_id: str = "",
    oracle_depth: OracleDepth | None = None,
) -> CaseFeatures:
    """Compute taxonomic features for one generated case."""
    metrics = compute_difficulty_metrics(fsm)
    reachable = reachable_state_ids(fsm)
    outgoing = _outgoing_counts(fsm, reachable)
    max_out_degree = max(outgoing.values()) if outgoing else 0
    components = compute_strongly_connected_components(fsm, reachable)
    num_guards = sum(1 for transition in fsm.transitions if transition.guard)
    num_timed_guards = sum(
        1
        for transition in fsm.transitions
        if transition.guard
        and any(token in transition.guard.lower() for token in ("time", "t >", "t <"))
    )
    num_timeouts = sum(1 for transition in fsm.transitions if transition.timeout is not None)
    structural = infer_structural_features(fsm)

    return CaseFeatures(
        case_id=case_id,
        machine_type=infer_machine_type(fsm),
        determinism=infer_determinism(fsm),
        completeness=infer_completeness(fsm),
        arity_class=infer_arity_class(metrics.branching_factor, max_out_degree),
        size_class=infer_size_class(metrics.state_count),
        guard_complexity=infer_guard_complexity(fsm),
        time_features=infer_time_features(fsm),
        graph_structure=infer_graph_structure(fsm),
        oracle_depth=oracle_depth or infer_oracle_depth(oracle_suite),
        bug_type=bug_type,
        num_states=metrics.state_count,
        num_events=len(fsm.events),
        num_transitions=metrics.transition_count,
        avg_out_degree=round(metrics.branching_factor, 4),
        max_out_degree=max_out_degree,
        num_guards=num_guards,
        num_timed_guards=num_timed_guards,
        num_timeouts=num_timeouts,
        num_cycles=metrics.cycles,
        scc_count=metrics.strongly_connected_components,
        has_nondeterminism=structural.has_nondeterminism,
        has_probabilities=structural.has_probabilities,
        has_cycles=structural.has_cycles,
        has_refusals=structural.has_refusals,
        has_discrete_time=structural.has_discrete_time,
        cycle_count=structural.cycle_count,
        strongly_connected_component_count=structural.strongly_connected_component_count,
        semantics_features=infer_semantics_features(fsm),
        seed=seed,
    )
