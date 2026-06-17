"""C1 baseline repair campaign export, manifest, and multi-seed random analysis."""

from __future__ import annotations

import csv
import json
import random
import shutil
import statistics
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.benchmark_utility import (
    C1_DETERMINISTIC_TOOL_IDS,
    C1_SEEDED_TOOL_IDS,
    C1_TOOL_IDS,
    TOOL_LABELS,
)
from fsmrepairbench.experiments import discover_experiment_cases
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.statistics import (
    ConfidenceIntervalExportResult,
    append_ci_section_to_report,
    bootstrap_ci as case_bootstrap_ci,
    C1_BASELINE_TOOL_IDS,
    compute_c1_detectable_confidence_intervals,
    compute_c1_paired_confidence_intervals,
    write_confidence_interval_exports,
    write_paired_confidence_interval_exports,
)
from fsmrepairbench.tool_runner import (
    ToolRunSummaryRow,
    build_tool_tasks,
    execute_tool_task,
    load_tool_config,
    resolve_cases_dir,
)

RELEASE_LABEL = "v0.2.0-analysis"
CAMPAIGN_LABEL = "C1-baseline-repair"
ZENODO_DOI = "10.5281/zenodo.20724095"
DEFAULT_DATASET_PATH = "data/fsmrepairbench_1k"
DEFAULT_COHORT_FILE = "analysis_cohort_1k.txt"
DEFAULT_TOOLS_DIR = "tools/baselines_c1"
DEFAULT_RAW_RUNS_DIR = "results/baseline_repair_C1"
LEGACY_RAW_RUNS_DIR = "results/repair_baseline_1k_c1"
DEFAULT_PAPER_EXPORT_DIR = "../paper1/results/baseline_repair_C1"
DEFAULT_WORKERS = 4

C1_MANIFEST_REQUIRED_FIELDS: tuple[str, ...] = (
    "release_label",
    "campaign_label",
    "zenodo_doi",
    "dataset_path",
    "cohort_file",
    "cohort_sha256",
    "number_of_cases",
    "tool_names",
    "tool_config_paths",
    "engine_config",
    "seeds",
    "workers",
    "timestamp_utc",
    "git_commit_hash",
    "output_files",
    "regeneration_commands",
)
DETERMINISTIC_TOOL_IDS: tuple[str, ...] = C1_DETERMINISTIC_TOOL_IDS
RANDOM_TOOL_ID = "baseline_random"
SEEDED_TOOL_IDS: tuple[str, ...] = C1_SEEDED_TOOL_IDS
DEFAULT_RANDOM_SEEDS: tuple[int, ...] = tuple(range(10))
ENGINE_MULTISEED_METRICS: tuple[str, ...] = (
    "detection_rate",
    "complete_repair_rate",
    "effective_repair_rate",
    "mean_delta_bpr",
)
ENGINE_PARTITIONS: tuple[str, ...] = ("cohort_wide", "detectable_only")
ENGINE_MULTISEED_SUMMARY_BASENAME = "multiseed_engine_summary"
ENGINE_MULTISEED_PER_SEED_BASENAME = "engine_multiseed_per_seed"
ENGINE_MULTISEED_TEX_BASENAME = "table_engine_multiseed"
BOOTSTRAP_SEED = 42
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_CI = 0.95

MULTISEED_SUMMARY_BASENAME = "random_multiseed_summary"
MULTISEED_PER_SEED_BASENAME = "random_multiseed_per_seed"
MULTISEED_TEX_BASENAME = "table_random_multiseed"

METRIC_NAMES: tuple[str, ...] = (
    "complete_repair_rate",
    "effective_repair_rate",
    "mean_delta_bpr",
    "regression_rate",
)

METRIC_FLAT_SUFFIXES: dict[str, tuple[str, ...]] = {
    "complete_repair_rate": ("mean", "std", "min", "max", "ci95_low", "ci95_high"),
    "effective_repair_rate": ("mean", "std", "min", "max", "ci95_low", "ci95_high"),
    "mean_delta_bpr": ("mean", "std", "min", "max", "ci95_low", "ci95_high"),
    "regression_rate": ("mean", "std", "ci95_low", "ci95_high"),
}


def multiseed_summary_column_names() -> tuple[str, ...]:
    """Return flattened multi-seed summary column names."""
    columns: list[str] = ["seed_count"]
    for metric, suffixes in METRIC_FLAT_SUFFIXES.items():
        for suffix in suffixes:
            columns.append(f"{metric}_{suffix}")
    return tuple(columns)


class BaselineRepairCampaignError(ValueError):
    """Raised when C1 baseline repair export fails."""


@dataclass(frozen=True)
class C1ExportResult:
    """Paths written by a C1 random multi-seed export."""

    raw_runs_dir: Path
    paper_export_dir: Path
    summary_csv_path: Path
    summary_json_path: Path
    per_seed_csv_path: Path
    tex_table_path: Path
    report_path: Path


def load_cohort_manifest(path: Path) -> list[str]:
    """Load one case ID per line from *path*."""
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise BaselineRepairCampaignError(msg)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_random_seeds(
    raw: str | None,
    *,
    default: Sequence[int] = DEFAULT_RANDOM_SEEDS,
) -> tuple[int, ...]:
    """Parse comma-separated random baseline seeds or an integer count (0..n-1)."""
    if raw is None or not str(raw).strip():
        return tuple(default)
    text = str(raw).strip()
    if text.isdigit():
        count = int(text)
        if count < 1:
            msg = "Seed count must be at least 1"
            raise BaselineRepairCampaignError(msg)
        return tuple(range(count))
    seeds: list[int] = []
    for part in text.split(","):
        part = part.strip()
        if not part:
            continue
        seeds.append(int(part))
    if not seeds:
        msg = "At least one random baseline seed is required"
        raise BaselineRepairCampaignError(msg)
    return tuple(seeds)


def parse_seeds(raw: str | None, *, default: Sequence[int] = DEFAULT_RANDOM_SEEDS) -> tuple[int, ...]:
    """Backward-compatible alias for :func:`parse_random_seeds`."""
    return parse_random_seeds(raw, default=default)


def _load_c1_summary_rows(raw_runs_dir: Path, cohort_ids: set[str]) -> list[dict[str, str]]:
    per_case_path = raw_runs_dir / "per_case_results.csv"
    summary_path = raw_runs_dir / "summary.csv"
    source_path = per_case_path if per_case_path.is_file() else summary_path
    if not source_path.is_file():
        return []
    rows: list[dict[str, str]] = []
    with source_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "case_id" not in reader.fieldnames:
            return []
        for row in reader:
            if row["case_id"] in cohort_ids:
                rows.append(dict(row))
    return rows


