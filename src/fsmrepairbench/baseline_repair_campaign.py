"""C1 baseline repair campaign export, manifest, and multi-seed random analysis."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.experiments import discover_experiment_cases
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.tool_runner import (
    ToolRunSummaryRow,
    build_tool_tasks,
    execute_tool_task,
    load_tool_config,
    resolve_cases_dir,
)

RELEASE_LABEL = "C1-baseline-repair"
ZENODO_DOI = "10.5281/zenodo.20602528"
ZENODO_RELEASE = "v0.2.0-analysis"
DEFAULT_COHORT_FILE = "analysis_cohort_1k.txt"
DEFAULT_TOOLS_DIR = "tools/baselines_c1"
DETERMINISTIC_TOOL_IDS: tuple[str, ...] = (
    "baseline_missing_transition",
    "baseline_wrong_target",
)
RANDOM_TOOL_ID = "baseline_random"
DEFAULT_RANDOM_SEEDS: tuple[int, ...] = tuple(range(10))

METRIC_NAMES: tuple[str, ...] = (
    "complete_repair_rate",
    "effective_repair_rate",
    "mean_delta_bpr",
)


class BaselineRepairCampaignError(ValueError):
    """Raised when C1 baseline repair export fails."""


@dataclass(frozen=True)
class C1ExportResult:
    """Paths written by a C1 baseline repair export."""

    output_dir: Path
    manifest_path: Path
    multi_seed_summary_path: Path
    multi_seed_json_path: Path


def load_cohort_manifest(path: Path) -> list[str]:
    """Load one case ID per line from *path*."""
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise BaselineRepairCampaignError(msg)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def parse_seeds(raw: str | None, *, default: Sequence[int] = DEFAULT_RANDOM_SEEDS) -> tuple[int, ...]:
    """Parse comma-separated seeds or an integer count (0..n-1)."""
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


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_resamples: int = 10_000,
    ci: float = 0.95,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    """Return a two-sided bootstrap confidence interval for the mean."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        value = float(values[0])
        return (value, value)

    generator = rng or random.Random(42)
    alpha = (1.0 - ci) / 2.0
    boot_means: list[float] = []
    sample_size = len(values)
    for _ in range(n_resamples):
        draw = [values[generator.randrange(sample_size)] for _ in range(sample_size)]
        boot_means.append(statistics.mean(draw))
    boot_means.sort()
    low_index = max(0, int(alpha * n_resamples))
    high_index = min(len(boot_means) - 1, int((1.0 - alpha) * n_resamples) - 1)
    return (boot_means[low_index], boot_means[high_index])


def summarize_random_rows(rows: Sequence[ToolRunSummaryRow]) -> dict[str, float | int]:
    """Aggregate cohort-level random baseline metrics from tool-run rows."""
    completed = [row for row in rows if row.status == "completed"]
    if not completed:
        return {
            "cases": 0,
            "complete_repair_rate": 0.0,
            "effective_repair_rate": 0.0,
            "mean_delta_bpr": 0.0,
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
    }


def compute_multi_seed_statistics(
    per_seed_metrics: Sequence[dict[str, float | int]],
    *,
    bootstrap_resamples: int = 10_000,
    bootstrap_seed: int = 42,
) -> dict[str, dict[str, float]]:
    """Compute mean/std/min/max and bootstrap 95% CI for each metric across seeds."""
    rng = random.Random(bootstrap_seed)
    stats: dict[str, dict[str, float]] = {}
    for metric in METRIC_NAMES:
        values = [float(item[metric]) for item in per_seed_metrics]
        low, high = bootstrap_ci(values, n_resamples=bootstrap_resamples, rng=rng)
        stats[metric] = {
            "mean": round(statistics.mean(values), 6),
            "std_dev": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "ci95_low": round(low, 6),
            "ci95_high": round(high, 6),
        }
    return stats


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

    random_config_path = tools_dir / "baseline_random.yaml"
    tool = load_tool_config(random_config_path)
    tool = tool.model_copy(
        update={"environment": {**tool.environment, "baseline_seed": str(seed)}},
    )
    tasks = build_tool_tasks(cases, [tool])
    rows: list[ToolRunSummaryRow] = []

    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    if workers == 1:
        for task in tasks:
            rows.append(
                execute_tool_task(task, output_dir=output_dir or Path(".")),
            )
    else:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {
                pool.submit(
                    execute_tool_task,
                    task,
                    output_dir=output_dir or Path("."),
                ): task
                for task in tasks
            }
            for future in as_completed(futures):
                rows.append(future.result())

    rows.sort(key=lambda row: row.case_id)
    return rows


