"""Benchmark novelty analysis for detecting synthetic dataset collapse."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fsmrepairbench.dataset_builder import is_case_complete
from fsmrepairbench.difficulty import compute_difficulty_metrics, reachable_state_ids
from fsmrepairbench.models import FSM, OracleSuite
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite
from fsmrepairbench.versioning import (
    VersioningError,
    detect_benchmark_version,
    discover_case_directories,
)

NOVELTY_REPORT_FILENAME = "novelty_report.json"

HIGH_SIMILARITY_CLUSTER_THRESHOLD = 0.85
PAIR_REPORT_THRESHOLD = 0.70

SIMILARITY_WEIGHTS: dict[str, float] = {
    "graph": 0.25,
    "transition": 0.30,
    "structural": 0.20,
    "oracle": 0.25,
}

CollapseRisk = Literal["low", "medium", "high"]


class NoveltyAnalysisError(ValueError):
    """Raised when novelty analysis cannot run."""


@dataclass(frozen=True)
class CaseArtifacts:
    """Loaded benchmark artifacts for one case."""

    case_id: str
    fsm: FSM
    oracle_suite: OracleSuite | None


@dataclass(frozen=True)
class PairwiseSimilarity:
    """Similarity metrics between two benchmark cases."""

    case_id_a: str
    case_id_b: str
    graph_similarity: float
    transition_similarity: float
    structural_similarity: float
    oracle_similarity: float
    combined_similarity: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "case_id_a": self.case_id_a,
            "case_id_b": self.case_id_b,
            "graph_similarity": round(self.graph_similarity, 4),
            "transition_similarity": round(self.transition_similarity, 4),
            "structural_similarity": round(self.structural_similarity, 4),
            "oracle_similarity": round(self.oracle_similarity, 4),
            "combined_similarity": round(self.combined_similarity, 4),
        }


@dataclass(frozen=True)
class NoveltyAnalysisResult:
    """Novelty analysis outcome for one dataset."""

    dataset_dir: Path
    report_path: Path
    report: dict[str, Any]
    collapsed: bool


def _jaccard(left: set[Any], right: set[Any]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _transition_set(fsm: FSM) -> set[tuple[str, str, str]]:
    return {(transition.source, transition.event, transition.target) for transition in fsm.transitions}


def _canonical_state_map(fsm: FSM) -> dict[str, int]:
    """Assign canonical indices via BFS from the initial state."""
    state_ids = {state.id for state in fsm.states}
    order: list[str] = []
    seen: set[str] = set()
    queue: deque[str] = deque([fsm.initial_state])

    while queue:
        current = queue.popleft()
        if current in seen or current not in state_ids:
            continue
        seen.add(current)
        order.append(current)
        targets = sorted(
            transition.target
            for transition in fsm.transitions
            if transition.source == current and transition.target in state_ids
        )
        for target in targets:
            if target not in seen:
                queue.append(target)

    for state_id in sorted(state_ids - seen):
        order.append(state_id)

    return {state_id: index for index, state_id in enumerate(order)}


def _normalized_graph_edges(fsm: FSM) -> set[tuple[int, int]]:
    mapping = _canonical_state_map(fsm)
    edges: set[tuple[int, int]] = set()
    for transition in fsm.transitions:
        if transition.source not in mapping or transition.target not in mapping:
            continue
        source = mapping[transition.source]
        target = mapping[transition.target]
        edges.add((min(source, target), max(source, target)))
    return edges


def _structural_fingerprint(fsm: FSM) -> tuple[int, int, int, float, int, int]:
    metrics = compute_difficulty_metrics(fsm)
    return (
        metrics.state_count,
        len(fsm.events),
        metrics.transition_count,
        round(metrics.branching_factor, 2),
        metrics.strongly_connected_components,
        metrics.cycles,
    )


def _oracle_signatures(suite: OracleSuite) -> set[tuple[tuple[str, str], ...]]:
    signatures: set[tuple[tuple[str, str], ...]] = set()
    for scenario in suite.scenarios:
        signature = tuple((step.event, step.expected_state) for step in scenario.steps)
        signatures.add(signature)
    return signatures


def graph_similarity(fsm_a: FSM, fsm_b: FSM) -> float:
    """Measure topology similarity using canonically labelled undirected edges."""
    return _jaccard(_normalized_graph_edges(fsm_a), _normalized_graph_edges(fsm_b))


def transition_similarity(fsm_a: FSM, fsm_b: FSM) -> float:
    """Measure similarity of labelled transition triples."""
    return _jaccard(_transition_set(fsm_a), _transition_set(fsm_b))


def structural_similarity(fsm_a: FSM, fsm_b: FSM) -> float:
    """Measure similarity of coarse structural fingerprints."""
    fingerprint_a = _structural_fingerprint(fsm_a)
    fingerprint_b = _structural_fingerprint(fsm_b)
    if fingerprint_a == fingerprint_b:
        return 1.0
    diffs = [abs(left - right) / max(left, right, 1) for left, right in zip(fingerprint_a, fingerprint_b)]
    return max(0.0, 1.0 - (sum(diffs) / len(diffs)))


def oracle_similarity(suite_a: OracleSuite | None, suite_b: OracleSuite | None) -> float:
    """Measure similarity of oracle scenario signatures."""
    if suite_a is None or suite_b is None:
        return 0.0
    return _jaccard(_oracle_signatures(suite_a), _oracle_signatures(suite_b))


def combined_similarity(
    *,
    graph: float,
    transition: float,
    structural: float,
    oracle: float,
) -> float:
    """Return a weighted aggregate similarity score."""
    return (
        SIMILARITY_WEIGHTS["graph"] * graph
        + SIMILARITY_WEIGHTS["transition"] * transition
        + SIMILARITY_WEIGHTS["structural"] * structural
        + SIMILARITY_WEIGHTS["oracle"] * oracle
    )


def compute_pairwise_similarity(case_a: CaseArtifacts, case_b: CaseArtifacts) -> PairwiseSimilarity:
    """Compute all similarity dimensions for one case pair."""
    graph = graph_similarity(case_a.fsm, case_b.fsm)
    transition = transition_similarity(case_a.fsm, case_b.fsm)
    structural = structural_similarity(case_a.fsm, case_b.fsm)
    oracle = oracle_similarity(case_a.oracle_suite, case_b.oracle_suite)
    combined = combined_similarity(
        graph=graph,
        transition=transition,
        structural=structural,
        oracle=oracle,
    )
    return PairwiseSimilarity(
        case_id_a=case_a.case_id,
        case_id_b=case_b.case_id,
        graph_similarity=graph,
        transition_similarity=transition,
        structural_similarity=structural,
        oracle_similarity=oracle,
        combined_similarity=combined,
    )


class _UnionFind:
    def __init__(self, items: list[str]) -> None:
        self.parent = {item: item for item in items}

    def find(self, item: str) -> str:
        if self.parent[item] != item:
            self.parent[item] = self.find(self.parent[item])
        return self.parent[item]

    def union(self, left: str, right: str) -> None:
        root_left = self.find(left)
        root_right = self.find(right)
        if root_left != root_right:
            self.parent[root_right] = root_left


def _cluster_highly_similar_cases(
    cases: list[CaseArtifacts],
    pairs: list[PairwiseSimilarity],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    """Group cases into clusters connected by high combined similarity."""
    if len(cases) < 2:
        return []

    union_find = _UnionFind([case.case_id for case in cases])
    pair_lookup: dict[frozenset[str], PairwiseSimilarity] = {}

    for pair in pairs:
        if pair.combined_similarity >= threshold:
            union_find.union(pair.case_id_a, pair.case_id_b)
        pair_lookup[frozenset((pair.case_id_a, pair.case_id_b))] = pair

    grouped: dict[str, list[str]] = {}
    for case in cases:
        root = union_find.find(case.case_id)
        grouped.setdefault(root, []).append(case.case_id)

    clusters: list[dict[str, Any]] = []
    for cluster_index, case_ids in enumerate(sorted(grouped.values(), key=len, reverse=True), start=1):
        if len(case_ids) < 2:
            continue

        cluster_pairs = [
            pair_lookup[frozenset((left, right))]
            for left in case_ids
            for right in case_ids
            if left < right and frozenset((left, right)) in pair_lookup
        ]
        if not cluster_pairs:
            continue

        clusters.append(
            {
                "cluster_id": cluster_index,
                "case_ids": sorted(case_ids),
                "size": len(case_ids),
                "mean_combined_similarity": round(
                    sum(pair.combined_similarity for pair in cluster_pairs) / len(cluster_pairs),
                    4,
                ),
                "mean_graph_similarity": round(
                    sum(pair.graph_similarity for pair in cluster_pairs) / len(cluster_pairs),
                    4,
                ),
                "mean_transition_similarity": round(
                    sum(pair.transition_similarity for pair in cluster_pairs) / len(cluster_pairs),
                    4,
                ),
                "mean_structural_similarity": round(
                    sum(pair.structural_similarity for pair in cluster_pairs) / len(cluster_pairs),
                    4,
                ),
                "mean_oracle_similarity": round(
                    sum(pair.oracle_similarity for pair in cluster_pairs) / len(cluster_pairs),
                    4,
                ),
            }
        )
    return clusters


def _collapse_risk(
    *,
    case_count: int,
    mean_combined_similarity: float,
    largest_cluster_size: int,
    clustered_case_count: int,
) -> CollapseRisk:
    if case_count <= 1 or clustered_case_count == 0:
        return "low"

    cluster_fraction = largest_cluster_size / case_count
    covered_fraction = clustered_case_count / case_count

    if cluster_fraction >= 0.50 or mean_combined_similarity >= 0.80 or covered_fraction >= 0.75:
        return "high"
    if cluster_fraction >= 0.25 or mean_combined_similarity >= 0.60 or covered_fraction >= 0.40:
        return "medium"
    return "low"


def _load_case_artifacts(case_dir: Path) -> CaseArtifacts | None:
    reference_path = case_dir / "reference_fsm.json"
    if not reference_path.is_file():
        return None

    fsm = load_fsm_json(reference_path)
    oracle_path = case_dir / "oracle_suite.json"
    oracle_suite = load_oracle_suite(oracle_path) if oracle_path.is_file() else None
    return CaseArtifacts(case_id=case_dir.name, fsm=fsm, oracle_suite=oracle_suite)


def _discover_cases(dataset_dir: Path) -> list[Path]:
    try:
        case_dirs = discover_case_directories(dataset_dir)
    except VersioningError as exc:
        raise NoveltyAnalysisError(str(exc)) from exc

    if case_dirs:
        return case_dirs

    cases_root = dataset_dir / "cases"
    if cases_root.is_dir():
        return sorted(
            path for path in cases_root.iterdir() if path.is_dir() and is_case_complete(path)
        )
    return []


def analyze_novelty(
    dataset_dir: Path,
    *,
    output_path: Path | None = None,
    cluster_threshold: float = HIGH_SIMILARITY_CLUSTER_THRESHOLD,
    pair_report_threshold: float = PAIR_REPORT_THRESHOLD,
) -> NoveltyAnalysisResult:
    """Measure benchmark novelty and write novelty_report.json."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise NoveltyAnalysisError(msg)

    case_dirs = _discover_cases(dataset_dir)
    if not case_dirs:
        msg = f"No benchmark cases found under {dataset_dir}"
        raise NoveltyAnalysisError(msg)

    cases: list[CaseArtifacts] = []
    for case_dir in case_dirs:
        artifacts = _load_case_artifacts(case_dir)
        if artifacts is not None:
            cases.append(artifacts)

    if not cases:
        msg = f"No reference FSMs found under {dataset_dir}"
        raise NoveltyAnalysisError(msg)

    pairs: list[PairwiseSimilarity] = []
    for index, case_a in enumerate(cases):
        for case_b in cases[index + 1 :]:
            pairs.append(compute_pairwise_similarity(case_a, case_b))

    reported_pairs = [
        pair for pair in pairs if pair.combined_similarity >= pair_report_threshold
    ]
    clusters = _cluster_highly_similar_cases(cases, pairs, threshold=cluster_threshold)

    combined_values = [pair.combined_similarity for pair in pairs]
    mean_combined = sum(combined_values) / len(combined_values) if combined_values else 0.0
    max_combined = max(combined_values) if combined_values else 0.0
    largest_cluster_size = max((cluster["size"] for cluster in clusters), default=0)
    clustered_case_ids = {case_id for cluster in clusters for case_id in cluster["case_ids"]}

    novelty_score = round(1.0 - mean_combined, 4)
    unique_fraction = round(
        (len(cases) - len(clustered_case_ids)) / len(cases) if cases else 1.0,
        4,
    )
    collapse_risk = _collapse_risk(
        case_count=len(cases),
        mean_combined_similarity=mean_combined,
        largest_cluster_size=largest_cluster_size,
        clustered_case_count=len(clustered_case_ids),
    )

    try:
        benchmark_version = detect_benchmark_version(dataset_dir).value
    except VersioningError:
        benchmark_version = "unknown"

    report: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "dataset_dir": str(dataset_dir),
        "benchmark_version": benchmark_version,
        "case_count": len(cases),
        "novelty_summary": {
            "novelty_score": novelty_score,
            "mean_combined_similarity": round(mean_combined, 4),
            "max_combined_similarity": round(max_combined, 4),
            "unique_fraction": unique_fraction,
            "collapse_risk": collapse_risk,
            "high_similarity_cluster_count": len(clusters),
            "largest_cluster_size": largest_cluster_size,
            "clustered_case_count": len(clustered_case_ids),
        },
        "similarity_thresholds": {
            "cluster_threshold": cluster_threshold,
            "pair_report_threshold": pair_report_threshold,
            "weights": SIMILARITY_WEIGHTS,
        },
        "high_similarity_clusters": clusters,
        "notable_pairs": [pair.to_dict() for pair in sorted(
            reported_pairs,
            key=lambda pair: pair.combined_similarity,
            reverse=True,
        )],
    }

    report_path = output_path or (dataset_dir / NOVELTY_REPORT_FILENAME)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return NoveltyAnalysisResult(
        dataset_dir=dataset_dir,
        report_path=report_path,
        report=report,
        collapsed=collapse_risk == "high",
    )