def _detectable_case_ids(dataset_dir: Path, cohort_ids: set[str]) -> set[str]:
    from fsmrepairbench.dataset_builder import DatasetBuilderError, load_dataset_cases

    try:
        cases = load_dataset_cases(dataset_dir)
    except DatasetBuilderError:
        return set()
    detectable: set[str] = set()
    for case in cases:
        if case.case_id in cohort_ids and case.bpr_delta > 0.0:
            detectable.add(case.case_id)
    return detectable


def write_c1_confidence_interval_exports(
    *,
    raw_runs_dir: Path,
    dataset_dir: Path,
    cohort_file: Path,
    paper_export_dir: Path | None = None,
    tool_ids: Sequence[str] | None = None,
    campaign: str = CAMPAIGN_LABEL,
    include_paired: bool = True,
) -> ConfidenceIntervalExportResult | None:
    """Write case-bootstrap CIs for C1 baseline repair metrics."""
    cohort_ids = set(load_cohort_manifest(cohort_file))
    tool_rows = _load_c1_summary_rows(raw_runs_dir, cohort_ids)
    if not tool_rows:
        return None

    if "oracle_detected" in tool_rows[0]:
        detectable_ids = {
            row["case_id"]
            for row in tool_rows
            if row.get("oracle_detected", "").strip().lower() == "true"
        }
    else:
        detectable_ids = _detectable_case_ids(dataset_dir, cohort_ids)
    ci_rows = compute_c1_detectable_confidence_intervals(
        tool_rows,
        detectable_case_ids=detectable_ids,
        tool_ids=tool_ids or list(C1_BASELINE_TOOL_IDS),
    )
    if not ci_rows:
        return None

    result = write_confidence_interval_exports(
        raw_runs_dir,
        campaign=campaign,
        rows=ci_rows,
        paper_export_dir=paper_export_dir,
    )
    if include_paired:
        paired_rows = compute_c1_paired_confidence_intervals(
            tool_rows,
            detectable_case_ids=detectable_ids,
        )
        if paired_rows:
            write_paired_confidence_interval_exports(
                raw_runs_dir,
                campaign=campaign,
                rows=paired_rows,
                paper_export_dir=paper_export_dir,
            )
    append_ci_section_to_report(raw_runs_dir / "report.md", ci_rows)
    if paper_export_dir is not None:
        append_ci_section_to_report(paper_export_dir / "report.md", ci_rows)
    return result


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_resamples: int = 10_000,
    ci: float = 0.95,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    """Return a two-sided bootstrap confidence interval for the mean (multi-seed)."""
    generator = rng or random.Random(BOOTSTRAP_SEED)
    return case_bootstrap_ci(values, n_resamples=n_resamples, ci=ci, rng=generator)


def summarize_random_rows(rows: Sequence[ToolRunSummaryRow]) -> dict[str, float | int]:
    """Aggregate cohort-level random baseline metrics from tool-run rows."""
    completed = [row for row in rows if row.status == "completed"]
    if not completed:
        return {
            "cases": 0,
            "complete_repair_rate": 0.0,
            "effective_repair_rate": 0.0,
            "mean_delta_bpr": 0.0,
            "regression_rate": 0.0,
        }
    return {
        "cases": len(completed),
        "complete_repair_rate": round(
            sum(1 for row in completed if row.complete_repair) / len(completed),
            6,
        ),
        "effective_repair_rate": round(
            sum(1 for row in completed if row.effective_repair) / len(completed),
            6,
        ),
        "mean_delta_bpr": round(statistics.mean(row.delta_bpr for row in completed), 6),
        "regression_rate": round(
            sum(1 for row in completed if row.regression) / len(completed),
            6,
        ),
    }


def compute_multi_seed_statistics(
    per_seed_metrics: Sequence[dict[str, float | int]],
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, float]]:
    """Compute mean/std/min/max and bootstrap 95% CI for each metric across seeds."""
    rng = random.Random(bootstrap_seed)
    stats: dict[str, dict[str, float]] = {}
    for metric in METRIC_NAMES:
        values = [float(item[metric]) for item in per_seed_metrics]
        low, high = bootstrap_ci(
            values,
            n_resamples=bootstrap_resamples,
            ci=BOOTSTRAP_CI,
            rng=rng,
        )
        stats[metric] = {
            "mean": round(statistics.mean(values), 6),
            "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "ci95_low": round(low, 6),
            "ci95_high": round(high, 6),
        }
    return stats


def run_seeded_baseline_for_seed(
    dataset_dir: Path,
    tools_dir: Path,
    case_ids: set[str],
    tool_id: str,
    seed: int,
    *,
    workers: int = 1,
    output_dir: Path | None = None,
) -> list[ToolRunSummaryRow]:
    """Run one seeded baseline engine on *case_ids* using *seed*."""
    if workers < 1:
        msg = "workers must be at least 1"
        raise BaselineRepairCampaignError(msg)

    cases_dir = resolve_cases_dir(dataset_dir)
    all_cases = discover_experiment_cases(cases_dir)
    cases = [case for case in all_cases if case.case_id in case_ids]
    missing = sorted(case_ids - {case.case_id for case in cases})
    if missing:
        msg = f"Cohort references missing cases: {', '.join(missing[:5])}"
        raise BaselineRepairCampaignError(msg)

    config_path = tools_dir / f"{tool_id}.yaml"
    if not config_path.is_file():
        msg = f"Missing tool config for {tool_id}: {config_path}"
        raise BaselineRepairCampaignError(msg)

    tool = load_tool_config(config_path)
    tool = tool.model_copy(
        update={"environment": {**tool.environment, "baseline_seed": str(seed)}},
    )
    tasks = build_tool_tasks(cases, [tool])
    rows: list[ToolRunSummaryRow] = []

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    run_output_dir = output_dir
    scratch_dir: tempfile.TemporaryDirectory[str] | None = None
    if run_output_dir is None:
        scratch_dir = tempfile.TemporaryDirectory(prefix="fsmrepairbench_multiseed_")
        run_output_dir = Path(scratch_dir.name)

    try:
        if workers == 1:
            for task in tasks:
                rows.append(
                    execute_tool_task(task, output_dir=run_output_dir),
                )
        else:
            from concurrent.futures import ThreadPoolExecutor, as_completed

            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {
                    pool.submit(
                        execute_tool_task,
                        task,
                        output_dir=run_output_dir,
                    ): task
                    for task in tasks
                }
                for future in as_completed(futures):
                    rows.append(future.result())
    finally:
        if scratch_dir is not None:
            shutil.rmtree(scratch_dir.name, ignore_errors=True)

    rows.sort(key=lambda row: row.case_id)
    return rows


