"""FSM difficulty estimation for benchmark instances."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.models import FSM
from fsmrepairbench.validators import load_fsm_json

DifficultyCategory = Literal["easy", "medium", "hard", "expert"]

REFERENCE_MAX_STATES = 50
REFERENCE_MAX_TRANSITIONS = 250
REFERENCE_MAX_BRANCHING = 5.0
REFERENCE_MAX_AVG_PATH = 25.0
REFERENCE_MAX_CYCLES = 20
REFERENCE_MAX_SCC = 50

METRIC_WEIGHTS: Mapping[str, float] = {
    "state_count": 0.15,
    "transition_count": 0.20,
    "branching_factor": 0.20,
    "average_path_length": 0.15,
    "cycles": 0.15,
    "strongly_connected_components": 0.15,
}


class DifficultyError(ValueError):
    """Raised when difficulty estimation input is invalid."""


@dataclass(frozen=True)
class DifficultyMetrics:
    """Structural metrics used to estimate difficulty."""

    state_count: int
    transition_count: int
    branching_factor: float
    average_path_length: float
    cycles: int
    strongly_connected_components: int


@dataclass(frozen=True)
class DifficultyEstimate:
    """Difficulty score and category for an FSM benchmark instance."""

    difficulty_score: float
    category: DifficultyCategory
    metrics: DifficultyMetrics

    def to_metadata(self) -> dict[str, object]:
        """Return JSON-serialisable difficulty metadata."""
        return {
            "difficulty_score": round(self.difficulty_score, 2),
            "category": self.category,
            "metrics": {
                "state_count": self.metrics.state_count,
                "transition_count": self.metrics.transition_count,
                "branching_factor": round(self.metrics.branching_factor, 4),
                "average_path_length": round(self.metrics.average_path_length, 4),
                "cycles": self.metrics.cycles,
                "strongly_connected_components": self.metrics.strongly_connected_components,
            },
        }


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


def _outgoing_graph(fsm: FSM, reachable: set[str]) -> dict[str, list[str]]:
    graph: dict[str, list[str]] = {state_id: [] for state_id in reachable}
    for transition in fsm.transitions:
        if transition.source in reachable and transition.target in reachable:
            graph[transition.source].append(transition.target)
    return graph


def compute_branching_factor(fsm: FSM, reachable: set[str]) -> float:
    """Return the average outgoing transition count over reachable states."""
    if not reachable:
        return 0.0

    outgoing_counts: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable:
            outgoing_counts[transition.source] += 1
    return sum(outgoing_counts.values()) / len(outgoing_counts)


def compute_average_path_length(fsm: FSM, reachable: set[str]) -> float:
    """Return the mean shortest-path length to other reachable states."""
    if fsm.initial_state not in reachable or len(reachable) <= 1:
        return 0.0

    graph = _outgoing_graph(fsm, reachable)
    distances: dict[str, int] = {fsm.initial_state: 0}
    queue: deque[str] = deque([fsm.initial_state])

    while queue:
        current = queue.popleft()
        for target in graph[current]:
            if target in distances:
                continue
            distances[target] = distances[current] + 1
            queue.append(target)

    path_lengths = [distance for state, distance in distances.items() if state != fsm.initial_state]
    if not path_lengths:
        return 0.0
    return sum(path_lengths) / len(path_lengths)


def compute_strongly_connected_components(fsm: FSM, reachable: set[str]) -> list[set[str]]:
    """Return strongly connected components in the reachable subgraph."""
    if not reachable:
        return []

    graph = _outgoing_graph(fsm, reachable)
    reverse_graph: dict[str, list[str]] = {state_id: [] for state_id in reachable}
    for source, targets in graph.items():
        for target in targets:
            reverse_graph[target].append(source)

    visited: set[str] = set()
    finish_order: list[str] = []

    def dfs_first(state: str) -> None:
        visited.add(state)
        for target in graph[state]:
            if target not in visited:
                dfs_first(target)
        finish_order.append(state)

    for state in sorted(reachable):
        if state not in visited:
            dfs_first(state)

    visited.clear()
    components: list[set[str]] = []

    def dfs_second(state: str, component: set[str]) -> None:
        visited.add(state)
        component.add(state)
        for source in reverse_graph[state]:
            if source not in visited:
                dfs_second(source, component)

    for state in reversed(finish_order):
        if state in visited:
            continue
        component: set[str] = set()
        dfs_second(state, component)
        components.append(component)

    return components


def compute_cycle_count(fsm: FSM, reachable: set[str], components: list[set[str]]) -> int:
    """Return a cycle count based on self-loops and cyclic SCCs."""
    self_loops = sum(
        1
        for transition in fsm.transitions
        if transition.source in reachable and transition.source == transition.target
    )
    cyclic_components = sum(1 for component in components if len(component) > 1)
    return self_loops + cyclic_components


def compute_difficulty_metrics(fsm: FSM) -> DifficultyMetrics:
    """Compute structural difficulty metrics for *fsm*."""
    reachable = reachable_state_ids(fsm)
    transitions = [
        transition
        for transition in fsm.transitions
        if transition.source in reachable and transition.target in reachable
    ]
    components = compute_strongly_connected_components(fsm, reachable)

    return DifficultyMetrics(
        state_count=len(reachable),
        transition_count=len(transitions),
        branching_factor=compute_branching_factor(fsm, reachable),
        average_path_length=compute_average_path_length(fsm, reachable),
        cycles=compute_cycle_count(fsm, reachable, components),
        strongly_connected_components=len(components),
    )


def _normalize_metric(name: str, value: float | int) -> float:
    maxima = {
        "state_count": REFERENCE_MAX_STATES,
        "transition_count": REFERENCE_MAX_TRANSITIONS,
        "branching_factor": REFERENCE_MAX_BRANCHING,
        "average_path_length": REFERENCE_MAX_AVG_PATH,
        "cycles": REFERENCE_MAX_CYCLES,
        "strongly_connected_components": REFERENCE_MAX_SCC,
    }
    maximum = maxima[name]
    return min(1.0, float(value) / maximum)


def category_for_score(score: float) -> DifficultyCategory:
    """Map a difficulty score in ``[0, 100]`` to a category label."""
    if score <= 25:
        return "easy"
    if score <= 50:
        return "medium"
    if score <= 75:
        return "hard"
    return "expert"


def estimate_difficulty(fsm: FSM) -> DifficultyEstimate:
    """Estimate benchmark difficulty for *fsm*."""
    metrics = compute_difficulty_metrics(fsm)
    normalized = {
        "state_count": _normalize_metric("state_count", metrics.state_count),
        "transition_count": _normalize_metric("transition_count", metrics.transition_count),
        "branching_factor": _normalize_metric("branching_factor", metrics.branching_factor),
        "average_path_length": _normalize_metric(
            "average_path_length",
            metrics.average_path_length,
        ),
        "cycles": _normalize_metric("cycles", metrics.cycles),
        "strongly_connected_components": _normalize_metric(
            "strongly_connected_components",
            metrics.strongly_connected_components,
        ),
    }
    weighted = sum(METRIC_WEIGHTS[name] * normalized[name] for name in METRIC_WEIGHTS)
    score = round(min(100.0, max(0.0, weighted * 100.0)), 2)
    return DifficultyEstimate(
        difficulty_score=score,
        category=category_for_score(score),
        metrics=metrics,
    )


def resolve_benchmark_fsm_path(path: Path) -> Path:
    """Resolve a benchmark case path to the reference FSM JSON file."""
    if path.is_dir():
        reference_path = path / "reference_fsm.json"
        if reference_path.is_file():
            return reference_path
        msg = f"No reference_fsm.json found in case directory: {path}"
        raise DifficultyError(msg)

    if path.name == "case_metadata.json":
        reference_path = path.parent / "reference_fsm.json"
        if reference_path.is_file():
            return reference_path
        msg = f"No reference_fsm.json found next to {path}"
        raise DifficultyError(msg)

    if path.suffix.lower() != ".json":
        msg = f"Unsupported benchmark path: {path}"
        raise DifficultyError(msg)

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Failed to read benchmark JSON: {exc}"
        raise DifficultyError(msg) from exc

    if isinstance(payload, dict) and "initial_state" in payload and "states" in payload:
        return path

    if isinstance(payload, dict) and "reference_fsm_id" in payload:
        reference_path = path.parent / "reference_fsm.json"
        if reference_path.is_file():
            return reference_path

    msg = f"Could not resolve reference FSM from {path}"
    raise DifficultyError(msg)


def estimate_difficulty_from_path(path: Path) -> DifficultyEstimate:
    """Load a benchmark case or FSM JSON file and estimate its difficulty."""
    reference_path = resolve_benchmark_fsm_path(path)
    fsm = load_fsm_json(reference_path)
    return estimate_difficulty(fsm)


def export_difficulty_metadata(estimate: DifficultyEstimate, path: Path) -> None:
    """Write difficulty metadata JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(estimate.to_metadata(), indent=2) + "\n", encoding="utf-8")
