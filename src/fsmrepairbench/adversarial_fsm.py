"""Adversarial FSM generation for LLM stress testing."""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.validators import validate_fsm

AdversarialPattern = Literal[
    "highly_symmetric",
    "long_dependency_chain",
    "hidden_cycles",
    "equivalent_states",
    "deceptive_transitions",
    "sparse_transitions",
    "dense_transitions",
    "delayed_effects",
    "temporal_constraints",
]

SUPPORTED_ADVERSARIAL_PATTERNS: tuple[AdversarialPattern, ...] = (
    "highly_symmetric",
    "long_dependency_chain",
    "hidden_cycles",
    "equivalent_states",
    "deceptive_transitions",
    "sparse_transitions",
    "dense_transitions",
    "delayed_effects",
    "temporal_constraints",
)

PATTERN_BASE_RANK: dict[AdversarialPattern, int] = {
    "sparse_transitions": 2,
    "highly_symmetric": 6,
    "long_dependency_chain": 5,
    "hidden_cycles": 7,
    "equivalent_states": 8,
    "deceptive_transitions": 7,
    "dense_transitions": 6,
    "delayed_effects": 8,
    "temporal_constraints": 9,
}

PATTERN_DESCRIPTIONS: dict[AdversarialPattern, str] = {
    "highly_symmetric": "Mirror-image branches with identical event labels and parallel structure.",
    "long_dependency_chain": "Sequential unlock chain where later transitions depend on earlier tokens.",
    "hidden_cycles": "Behavioural cycle concealed behind several intermediate states.",
    "equivalent_states": "Bisimilar states that appear mergeable but must remain distinct.",
    "deceptive_transitions": "Misleading event and guard names that contradict their effects.",
    "sparse_transitions": "Large state space with very few observable transitions.",
    "dense_transitions": "High branching with many guarded alternatives per state.",
    "delayed_effects": "Visible state changes deferred until an arming sequence completes.",
    "temporal_constraints": "Discrete-time transitions that must fire in strict order.",
}

METADATA_CSV_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "filename",
    "metadata_filename",
    "pattern",
    "seed",
    "difficulty_rank",
    "difficulty_label",
    "state_count",
    "transition_count",
    "event_count",
    "llm_trap_count",
)

DifficultyLabel = Literal["trivial", "easy", "moderate", "hard", "very_hard", "expert"]


class AdversarialFSMError(ValueError):
    """Raised when adversarial FSM generation fails."""


class AdversarialDifficultyMetadata(BaseModel):
    """Difficulty metadata for one adversarial FSM."""

    rank: int = Field(ge=1, le=10)
    label: DifficultyLabel
    pattern: AdversarialPattern
    pattern_base_rank: int = Field(ge=1, le=10)
    structural_adjustment: int = Field(ge=0)
    scale_factor: float = Field(ge=0.0, le=2.0)
    features: dict[str, int | float | bool | str | list[str]] = Field(default_factory=dict)
    llm_trap_signals: list[str] = Field(default_factory=list)
    description: str = ""


class AdversarialFSMMetadata(BaseModel):
    """Full metadata record for one adversarial FSM."""

    fsm_id: str
    filename: str
    metadata_filename: str
    pattern: AdversarialPattern
    seed: int
    difficulty: AdversarialDifficultyMetadata
    state_count: int
    transition_count: int
    event_count: int
    initial_state: str
    events: list[str]

    def to_csv_row(self) -> dict[str, object]:
        return {
            "fsm_id": self.fsm_id,
            "filename": self.filename,
            "metadata_filename": self.metadata_filename,
            "pattern": self.pattern,
            "seed": self.seed,
            "difficulty_rank": self.difficulty.rank,
            "difficulty_label": self.difficulty.label,
            "state_count": self.state_count,
            "transition_count": self.transition_count,
            "event_count": self.event_count,
            "llm_trap_count": len(self.difficulty.llm_trap_signals),
        }