def run_random_baseline_for_seed(
    dataset_dir: Path,
    tools_dir: Path,
    case_ids: set[str],
    seed: int,
    *,
    workers: int = 1,
    output_dir: Path | None = None,
) -> list[ToolRunSummaryRow]:
    """Run the random baseline on *case_ids* using *seed*."""
    return run_seeded_baseline_for_seed(
        dataset_dir,
        tools_dir,
        case_ids,
        RANDOM_TOOL_ID,
        seed,
        workers=workers,
        output_dir=output_dir,
    )


def _oracle_detected(row: ToolRunSummaryRow) -> bool:
    return row.initial_bpr < 1.0 - 1e-9


def _partition_rows(
    rows: Sequence[ToolRunSummaryRow],
    partition: str,
) -> list[ToolRunSummaryRow]:
    if partition == "detectable_only":
        return [row for row in rows if _oracle_detected(row)]
    return list(rows)


def summarize_engine_seed_metrics(
    rows: Sequence[ToolRunSummaryRow],
    *,
    seed: int | None = None,
) -> dict[str, float | int]:
    """Aggregate cohort-level metrics for one engine seed run."""
    completed = [row for row in rows if row.status == "completed"]
    metrics: dict[str, float | int] = {"cases": len(completed)}
    if seed is not None:
        metrics["seed"] = seed

    for partition in ENGINE_PARTITIONS:
        subset = _partition_rows(completed, partition)
        prefix = f"{partition}_"
        if not subset:
            for metric in ENGINE_MULTISEED_METRICS:
                metrics[f"{prefix}{metric}"] = 0.0
            metrics[f"{prefix}n_cases"] = 0
            continue

        metrics[f"{prefix}n_cases"] = len(subset)
        metrics[f"{prefix}detection_rate"] = round(
            sum(1 for row in subset if _oracle_detected(row)) / len(subset),
            6,
        )
        metrics[f"{prefix}complete_repair_rate"] = round(
            sum(1 for row in subset if row.complete_repair) / len(subset),
            6,
        )
        metrics[f"{prefix}effective_repair_rate"] = round(
            sum(1 for row in subset if row.effective_repair) / len(subset),
            6,
        )
        metrics[f"{prefix}mean_delta_bpr"] = round(
            statistics.mean(row.delta_bpr for row in subset),
            6,
        )

    legacy_completed = completed
    metrics.update(
        {
            "complete_repair_rate": round(
                sum(1 for row in legacy_completed if row.complete_repair) / len(legacy_completed),
                6,
            )
            if legacy_completed
            else 0.0,
            "effective_repair_rate": round(
                sum(1 for row in legacy_completed if row.effective_repair) / len(legacy_completed),
                6,
            )
            if legacy_completed
            else 0.0,
            "mean_delta_bpr": round(
                statistics.mean(row.delta_bpr for row in legacy_completed),
                6,
            )
            if legacy_completed
            else 0.0,
            "regression_rate": round(
                sum(1 for row in legacy_completed if row.regression) / len(legacy_completed),
                6,
            )
            if legacy_completed
            else 0.0,
        }
    )
    return metrics


def _metric_values_from_seed_rows(
    per_seed: Sequence[Mapping[str, float | int]],
    *,
    partition: str,
    metric: str,
) -> list[float]:
    key = f"{partition}_{metric}"
    return [float(row[key]) for row in per_seed if key in row]


def aggregate_engine_multiseed_statistics(
    per_seed: Sequence[Mapping[str, float | int]],
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, float]]:
    """Compute mean/std/min/max and bootstrap 95% CI for each partition metric."""
    rng = random.Random(bootstrap_seed)
    stats: dict[str, dict[str, float]] = {}
    for partition in ENGINE_PARTITIONS:
        for metric in ENGINE_MULTISEED_METRICS:
            values = _metric_values_from_seed_rows(
                per_seed,
                partition=partition,
                metric=metric,
            )
            if not values:
                continue
            low, high = bootstrap_ci(
                values,
                n_resamples=bootstrap_resamples,
                ci=BOOTSTRAP_CI,
                rng=rng,
            )
            key = f"{partition}::{metric}"
            stats[key] = {
                "mean": round(statistics.mean(values), 6),
                "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
                "min": round(min(values), 6),
                "max": round(max(values), 6),
                "ci95_low": round(low, 6),
                "ci95_high": round(high, 6),
            }
    return stats


def run_multi_seed_engine_analysis(
    dataset_dir: Path,
    tools_dir: Path,
    case_ids: set[str],
    tool_id: str,
    seeds: Sequence[int],
    *,
    workers: int = 1,
    multi_seed_dir: Path | None = None,
) -> tuple[list[dict[str, float | int]], dict[str, dict[str, float]]]:
    """Run one seeded engine for each seed and return per-seed metrics plus aggregates."""
    per_seed: list[dict[str, float | int]] = []
    for seed in seeds:
        seed_dir = None
        if multi_seed_dir is not None:
            seed_dir = multi_seed_dir / tool_id / f"seed_{seed:04d}"
        rows = run_seeded_baseline_for_seed(
            dataset_dir,
            tools_dir,
            case_ids,
            tool_id,
            seed,
            workers=workers,
            output_dir=seed_dir,
        )
        metrics = summarize_engine_seed_metrics(rows, seed=seed)
        metrics["tool_id"] = tool_id
        per_seed.append(metrics)
    aggregate = aggregate_engine_multiseed_statistics(per_seed)
    return per_seed, aggregate


