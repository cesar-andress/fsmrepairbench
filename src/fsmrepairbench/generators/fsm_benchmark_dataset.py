"""Reproducible large-scale FSM benchmark dataset generation framework.

Generates finite-state machines spanning classic automata families (DFA, NFA,
Mealy, Moore, EFSM, timed FSM) and exports a flat dataset directory:

    dataset/
        metadata.csv
        fsm_000001.json
        fsm_000002.json
        ...
"""

from __future__ import annotations

import csv
import random
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.difficulty import (
    compute_branching_factor,
    compute_cycle_count,
    compute_strongly_connected_components,
    reachable_state_ids,
)
from fsmrepairbench.generators.synthetic_factory import (
    COMPLEXITY_PRESETS,
    SyntheticFactoryError,
    SyntheticGenerationParams,
    export_fsm_json,
    generate_synthetic_fsm,
)
from fsmrepairbench.models import CyclicStructureMetadata, FSM, State, Transition
from fsmrepairbench.validators import validate_fsm

FSMBenchmarkType = Literal["DFA", "NFA", "Mealy", "Moore", "EFSM", "Timed FSM"]

SUPPORTED_FSM_TYPES: tuple[FSMBenchmarkType, ...] = (
    "DFA",
    "NFA",
    "Mealy",
    "Moore",
    "EFSM",
    "Timed FSM",
)

METADATA_CSV_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "filename",
    "type",
    "seed",
    "num_states",
    "num_transitions",
    "alphabet_size",
    "branching_factor",
    "determinism_score",
    "reachability_score",
    "strongly_connected_components",
    "dead_states",
    "sink_states",
    "cycle_count",
)


class FSMBenchmarkDatasetError(ValueError):
    """Raised when benchmark dataset generation fails."""


@dataclass(frozen=True)
class FSMBenchmarkGenerationConfig:
    """Configuration for reproducible FSM dataset generation."""

    count: int = 10_000
    seed: int = 42
    output_dir: Path = Path("dataset")


@dataclass(frozen=True)
class FSMMetadata:
    """Structural metadata captured for one generated FSM."""

    fsm_id: str
    filename: str
    type: FSMBenchmarkType
    seed: int
    num_states: int
    num_transitions: int
    alphabet_size: int
    branching_factor: float
    determinism_score: float
    reachability_score: float
    strongly_connected_components: int
    dead_states: int
    sink_states: int
    cycle_count: int

    def to_csv_row(self) -> dict[str, object]:
        return {
            "fsm_id": self.fsm_id,
            "filename": self.filename,
            "type": self.type,
            "seed": self.seed,
            "num_states": self.num_states,
            "num_transitions": self.num_transitions,
            "alphabet_size": self.alphabet_size,
            "branching_factor": round(self.branching_factor, 4),
            "determinism_score": round(self.determinism_score, 4),
            "reachability_score": round(self.reachability_score, 4),
            "strongly_connected_components": self.strongly_connected_components,
            "dead_states": self.dead_states,
            "sink_states": self.sink_states,
            "cycle_count": self.cycle_count,
        }


def fsm_type_for_index(index: int) -> FSMBenchmarkType:
    """Cycle machine families deterministically by dataset index."""
    return SUPPORTED_FSM_TYPES[(index - 1) % len(SUPPORTED_FSM_TYPES)]


def fsm_filename_for_index(index: int) -> str:
    """Return the canonical JSON filename for *index* (1-based)."""
    return f"fsm_{index:06d}.json"


def fsm_id_for_index(index: int, fsm_type: FSMBenchmarkType, seed: int) -> str:
    """Return a stable unique identifier for one generated FSM."""
    type_slug = fsm_type.lower().replace(" ", "_")
    return f"fsm_{index:06d}_{type_slug}_{seed}"


def _generation_params_for_index(
    index: int,
    fsm_type: FSMBenchmarkType,
    base_seed: int,
) -> SyntheticGenerationParams:
    """Derive synthetic factory parameters from index, type, and global seed."""
    fsm_seed = base_seed + index * 997
    rng = random.Random(fsm_seed)
    complexity_keys = tuple(COMPLEXITY_PRESETS.keys())
    preset = COMPLEXITY_PRESETS[complexity_keys[(index - 1) % len(complexity_keys)]]

    num_states = max(3, preset["num_states"] + rng.randint(-2, 3))
    num_events = max(2, preset["num_events"] + rng.randint(-1, 2))
    branching_factor = max(1, preset["branching_factor"] + rng.randint(-1, 1))
    deterministic = True
    allow_dead_states = index % 7 == 0

    return SyntheticGenerationParams(
        num_states=num_states,
        num_events=num_events,
        branching_factor=branching_factor,
        deterministic=deterministic,
        allow_dead_states=allow_dead_states,
        seed=fsm_seed,
    )


