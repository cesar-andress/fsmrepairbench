"""C1 extended baseline repair campaign (search, composite, LLM-template engines)."""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.baseline_repair_campaign import (
    DEFAULT_COHORT_FILE,
    DEFAULT_DATASET_PATH,
    DEFAULT_WORKERS,
    build_c1_manifest,
    load_cohort_manifest,
    write_c1_confidence_interval_exports,
    write_c1_manifest,
)
from fsmrepairbench.c1_baseline_repair_exports import (
    C1BaselineRepairExportError,
    _dataset_rows_by_id,
    _enriched_rows,
    _load_tool_runs,
    _summary_metrics,
    _write_csv,
)
from fsmrepairbench.localization_baselines import localize_case_baseline
EXTENDED_CAMPAIGN_LABEL = "C1-extended-baseline-repair"
EXTENDED_RELEASE_LABEL = "C1-extended-baseline-repair"
DEFAULT_EXTENDED_TOOLS_DIR = "tools/baselines_c1_extended"
DEFAULT_EXTENDED_RAW_RUNS_DIR = "results/baseline_repair_C1_extended"
DEFAULT_EXTENDED_PAPER_EXPORT_DIR = "../paper1/results/baseline_repair_C1_extended"

EXTENDED_TOOL_IDS: tuple[str, ...] = (
    "baseline_search_bpr",
    "baseline_oracle_composite",
    "baseline_llm_template",
)

EXTENDED_TOOL_LABELS: dict[str, str] = {
    "baseline_search_bpr": "search-bpr",
    "baseline_oracle_composite": "oracle-composite",
    "baseline_llm_template": "llm-template",
}

LOCALIZATION_COUPLING_COLUMNS: tuple[str, ...] = (
    "case_id",
    "tool_id",
    "mutation_operator",
    "oracle_detected",
    "complete_repair",
    "effective_repair",
    "delta_bpr",
    "structural_diff_top1_hit",
    "structural_diff_top3_hit",
    "structural_diff_top5_hit",
    "structural_diff_rank",
    "structural_diff_mrr",
)


@dataclass(frozen=True)
class C1ExtendedExportResult:
    output_dir: Path
    per_case_results_path: Path
    leaderboard_path: Path
    manifest_path: Path
    localization_coupling_path: Path
    report_path: Path


def _active_tool_ids(enriched: list[dict]) -> tuple[str, ...]:
    present = {str(row["tool_id"]) for row in enriched}
    return tuple(tool_id for tool_id in EXTENDED_TOOL_IDS if tool_id in present)


def _default_regeneration_commands(*, dataset_path: str, out_dir: str, workers: int) -> list[str]:
    return [
        (
            f"fsmrepairbench run-c1-extended-baseline-repair {dataset_path} "
            f"--out {out_dir} --workers {workers}"
        ),
        (
            f"fsmrepairbench run-tools {dataset_path} {DEFAULT_EXTENDED_TOOLS_DIR}/ "
            f"--out {out_dir} "
            f"--cohort-file {dataset_path}/{DEFAULT_COHORT_FILE} "
            f"--workers {workers}"
        ),
        "python ../paper1/scripts/generate_baseline_repair_C1_extended_outputs.py",
    ]