def deterministic_engine_multiseed_rows(
    enriched_rows: Sequence[Mapping[str, Any]],
    *,
    tool_id: str,
) -> list[dict[str, str | int | float]]:
    """Build single-run engine summary rows for deterministic baselines."""
    tool_rows = [row for row in enriched_rows if str(row.get("tool_id")) == tool_id]
    rows: list[dict[str, str | int | float]] = []
    for partition in ENGINE_PARTITIONS:
        if partition == "detectable_only":
            subset = [row for row in tool_rows if row.get("oracle_detected")]
        else:
            subset = list(tool_rows)
        if not subset:
            continue
        n_cases = len(subset)
        detection_rate = round(
            sum(1 for row in subset if row.get("oracle_detected")) / n_cases,
            6,
        )
        complete_rate = round(
            sum(1 for row in subset if row.get("complete_repair")) / n_cases,
            6,
        )
        effective_rate = round(
            sum(1 for row in subset if row.get("effective_repair")) / n_cases,
            6,
        )
        mean_delta = round(
            statistics.mean(float(row["delta_bpr"]) for row in subset),
            6,
        )
        for metric, value in (
            ("detection_rate", detection_rate),
            ("complete_repair_rate", complete_rate),
            ("effective_repair_rate", effective_rate),
            ("mean_delta_bpr", mean_delta),
        ):
            rows.append(
                {
                    "tool_id": tool_id,
                    "tool_label": TOOL_LABELS.get(tool_id, tool_id),
                    "partition": partition,
                    "metric": metric,
                    "n_cases": n_cases,
                    "mean": value,
                    "std": 0.0,
                    "min": value,
                    "max": value,
                    "ci95_low": value,
                    "ci95_high": value,
                    "ci_method": "single_run",
                    "seed_count": 1,
                }
            )
    return rows


def build_engine_multiseed_summary_rows(
    *,
    enriched_rows: Sequence[Mapping[str, Any]] | None,
    seeded_results: Mapping[str, tuple[list[dict[str, float | int]], dict[str, dict[str, float]]]],
    seeds: Sequence[int],
) -> list[dict[str, str | int | float]]:
    """Combine deterministic single-run and seeded multi-run engine summaries."""
    summary_rows: list[dict[str, str | int | float]] = []
    seed_count = len(seeds)

    for tool_id in C1_TOOL_IDS:
        if tool_id in SEEDED_TOOL_IDS and tool_id in seeded_results:
            _per_seed, aggregate = seeded_results[tool_id]
            for key, stats in aggregate.items():
                partition, metric = key.split("::", 1)
                n_cases_key = f"{partition}_n_cases"
                n_cases = int(_per_seed[-1].get(n_cases_key, 0)) if _per_seed else 0
                summary_rows.append(
                    {
                        "tool_id": tool_id,
                        "tool_label": TOOL_LABELS.get(tool_id, tool_id),
                        "partition": partition,
                        "metric": metric,
                        "n_cases": n_cases,
                        "mean": stats["mean"],
                        "std": stats["std"],
                        "min": stats["min"],
                        "max": stats["max"],
                        "ci95_low": stats["ci95_low"],
                        "ci95_high": stats["ci95_high"],
                        "ci_method": "seed_bootstrap",
                        "seed_count": seed_count,
                    }
                )
        elif enriched_rows is not None and tool_id in C1_DETERMINISTIC_TOOL_IDS:
            summary_rows.extend(
                deterministic_engine_multiseed_rows(enriched_rows, tool_id=tool_id)
            )
    return summary_rows


def write_engine_multiseed_exports(
    *,
    raw_runs_dir: Path,
    paper_export_dir: Path,
    summary_rows: Sequence[Mapping[str, str | int | float]],
    per_seed_rows: Sequence[Mapping[str, str | int | float]] | None = None,
) -> Path:
    """Write multiseed_engine_summary.csv and LaTeX table for all C1 engines."""
    fieldnames = [
        "tool_id",
        "tool_label",
        "partition",
        "metric",
        "n_cases",
        "mean",
        "std",
        "min",
        "max",
        "ci95_low",
        "ci95_high",
        "ci_method",
        "seed_count",
    ]
    summary_csv = raw_runs_dir / f"{ENGINE_MULTISEED_SUMMARY_BASENAME}.csv"
    _write_csv(summary_csv, fieldnames, [dict(row) for row in summary_rows])

    if per_seed_rows:
        per_seed_csv = raw_runs_dir / f"{ENGINE_MULTISEED_PER_SEED_BASENAME}.csv"
        per_seed_fields = sorted({key for row in per_seed_rows for key in row})
        _write_csv(per_seed_csv, per_seed_fields, [dict(row) for row in per_seed_rows])

    tex_path = raw_runs_dir / "tables" / f"{ENGINE_MULTISEED_TEX_BASENAME}.tex"
    tex_path.parent.mkdir(parents=True, exist_ok=True)
    body: list[list[str]] = []
    lookup = {
        (str(row["tool_id"]), str(row["partition"]), str(row["metric"])): row
        for row in summary_rows
    }
    for tool_id in C1_TOOL_IDS:
        label = TOOL_LABELS.get(tool_id, tool_id)
        det = lookup.get((tool_id, "detectable_only", "complete_repair_rate"))
        eff = lookup.get((tool_id, "detectable_only", "effective_repair_rate"))
        delta = lookup.get((tool_id, "detectable_only", "mean_delta_bpr"))
        if det is None and eff is None and delta is None:
            continue

        def _cell(row: Mapping[str, str | int | float] | None) -> str:
            if row is None:
                return "---"
            mean = float(row["mean"])
            std = float(row["std"])
            if float(row["seed_count"]) <= 1:
                return f"{mean:.4f}"
            return f"{mean:.4f} $\\pm$ {std:.4f}"

        body.append(
            [
                label.replace("-", "\\-"),
                _cell(det),
                _cell(eff),
                _cell(delta),
            ]
        )

    tex_lines = [
        "% Auto-generated from fsmrepairbench.baseline_repair_campaign",
        "\\begin{table}[t]",
        "\\caption{C1 baseline repair engines: detectable-only complete and effective repair "
        "and mean $\\Delta$BPR (mean $\\pm$ std across seeds for stochastic engines; "
        "single-run values for deterministic engines). "
        "\\textbf{Primary partition: detectable-only} ($n=495$); "
        "cohort-wide$^\\dagger$ totals appear in \\texttt{leaderboard.csv}.}",
        f"\\label{{tab:{ENGINE_MULTISEED_TEX_BASENAME}}}",
        "\\begin{tabular}{@{}lrrr@{}}",
        "\\toprule",
        "Engine & Complete (detect.) & Effective (detect.) & Mean $\\Delta$BPR (detect.) \\\\",
        "\\midrule",
    ]
    tex_lines.extend(" & ".join(row) + " \\\\" for row in body)
    tex_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    tex_path.write_text("\n".join(tex_lines), encoding="utf-8")

    paper_export_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        f"{ENGINE_MULTISEED_SUMMARY_BASENAME}.csv",
        f"{ENGINE_MULTISEED_PER_SEED_BASENAME}.csv",
    ):
        src = raw_runs_dir / name
        dest = paper_export_dir / name
        if src.is_file() and src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
    dest_tex = paper_export_dir / "tables" / f"{ENGINE_MULTISEED_TEX_BASENAME}.tex"
    if tex_path.resolve() != dest_tex.resolve():
        dest_tex.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(tex_path, dest_tex)
    return summary_csv