def run_multi_seed_random_analysis(
    dataset_dir: Path,
    tools_dir: Path,
    case_ids: set[str],
    seeds: Sequence[int],
    *,
    workers: int = 1,
    multi_seed_dir: Path | None = None,
) -> tuple[list[dict[str, float | int]], dict[str, dict[str, float]]]:
    """Run random baseline for each seed and return per-seed metrics plus aggregates."""
    per_seed: list[dict[str, float | int]] = []
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
    aggregate = compute_multi_seed_statistics(per_seed)
    return per_seed, aggregate


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_multi_seed_exports(
    out_dir: Path,
    per_seed: Sequence[dict[str, float | int]],
    aggregate: dict[str, dict[str, float]],
    *,
    seeds: Sequence[int],
) -> tuple[Path, Path, Path]:
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    per_seed_path = out_dir / "random_multi_seed_summary.csv"
    _write_csv(
        per_seed_path,
        ["seed", "cases", *METRIC_NAMES],
        [dict(row) for row in per_seed],
    )

    aggregate_rows = [
        {
            "metric": metric,
            **aggregate[metric],
        }
        for metric in METRIC_NAMES
    ]
    aggregate_csv = out_dir / "random_multi_seed_aggregate.csv"
    _write_csv(
        aggregate_csv,
        ["metric", "mean", "std_dev", "min", "max", "ci95_low", "ci95_high"],
        aggregate_rows,
    )

    aggregate_json = out_dir / "random_multi_seed_aggregate.json"
    payload = {
        "tool_id": RANDOM_TOOL_ID,
        "seeds": list(seeds),
        "per_seed": [dict(row) for row in per_seed],
        "aggregate": aggregate,
        "bootstrap": {"method": "percentile", "ci": 0.95, "resamples": 10_000},
        "generated_at": datetime.now(UTC).isoformat(),
    }
    aggregate_json.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    tex_lines = [
        "% Auto-generated from fsmrepairbench.baseline_repair_campaign",
        "\\begin{table}[t]",
        "\\caption{Multi-seed random baseline repair statistics ($n="
        f"{len(seeds)}$ seeds). "
        "Takeaway: cohort-level random baseline metrics vary across seeds; "
        "95\\% bootstrap CIs summarise seed-level dispersion.}",
        "\\label{tab:baseline-random-multi-seed}",
        "\\begin{tabular}{@{}lrrrrrr@{}}",
        "\\toprule",
        "Metric & Mean & Std & Min & Max & CI low & CI high \\\\",
        "\\midrule",
    ]
    for metric in METRIC_NAMES:
        stats = aggregate[metric]
        label = metric.replace("_", "\\_")
        tex_lines.append(
            f"{label} & {stats['mean']:.4f} & {stats['std_dev']:.4f} & "
            f"{stats['min']:.4f} & {stats['max']:.4f} & "
            f"{stats['ci95_low']:.4f} & {stats['ci95_high']:.4f} \\\\"
        )
    tex_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    tex_path = tables_dir / "table_random_multi_seed_aggregate.tex"
    tex_path.write_text("\n".join(tex_lines), encoding="utf-8")
    return per_seed_path, aggregate_csv, aggregate_json