def write_localization_coupling_export(
    *,
    dataset_dir: Path,
    enriched: list[dict],
    output_path: Path,
) -> Path:
    """Join extended repair outcomes with structural-diff localization top-k ranks."""
    rows: list[dict[str, str | float | bool | int]] = []
    cache: dict[str, object] = {}

    for row in enriched:
        if str(row["tool_id"]) not in EXTENDED_TOOL_IDS:
            continue
        case_id = str(row["case_id"])
        if case_id not in cache:
            case_dir = dataset_dir / "cases" / case_id
            try:
                localization = localize_case_baseline(case_dir, method="structural_diff")
            except (FileNotFoundError, OSError, ValueError):
                localization = None
            cache[case_id] = localization

        localization = cache[case_id]
        rows.append(
            {
                "case_id": case_id,
                "tool_id": str(row["tool_id"]),
                "mutation_operator": str(row["mutation_operator"]),
                "oracle_detected": bool(row["oracle_detected"]),
                "complete_repair": bool(row["complete_repair"]),
                "effective_repair": bool(row["effective_repair"]),
                "delta_bpr": float(row["delta_bpr"]),
                "structural_diff_top1_hit": bool(getattr(localization, "top1_hit", False)),
                "structural_diff_top3_hit": bool(getattr(localization, "top3_hit", False)),
                "structural_diff_top5_hit": bool(getattr(localization, "top5_hit", False)),
                "structural_diff_rank": getattr(localization, "rank_of_target", "") or "",
                "structural_diff_mrr": float(getattr(localization, "reciprocal_rank", 0.0)),
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output_path, list(LOCALIZATION_COUPLING_COLUMNS), rows)
    return output_path


def generate_c1_extended_baseline_exports(
    dataset_dir: Path,
    *,
    out_dir: Path,
    cohort_file: Path | None = None,
    tools_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    workers: int = DEFAULT_WORKERS,
    repo_root: Path | None = None,
) -> C1ExtendedExportResult:
    """Write extended baseline CSV exports and manifest from run-tools output."""
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    cohort_path = cohort_file or (dataset_dir / DEFAULT_COHORT_FILE)
    tools_path = tools_dir or (repo_root / DEFAULT_EXTENDED_TOOLS_DIR)
    cohort_ids = set(load_cohort_manifest(cohort_path))
    case_count = len(cohort_ids)

    summary_path = out_dir / "summary.csv"
    per_case_path = out_dir / "per_case_results.csv"
    if summary_path.is_file():
        runs = _load_tool_runs(summary_path, cohort_ids)
        dataset_rows = _dataset_rows_by_id(dataset_dir, cohort_ids)
        enriched = _enriched_rows(runs, dataset_rows)
    elif per_case_path.is_file():
        enriched = []
        for row in csv.DictReader(per_case_path.open(encoding="utf-8")):
            if row["case_id"] not in cohort_ids:
                continue
            parsed: dict[str, str | float | bool | int] = dict(row)
            for key in ("initial_bpr", "final_bpr", "delta_bpr", "faulty_bpr", "reference_bpr", "difficulty_score", "bpr_delta_pre_repair"):
                if key in parsed and parsed[key] != "":
                    parsed[key] = float(parsed[key])
            for key in ("complete_repair", "effective_repair", "regression", "oracle_detected"):
                if key in parsed:
                    parsed[key] = str(parsed[key]).strip().lower() == "true"
            enriched.append(parsed)
    else:
        msg = f"Missing extended run output in {out_dir}"
        raise C1BaselineRepairExportError(msg)

    if not enriched:
        msg = f"No extended baseline rows for cohort in {out_dir}"
        raise C1BaselineRepairExportError(msg)

    tool_ids = _active_tool_ids(enriched)
    out_dir.mkdir(parents=True, exist_ok=True)

    per_case_fields = list(enriched[0].keys())
    per_case_path = out_dir / "per_case_results.csv"
    _write_csv(per_case_path, per_case_fields, enriched)

    summaries = [_summary_metrics(enriched, tool_id) for tool_id in tool_ids]
    leaderboard_fields = [
        "tool_id",
        "cases",
        "detectable_cases",
        "oracle_saturated_cases",
        "complete_repair_rate_detectable_only",
        "effective_repair_rate_detectable_only",
        "complete_repair_rate",
        "effective_repair_rate",
        "regression_rate",
        "mean_delta_bpr",
        "mean_initial_bpr",
        "mean_final_bpr",
    ]
    leaderboard_path = out_dir / "leaderboard.csv"
    _write_csv(leaderboard_path, leaderboard_fields, summaries)

    localization_path = write_localization_coupling_export(
        dataset_dir=dataset_dir,
        enriched=enriched,
        output_path=out_dir / "repair_localization_coupling.csv",
    )

    detectable_count = sum(1 for row in enriched if row["oracle_detected"] and row["tool_id"] == tool_ids[0])
    report_lines = [
        "# C1 Extended Baseline Repair Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Dataset: `{dataset_dir}`",
        f"Cohort: `{cohort_path.name}` ({case_count} cases)",
        f"Campaign: {EXTENDED_CAMPAIGN_LABEL}",
        "",
        "## Leaderboard",
        "",
    ]
    for summary in summaries:
        report_lines.append(
            f"- **{summary['tool_id']}** ({EXTENDED_TOOL_LABELS.get(str(summary['tool_id']), summary['tool_id'])}): "
            f"detectable-only complete={summary['complete_repair_rate_detectable_only']:.4f}, "
            f"effective={summary['effective_repair_rate_detectable_only']:.4f}, "
            f"mean ΔBPR={summary['mean_delta_bpr']:.4f}"
        )
    report_lines.extend(
        [
            "",
            "## Localization coupling",
            "",
            f"- Structural-diff top-k ranks joined in `{localization_path.name}`",
            f"- Detectable cases in cohort: {detectable_count} (per primary tool row)",
            "",
        ]
    )
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    manifest = build_c1_manifest(
        dataset_path=dataset_dir,
        cohort_file=cohort_path,
        tools_dir=tools_path,
        workers=workers,
        number_of_cases=case_count,
        output_files=sorted(
            name
            for name in (
                "summary.csv",
                "per_case_results.csv",
                "leaderboard.csv",
                "repair_localization_coupling.csv",
                "confidence_intervals.csv",
                "confidence_intervals.json",
                "report.md",
                "manifest.json",
            )
            if (out_dir / name).is_file() or name in {"manifest.json", "confidence_intervals.csv", "confidence_intervals.json"}
        ),
        regeneration_commands=_default_regeneration_commands(
            dataset_path=str(dataset_dir),
            out_dir=str(out_dir),
            workers=workers,
        ),
        repo_root=repo_root,
    )
    manifest["release_label"] = EXTENDED_RELEASE_LABEL
    manifest["campaign_label"] = EXTENDED_CAMPAIGN_LABEL
    manifest["extended_engines"] = list(EXTENDED_TOOL_LABELS.values())
    manifest_path = out_dir / "manifest.json"
    write_c1_manifest(manifest_path, manifest)

    write_c1_confidence_interval_exports(
        raw_runs_dir=out_dir,
        dataset_dir=dataset_dir,
        cohort_file=cohort_path,
        paper_export_dir=paper_export_dir or out_dir,
        tool_ids=list(EXTENDED_TOOL_IDS),
        campaign=EXTENDED_CAMPAIGN_LABEL,
        include_paired=False,
    )

    paper_dir = paper_export_dir or out_dir
    if paper_dir.resolve() != out_dir.resolve():
        paper_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "per_case_results.csv",
            "leaderboard.csv",
            "repair_localization_coupling.csv",
            "report.md",
            "manifest.json",
            "confidence_intervals.csv",
            "confidence_intervals.json",
        ):
            source = out_dir / name
            if source.is_file():
                shutil.copy2(source, paper_dir / name)

    return C1ExtendedExportResult(
        output_dir=out_dir,
        per_case_results_path=per_case_path,
        leaderboard_path=leaderboard_path,
        manifest_path=manifest_path,
        localization_coupling_path=localization_path,
        report_path=report_path,
    )