def run_c1_engine_multiseed_analysis(
    dataset_dir: Path,
    cohort_file: Path,
    tools_dir: Path,
    raw_runs_dir: Path,
    paper_export_dir: Path,
    *,
    seeds: Sequence[int] = DEFAULT_RANDOM_SEEDS,
    workers: int = DEFAULT_WORKERS,
    write_per_seed_json: bool = False,
    enriched_rows: Sequence[Mapping[str, Any]] | None = None,
) -> Path:
    """Run multi-seed analysis for all seeded C1 engines and export summary tables."""
    case_ids = set(load_cohort_manifest(cohort_file))
    multi_seed_root = raw_runs_dir / "multi_seed" if write_per_seed_json else None
    seeded_results: dict[str, tuple[list[dict[str, float | int]], dict[str, dict[str, float]]]] = {}
    per_seed_rows: list[dict[str, str | int | float]] = []

    for tool_id in SEEDED_TOOL_IDS:
        tool_seed_dir = multi_seed_root / tool_id if multi_seed_root is not None else None
        per_seed, aggregate = run_multi_seed_engine_analysis(
            dataset_dir,
            tools_dir,
            case_ids,
            tool_id,
            seeds,
            workers=workers,
            multi_seed_dir=tool_seed_dir,
        )
        seeded_results[tool_id] = (per_seed, aggregate)
        for row in per_seed:
            flat = dict(row)
            flat["tool_label"] = TOOL_LABELS.get(tool_id, tool_id)
            per_seed_rows.append(flat)

    summary_rows = build_engine_multiseed_summary_rows(
        enriched_rows=enriched_rows,
        seeded_results=seeded_results,
        seeds=seeds,
    )
    return write_engine_multiseed_exports(
        raw_runs_dir=raw_runs_dir,
        paper_export_dir=paper_export_dir,
        summary_rows=summary_rows,
        per_seed_rows=per_seed_rows or None,
    )


def run_multi_seed_random_analysis(
    dataset_dir: Path,
    tools_dir: Path,
    case_ids: set[str],
    seeds: Sequence[int],
    *,
    workers: int = 1,
    multi_seed_dir: Path | None = None,
    collect_subgroups: bool = False,
) -> tuple[
    list[dict[str, float | int]],
    dict[str, dict[str, float]],
    list[dict[str, dict[str, dict[str, dict[str, float | int]]]]] | None,
]:
    """Run random baseline for each seed and return per-seed metrics plus aggregates."""
    from fsmrepairbench.c1_multiseed_variance import (
        _load_dataset_rows,
        summarize_seed_subgroups,
    )

    dataset_rows = _load_dataset_rows(dataset_dir, case_ids) if collect_subgroups else None
    per_seed: list[dict[str, float | int]] = []
    per_seed_subgroups: list[dict[str, dict[str, dict[str, dict[str, float | int]]]]] | None = (
        [] if collect_subgroups else None
    )
    for seed in seeds:
        seed_dir = None
        if multi_seed_dir is not None:
            seed_dir = multi_seed_dir / f"seed_{seed:04d}"
        rows = run_random_baseline_for_seed(
            dataset_dir,
            tools_dir,
            case_ids,
            seed,
            workers=workers,
            output_dir=seed_dir,
        )
        metrics = summarize_random_rows(rows)
        metrics["seed"] = seed
        per_seed.append(metrics)
        if collect_subgroups and dataset_rows is not None and per_seed_subgroups is not None:
            per_seed_subgroups.append(summarize_seed_subgroups(rows, dataset_rows))
    aggregate = compute_multi_seed_statistics(per_seed)
    return per_seed, aggregate, per_seed_subgroups


def _load_engine_config(tools_dir: Path) -> list[dict[str, Any]]:
    """Load YAML tool configs for manifest engine_config."""
    configs: list[dict[str, Any]] = []
    for path in sorted(tools_dir.glob("baseline_*.yaml")):
        tool = load_tool_config(path)
        configs.append(
            {
                "tool_id": tool.tool_id,
                "command": tool.command,
                "timeout_seconds": tool.timeout_seconds,
                "environment": dict(tool.environment),
                "iterations": tool.iterations,
                "temperature": tool.temperature,
            }
        )
    return configs


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def flatten_multi_seed_statistics(
    aggregate: dict[str, dict[str, float]],
    *,
    seed_count: int,
) -> dict[str, float | int]:
    """Flatten nested aggregate statistics to publication column names."""
    flat: dict[str, float | int] = {"seed_count": seed_count}
    for metric, suffixes in METRIC_FLAT_SUFFIXES.items():
        metric_stats = aggregate[metric]
        for suffix in suffixes:
            source_key = "std" if suffix == "std" else suffix
            flat[f"{metric}_{suffix}"] = metric_stats[source_key]
    return flat