@dataclass(frozen=True)
class AdversarialGenerationResult:
    """Paths written for one adversarial FSM."""

    fsm: FSM
    metadata: AdversarialFSMMetadata
    fsm_path: Path
    metadata_path: Path


@dataclass(frozen=True)
class AdversarialDatasetResult:
    """Paths written for an adversarial FSM dataset."""

    output_dir: Path
    metadata_csv_path: Path
    records: tuple[AdversarialFSMMetadata, ...]


def rank_label(rank: int) -> DifficultyLabel:
    """Map a 1-10 rank to a human-readable label."""
    if rank <= 2:
        return "trivial"
    if rank <= 4:
        return "easy"
    if rank <= 5:
        return "moderate"
    if rank <= 7:
        return "hard"
    if rank <= 9:
        return "very_hard"
    return "expert"


def compute_difficulty_rank(
    fsm: FSM,
    pattern: AdversarialPattern,
    *,
    scale: float = 1.0,
    extra_adjustment: int = 0,
    features: dict[str, int | float | bool | str | list[str]] | None = None,
) -> AdversarialDifficultyMetadata:
    """Compute a 1-10 difficulty rank for an adversarial FSM."""
    base = PATTERN_BASE_RANK[pattern]
    adjustment = extra_adjustment
    if len(fsm.states) >= 14:
        adjustment += 1
    if len(fsm.transitions) >= 28:
        adjustment += 1
    if scale >= 1.25:
        adjustment += 1

    feature_values = features or {}
    if isinstance(feature_values.get("chain_length"), int) and feature_values["chain_length"] >= 10:
        adjustment += 1
    if isinstance(feature_values.get("symmetry_depth"), int) and feature_values["symmetry_depth"] >= 4:
        adjustment += 1
    if isinstance(feature_values.get("hidden_cycle_length"), int) and feature_values["hidden_cycle_length"] >= 4:
        adjustment += 1

    rank = max(1, min(10, base + adjustment))
    traps = _default_trap_signals(pattern, feature_values)
    return AdversarialDifficultyMetadata(
        rank=rank,
        label=rank_label(rank),
        pattern=pattern,
        pattern_base_rank=base,
        structural_adjustment=adjustment,
        scale_factor=round(scale, 4),
        features=feature_values,
        llm_trap_signals=traps,
        description=PATTERN_DESCRIPTIONS[pattern],
    )


def _default_trap_signals(
    pattern: AdversarialPattern,
    features: dict[str, int | float | bool | str | list[str]],
) -> list[str]:
    traps = [f"pattern:{pattern}"]
    if pattern == "highly_symmetric":
        traps.append("symmetric_branch_confusion")
    elif pattern == "long_dependency_chain":
        traps.append("order_sensitive_unlock_chain")
    elif pattern == "hidden_cycles":
        traps.append("locally_acyclic_global_cycle")
    elif pattern == "equivalent_states":
        traps.append("spurious_state_merge")
    elif pattern == "deceptive_transitions":
        traps.append("misleading_event_names")
    elif pattern == "sparse_transitions":
        traps.append("underconnected_state_space")
    elif pattern == "dense_transitions":
        traps.append("guard_selection_overload")
    elif pattern == "delayed_effects":
        traps.append("deferred_state_change")
    elif pattern == "temporal_constraints":
        traps.append("ordered_discrete_time_steps")
    for key in ("equivalent_pair", "deceptive_events", "hidden_cycle_states"):
        value = features.get(key)
        if isinstance(value, list) and value:
            traps.append(f"{key}:{'|'.join(str(item) for item in value)}")
    return traps


def _finalize(
    fsm: FSM,
    *,
    pattern: AdversarialPattern,
    seed: int,
    scale: float,
    extra_adjustment: int,
    features: dict[str, int | float | bool | str | list[str]],
) -> tuple[FSM, AdversarialDifficultyMetadata]:
    errors = validate_fsm(fsm)
    if errors:
        msg = f"Generated invalid adversarial FSM ({pattern}): {errors[0]}"
        raise AdversarialFSMError(msg)
    difficulty = compute_difficulty_rank(
        fsm,
        pattern,
        scale=scale,
        extra_adjustment=extra_adjustment,
        features=features,
    )
    return fsm, difficulty