def compute_determinism_score(fsm: FSM) -> float:
    """Fraction of reachable (source, event) pairs with exactly one outgoing transition."""
    reachable = reachable_state_ids(fsm)
    pair_counts: dict[tuple[str, str], int] = defaultdict(int)
    for transition in fsm.transitions:
        if transition.source in reachable:
            pair_counts[(transition.source, transition.event)] += 1
    if not pair_counts:
        return 1.0
    deterministic_pairs = sum(1 for count in pair_counts.values() if count == 1)
    return deterministic_pairs / len(pair_counts)


def compute_reachability_score(fsm: FSM) -> float:
    """Fraction of declared states reachable from the initial state."""
    if not fsm.states:
        return 0.0
    reachable = reachable_state_ids(fsm)
    return len(reachable) / len(fsm.states)


def count_dead_states(fsm: FSM) -> int:
    """Count states not reachable from the initial state."""
    reachable = reachable_state_ids(fsm)
    return sum(1 for state in fsm.states if state.id not in reachable)


def count_sink_states(fsm: FSM) -> int:
    """Count reachable states with no outgoing transitions in the reachable subgraph."""
    reachable = reachable_state_ids(fsm)
    outgoing: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable and transition.target in reachable:
            outgoing[transition.source] += 1
    return sum(1 for state_id in reachable if outgoing[state_id] == 0)


def compute_fsm_metadata(fsm: FSM, *, fsm_type: FSMBenchmarkType, seed: int, filename: str) -> FSMMetadata:
    """Compute benchmark metadata for *fsm*."""
    reachable = reachable_state_ids(fsm)
    components = compute_strongly_connected_components(fsm, reachable)
    cycle_count = compute_cycle_count(fsm, reachable, components)

    return FSMMetadata(
        fsm_id=fsm.id,
        filename=filename,
        type=fsm_type,
        seed=seed,
        num_states=len(fsm.states),
        num_transitions=len(fsm.transitions),
        alphabet_size=len(fsm.events),
        branching_factor=compute_branching_factor(fsm, reachable),
        determinism_score=compute_determinism_score(fsm),
        reachability_score=compute_reachability_score(fsm),
        strongly_connected_components=len(components),
        dead_states=count_dead_states(fsm),
        sink_states=count_sink_states(fsm),
        cycle_count=cycle_count,
    )


def _apply_mealy_machine(fsm: FSM, seed: int) -> FSM:
    transitions = [
        transition.model_copy(update={"output": f"out_{seed}_{index}"})
        for index, transition in enumerate(fsm.transitions)
    ]
    return fsm.model_copy(update={"transitions": transitions})


def _apply_moore_machine(fsm: FSM, seed: int) -> FSM:
    states = [
        state.model_copy(update={"state_output": f"state_out_{seed}_{index}"})
        for index, state in enumerate(fsm.states)
    ]
    return fsm.model_copy(update={"states": states})


def _apply_efsm(fsm: FSM, seed: int) -> FSM:
    transitions = [
        transition.model_copy(update={"guard": f"x_{seed}_{index} > 0 and y_{seed}_{index} < 10"})
        for index, transition in enumerate(fsm.transitions)
    ]
    return fsm.model_copy(
        update={
            "variables": {"x": "int", "y": "int"},
            "transitions": transitions,
        }
    )


def _apply_timed_fsm(fsm: FSM, seed: int) -> FSM:
    transitions = [
        transition.model_copy(update={"timeout": float(1 + (index % 5))})
        for index, transition in enumerate(fsm.transitions)
    ]
    return fsm.model_copy(
        update={
            "discrete_time_step": 1.0,
            "semantics_mode": "timed_discrete",
            "transitions": transitions,
        }
    )


def _apply_dfa(fsm: FSM) -> FSM:
    """Keep at most one transition per reachable (source, event) pair."""
    reachable = reachable_state_ids(fsm)
    kept: list[Transition] = []
    seen_pairs: set[tuple[str, str]] = set()
    for transition in fsm.transitions:
        if transition.source not in reachable:
            kept.append(transition)
            continue
        pair = (transition.source, transition.event)
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        kept.append(transition.model_copy(update={"guard": None}))
    return fsm.model_copy(update={"transitions": kept})


