"""Oracle depth ablation: sensitivity of detection metrics to oracle suite depth."""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.analytics import (
    _pyplot,
    _save_bar_plot,
    _save_histogram,
    compute_benchmark_analytics,
    compute_mutation_detection_rates,
    write_analysis_summary_csv,
    write_distributions_csv,
)
from fsmrepairbench.dataset_builder import (
    DatasetCaseRow,
    _primary_mutation_operator,
    resolve_coupling_case_file,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.oracle_generator import (
    DepthLevel,
    OracleGeneratorError,
    ScenarioPolicy,
    compute_coverage,
    generate_oracle_suite,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.statistics import (
    append_ci_section_to_report,
    compute_c3_confidence_intervals,
    write_confidence_interval_exports,
)
from fsmrepairbench.validators import load_fsm_json

ABLATION_DEPTHS: tuple[DepthLevel, ...] = ("shallow", "medium", "deep")
DEFAULT_COHORT_SIZE = 200
DEFAULT_COHORT_SEED = 44
DEFAULT_V2_OUTPUT = Path("results/oracle_depth_ablation_v2")
DEFAULT_V2_PAPER_EXPORT = Path("../paper1/results/oracle_depth_ablation_v2")
SCENARIO_POLICIES: tuple[ScenarioPolicy, ...] = ("shortest-path", "depth-forced")
V2_EXPERIMENT = "C3-oracle-depth-ablation-v2"
COHORT_FILENAME = "oracle_depth_ablation_200.txt"
COHORT_JSON_FILENAME = "oracle_depth_ablation_200.json"
PER_CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "oracle_depth",
    "mutation_operator",
    "size_class",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "fault_detected",
    "oracle_state_coverage",
    "oracle_transition_coverage",
    "oracle_event_coverage",
    "scenario_count",
    "max_scenario_steps",
)
DEPTH_SUMMARY_COLUMNS: tuple[str, ...] = (
    "oracle_depth",
    "case_count",
    "overall_detection_rate",
    "detectable_case_ratio",
    "mean_reference_bpr",
    "mean_faulty_bpr",
    "mean_bpr_delta",
    "mean_oracle_state_coverage",
    "mean_oracle_transition_coverage",
    "mean_oracle_event_coverage",
    "mean_scenario_count",
    "mean_max_scenario_steps",
    "skipped_reference_bpr_cases",
)
V2_PER_CASE_COLUMNS: tuple[str, ...] = PER_CASE_COLUMNS + (
    "scenario_policy",
    "declared_max_depth",
    "observed_max_executed_depth",
    "mean_scenario_length",
    "median_scenario_length",
    "max_scenario_length",
)
V2_DEPTH_SUMMARY_COLUMNS: tuple[str, ...] = DEPTH_SUMMARY_COLUMNS + (
    "scenario_policy",
    "declared_max_depth",
    "mean_scenario_length",
    "median_scenario_length",
    "max_scenario_length",
    "detection_gains_vs_shallow",
    "detection_losses_vs_shallow",
)
PAIRED_DETECTION_COLUMNS: tuple[str, ...] = (
    "comparison_depth",
    "both_detected",
    "shallow_only_detected",
    "higher_only_detected",
    "neither_detected",
    "detection_gains",
    "detection_losses",
    "mcnemar_chi2",
)
COVERAGE_BY_DEPTH_COLUMNS: tuple[str, ...] = (
    "oracle_depth",
    "scenario_policy",
    "declared_max_depth",
    "case_count",
    "mean_oracle_state_coverage",
    "mean_oracle_transition_coverage",
    "mean_oracle_event_coverage",
    "mean_scenario_count",
    "mean_scenario_length",
    "median_scenario_length",
    "max_scenario_length",
)


class OracleDepthAblationError(RuntimeError):
    """Raised when oracle depth ablation cannot be completed."""


@dataclass(frozen=True)
class DepthCaseResult:
    """Behavioural metrics for one case at one oracle depth."""

    case_id: str
    depth: DepthLevel
    mutation_operator: str
    size_class: str
    reference_bpr: float
    faulty_bpr: float
    bpr_delta: float
    fault_detected: bool
    oracle_state_coverage: float
    oracle_transition_coverage: float
    oracle_event_coverage: float
    scenario_count: int
    max_scenario_steps: int
    scenario_policy: ScenarioPolicy = "shortest-path"
    declared_max_depth: int = 0
    observed_max_executed_depth: int = 0
    mean_scenario_length: float = 0.0
    median_scenario_length: float = 0.0
    max_scenario_length: int = 0

    def to_dict(self) -> dict[str, str | float | bool | int]:
        payload = {
            "case_id": self.case_id,
            "oracle_depth": self.depth,
            "mutation_operator": self.mutation_operator,
            "size_class": self.size_class,
            "reference_bpr": round(self.reference_bpr, 6),
            "faulty_bpr": round(self.faulty_bpr, 6),
            "bpr_delta": round(self.bpr_delta, 6),
            "fault_detected": self.fault_detected,
            "oracle_state_coverage": round(self.oracle_state_coverage, 6),
            "oracle_transition_coverage": round(self.oracle_transition_coverage, 6),
            "oracle_event_coverage": round(self.oracle_event_coverage, 6),
            "scenario_count": self.scenario_count,
            "max_scenario_steps": self.max_scenario_steps,
        }
        if self.scenario_policy == "depth-forced":
            payload.update(
                {
                    "scenario_policy": self.scenario_policy,
                    "declared_max_depth": self.declared_max_depth,
                    "observed_max_executed_depth": self.observed_max_executed_depth,
                    "mean_scenario_length": round(self.mean_scenario_length, 6),
                    "median_scenario_length": round(self.median_scenario_length, 6),
                    "max_scenario_length": self.max_scenario_length,
                }
            )
        return payload

    def to_v2_dict(self) -> dict[str, str | float | bool | int]:
        return {
            "case_id": self.case_id,
            "oracle_depth": self.depth,
            "mutation_operator": self.mutation_operator,
            "size_class": self.size_class,
            "reference_bpr": round(self.reference_bpr, 6),
            "faulty_bpr": round(self.faulty_bpr, 6),
            "bpr_delta": round(self.bpr_delta, 6),
            "fault_detected": self.fault_detected,
            "oracle_state_coverage": round(self.oracle_state_coverage, 6),
            "oracle_transition_coverage": round(self.oracle_transition_coverage, 6),
            "oracle_event_coverage": round(self.oracle_event_coverage, 6),
            "scenario_count": self.scenario_count,
            "max_scenario_steps": self.max_scenario_steps,
            "scenario_policy": self.scenario_policy,
            "declared_max_depth": self.declared_max_depth,
            "observed_max_executed_depth": self.observed_max_executed_depth,
            "mean_scenario_length": round(self.mean_scenario_length, 6),
            "median_scenario_length": round(self.median_scenario_length, 6),
            "max_scenario_length": self.max_scenario_length,
        }

    def to_dataset_case_row(self, *, complexity: str = "small") -> DatasetCaseRow:
        return DatasetCaseRow(
            case_id=self.case_id,
            reference_fsm_id=self.case_id,
            faulty_fsm_id=self.case_id,
            complexity=complexity,  # type: ignore[arg-type]
            state_count=0,
            transition_count=0,
            event_count=0,
            mutation_operator=self.mutation_operator,
            difficulty_score=0.0,
            oracle_state_coverage=self.oracle_state_coverage,
            oracle_transition_coverage=self.oracle_transition_coverage,
            oracle_event_coverage=self.oracle_event_coverage,
            reference_bpr=self.reference_bpr,
            faulty_bpr=self.faulty_bpr,
            bpr_delta=self.bpr_delta,
            valid_reference=True,
            valid_faulty=True,
            status="completed",
        )


@dataclass(frozen=True)
class OracleDepthAblationResult:
    """Paths written by an oracle depth ablation run."""

    dataset_dir: Path
    output_dir: Path
    cohort_path: Path
    cohort_manifest_path: Path
    per_case_path: Path
    depth_summary_path: Path
    summary_path: Path
    distributions_path: Path
    report_path: Path
    figures_dir: Path
    tables_dir: Path
    case_count: int
    manifest_path: Path | None = None
    paired_detection_path: Path | None = None
    coverage_by_depth_path: Path | None = None
    paper_export_dir: Path | None = None


def _size_class_to_complexity(size_class: str) -> str:
    if size_class in {"small", "medium", "large", "very_large"}:
        return size_class
    if size_class in {"tiny", "small"}:
        return "small"
    if size_class == "medium":
        return "medium"
    if size_class == "large":
        return "large"
    return "very_large"


def _load_progress_index(dataset_dir: Path) -> dict[str, dict[str, str]]:
    progress_path = dataset_dir / "progress.csv"
    if not progress_path.is_file():
        return {}
    return {
        row["case_id"]: row
        for row in csv.DictReader(progress_path.open(encoding="utf-8"))
        if row.get("case_id")
    }


def _load_case_strata(case_dir: Path) -> tuple[str, str, str]:
    """Return ``(case_id, mutation_operator, stratification_size_key)``."""
    features_path = case_dir / "case_features.json"
    metadata_path = case_dir / "case_metadata.json"
    if features_path.is_file():
        features = json.loads(features_path.read_text(encoding="utf-8"))
        bug_metadata = BugMetadata.model_validate(
            json.loads((case_dir / "bug_metadata.json").read_text(encoding="utf-8"))
        )
        return (
            str(features["case_id"]),
            _primary_mutation_operator(bug_metadata.mutation_operator),
            str(features.get("size_class", "unknown")),
        )
    if metadata_path.is_file():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        return (
            str(metadata["case_id"]),
            str(metadata["mutation_operator"]),
            str(metadata.get("complexity", "unknown")),
        )
    msg = f"Missing case metadata under {case_dir}"
    raise OracleDepthAblationError(msg)


def load_cohort_manifest(path: Path) -> list[str]:
    """Load one case ID per line from *path*."""
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise OracleDepthAblationError(msg)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_ablation_cohort(
    dataset_dir: Path,
    *,
    cohort_manifest: Path | None = None,
    size: int = DEFAULT_COHORT_SIZE,
    seed: int = DEFAULT_COHORT_SEED,
) -> list[str]:
    """Select a stratified reproducible sample from the analysis cohort."""
    del seed  # Reserved for future seeded tie-breaking; selection is deterministic.
    if size < 1:
        msg = "Cohort size must be at least 1"
        raise OracleDepthAblationError(msg)

    source = cohort_manifest or (dataset_dir / "analysis_cohort_1k.txt")
    candidate_ids = load_cohort_manifest(source)
    progress_index = _load_progress_index(dataset_dir)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for case_id in candidate_ids:
        case_dir = dataset_dir / "cases" / case_id
        if not case_dir.is_dir():
            continue
        features_path = case_dir / "case_features.json"
        if features_path.is_file():
            features = json.loads(features_path.read_text(encoding="utf-8"))
            operator = str(features.get("bug_type", "unknown"))
            size_class = str(features.get("size_class", "unknown"))
        elif case_id in progress_index:
            row = progress_index[case_id]
            operator = str(row.get("mutation_operator", "unknown"))
            size_class = str(row.get("complexity", "unknown"))
        else:
            continue
        groups[(operator, size_class)].append(case_id)

    for key in groups:
        groups[key] = sorted(groups[key])

    available = sum(len(values) for values in groups.values())
    if available < size:
        msg = f"Need {size} stratified cases, found {available} in {source}"
        raise OracleDepthAblationError(msg)

    selected: list[str] = []
    pointers = dict.fromkeys(sorted(groups), 0)
    while len(selected) < size:
        added = False
        for key in sorted(groups):
            index = pointers[key]
            if index < len(groups[key]):
                selected.append(groups[key][index])
                pointers[key] = index + 1
                added = True
                if len(selected) >= size:
                    break
        if not added:
            break

    if len(selected) < size:
        msg = f"Could only select {len(selected)} of {size} requested cases"
        raise OracleDepthAblationError(msg)
    return selected


def write_ablation_cohort_manifest(
    dataset_dir: Path,
    case_ids: list[str],
    *,
    source_manifest: Path | None = None,
) -> tuple[Path, Path]:
    """Write pinned ablation cohort list and JSON manifest under *dataset_dir*."""
    txt_path = dataset_dir / COHORT_FILENAME
    json_path = dataset_dir / COHORT_JSON_FILENAME
    txt_path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    digest = hashlib.sha256(txt_path.read_bytes()).hexdigest()
    payload = {
        "dataset": dataset_dir.name,
        "experiment": "C3-oracle-depth-ablation",
        "cohort_size": len(case_ids),
        "case_ids": case_ids,
        "source_manifest": str((source_manifest or dataset_dir / "analysis_cohort_1k.txt").name),
        "sha256": digest,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return txt_path, json_path


def score_case_at_depth(
    case_dir: Path,
    depth: DepthLevel,
    *,
    scenario_policy: ScenarioPolicy = "shortest-path",
) -> DepthCaseResult:
    """Regenerate oracle at *depth* and score reference/faulty FSMs."""
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    if reference_path is None or faulty_path is None:
        msg = f"Incomplete case directory: {case_dir}"
        raise OracleDepthAblationError(msg)

    case_id, mutation_operator, size_class = _load_case_strata(case_dir)
    reference = load_fsm_json(reference_path)
    faulty = load_fsm_json(faulty_path)

    try:
        generation = generate_oracle_suite(reference, depth=depth, policy=scenario_policy)
    except OracleGeneratorError as exc:
        msg = f"Oracle generation failed for {case_dir.name} at {depth}: {exc}"
        raise OracleDepthAblationError(msg) from exc

    reference_bpr = score_oracle_suite(reference, generation.suite).bpr
    if reference_bpr != 1.0:
        msg = f"Reference BPR {reference_bpr:.4f} != 1.0 for {case_dir.name} at {depth}"
        raise OracleDepthAblationError(msg)

    faulty_bpr = score_oracle_suite(faulty, generation.suite).bpr
    coverage = compute_coverage(reference, generation.suite)
    bpr_delta = reference_bpr - faulty_bpr
    scenario_steps = [len(scenario.steps) for scenario in generation.suite.scenarios]

    return DepthCaseResult(
        case_id=case_id,
        depth=depth,
        mutation_operator=mutation_operator,
        size_class=size_class,
        reference_bpr=reference_bpr,
        faulty_bpr=faulty_bpr,
        bpr_delta=bpr_delta,
        fault_detected=bpr_delta > 0.0,
        oracle_state_coverage=coverage.state_coverage,
        oracle_transition_coverage=coverage.transition_coverage,
        oracle_event_coverage=coverage.event_coverage,
        scenario_count=len(generation.suite.scenarios),
        max_scenario_steps=max(scenario_steps) if scenario_steps else 0,
        scenario_policy=scenario_policy,
        declared_max_depth=generation.declared_max_depth,
        observed_max_executed_depth=generation.max_scenario_length,
        mean_scenario_length=generation.mean_scenario_length,
        median_scenario_length=generation.median_scenario_length,
        max_scenario_length=generation.max_scenario_length,
    )


def _aggregate_depth_summary(
    depth: DepthLevel,
    rows: list[DepthCaseResult],
    *,
    skipped: int,
    scenario_policy: ScenarioPolicy = "shortest-path",
    detection_gains_vs_shallow: int = 0,
    detection_losses_vs_shallow: int = 0,
) -> dict[str, str | float | int]:
    if not rows:
        msg = f"No scored cases for depth {depth}"
        raise OracleDepthAblationError(msg)
    detected = sum(1 for row in rows if row.fault_detected)
    count = len(rows)
    summary: dict[str, str | float | int] = {
        "oracle_depth": depth,
        "case_count": count,
        "overall_detection_rate": round(detected / count, 6),
        "detectable_case_ratio": round(detected / count, 6),
        "mean_reference_bpr": round(sum(row.reference_bpr for row in rows) / count, 6),
        "mean_faulty_bpr": round(sum(row.faulty_bpr for row in rows) / count, 6),
        "mean_bpr_delta": round(sum(row.bpr_delta for row in rows) / count, 6),
        "mean_oracle_state_coverage": round(
            sum(row.oracle_state_coverage for row in rows) / count, 6
        ),
        "mean_oracle_transition_coverage": round(
            sum(row.oracle_transition_coverage for row in rows) / count, 6
        ),
        "mean_oracle_event_coverage": round(
            sum(row.oracle_event_coverage for row in rows) / count, 6
        ),
        "mean_scenario_count": round(sum(row.scenario_count for row in rows) / count, 2),
        "mean_max_scenario_steps": round(
            sum(row.max_scenario_steps for row in rows) / count, 2
        ),
        "skipped_reference_bpr_cases": skipped,
    }
    if scenario_policy == "depth-forced":
        summary.update(
            {
                "scenario_policy": scenario_policy,
                "declared_max_depth": rows[0].declared_max_depth,
                "mean_scenario_length": round(
                    sum(row.mean_scenario_length for row in rows) / count, 2
                ),
                "median_scenario_length": round(
                    sum(row.median_scenario_length for row in rows) / count, 2
                ),
                "max_scenario_length": max(row.max_scenario_length for row in rows),
                "detection_gains_vs_shallow": detection_gains_vs_shallow,
                "detection_losses_vs_shallow": detection_losses_vs_shallow,
            }
        )
    return summary


def _detection_sets(
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
    *,
    depth: DepthLevel,
) -> dict[str, bool]:
    return {row.case_id: row.fault_detected for row in depth_rows[depth]}


def compute_paired_detection_changes(
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
) -> list[dict[str, str | float | int]]:
    shallow = _detection_sets(depth_rows, depth="shallow")
    rows: list[dict[str, str | float | int]] = []
    for depth in ("medium", "deep"):
        higher = _detection_sets(depth_rows, depth=depth)  # type: ignore[arg-type]
        both = sum(1 for case_id in shallow if shallow[case_id] and higher.get(case_id, False))
        shallow_only = sum(
            1 for case_id in shallow if shallow[case_id] and not higher.get(case_id, False)
        )
        higher_only = sum(
            1 for case_id in shallow if not shallow[case_id] and higher.get(case_id, False)
        )
        neither = sum(
            1 for case_id in shallow if not shallow[case_id] and not higher.get(case_id, False)
        )
        gains = higher_only
        losses = shallow_only
        discordant = gains + losses
        mcnemar = round(((gains - losses) ** 2) / discordant, 6) if discordant else 0.0
        rows.append(
            {
                "comparison_depth": depth,
                "both_detected": both,
                "shallow_only_detected": shallow_only,
                "higher_only_detected": higher_only,
                "neither_detected": neither,
                "detection_gains": gains,
                "detection_losses": losses,
                "mcnemar_chi2": mcnemar,
            }
        )
    return rows


def _paired_gains_losses(
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
    *,
    depth: DepthLevel,
) -> tuple[int, int]:
    shallow = _detection_sets(depth_rows, depth="shallow")
    higher = _detection_sets(depth_rows, depth=depth)
    gains = sum(
        1 for case_id in shallow if not shallow[case_id] and higher.get(case_id, False)
    )
    losses = sum(
        1 for case_id in shallow if shallow[case_id] and not higher.get(case_id, False)
    )
    return gains, losses


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str | float | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _coverage_by_depth_rows(
    depth_summaries: list[dict[str, str | float | int]],
) -> list[dict[str, str | float | int]]:
    rows: list[dict[str, str | float | int]] = []
    for summary in depth_summaries:
        rows.append(
            {
                "oracle_depth": summary["oracle_depth"],
                "scenario_policy": summary.get("scenario_policy", "shortest-path"),
                "declared_max_depth": summary.get("declared_max_depth", ""),
                "case_count": summary["case_count"],
                "mean_oracle_state_coverage": summary["mean_oracle_state_coverage"],
                "mean_oracle_transition_coverage": summary["mean_oracle_transition_coverage"],
                "mean_oracle_event_coverage": summary["mean_oracle_event_coverage"],
                "mean_scenario_count": summary["mean_scenario_count"],
                "mean_scenario_length": summary.get("mean_scenario_length", summary["mean_max_scenario_steps"]),
                "median_scenario_length": summary.get("median_scenario_length", ""),
                "max_scenario_length": summary.get("max_scenario_length", ""),
            }
        )
    return rows


def _write_depth_summary_csv(
    path: Path,
    summaries: list[dict[str, str | float | int]],
    *,
    scenario_policy: ScenarioPolicy = "shortest-path",
) -> None:
    fieldnames = list(V2_DEPTH_SUMMARY_COLUMNS if scenario_policy == "depth-forced" else DEPTH_SUMMARY_COLUMNS)
    _write_csv(path, fieldnames, summaries)


def _write_per_case_csv(
    path: Path,
    rows: list[DepthCaseResult],
    *,
    scenario_policy: ScenarioPolicy = "shortest-path",
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(V2_PER_CASE_COLUMNS if scenario_policy == "depth-forced" else PER_CASE_COLUMNS)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = row.to_v2_dict() if scenario_policy == "depth-forced" else row.to_dict()
            writer.writerow(payload)


def _cases_for_depth(rows: list[DepthCaseResult], depth: DepthLevel) -> list[DatasetCaseRow]:
    return [
        row.to_dataset_case_row(complexity=_size_class_to_complexity(row.size_class))
        for row in rows
        if row.depth == depth
    ]


def _write_combined_summary_csv(
    path: Path,
    *,
    dataset_dir: Path,
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
) -> None:
    rows: list[dict[str, str | float]] = []
    for depth in ABLATION_DEPTHS:
        case_results = depth_rows[depth]
        cases = _cases_for_depth(case_results, depth)
        analytics = compute_benchmark_analytics(cases)
        write_analysis_summary_csv(
            path.parent / f"_tmp_summary_{depth}.csv",
            cases=cases,
            analytics=analytics,
        )
        for row in csv.DictReader(
            (path.parent / f"_tmp_summary_{depth}.csv").open(encoding="utf-8")
        ):
            rows.append({"oracle_depth": depth, "metric": row["metric"], "value": row["value"]})
        (path.parent / f"_tmp_summary_{depth}.csv").unlink(missing_ok=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=("oracle_depth", "metric", "value"))
        writer.writeheader()
        writer.writerows(rows)


def _write_combined_distributions_csv(
    path: Path,
    *,
    dataset_dir: Path,
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
) -> None:
    rows: list[dict[str, str | float]] = []
    for depth in ABLATION_DEPTHS:
        case_results = depth_rows[depth]
        cases = _cases_for_depth(case_results, depth)
        analytics = compute_benchmark_analytics(cases)
        tmp = path.parent / f"_tmp_dist_{depth}.csv"
        write_distributions_csv(tmp, cases=cases, analytics=analytics, dataset_dir=dataset_dir)
        for row in csv.DictReader(tmp.open(encoding="utf-8")):
            rows.append(
                {
                    "oracle_depth": depth,
                    "metric": row["metric"],
                    "bucket": row["bucket"],
                    "count": row["count"],
                    "fraction": row["fraction"],
                }
            )
        tmp.unlink(missing_ok=True)

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=("oracle_depth", "metric", "bucket", "count", "fraction")
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_ablation_figures(
    figures_dir: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    depths = [str(row["oracle_depth"]) for row in depth_summaries]
    detection_rates = [float(row["overall_detection_rate"]) * 100.0 for row in depth_summaries]
    mean_deltas = [float(row["mean_bpr_delta"]) for row in depth_summaries]
    transition_cov = [float(row["mean_oracle_transition_coverage"]) * 100.0 for row in depth_summaries]

    _save_bar_plot(
        figures_dir / "detection_rate_by_depth.png",
        title="Mutation Detection Rate by Oracle Depth",
        xlabel="Oracle Depth",
        ylabel="Detection Rate (%)",
        labels=depths,
        values=[round(value, 1) for value in detection_rates],
    )
    _save_bar_plot(
        figures_dir / "mean_bpr_delta_by_depth.png",
        title="Mean BPR Delta by Oracle Depth",
        xlabel="Oracle Depth",
        ylabel="Mean BPR Delta",
        labels=depths,
        values=[round(value, 4) for value in mean_deltas],
    )
    _save_bar_plot(
        figures_dir / "oracle_transition_coverage_by_depth.png",
        title="Mean Oracle Transition Coverage by Depth",
        xlabel="Oracle Depth",
        ylabel="Transition Coverage (%)",
        labels=depths,
        values=[round(value, 1) for value in transition_cov],
    )

    active_operators = [
        operator
        for operator in MUTATION_OPERATORS
        if any(row.mutation_operator == operator for rows in depth_rows.values() for row in rows)
    ]
    if active_operators:
        plt = _pyplot()
        figure, axis = plt.subplots(figsize=(10, 5))
        width = 0.25
        x_positions = list(range(len(active_operators)))
        for index, depth in enumerate(ABLATION_DEPTHS):
            rates = compute_mutation_detection_rates(_cases_for_depth(depth_rows[depth], depth))
            values = [rates.get(operator, 0.0) * 100.0 for operator in active_operators]
            offsets = [pos + (index - 1) * width for pos in x_positions]
            axis.bar(offsets, values, width=width, label=depth)
        axis.set_title("Mutation Detection Rate by Operator and Oracle Depth")
        axis.set_xlabel("Mutation Operator")
        axis.set_ylabel("Detection Rate (%)")
        axis.set_xticks(x_positions)
        axis.set_xticklabels(active_operators, rotation=45, ha="right")
        axis.legend()
        figure.tight_layout()
        figure.savefig(figures_dir / "mutation_detection_by_operator_depth.png", dpi=120)
        plt.close(figure)

    shallow_detected = {
        row.case_id for row in depth_rows["shallow"] if row.fault_detected
    }
    for depth in ("medium", "deep"):
        depth_detected = {row.case_id for row in depth_rows[depth] if row.fault_detected}
        gained = len(depth_detected - shallow_detected)
        lost = len(shallow_detected - depth_detected)
        _save_bar_plot(
            figures_dir / f"detection_delta_vs_shallow_{depth}.png",
            title=f"Detection Changes vs Shallow ({depth})",
            xlabel="Change Type",
            ylabel="Cases",
            labels=["newly_detected", "lost_detection"],
            values=[gained, lost],
        )

    for depth in ABLATION_DEPTHS:
        deltas = [row.bpr_delta for row in depth_rows[depth]]
        _save_histogram(
            figures_dir / f"bpr_delta_distribution_{depth}.png",
            title=f"BPR Delta Distribution ({depth})",
            xlabel="BPR Delta",
            values=deltas,
            bins=min(10, max(3, len(set(deltas)))),
        )


def _write_publication_tables(
    tables_dir: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    header = (
        "Oracle Depth & Cases & Detection Rate & Detectable Ratio & "
        "Mean Faulty BPR & Mean BPR Delta & Mean Trans. Cov. \\\\"
    )
    lines = [
        "% Auto-generated by run-oracle-depth-ablation",
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        header,
        "\\midrule",
    ]
    for row in depth_summaries:
        lines.append(
            f"{row['oracle_depth']} & {row['case_count']} & "
            f"{100 * float(row['overall_detection_rate']):.1f}\\% & "
            f"{100 * float(row['detectable_case_ratio']):.1f}\\% & "
            f"{float(row['mean_faulty_bpr']):.3f} & "
            f"{float(row['mean_bpr_delta']):.3f} & "
            f"{100 * float(row['mean_oracle_transition_coverage']):.1f}\\% \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (tables_dir / "table_depth_summary.tex").write_text("\n".join(lines), encoding="utf-8")

    active_operators = sorted(
        {
            row.mutation_operator
            for rows in depth_rows.values()
            for row in rows
            if row.mutation_operator
        }
    )
    op_header = "Operator & " + " & ".join(ABLATION_DEPTHS) + " \\\\"
    op_lines = [
        "% Auto-generated by run-oracle-depth-ablation",
        "\\begin{tabular}{l" + "r" * len(ABLATION_DEPTHS) + "}",
        "\\toprule",
        op_header,
        "\\midrule",
    ]
    for operator in active_operators:
        cells = [operator]
        for depth in ABLATION_DEPTHS:
            rates = compute_mutation_detection_rates(_cases_for_depth(depth_rows[depth], depth))
            cells.append(f"{100 * rates.get(operator, 0.0):.1f}\\%")
        op_lines.append(" & ".join(cells) + " \\\\")
    op_lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (tables_dir / "table_detection_by_operator_depth.tex").write_text(
        "\n".join(op_lines), encoding="utf-8"
    )


def _sensitivity_conclusion(
    depth_summaries: list[dict[str, str | float | int]],
    *,
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
) -> str:
    by_depth = {str(row["oracle_depth"]): row for row in depth_summaries}
    shallow_rate = float(by_depth["shallow"]["overall_detection_rate"])
    deep_rate = float(by_depth["deep"]["overall_detection_rate"])
    medium_rate = float(by_depth["medium"]["overall_detection_rate"])
    delta_deep = deep_rate - shallow_rate
    delta_medium = medium_rate - shallow_rate

    shallow_detected = {row.case_id for row in depth_rows["shallow"] if row.fault_detected}
    deep_detected = {row.case_id for row in depth_rows["deep"] if row.fault_detected}
    gained = len(deep_detected - shallow_detected)
    lost = len(shallow_detected - deep_detected)
    total = int(by_depth["shallow"]["case_count"])

    if abs(delta_deep) < 0.01 and abs(delta_medium) < 0.01:
        sensitivity = (
            "Benchmark detection conclusions are **largely insensitive** to oracle depth "
            f"within the tested presets: overall detection moves from {shallow_rate:.1%} "
            f"(shallow) to {medium_rate:.1%} (medium) and {deep_rate:.1%} (deep)."
        )
    elif delta_deep > 0.05:
        sensitivity = (
            "Benchmark detection conclusions are **moderately sensitive** to oracle depth: "
            f"overall detection rises from {shallow_rate:.1%} at shallow to {deep_rate:.1%} "
            f"at deep (+{delta_deep:.1%} absolute). Deeper suites expose faults that shallow "
            "behavioural checks miss."
        )
    elif delta_deep < -0.05:
        sensitivity = (
            "Benchmark detection conclusions **decrease** with deeper oracles in this sample "
            f"({shallow_rate:.1%} shallow vs {deep_rate:.1%} deep), suggesting longer "
            "scenarios can mask certain mutation signatures on faulty FSMs."
        )
    else:
        sensitivity = (
            "Benchmark detection conclusions show **modest sensitivity** to oracle depth: "
            f"overall detection changes from {shallow_rate:.1%} (shallow) to {medium_rate:.1%} "
            f"(medium) and {deep_rate:.1%} (deep)."
        )

    paired = (
        f"Paired on {total} cases: {gained} faults newly detected at deep vs shallow, "
        f"{lost} faults detected only at shallow."
    )
    return f"{sensitivity} {paired}"


def write_ablation_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    cohort_path: Path,
    depth_summaries: list[dict[str, str | float | int]],
    depth_rows: dict[DepthLevel, list[DepthCaseResult]],
    scenario_policy: ScenarioPolicy = "shortest-path",
    paired_detection_rows: list[dict[str, str | float | int]] | None = None,
) -> None:
    """Write Markdown report answering oracle-depth sensitivity."""
    conclusion = _sensitivity_conclusion(depth_summaries, depth_rows=depth_rows)
    policy_line = (
        "- **Scenario policy:** depth-forced (longer random walks + extra scenarios when needed)"
        if scenario_policy == "depth-forced"
        else "- **Oracles:** regenerated with existing `generate_oracle_suite` presets only"
    )
    lines = [
        "# Oracle Depth Ablation (C3)",
        "",
        "Sensitivity analysis of mutation detection, BPR, and oracle coverage to "
        "behavioural oracle depth presets (`shallow`, `medium`, `deep`).",
        "",
        "## Experimental design",
        "",
        f"- **Dataset:** `{dataset_dir}`",
        f"- **Cohort:** {depth_summaries[0]['case_count']} cases (`{cohort_path.name}`)",
        "- **FSMs:** fixed reference/faulty machines from the published release",
        policy_line,
        "- **Depth presets:** shallow (max 5 steps), medium (12), deep (25)",
        "",
        "## Research question",
        "",
        "**How sensitive are benchmark conclusions to oracle depth?**",
        "",
        conclusion,
        "",
        "## Summary by oracle depth",
        "",
        "| Depth | Cases | Detection rate | Detectable ratio | Mean faulty BPR | Mean BPR delta | Mean trans. cov. |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in depth_summaries:
        lines.append(
            f"| `{row['oracle_depth']}` | {row['case_count']} | "
            f"{float(row['overall_detection_rate']):.2%} | "
            f"{float(row['detectable_case_ratio']):.2%} | "
            f"{float(row['mean_faulty_bpr']):.4f} | "
            f"{float(row['mean_bpr_delta']):.4f} | "
            f"{float(row['mean_oracle_transition_coverage']):.2%} |"
        )

    lines.extend(
        [
            "",
            "## Mutation operator detection by depth",
            "",
            "| Operator | Shallow | Medium | Deep |",
            "|---|---:|---:|---:|",
        ]
    )
    operators = sorted({row.mutation_operator for rows in depth_rows.values() for row in rows})
    for operator in operators:
        cells = [f"`{operator}`"]
        for depth in ABLATION_DEPTHS:
            rates = compute_mutation_detection_rates(_cases_for_depth(depth_rows[depth], depth))
            cells.append(f"{rates.get(operator, 0.0):.2%}")
        lines.append("| " + " | ".join(cells) + " |")

    if paired_detection_rows:
        lines.extend(
            [
                "",
                "## Paired detection changes vs shallow (McNemar-style)",
                "",
                "| Depth | Both | Shallow only | Higher only | Neither | Gains | Losses | χ² |",
                "|---|---:|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for row in paired_detection_rows:
            lines.append(
                f"| `{row['comparison_depth']}` | {row['both_detected']} | "
                f"{row['shallow_only_detected']} | {row['higher_only_detected']} | "
                f"{row['neither_detected']} | {row['detection_gains']} | "
                f"{row['detection_losses']} | {row['mcnemar_chi2']} |"
            )

    lines.extend(
        [
            "",
            "## Figures",
            "",
            "![Detection rate by depth](figures/detection_rate_by_depth.png)",
            "",
            "![Mutation detection by operator and depth](figures/mutation_detection_by_operator_depth.png)",
            "",
            "![Mean BPR delta by depth](figures/mean_bpr_delta_by_depth.png)",
            "",
            "![Oracle transition coverage by depth](figures/oracle_transition_coverage_by_depth.png)",
            "",
            "## Artifacts",
            "",
            f"- Depth summary: `{output_dir / 'depth_summary.csv'}`",
            f"- Combined summary: `{output_dir / 'summary.csv'}`",
            f"- Distributions: `{output_dir / 'distributions.csv'}`",
            f"- Per-case results: `{output_dir / 'per_case_results.csv'}`",
            f"- Confidence intervals: `{output_dir / 'confidence_intervals.csv'}`",
        ]
    )
    if scenario_policy == "depth-forced":
        lines.extend(
            [
                f"- Paired detection changes: `{output_dir / 'paired_detection_changes.csv'}`",
                f"- Coverage by depth: `{output_dir / 'coverage_by_depth.csv'}`",
            ]
        )
    lines.extend(
        [
            f"- LaTeX tables: `{output_dir / 'tables'}/`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_v2_publication_tables(
    tables_dir: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
    paired_detection_rows: list[dict[str, str | float | int]],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by run-oracle-depth-ablation --scenario-policy depth-forced",
        "\\begin{table}[t]",
        "\\caption{Depth-forced oracle ablation summary by preset.}",
        "\\label{tab:c3-depth-forced-summary}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrr@{}}",
        "\\toprule",
        "Depth & Cases & Detection & Mean len. & Max len. & Scenarios & $\\Delta$BPR \\\\",
        "\\midrule",
    ]
    for row in depth_summaries:
        lines.append(
            f"{row['oracle_depth']} & {row['case_count']} & "
            f"{100 * float(row['overall_detection_rate']):.1f}\\% & "
            f"{float(row['mean_scenario_length']):.1f} & "
            f"{int(row['max_scenario_length'])} & "
            f"{float(row['mean_scenario_count']):.1f} & "
            f"{float(row['mean_bpr_delta']):.3f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_depth_forced_summary.tex").write_text("\n".join(lines), encoding="utf-8")

    paired_lines = [
        "% Auto-generated by run-oracle-depth-ablation --scenario-policy depth-forced",
        "\\begin{table}[t]",
        "\\caption{Paired detection changes vs shallow (McNemar-style counts).}",
        "\\label{tab:c3-paired-detection}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrr@{}}",
        "\\toprule",
        "Depth & Both & Shallow only & Higher only & Neither & Gains & Losses \\\\",
        "\\midrule",
    ]
    for row in paired_detection_rows:
        paired_lines.append(
            f"{row['comparison_depth']} & {row['both_detected']} & "
            f"{row['shallow_only_detected']} & {row['higher_only_detected']} & "
            f"{row['neither_detected']} & {row['detection_gains']} & {row['detection_losses']} \\\\"
        )
    paired_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_paired_detection_changes.tex").write_text(
        "\n".join(paired_lines),
        encoding="utf-8",
    )


def _copy_paper_exports(
    *,
    output_dir: Path,
    paper_export_dir: Path,
) -> None:
    paper_export_dir.mkdir(parents=True, exist_ok=True)
    paper_tables = paper_export_dir / "tables"
    paper_tables.mkdir(parents=True, exist_ok=True)
    for name in (
        "depth_summary.csv",
        "per_case_results.csv",
        "paired_detection_changes.csv",
        "coverage_by_depth.csv",
        "report.md",
        "manifest.json",
    ):
        source = output_dir / name
        if source.is_file():
            (paper_export_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for tex_name in ("table_depth_forced_summary.tex", "table_paired_detection_changes.tex"):
        source = output_dir / "tables" / tex_name
        if source.is_file():
            (paper_tables / tex_name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")


def run_oracle_depth_ablation(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_size: int = DEFAULT_COHORT_SIZE,
    cohort_manifest: Path | None = None,
    cohort_path: Path | None = None,
    write_cohort: bool = True,
    scenario_policy: ScenarioPolicy = "shortest-path",
    paper_export_dir: Path | None = None,
) -> OracleDepthAblationResult:
    """Run oracle depth ablation on a pinned stratified cohort."""
    if scenario_policy not in SCENARIO_POLICIES:
        msg = f"Unsupported scenario policy: {scenario_policy}"
        raise OracleDepthAblationError(msg)

    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise OracleDepthAblationError(msg)

    if scenario_policy == "depth-forced":
        out = output_dir or DEFAULT_V2_OUTPUT
        paper_dir = paper_export_dir or DEFAULT_V2_PAPER_EXPORT
    else:
        out = output_dir or Path("results/oracle_depth_ablation")
        paper_dir = None
    out.mkdir(parents=True, exist_ok=True)

    if cohort_path is not None and cohort_path.is_file():
        case_ids = load_cohort_manifest(cohort_path)
    else:
        case_ids = select_ablation_cohort(
            dataset_dir,
            cohort_manifest=cohort_manifest,
            size=cohort_size,
        )

    cohort_txt = cohort_path
    cohort_json = None
    if write_cohort and cohort_path is None:
        cohort_txt, cohort_json = write_ablation_cohort_manifest(
            dataset_dir,
            case_ids,
            source_manifest=cohort_manifest,
        )
    elif cohort_path is not None:
        cohort_txt = cohort_path
        cohort_json = cohort_path.with_suffix(".json")

    per_case_rows: list[DepthCaseResult] = []
    depth_rows: dict[DepthLevel, list[DepthCaseResult]] = {depth: [] for depth in ABLATION_DEPTHS}
    skipped_by_depth: Counter[DepthLevel] = Counter()

    for depth in ABLATION_DEPTHS:
        for case_id in case_ids:
            case_dir = dataset_dir / "cases" / case_id
            try:
                result = score_case_at_depth(
                    case_dir,
                    depth,
                    scenario_policy=scenario_policy,
                )
            except OracleDepthAblationError:
                skipped_by_depth[depth] += 1
                continue
            per_case_rows.append(result)
            depth_rows[depth].append(result)

    if not per_case_rows:
        msg = "No cases scored successfully across any oracle depth"
        raise OracleDepthAblationError(msg)

    paired_detection_rows = compute_paired_detection_changes(depth_rows)
    depth_summaries = []
    for depth in ABLATION_DEPTHS:
        if not depth_rows[depth]:
            continue
        gains, losses = (0, 0)
        if depth != "shallow":
            gains, losses = _paired_gains_losses(depth_rows, depth=depth)
        depth_summaries.append(
            _aggregate_depth_summary(
                depth,
                depth_rows[depth],
                skipped=skipped_by_depth[depth],
                scenario_policy=scenario_policy,
                detection_gains_vs_shallow=gains,
                detection_losses_vs_shallow=losses,
            )
        )

    per_case_path = out / "per_case_results.csv"
    depth_summary_path = out / "depth_summary.csv"
    summary_path = out / "summary.csv"
    distributions_path = out / "distributions.csv"
    report_path = out / "report.md"
    figures_dir = out / "figures"
    tables_dir = out / "tables"
    paired_detection_path = out / "paired_detection_changes.csv"
    coverage_by_depth_path = out / "coverage_by_depth.csv"
    manifest_path = out / "manifest.json"

    _write_per_case_csv(per_case_path, per_case_rows, scenario_policy=scenario_policy)
    _write_depth_summary_csv(depth_summary_path, depth_summaries, scenario_policy=scenario_policy)
    if scenario_policy == "depth-forced":
        _write_csv(paired_detection_path, list(PAIRED_DETECTION_COLUMNS), paired_detection_rows)
        _write_csv(
            coverage_by_depth_path,
            list(COVERAGE_BY_DEPTH_COLUMNS),
            _coverage_by_depth_rows(depth_summaries),
        )
    _write_combined_summary_csv(
        summary_path,
        dataset_dir=dataset_dir,
        depth_rows=depth_rows,
    )
    _write_combined_distributions_csv(
        distributions_path,
        dataset_dir=dataset_dir,
        depth_rows=depth_rows,
    )
    _write_ablation_figures(figures_dir, depth_summaries=depth_summaries, depth_rows=depth_rows)
    _write_publication_tables(
        tables_dir,
        depth_summaries=depth_summaries,
        depth_rows=depth_rows,
    )
    if scenario_policy == "depth-forced":
        _write_v2_publication_tables(
            tables_dir,
            depth_summaries=depth_summaries,
            paired_detection_rows=paired_detection_rows,
        )
    write_ablation_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME),
        depth_summaries=depth_summaries,
        depth_rows=depth_rows,
        scenario_policy=scenario_policy,
        paired_detection_rows=paired_detection_rows if scenario_policy == "depth-forced" else None,
    )

    ci_rows = compute_c3_confidence_intervals({depth: depth_rows[depth] for depth in ABLATION_DEPTHS})
    write_confidence_interval_exports(
        out,
        campaign="C3-oracle-depth-ablation",
        rows=ci_rows,
    )
    append_ci_section_to_report(report_path, ci_rows)

    manifest = {
        "experiment": V2_EXPERIMENT if scenario_policy == "depth-forced" else "C3-oracle-depth-ablation",
        "dataset_dir": str(dataset_dir),
        "output_dir": str(out),
        "cohort_size": len(case_ids),
        "cohort_path": str(cohort_txt),
        "scenario_policy": scenario_policy,
        "depths": list(ABLATION_DEPTHS),
        "depth_summaries": depth_summaries,
        "paired_detection_changes": paired_detection_rows if scenario_policy == "depth-forced" else None,
        "skipped_by_depth": dict(skipped_by_depth),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    if scenario_policy == "depth-forced" and paper_dir is not None:
        _copy_paper_exports(output_dir=out, paper_export_dir=paper_dir)

    return OracleDepthAblationResult(
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME),
        cohort_manifest_path=cohort_json or (dataset_dir / COHORT_JSON_FILENAME),
        per_case_path=per_case_path,
        depth_summary_path=depth_summary_path,
        summary_path=summary_path,
        distributions_path=distributions_path,
        report_path=report_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        case_count=len(case_ids),
        manifest_path=manifest_path,
        paired_detection_path=paired_detection_path if scenario_policy == "depth-forced" else None,
        coverage_by_depth_path=coverage_by_depth_path if scenario_policy == "depth-forced" else None,
        paper_export_dir=paper_dir,
    )