def _write_multiseed_report(
    path: Path,
    *,
    seeds: Sequence[int],
    flat_summary: dict[str, float | int],
    single_seed_complete_repair_rate: float | None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# C1 Random Baseline Multi-Seed Analysis",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Interpretation",
        "",
        "Deterministic baselines (`missing-transition`, `wrong-target`) are unchanged.",
        "The original single-seed random baseline (seed 0) remains in `leaderboard.csv` "
        "for backward compatibility.",
        "The multi-seed random summary below is the preferred floor estimate for STVR reporting.",
        "",
        "## Bootstrap confidence intervals",
        "",
        f"- Method: percentile bootstrap on seed-level cohort metrics",
        f"- Confidence level: {BOOTSTRAP_CI:.0%}",
        f"- Resamples: {BOOTSTRAP_RESAMPLES}",
        f"- Bootstrap RNG seed: {BOOTSTRAP_SEED}",
        f"- Random baseline seeds: {', '.join(str(seed) for seed in seeds)}",
        "",
        "## Multi-seed summary (preferred random floor)",
        "",
    ]
    if single_seed_complete_repair_rate is not None:
        lines.extend(
            [
                f"- Single-seed complete repair (seed 0, legacy): {single_seed_complete_repair_rate:.6f}",
                f"- Multi-seed complete repair mean: {flat_summary['complete_repair_rate_mean']:.6f}",
                f"- Multi-seed complete repair 95% CI: "
                f"[{flat_summary['complete_repair_rate_ci95_low']:.6f}, "
                f"{flat_summary['complete_repair_rate_ci95_high']:.6f}]",
                "",
            ]
        )
    for key in multiseed_summary_column_names():
        if key == "seed_count":
            continue
        lines.append(f"- `{key}`: {flat_summary[key]}")
    lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_multiseed_tex_table(path: Path, flat_summary: dict[str, float | int], *, seed_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        (
            "Complete repair rate",
            flat_summary["complete_repair_rate_mean"],
            flat_summary["complete_repair_rate_std"],
            flat_summary["complete_repair_rate_ci95_low"],
            flat_summary["complete_repair_rate_ci95_high"],
        ),
        (
            "Effective repair rate",
            flat_summary["effective_repair_rate_mean"],
            flat_summary["effective_repair_rate_std"],
            flat_summary["effective_repair_rate_ci95_low"],
            flat_summary["effective_repair_rate_ci95_high"],
        ),
        (
            "Mean $\\Delta$BPR",
            flat_summary["mean_delta_bpr_mean"],
            flat_summary["mean_delta_bpr_std"],
            flat_summary["mean_delta_bpr_ci95_low"],
            flat_summary["mean_delta_bpr_ci95_high"],
        ),
        (
            "Regression rate",
            flat_summary["regression_rate_mean"],
            flat_summary["regression_rate_std"],
            flat_summary["regression_rate_ci95_low"],
            flat_summary["regression_rate_ci95_high"],
        ),
    ]
    tex_lines = [
        "% Auto-generated from fsmrepairbench.baseline_repair_campaign",
        "\\begin{table}[t]",
        f"\\caption{{Multi-seed random baseline repair statistics ($n={seed_count}$ seeds). "
        "Takeaway: the multi-seed random floor is the preferred estimate; seed-0 leaderboard "
        "values remain for backward compatibility.}",
        f"\\label{{tab:{MULTISEED_TEX_BASENAME}}}",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Metric & Mean & Std & CI low & CI high \\\\",
        "\\midrule",
    ]
    for label, mean, std, low, high in rows:
        tex_lines.append(
            f"{label} & {mean:.4f} & {std:.4f} & {low:.4f} & {high:.4f} \\\\"
        )
    tex_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(tex_lines), encoding="utf-8")