def _apply_nfa(fsm: FSM, seed: int) -> FSM:
    rng = random.Random(seed + 17)
    reachable = reachable_state_ids(fsm)
    candidates = [transition for transition in fsm.transitions if transition.source in reachable]
    if not candidates:
        return fsm

    base = rng.choice(candidates)
    alternate_targets = [
        state.id
        for state in fsm.states
        if state.id in reachable and state.id != base.target
    ]
    if not alternate_targets:
        return fsm

    duplicate = base.model_copy(
        update={
            "id": f"{base.id}_nfa_{seed}",
            "target": rng.choice(alternate_targets),
            "guard": base.guard,
            "is_nondeterministic": True,
        }
    )
    return fsm.model_copy(update={"transitions": [*fsm.transitions, duplicate]})


def _apply_fsm_type(fsm: FSM, fsm_type: FSMBenchmarkType, seed: int) -> FSM:
    if fsm_type == "DFA":
        return _apply_dfa(fsm)
    if fsm_type == "NFA":
        return _apply_nfa(_apply_dfa(fsm), seed)
    if fsm_type == "Mealy":
        return _apply_mealy_machine(_apply_dfa(fsm), seed)
    if fsm_type == "Moore":
        return _apply_moore_machine(_apply_dfa(fsm), seed)
    if fsm_type == "EFSM":
        return _apply_efsm(fsm, seed)
    if fsm_type == "Timed FSM":
        return _apply_timed_fsm(_apply_dfa(fsm), seed)
    msg = f"Unsupported FSM type '{fsm_type}'"
    raise FSMBenchmarkDatasetError(msg)


def _attach_graph_metadata(fsm: FSM, metadata: FSMMetadata) -> FSM:
    return fsm.model_copy(
        update={
            "cyclic_metadata": CyclicStructureMetadata(
                cycle_count=metadata.cycle_count,
                strongly_connected_component_count=metadata.strongly_connected_components,
                is_cyclic=metadata.cycle_count > 0,
            )
        }
    )


def generate_single_fsm(index: int, *, base_seed: int) -> tuple[FSM, FSMMetadata]:
    """Generate one benchmark FSM and its metadata."""
    if index < 1:
        msg = "index must be at least 1"
        raise FSMBenchmarkDatasetError(msg)

    fsm_type = fsm_type_for_index(index)
    params = _generation_params_for_index(index, fsm_type, base_seed)
    filename = fsm_filename_for_index(index)
    fsm_id = fsm_id_for_index(index, fsm_type, params.seed)

    last_error: str | None = None
    for attempt in range(8):
        try:
            attempt_params = SyntheticGenerationParams(
                num_states=params.num_states,
                num_events=params.num_events,
                branching_factor=params.branching_factor,
                deterministic=params.deterministic,
                allow_dead_states=params.allow_dead_states,
                seed=params.seed + attempt,
            )
            fsm = generate_synthetic_fsm(attempt_params)
            fsm = _apply_fsm_type(fsm, fsm_type, attempt_params.seed)
            fsm = fsm.model_copy(
                update={
                    "id": fsm_id,
                    "name": f"{fsm_type} benchmark FSM #{index:06d}",
                    "description": (
                        f"Generated {fsm_type} with seed={attempt_params.seed}, "
                        f"index={index}, base_seed={base_seed}"
                    ),
                }
            )
            errors = validate_fsm(fsm, allow_nondeterminism=fsm_type == "NFA")
            if errors:
                raise SyntheticFactoryError(errors[0])

            metadata = compute_fsm_metadata(
                fsm,
                fsm_type=fsm_type,
                seed=attempt_params.seed,
                filename=filename,
            )
            fsm = _attach_graph_metadata(fsm, metadata)
            return fsm, metadata
        except SyntheticFactoryError as exc:
            last_error = str(exc)

    msg = f"Failed to generate FSM at index {index}: {last_error}"
    raise FSMBenchmarkDatasetError(msg)


def write_metadata_csv(path: Path, records: Sequence[FSMMetadata]) -> None:
    """Write dataset metadata CSV to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METADATA_CSV_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def generate_fsm_benchmark_dataset(config: FSMBenchmarkGenerationConfig) -> list[FSMMetadata]:
    """Generate *config.count* FSMs and export them under *config.output_dir*."""
    if config.count < 1:
        msg = "count must be at least 1"
        raise FSMBenchmarkDatasetError(msg)

    output_dir = config.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    records: list[FSMMetadata] = []
    for index in range(1, config.count + 1):
        fsm, metadata = generate_single_fsm(index, base_seed=config.seed)
        export_fsm_json(fsm, output_dir / metadata.filename)
        records.append(metadata)

    write_metadata_csv(output_dir / "metadata.csv", records)
    return records


def dataset_type_distribution(records: Sequence[FSMMetadata]) -> dict[str, int]:
    """Return counts per machine type in *records*."""
    counts = Counter(record.type for record in records)
    return {fsm_type: counts.get(fsm_type, 0) for fsm_type in SUPPORTED_FSM_TYPES}