def build_c1_manifest(
    *,
    dataset_dir: Path,
    cohort_path: Path,
    tools_dir: Path,
    workers: int,
    case_count: int,
    tool_ids: Sequence[str],
    output_files: Sequence[str],
    random_seeds: Sequence[int],
    multi_seed_aggregate: dict[str, dict[str, float]] | None = None,
    raw_runs_dir: Path | None = None,
) -> dict[str, Any]:
    """Build the C1 campaign manifest payload."""
    cohort_sha256 = sha256_file(cohort_path)
    tool_configs = sorted(path.name for path in tools_dir.glob("*.yaml"))
    manifest: dict[str, Any] = {
        "release_label": RELEASE_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "zenodo_release": ZENODO_RELEASE,
        "dataset_dir": str(dataset_dir),
        "cohort_path": str(cohort_path),
        "cohort_sha256": cohort_sha256,
        "case_count": case_count,
        "tool_ids": list(tool_ids),
        "tool_configs": tool_configs,
        "tools_dir": str(tools_dir),
        "workers": workers,
        "random_baseline_seeds": list(random_seeds),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "git_commit": get_git_commit(),
        "output_files": list(output_files),
    }
    if raw_runs_dir is not None:
        manifest["raw_runs_dir"] = str(raw_runs_dir)
    if multi_seed_aggregate is not None:
        manifest["random_multi_seed_aggregate"] = multi_seed_aggregate
    return manifest


def write_c1_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    """Write *manifest* JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


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
    """Write manifest.json after all C1 export files exist under *out_dir*."""
    tool_ids = [*DETERMINISTIC_TOOL_IDS, RANDOM_TOOL_ID]
    manifest = build_c1_manifest(
        dataset_dir=dataset_dir,
        cohort_path=cohort_path,
        tools_dir=tools_dir,
        workers=workers,
        case_count=case_count,
        tool_ids=tool_ids,
        output_files=list_output_files(out_dir),
        random_seeds=random_seeds,
        multi_seed_aggregate=multi_seed_aggregate,
        raw_runs_dir=raw_runs_dir,
    )
    # manifest.json is included in output_files; write after building list without it
    manifest["output_files"] = [
        path
        for path in list_output_files(out_dir)
        if path != "manifest.json"
    ] + ["manifest.json"]
    return write_c1_manifest(out_dir / "manifest.json", manifest)


def export_c1_multi_seed_analysis(
    dataset_dir: Path,
    cohort_path: Path,
    tools_dir: Path,
    out_dir: Path,
    *,
    seeds: Sequence[int] = DEFAULT_RANDOM_SEEDS,
    workers: int = 1,
    write_per_seed_runs: bool = True,
) -> C1ExportResult:
    """Run multi-seed random baseline analysis and write export artefacts."""
    case_ids = set(load_cohort_manifest(cohort_path))
    multi_seed_dir = out_dir / "multi_seed" if write_per_seed_runs else None
    per_seed, aggregate = run_multi_seed_random_analysis(
        dataset_dir,
        tools_dir,
        case_ids,
        seeds,
        workers=workers,
        multi_seed_dir=multi_seed_dir,
    )
    write_multi_seed_exports(
        out_dir,
        per_seed,
        aggregate,
        seeds=seeds,
    )

    manifest_path = finalize_c1_manifest(
        dataset_dir=dataset_dir,
        cohort_path=cohort_path,
        tools_dir=tools_dir,
        out_dir=out_dir,
        workers=workers,
        case_count=len(case_ids),
        random_seeds=seeds,
        multi_seed_aggregate=aggregate,
    )
    return C1ExportResult(
        output_dir=out_dir,
        manifest_path=manifest_path,
        multi_seed_summary_path=out_dir / "random_multi_seed_summary.csv",
        multi_seed_json_path=out_dir / "random_multi_seed_aggregate.json",
    )