def write_random_multiseed_exports(
    *,
    raw_runs_dir: Path,
    paper_export_dir: Path,
    per_seed: Sequence[dict[str, float | int]],
    aggregate: dict[str, dict[str, float]],
    seeds: Sequence[int],
    single_seed_complete_repair_rate: float | None = None,
) -> C1ExportResult:
    """Write random multi-seed CSV/JSON exports, LaTeX table, and report."""
    raw_runs_dir.mkdir(parents=True, exist_ok=True)
    paper_export_dir.mkdir(parents=True, exist_ok=True)

    flat_summary = flatten_multi_seed_statistics(aggregate, seed_count=len(seeds))
    summary_columns = list(multiseed_summary_column_names())

    summary_csv = raw_runs_dir / f"{MULTISEED_SUMMARY_BASENAME}.csv"
    _write_csv(summary_csv, summary_columns, [flat_summary])

    summary_json_path = raw_runs_dir / f"{MULTISEED_SUMMARY_BASENAME}.json"
    summary_payload = {
        "tool_id": RANDOM_TOOL_ID,
        "seeds": list(seeds),
        "summary": flat_summary,
        "aggregate": aggregate,
        "bootstrap": {
            "method": "percentile",
            "ci": BOOTSTRAP_CI,
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "backward_compatibility": {
            "single_seed_leaderboard_tool": RANDOM_TOOL_ID,
            "single_seed_default": 0,
            "single_seed_complete_repair_rate": single_seed_complete_repair_rate,
            "preferred_estimate": "multi_seed_summary",
        },
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    summary_json_path.write_text(json.dumps(summary_payload, indent=2) + "\n", encoding="utf-8")

    per_seed_csv = raw_runs_dir / f"{MULTISEED_PER_SEED_BASENAME}.csv"
    per_seed_columns = ["seed", "cases", *METRIC_NAMES]
    _write_csv(per_seed_csv, per_seed_columns, [dict(row) for row in per_seed])

    report_path = raw_runs_dir / "report.md"
    _write_multiseed_report(
        report_path,
        seeds=seeds,
        flat_summary=flat_summary,
        single_seed_complete_repair_rate=single_seed_complete_repair_rate,
    )

    tex_path = raw_runs_dir / "tables" / f"{MULTISEED_TEX_BASENAME}.tex"
    _write_multiseed_tex_table(tex_path, flat_summary, seed_count=len(seeds))

    paper_report = paper_export_dir / "report.md"
    if paper_report.is_file():
        existing = paper_report.read_text(encoding="utf-8")
        marker = "## Multi-seed random baseline"
        block = report_path.read_text(encoding="utf-8")
        if marker in existing:
            head, _, _tail = existing.partition(marker)
            paper_report.write_text(head + block, encoding="utf-8")
        else:
            paper_report.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")
    else:
        paper_report.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    return C1ExportResult(
        raw_runs_dir=raw_runs_dir,
        paper_export_dir=paper_export_dir,
        summary_csv_path=summary_csv,
        summary_json_path=summary_json_path,
        per_seed_csv_path=per_seed_csv,
        tex_table_path=tex_path,
        report_path=report_path,
    )


def write_multi_seed_exports(
    out_dir: Path,
    per_seed: Sequence[dict[str, float | int]],
    aggregate: dict[str, dict[str, float]],
    *,
    seeds: Sequence[int],
    paper_export_dir: Path | None = None,
    single_seed_complete_repair_rate: float | None = None,
) -> C1ExportResult:
    """Backward-compatible wrapper writing exports under *out_dir*."""
    paper_dir = paper_export_dir or Path(DEFAULT_PAPER_EXPORT_DIR)
    return write_random_multiseed_exports(
        raw_runs_dir=out_dir,
        paper_export_dir=paper_dir,
        per_seed=per_seed,
        aggregate=aggregate,
        seeds=seeds,
        single_seed_complete_repair_rate=single_seed_complete_repair_rate,
    )


def _read_single_seed_random_complete_rate(raw_runs_dir: Path) -> float | None:
    leaderboard = raw_runs_dir / "leaderboard.csv"
    if not leaderboard.is_file():
        return None
    for row in csv.DictReader(leaderboard.open(encoding="utf-8")):
        if row.get("tool_id") == RANDOM_TOOL_ID:
            raw = row.get("complete_repair_rate_cohort_wide") or row.get("complete_repair_rate")
            if raw:
                return float(raw)
    return None


def run_c1_random_multiseed_analysis(
    dataset_dir: Path,
    cohort_file: Path,
    tools_dir: Path,
    raw_runs_dir: Path,
    paper_export_dir: Path,
    *,
    random_seeds: Sequence[int] = DEFAULT_RANDOM_SEEDS,
    workers: int = DEFAULT_WORKERS,
    write_per_seed_json: bool = False,
    enriched_rows: Sequence[dict[str, Any]] | None = None,
    case_count: int | None = None,
    detectable_count: int | None = None,
) -> C1ExportResult:
    """Run multi-seed random baseline analysis without altering deterministic baselines."""
    from fsmrepairbench.c1_multiseed_variance import write_c1_multiseed_variance_exports

    case_ids = set(load_cohort_manifest(cohort_file))
    multi_seed_dir = raw_runs_dir / "multi_seed" if write_per_seed_json else None
    per_seed, aggregate, per_seed_subgroups = run_multi_seed_random_analysis(
        dataset_dir,
        tools_dir,
        case_ids,
        random_seeds,
        workers=workers,
        multi_seed_dir=multi_seed_dir,
        collect_subgroups=enriched_rows is not None,
    )
    single_seed_rate = _read_single_seed_random_complete_rate(raw_runs_dir)
    result = write_random_multiseed_exports(
        raw_runs_dir=raw_runs_dir,
        paper_export_dir=paper_export_dir,
        per_seed=per_seed,
        aggregate=aggregate,
        seeds=random_seeds,
        single_seed_complete_repair_rate=single_seed_rate,
    )
    if enriched_rows is not None and per_seed_subgroups is not None:
        resolved_case_count = case_count if case_count is not None else len(case_ids)
        resolved_detectable = detectable_count
        if resolved_detectable is None:
            resolved_detectable = len(
                {
                    str(row["case_id"])
                    for row in enriched_rows
                    if row.get("oracle_detected")
                }
            )
        write_c1_multiseed_variance_exports(
            raw_runs_dir=raw_runs_dir,
            paper_export_dir=paper_export_dir,
            enriched_rows=enriched_rows,
            per_seed_subgroups=per_seed_subgroups,
            seed_count=len(random_seeds),
            case_count=resolved_case_count,
            detectable_count=resolved_detectable,
        )
    run_c1_engine_multiseed_analysis(
        dataset_dir,
        cohort_file,
        tools_dir,
        raw_runs_dir,
        paper_export_dir,
        seeds=random_seeds,
        workers=workers,
        write_per_seed_json=write_per_seed_json,
        enriched_rows=enriched_rows,
    )
    publish_c1_manifests(
        dataset_dir=dataset_dir,
        cohort_file=cohort_file,
        tools_dir=tools_dir,
        raw_runs_dir=raw_runs_dir,
        paper_export_dir=paper_export_dir,
        workers=workers,
        number_of_cases=len(case_ids),
        seeds=random_seeds,
    )
    write_c1_confidence_interval_exports(
        raw_runs_dir=raw_runs_dir,
        dataset_dir=dataset_dir,
        cohort_file=cohort_file,
        paper_export_dir=paper_export_dir,
    )
    return result


@dataclass(frozen=True)
class C1ManifestResult:
    """Paths to C1 manifest files written for raw runs and paper export."""

    raw_manifest_path: Path
    paper_manifest_path: Path


def default_regeneration_commands(
    *,
    dataset_path: str = DEFAULT_DATASET_PATH,
    tools_dir: str = DEFAULT_TOOLS_DIR,
    raw_runs_dir: str = DEFAULT_RAW_RUNS_DIR,
    workers: int = DEFAULT_WORKERS,
) -> list[str]:
    """Return verbatim CLI commands to regenerate the C1 campaign."""
    return [
        (
            f"fsmrepairbench run-c1-baseline-repair {dataset_path} "
            f"--out {raw_runs_dir} --workers {workers}"
        ),
        (
            f"fsmrepairbench run-tools {dataset_path} {tools_dir}/ "
            f"--out {raw_runs_dir} "
            f"--cohort-file {dataset_path}/{DEFAULT_COHORT_FILE} "
            f"--workers {workers}"
        ),
        (
            f"fsmrepairbench export-c1-baseline-repair {dataset_path} "
            f"--out {raw_runs_dir} --workers {workers}"
        ),
    ]


def _relative_repo_path(path: Path, *, base: Path | None = None) -> str:
    """Return *path* relative to the repository root when possible."""
    repo_root = base or Path(__file__).resolve().parents[2]
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def _tool_config_paths(tools_dir: Path, *, repo_root: Path | None = None) -> list[str]:
    return sorted(_relative_repo_path(path, base=repo_root) for path in tools_dir.glob("*.yaml"))


def list_raw_run_output_files(raw_runs_dir: Path) -> list[str]:
    """List manifest-tracked files under the raw C1 run-tools directory."""
    files: list[str] = []
    for name in (
        "summary.csv",
        "leaderboard.csv",
        "tool_run_manifest.json",
        f"{MULTISEED_SUMMARY_BASENAME}.csv",
        f"{MULTISEED_SUMMARY_BASENAME}.json",
        f"{MULTISEED_PER_SEED_BASENAME}.csv",
        f"{ENGINE_MULTISEED_PER_SEED_BASENAME}.csv",
        "multiseed_by_operator.csv",
        "multiseed_by_operator.json",
        "multiseed_by_tier.csv",
        "multiseed_by_tier.json",
        "multiseed_engine_summary.csv",
        "confidence_intervals.csv",
        "confidence_intervals.json",
        "report.md",
    ):
        if (raw_runs_dir / name).is_file():
            files.append(name)
    if any(raw_runs_dir.glob("case_*__*.json")):
        files.append("case_*__*.json")
    if (raw_runs_dir / "multi_seed").is_dir():
        files.append("multi_seed/")
    files.append("manifest.json")
    return sorted(set(files))


def build_c1_manifest(
    *,
    dataset_path: Path | str,
    cohort_file: Path | str,
    tools_dir: Path,
    workers: int,
    number_of_cases: int,
    output_files: Sequence[str],
    regeneration_commands: Sequence[str] | None = None,
    repo_root: Path | None = None,
    seeds: Sequence[int] | None = None,
) -> dict[str, Any]:
    """Build the C1 campaign manifest payload."""
    cohort_path = Path(cohort_file)
    cohort_sha256 = sha256_file(cohort_path)
    tool_names = sorted(path.stem for path in tools_dir.glob("baseline_*.yaml"))

    manifest: dict[str, Any] = {
        "release_label": RELEASE_LABEL,
        "campaign_label": CAMPAIGN_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "dataset_path": _relative_repo_path(Path(dataset_path), base=repo_root),
        "cohort_file": _relative_repo_path(cohort_path, base=repo_root),
        "cohort_sha256": cohort_sha256,
        "number_of_cases": number_of_cases,
        "tool_names": tool_names,
        "tool_config_paths": _tool_config_paths(tools_dir, repo_root=repo_root),
        "engine_config": _load_engine_config(tools_dir),
        "seeds": list(seeds if seeds is not None else DEFAULT_RANDOM_SEEDS),
        "workers": workers,
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit_hash": get_git_commit(),
        "output_files": sorted(output_files),
        "regeneration_commands": list(
            regeneration_commands
            or default_regeneration_commands(workers=workers),
        ),
    }
    return manifest


def write_c1_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    """Write *manifest* JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def publish_c1_manifests(
    *,
    dataset_dir: Path,
    cohort_file: Path,
    tools_dir: Path,
    raw_runs_dir: Path,
    paper_export_dir: Path,
    workers: int = DEFAULT_WORKERS,
    number_of_cases: int | None = None,
    regeneration_commands: Sequence[str] | None = None,
    repo_root: Path | None = None,
    seeds: Sequence[int] | None = None,
) -> C1ManifestResult:
    """Write C1 manifest.json to raw runs and copy to the paper export directory."""
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    case_count = number_of_cases if number_of_cases is not None else len(
        load_cohort_manifest(cohort_file),
    )

    raw_manifest = build_c1_manifest(
        dataset_path=dataset_dir,
        cohort_file=cohort_file,
        tools_dir=tools_dir,
        workers=workers,
        number_of_cases=case_count,
        output_files=list_raw_run_output_files(raw_runs_dir),
        regeneration_commands=regeneration_commands,
        repo_root=repo_root,
        seeds=seeds,
    )
    raw_path = write_c1_manifest(raw_runs_dir / "manifest.json", raw_manifest)

    paper_manifest = build_c1_manifest(
        dataset_path=dataset_dir,
        cohort_file=cohort_file,
        tools_dir=tools_dir,
        workers=workers,
        number_of_cases=case_count,
        output_files=list_output_files(paper_export_dir),
        regeneration_commands=regeneration_commands,
        repo_root=repo_root,
        seeds=seeds,
    )
    paper_manifest["output_files"] = [
        path for path in paper_manifest["output_files"] if path != "manifest.json"
    ] + ["manifest.json"]
    if "leaderboard.csv" not in paper_manifest["output_files"]:
        paper_manifest["output_files"].append("leaderboard.csv")
    if "per_case_results.csv" not in paper_manifest["output_files"]:
        paper_manifest["output_files"].append("per_case_results.csv")
    paper_manifest["output_files"] = sorted(set(paper_manifest["output_files"]))
    paper_manifest["raw_runs_manifest"] = _relative_repo_path(raw_path, base=repo_root)

    paper_export_dir.mkdir(parents=True, exist_ok=True)
    paper_path = write_c1_manifest(paper_export_dir / "manifest.json", paper_manifest)

    return C1ManifestResult(raw_manifest_path=raw_path, paper_manifest_path=paper_path)


def list_output_files(out_dir: Path) -> list[str]:
    """Return relative paths for export artefacts (exclude per-case multi-seed JSON)."""
    files: list[str] = []
    has_multi_seed_cases = False
    for path in sorted(out_dir.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(out_dir).as_posix()
        if rel.startswith("multi_seed/seed_") and rel.endswith(".json"):
            has_multi_seed_cases = True
            continue
        files.append(rel)
    if has_multi_seed_cases and "multi_seed/" not in files:
        files.append("multi_seed/")
    return sorted(files)


def finalize_c1_manifest(
    *,
    dataset_dir: Path,
    cohort_path: Path,
    tools_dir: Path,
    out_dir: Path,
    workers: int,
    case_count: int,
    random_seeds: Sequence[int],
    multi_seed_aggregate: dict[str, dict[str, float]] | None = None,
    raw_runs_dir: Path | None = None,
) -> Path:
    """Write paper and raw C1 manifests after export files exist."""
    _ = random_seeds, multi_seed_aggregate
    raw_dir = raw_runs_dir or (Path(__file__).resolve().parents[2] / DEFAULT_RAW_RUNS_DIR)
    result = publish_c1_manifests(
        dataset_dir=dataset_dir,
        cohort_file=cohort_path,
        tools_dir=tools_dir,
        raw_runs_dir=raw_dir,
        paper_export_dir=out_dir,
        workers=workers,
        number_of_cases=case_count,
    )
    return result.paper_manifest_path


def export_c1_multi_seed_analysis(
    dataset_dir: Path,
    cohort_path: Path,
    tools_dir: Path,
    out_dir: Path,
    *,
    seeds: Sequence[int] = DEFAULT_RANDOM_SEEDS,
    workers: int = 1,
    write_per_seed_runs: bool = True,
    raw_runs_dir: Path | None = None,
) -> C1ExportResult:
    """Run multi-seed random baseline analysis and write export artefacts."""
    raw_dir = raw_runs_dir or (Path(__file__).resolve().parents[2] / DEFAULT_RAW_RUNS_DIR)
    return run_c1_random_multiseed_analysis(
        dataset_dir,
        cohort_path,
        tools_dir,
        raw_dir,
        out_dir,
        random_seeds=seeds,
        workers=workers,
        write_per_seed_json=write_per_seed_runs,
    )