def _scale_from_seed(seed: int) -> float:
    return 1.0 + ((seed % 5) * 0.1)


def generate_highly_symmetric_fsm(seed: int, *, depth: int = 4) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate a symmetric twin-branch FSM."""
    rng = random.Random(seed)
    depth = max(3, depth + (seed % 2))
    left_states = [f"left_{index}" for index in range(depth)]
    right_states = [f"right_{index}" for index in range(depth)]
    states = [State(id="root"), *(State(id=state_id) for state_id in left_states + right_states)]
    events = ["choose_left", "choose_right", "advance", "mirror_advance", "converge"]
    transitions: list[Transition] = [
        Transition(id="t_root_left", source="root", event="choose_left", target=left_states[0]),
        Transition(id="t_root_right", source="root", event="choose_right", target=right_states[0]),
    ]
    counter = 2
    for index in range(depth - 1):
        counter += 1
        transitions.append(
            Transition(
                id=f"t_left_{counter}",
                source=left_states[index],
                event="advance",
                target=left_states[index + 1],
            )
        )
        counter += 1
        transitions.append(
            Transition(
                id=f"t_right_{counter}",
                source=right_states[index],
                event="mirror_advance",
                target=right_states[index + 1],
            )
        )
    counter += 1
    transitions.append(
        Transition(
            id=f"t_left_converge_{counter}",
            source=left_states[-1],
            event="converge",
            target=right_states[-1],
        )
    )
    counter += 1
    transitions.append(
        Transition(
            id=f"t_right_converge_{counter}",
            source=right_states[-1],
            event="converge",
            target=left_states[-1],
        )
    )
    if rng.random() < 0.5:
        counter += 1
        transitions.append(
            Transition(
                id=f"t_cross_{counter}",
                source=left_states[depth // 2],
                event="mirror_advance",
                target=right_states[depth // 2],
            )
        )

    fsm = FSM(
        id=f"adv_symmetric_{seed}",
        name=f"Adversarial symmetric FSM ({seed})",
        description=(
            "Highly symmetric branches with parallel structure designed to confuse "
            "transition-table inference and next-state prediction."
        ),
        states=states,
        initial_state="root",
        events=events,
        transitions=transitions,
    )
    features = {
        "symmetry_depth": depth,
        "branch_count": 2,
        "mirror_events": ["advance", "mirror_advance"],
    }
    return _finalize(
        fsm,
        pattern="highly_symmetric",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=max(0, depth - 3),
        features=features,
    )


def generate_long_dependency_chain_fsm(
    seed: int,
    *,
    chain_length: int = 8,
) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate a sequential unlock-chain FSM."""
    chain_length = max(5, chain_length + (seed % 3))
    states = [State(id=f"stage_{index}") for index in range(chain_length)]
    events = ["unlock", "advance", "commit"]
    transitions: list[Transition] = []
    transitions.append(
        Transition(
            id="t_unlock_0",
            source="stage_0",
            event="unlock",
            target="stage_0",
            guard="token_0",
            action="set_token_1",
        )
    )
    for index in range(chain_length - 1):
        transitions.append(
            Transition(
                id=f"t_advance_{index}",
                source=f"stage_{index}",
                event="advance",
                target=f"stage_{index + 1}",
                guard=f"token_{index + 1}",
            )
        )
        transitions.append(
            Transition(
                id=f"t_unlock_{index + 1}",
                source=f"stage_{index}",
                event="unlock",
                target=f"stage_{index}",
                guard=f"token_{index + 1}",
                action=f"prepare_token_{index + 2}",
            )
        )
    transitions.append(
        Transition(
            id="t_commit",
            source=f"stage_{chain_length - 1}",
            event="commit",
            target=f"stage_{chain_length - 1}",
            guard=f"token_{chain_length}",
            action="done",
        )
    )
    fsm = FSM(
        id=f"adv_chain_{seed}",
        name=f"Adversarial dependency chain ({seed})",
        description=(
            "Long dependency chain where each advance step depends on prior unlock tokens."
        ),
        states=states,
        initial_state="stage_0",
        events=events,
        transitions=transitions,
    )
    return _finalize(
        fsm,
        pattern="long_dependency_chain",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=max(0, (chain_length - 5) // 3),
        features={"chain_length": chain_length, "unlock_stages": chain_length},
    )


def generate_hidden_cycles_fsm(seed: int) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate an FSM with a cycle hidden behind intermediate states."""
    cycle_states = [f"cycle_{index}" for index in range(4)]
    states = [
        State(id="entry"),
        State(id="buffer"),
        *(State(id=state_id) for state_id in cycle_states),
        State(id="exit"),
    ]
    events = ["enter", "shift", "rotate", "escape", "finish"]
    transitions = [
        Transition(id="t_entry", source="entry", event="enter", target="buffer"),
        Transition(id="t_buffer", source="buffer", event="shift", target=cycle_states[0]),
        Transition(id="t_c0", source=cycle_states[0], event="rotate", target=cycle_states[1]),
        Transition(id="t_c1", source=cycle_states[1], event="rotate", target=cycle_states[2]),
        Transition(id="t_c2", source=cycle_states[2], event="rotate", target=cycle_states[3]),
        Transition(id="t_c3", source=cycle_states[3], event="rotate", target=cycle_states[0]),
        Transition(id="t_escape", source=cycle_states[1], event="escape", target="exit"),
        Transition(id="t_finish", source="exit", event="finish", target="exit"),
        Transition(id="t_short", source="buffer", event="finish", target="exit", guard="fast_path"),
    ]
    fsm = FSM(
        id=f"adv_hidden_cycle_{seed}",
        name=f"Adversarial hidden cycle ({seed})",
        description="Cycle concealed behind multiple intermediate states and decoy exits.",
        states=states,
        initial_state="entry",
        events=events,
        transitions=transitions,
    )
    return _finalize(
        fsm,
        pattern="hidden_cycles",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=0,
        features={
            "hidden_cycle_length": len(cycle_states),
            "hidden_cycle_states": cycle_states,
            "decoy_exit": "exit",
        },
    )


def generate_equivalent_states_fsm(seed: int) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate an FSM with bisimilar but distinct states."""
    twin_a = "twin_a"
    twin_b = "twin_b"
    states = [
        State(id="start"),
        State(id=twin_a),
        State(id=twin_b),
        State(id="sink"),
    ]
    events = ["open", "close", "noop"]
    transitions = [
        Transition(id="t_start_a", source="start", event="open", target=twin_a),
        Transition(id="t_start_b", source="start", event="open", target=twin_b, guard="alt"),
        Transition(id="t_a_open", source=twin_a, event="open", target="sink"),
        Transition(id="t_b_open", source=twin_b, event="open", target="sink"),
        Transition(id="t_a_close", source=twin_a, event="close", target=twin_a),
        Transition(id="t_b_close", source=twin_b, event="close", target=twin_b),
        Transition(id="t_a_noop", source=twin_a, event="noop", target=twin_a),
        Transition(id="t_b_noop", source=twin_b, event="noop", target=twin_b),
    ]
    fsm = FSM(
        id=f"adv_equivalent_{seed}",
        name=f"Adversarial equivalent states ({seed})",
        description="Distinct states with identical observable transitions to trap merge heuristics.",
        states=states,
        initial_state="start",
        events=events,
        transitions=transitions,
    )
    return _finalize(
        fsm,
        pattern="equivalent_states",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=0,
        features={"equivalent_pair": [twin_a, twin_b], "equivalent_count": 2},
    )


def generate_deceptive_transitions_fsm(seed: int) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate an FSM with misleading event and guard names."""
    states = [State(id="idle"), State(id="armed"), State(id="done"), State(id="blocked")]
    events = ["increment", "reset", "approve", "reject"]
    transitions = [
        Transition(
            id="t_inc",
            source="idle",
            event="increment",
            target="blocked",
            guard="looks_positive",
            action="decrease_counter",
        ),
        Transition(
            id="t_reset",
            source="blocked",
            event="reset",
            target="armed",
            guard="safe_reset",
            action="increase_counter",
        ),
        Transition(
            id="t_approve",
            source="armed",
            event="approve",
            target="done",
            guard="deny_access",
        ),
        Transition(
            id="t_reject",
            source="armed",
            event="reject",
            target="idle",
            guard="grant_access",
        ),
        Transition(
            id="t_done",
            source="done",
            event="reset",
            target="idle",
        ),
    ]
    fsm = FSM(
        id=f"adv_deceptive_{seed}",
        name=f"Adversarial deceptive transitions ({seed})",
        description="Event and guard names contradict their actual behavioural effects.",
        states=states,
        initial_state="idle",
        events=events,
        transitions=transitions,
    )
    return _finalize(
        fsm,
        pattern="deceptive_transitions",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=0,
        features={"deceptive_events": events, "misleading_guards": True},
    )


def generate_sparse_transitions_fsm(seed: int, *, num_states: int = 12) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate a large state space with very few transitions."""
    num_states = max(10, num_states + (seed % 4))
    state_ids = [f"s{index}" for index in range(num_states)]
    states = [State(id=state_id) for state_id in state_ids]
    events = ["step", "skip", "halt"]
    transitions = [
        Transition(
            id=f"t_chain_{index}",
            source=state_ids[index],
            event="step",
            target=state_ids[index + 1],
        )
        for index in range(num_states - 1)
    ]
    transitions.append(
        Transition(
            id="t_skip",
            source=state_ids[0],
            event="skip",
            target=state_ids[-1],
            guard="rare",
        )
    )
    fsm = FSM(
        id=f"adv_sparse_{seed}",
        name=f"Adversarial sparse transitions ({seed})",
        description="Sparse transition graph over many states to fool coverage and repair heuristics.",
        states=states,
        initial_state=state_ids[0],
        events=events,
        transitions=transitions,
    )
    density = len(transitions) / max(1, num_states * len(events))
    return _finalize(
        fsm,
        pattern="sparse_transitions",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=max(0, (num_states - 10) // 6),
        features={
            "state_count": num_states,
            "transition_density": round(density, 4),
            "reachable_chain_length": num_states,
        },
    )


def generate_dense_transitions_fsm(seed: int) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate a highly connected guarded transition graph."""
    rng = random.Random(seed)
    hub_states = ["hub_a", "hub_b", "hub_c"]
    leaf_states = [f"leaf_{index}" for index in range(4)]
    states = [State(id="start"), *(State(id=state_id) for state_id in hub_states + leaf_states)]
    events = ["alpha", "beta", "gamma", "delta"]
    transitions: list[Transition] = []
    counter = 0
    for source in ["start", *hub_states]:
        for event in events:
            for guard_index, target in enumerate([*hub_states, *leaf_states]):
                if source == target:
                    continue
                counter += 1
                transitions.append(
                    Transition(
                        id=f"t_dense_{counter}",
                        source=source,
                        event=event,
                        target=target,
                        guard=f"g_{source}_{event}_{guard_index}",
                    )
                )
                if len(transitions) >= 36 + rng.randint(0, 6):
                    break
            if len(transitions) >= 36 + rng.randint(0, 6):
                break
        if len(transitions) >= 36 + rng.randint(0, 6):
            break

    fsm = FSM(
        id=f"adv_dense_{seed}",
        name=f"Adversarial dense transitions ({seed})",
        description="Dense guarded transition graph designed to overload LLM attention.",
        states=states,
        initial_state="start",
        events=events,
        transitions=transitions,
    )
    return _finalize(
        fsm,
        pattern="dense_transitions",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=1 if len(transitions) >= 40 else 0,
        features={
            "transition_count": len(transitions),
            "average_out_degree": round(len(transitions) / len(states), 4),
            "guard_count": len(transitions),
        },
    )


def generate_delayed_effects_fsm(seed: int) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate an FSM where visible effects are deferred until arming completes."""
    states = [
        State(id="idle"),
        State(id="armed_a"),
        State(id="armed_b"),
        State(id="latent"),
        State(id="visible_on"),
        State(id="visible_off"),
    ]
    events = ["prepare", "prime", "trigger", "cancel"]
    transitions = [
        Transition(id="t_prepare", source="idle", event="prepare", target="armed_a"),
        Transition(id="t_prime", source="armed_a", event="prime", target="armed_b"),
        Transition(
            id="t_trigger_on",
            source="armed_b",
            event="trigger",
            target="latent",
            action="schedule_on",
        ),
        Transition(
            id="t_latent_on",
            source="latent",
            event="trigger",
            target="visible_on",
            guard="effect_ready",
        ),
        Transition(id="t_cancel", source="armed_a", event="cancel", target="idle"),
        Transition(id="t_cancel_b", source="armed_b", event="cancel", target="idle"),
        Transition(id="t_off", source="visible_on", event="cancel", target="visible_off"),
    ]
    fsm = FSM(
        id=f"adv_delayed_{seed}",
        name=f"Adversarial delayed effects ({seed})",
        description="State changes become visible only after a multi-step arming sequence.",
        states=states,
        initial_state="idle",
        events=events,
        transitions=transitions,
    )
    return _finalize(
        fsm,
        pattern="delayed_effects",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=0,
        features={"arming_steps": 3, "latent_state": "latent"},
    )


def generate_temporal_constraints_fsm(seed: int) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate an FSM with ordered discrete-time constraints."""
    states = [State(id="t0"), State(id="t1"), State(id="t2"), State(id="t3"), State(id="done")]
    events = ["tick", "measure", "finalize"]
    transitions = [
        Transition(
            id="t_tick_0",
            source="t0",
            event="tick",
            target="t1",
            discrete_time=1,
        ),
        Transition(
            id="t_tick_1",
            source="t1",
            event="tick",
            target="t2",
            discrete_time=2,
        ),
        Transition(
            id="t_measure",
            source="t2",
            event="measure",
            target="t3",
            discrete_time=3,
        ),
        Transition(
            id="t_finalize",
            source="t3",
            event="finalize",
            target="done",
            discrete_time=4,
        ),
        Transition(
            id="t_early",
            source="t0",
            event="finalize",
            target="t0",
            guard="too_early",
            discrete_time=1,
        ),
    ]
    fsm = FSM(
        id=f"adv_temporal_{seed}",
        name=f"Adversarial temporal constraints ({seed})",
        description="Discrete-time transitions must fire in strict order to reach acceptance.",
        states=states,
        initial_state="t0",
        events=events,
        transitions=transitions,
        semantics_mode="timed_discrete",
        discrete_time_step=1.0,
    )
    return _finalize(
        fsm,
        pattern="temporal_constraints",
        seed=seed,
        scale=_scale_from_seed(seed),
        extra_adjustment=0,
        features={"timed_steps": 4, "semantics_mode": "timed_discrete"},
    )


PATTERN_GENERATORS: dict[
    AdversarialPattern,
    Callable[[int], tuple[FSM, AdversarialDifficultyMetadata]],
] = {
    "highly_symmetric": generate_highly_symmetric_fsm,
    "long_dependency_chain": generate_long_dependency_chain_fsm,
    "hidden_cycles": generate_hidden_cycles_fsm,
    "equivalent_states": generate_equivalent_states_fsm,
    "deceptive_transitions": generate_deceptive_transitions_fsm,
    "sparse_transitions": generate_sparse_transitions_fsm,
    "dense_transitions": generate_dense_transitions_fsm,
    "delayed_effects": generate_delayed_effects_fsm,
    "temporal_constraints": generate_temporal_constraints_fsm,
}


def pattern_for_index(index: int) -> AdversarialPattern:
    """Select an adversarial pattern deterministically by index."""
    return SUPPORTED_ADVERSARIAL_PATTERNS[(index - 1) % len(SUPPORTED_ADVERSARIAL_PATTERNS)]


def generate_adversarial_fsm(
    pattern: AdversarialPattern,
    *,
    seed: int = 42,
) -> tuple[FSM, AdversarialDifficultyMetadata]:
    """Generate one adversarial FSM for *pattern*."""
    if pattern not in PATTERN_GENERATORS:
        msg = f"Unsupported adversarial pattern: {pattern}"
        raise AdversarialFSMError(msg)
    return PATTERN_GENERATORS[pattern](seed)


def build_metadata_record(
    fsm: FSM,
    difficulty: AdversarialDifficultyMetadata,
    *,
    pattern: AdversarialPattern,
    seed: int,
    filename: str,
    metadata_filename: str,
) -> AdversarialFSMMetadata:
    """Build a metadata record for export."""
    return AdversarialFSMMetadata(
        fsm_id=fsm.id,
        filename=filename,
        metadata_filename=metadata_filename,
        pattern=pattern,
        seed=seed,
        difficulty=difficulty,
        state_count=len(fsm.states),
        transition_count=len(fsm.transitions),
        event_count=len(fsm.events),
        initial_state=fsm.initial_state,
        events=list(fsm.events),
    )


def write_adversarial_fsm(
    output_dir: Path,
    fsm: FSM,
    metadata: AdversarialFSMMetadata,
) -> AdversarialGenerationResult:
    """Write one adversarial FSM JSON file and metadata JSON."""
    output_dir.mkdir(parents=True, exist_ok=True)
    fsm_path = output_dir / metadata.filename
    metadata_path = output_dir / metadata.metadata_filename
    fsm_path.write_text(fsm.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
    metadata_path.write_text(metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return AdversarialGenerationResult(
        fsm=fsm,
        metadata=metadata,
        fsm_path=fsm_path,
        metadata_path=metadata_path,
    )


def write_metadata_csv(path: Path, records: Sequence[AdversarialFSMMetadata]) -> None:
    """Write dataset metadata CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METADATA_CSV_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def generate_adversarial_dataset(
    *,
    output_dir: Path,
    count: int | None = None,
    seed: int = 42,
    patterns: Sequence[AdversarialPattern] | None = None,
) -> AdversarialDatasetResult:
    """Generate adversarial FSMs for every pattern or *count* indexed instances."""
    selected_patterns = tuple(patterns or SUPPORTED_ADVERSARIAL_PATTERNS)
    if not selected_patterns:
        msg = "At least one adversarial pattern must be selected"
        raise AdversarialFSMError(msg)

    total = count if count is not None else len(selected_patterns)
    if total < 1:
        msg = "count must be at least 1"
        raise AdversarialFSMError(msg)

    records: list[AdversarialFSMMetadata] = []
    for index in range(1, total + 1):
        pattern = selected_patterns[(index - 1) % len(selected_patterns)]
        instance_seed = seed + index * 1000
        fsm, difficulty = generate_adversarial_fsm(pattern, seed=instance_seed)
        filename = f"adversarial_{index:06d}.json"
        metadata_filename = f"adversarial_{index:06d}_metadata.json"
        record = build_metadata_record(
            fsm,
            difficulty,
            pattern=pattern,
            seed=instance_seed,
            filename=filename,
            metadata_filename=metadata_filename,
        )
        write_adversarial_fsm(output_dir, fsm, record)
        records.append(record)

    csv_path = output_dir / "metadata.csv"
    write_metadata_csv(csv_path, records)
    manifest_path = output_dir / "dataset_manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "dataset_kind": "adversarial_fsm",
                "seed": seed,
                "count": len(records),
                "patterns": list(selected_patterns),
                "difficulty_rank_range": {
                    "min": min(record.difficulty.rank for record in records),
                    "max": max(record.difficulty.rank for record in records),
                },
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return AdversarialDatasetResult(
        output_dir=output_dir,
        metadata_csv_path=csv_path,
        records=tuple(records),
    )