def run_c1_extended_baseline_experiment(
    dataset_dir: Path,
    *,
    out_dir: Path | None = None,
    cohort_file: Path | None = None,
    tools_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    workers: int = DEFAULT_WORKERS,
    resume: bool = True,
    skip_tool_runs: bool = False,
    repo_root: Path | None = None,
) -> C1ExtendedExportResult:
    """Run extended baseline repair tools and write frozen exports."""
    from fsmrepairbench.tool_runner import run_tools

    repo_root = repo_root or Path(__file__).resolve().parents[2]
    output_dir = out_dir or (repo_root / DEFAULT_EXTENDED_RAW_RUNS_DIR)
    cohort_path = cohort_file or (dataset_dir / DEFAULT_COHORT_FILE)
    tools_path = tools_dir or (repo_root / DEFAULT_EXTENDED_TOOLS_DIR)
    paper_dir = paper_export_dir or (repo_root.parent / "paper1/results/baseline_repair_C1_extended")

    if not skip_tool_runs:
        run_tools(
            dataset_dir,
            tools_path,
            output_dir,
            cohort_file=cohort_path,
            resume=resume,
            workers=workers,
        )

    return generate_c1_extended_baseline_exports(
        dataset_dir,
        out_dir=output_dir,
        cohort_file=cohort_path,
        tools_dir=tools_path,
        paper_export_dir=paper_dir,
        workers=workers,
        repo_root=repo_root,
    )
