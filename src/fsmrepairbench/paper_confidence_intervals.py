"""Aggregate bootstrap confidence intervals for paper headline metrics."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.statistics import (
    BOOTSTRAP_SEED,
    CAMPAIGN_CI_METRICS,
    CONFIDENCE_INTERVAL_CSV_COLUMNS,
    PAIRED_CONFIDENCE_INTERVAL_CSV_COLUMNS,
    ConfidenceIntervalRow,
    PairedConfidenceIntervalRow,
    ci_row_lookup,
    compute_c1_detectable_confidence_intervals,
    compute_c1_paired_confidence_intervals,
    compute_c3_confidence_intervals,
    compute_rq2_confidence_intervals,
    compute_rq3_confidence_intervals,
    compute_rq3_cohort_confidence_intervals,
    compute_rq4_confidence_intervals,
    compute_rq4_paired_confidence_intervals,
    confidence_interval_rows_to_dicts,
    filter_campaign_ci_rows,
    filter_ci_rows_by_group,
    filter_paper_main_ci_rows,
    filter_paired_ci_rows_by_group,
    paired_confidence_interval_rows_to_dicts,
    render_campaign_ci_tex,
    render_paper_main_ci_tex,
    render_paired_ci_tex,
    write_confidence_interval_exports,
    write_paired_confidence_interval_exports,
)

PAPER_CI_DIR_NAME = "confidence_intervals"
DEFAULT_PAPER_CI_RELATIVE = Path("results") / PAPER_CI_DIR_NAME
DEFAULT_PAPER_EXPORT_RELATIVE = Path("../paper1/results") / PAPER_CI_DIR_NAME

CAMPAIGN_RESULT_DIRS: dict[str, tuple[str, str]] = {
    "C1": ("baseline_repair_C1", "C1-baseline-repair"),
    "RQ3": ("rq3_localization_1k", "RQ3-localization"),
    "RQ4": ("rq4_coupling_250", "RQ4-coupling"),
}


@dataclass(frozen=True)
class PaperConfidenceIntervalPaths:
    """Default frozen per-case inputs for headline CI aggregation."""

    rq2_progress_csv: Path
    analysis_cohort_file: Path
    c1_per_case_csv: Path
    rq3_per_case_csv: Path
    rq4_per_case_csv: Path
    c3_per_case_csv: Path


@dataclass(frozen=True)
class PaperConfidenceIntervalResult:
    """Paths written by :func:`export_paper_confidence_intervals`."""

    output_dir: Path
    csv_path: Path
    json_path: Path
    paired_csv_path: Path
    main_tex_path: Path
    campaign_tex_path: Path
    paired_tex_path: Path
    paper_csv_path: Path | None
    paper_paired_csv_path: Path | None
    paper_main_tex_path: Path | None
    paper_campaign_tex_path: Path | None
    paper_paired_tex_path: Path | None
    rows: tuple[ConfidenceIntervalRow, ...]
    paired_rows: tuple[PairedConfidenceIntervalRow, ...]
    main_rows: tuple[ConfidenceIntervalRow, ...]
    campaign_rows: tuple[ConfidenceIntervalRow, ...]


class PaperConfidenceIntervalError(RuntimeError):
    """Raised when paper CI aggregation cannot be completed."""


@dataclass(frozen=True)
class _ProgressCase:
    bpr_delta: float
    faulty_bpr: float


def default_paper_ci_paths(repo_root: Path | None = None) -> PaperConfidenceIntervalPaths:
    """Return default frozen CSV paths relative to the repository root."""
    base = repo_root or Path(__file__).resolve().parents[2]
    paper_results = base.parent / "paper1" / "results"
    dataset_dir = base / "data/fsmrepairbench_1k"
    return PaperConfidenceIntervalPaths(
        rq2_progress_csv=dataset_dir / "progress.csv",
        analysis_cohort_file=dataset_dir / "analysis_cohort_1k.txt",
        c1_per_case_csv=paper_results / "baseline_repair_C1/per_case_results.csv",
        rq3_per_case_csv=paper_results / "rq3_localization_1k/per_case_results.csv",
        rq4_per_case_csv=paper_results / "rq4_coupling_250/per_case_results.csv",
        c3_per_case_csv=paper_results / "oracle_depth_ablation/per_case_results.csv",
    )


def load_cohort_case_ids(path: Path) -> set[str]:
    """Load pinned analysis cohort case IDs."""
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise PaperConfidenceIntervalError(msg)
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_csv_dict_rows(path: Path) -> list[dict[str, str]]:
    """Load a CSV file into dict rows."""
    if not path.is_file():
        msg = f"CSV input not found: {path}"
        raise PaperConfidenceIntervalError(msg)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"CSV has no header: {path}"
            raise PaperConfidenceIntervalError(msg)
        return list(reader)


def load_progress_cases(
    path: Path,
    *,
    cohort_ids: set[str] | None = None,
) -> list[_ProgressCase]:
    """Load RQ2 per-case metrics from a frozen dataset progress/index CSV."""
    rows = load_csv_dict_rows(path)
    cases: list[_ProgressCase] = []
    for row in rows:
        if row.get("status", "completed") != "completed":
            continue
        case_id = str(row["case_id"])
        if cohort_ids is not None and case_id not in cohort_ids:
            continue
        cases.append(
            _ProgressCase(
                bpr_delta=float(row["bpr_delta"]),
                faulty_bpr=float(row["faulty_bpr"]),
            )
        )
    return cases


def detectable_case_ids_from_progress(
    path: Path,
    *,
    cohort_ids: set[str] | None = None,
) -> set[str]:
    """Return case IDs with oracle-detectable faults from frozen progress CSV."""
    rows = load_csv_dict_rows(path)
    detectable: set[str] = set()
    for row in rows:
        if row.get("status", "completed") != "completed":
            continue
        case_id = str(row["case_id"])
        if cohort_ids is not None and case_id not in cohort_ids:
            continue
        if float(row["bpr_delta"]) > 0.0:
            detectable.add(case_id)
    return detectable


def group_c3_rows_by_depth(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Partition C3 per-case rows by oracle depth preset."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        depth = str(row.get("oracle_depth", "")).strip()
        if not depth:
            continue
        grouped.setdefault(depth, []).append(row)
    return grouped


def collect_paper_confidence_intervals(
    *,
    paths: PaperConfidenceIntervalPaths | None = None,
    repo_root: Path | None = None,
) -> tuple[list[ConfidenceIntervalRow], list[PairedConfidenceIntervalRow]]:
    """Compute headline bootstrap CIs from frozen per-case campaign exports."""
    resolved_paths = paths or default_paper_ci_paths(repo_root)
    cohort_ids = load_cohort_case_ids(resolved_paths.analysis_cohort_file)
    rq2_cases = load_progress_cases(
        resolved_paths.rq2_progress_csv,
        cohort_ids=cohort_ids,
    )
    detectable_ids = detectable_case_ids_from_progress(
        resolved_paths.rq2_progress_csv,
        cohort_ids=cohort_ids,
    )
    c1_rows = load_csv_dict_rows(resolved_paths.c1_per_case_csv)
    rq3_rows = load_csv_dict_rows(resolved_paths.rq3_per_case_csv)
    rq4_rows = load_csv_dict_rows(resolved_paths.rq4_per_case_csv)
    c3_rows = load_csv_dict_rows(resolved_paths.c3_per_case_csv)

    rows: list[ConfidenceIntervalRow] = []
    rows.extend(compute_rq2_confidence_intervals(rq2_cases))
    rows.extend(
        compute_c1_detectable_confidence_intervals(
            c1_rows,
            detectable_case_ids=detectable_ids,
        )
    )
    rows.extend(compute_rq3_confidence_intervals(rq3_rows, detectable_case_ids=detectable_ids))
    rows.extend(compute_rq3_cohort_confidence_intervals(rq2_cases))
    rows.extend(compute_rq4_confidence_intervals(rq4_rows))
    rows.extend(compute_c3_confidence_intervals(group_c3_rows_by_depth(c3_rows)))

    paired_rows: list[PairedConfidenceIntervalRow] = []
    paired_rows.extend(
        compute_c1_paired_confidence_intervals(
            c1_rows,
            detectable_case_ids=detectable_ids,
        )
    )
    paired_rows.extend(compute_rq4_paired_confidence_intervals(rq4_rows))
    return rows, paired_rows


def _append_ci_columns(
    row: dict[str, str],
    *,
    prefix: str,
    ci_row: ConfidenceIntervalRow | None,
    as_percent: bool = True,
) -> None:
    if ci_row is None:
        row[f"{prefix}_mean"] = ""
        row[f"{prefix}_ci95_low"] = ""
        row[f"{prefix}_ci95_high"] = ""
        return
    if as_percent:
        row[f"{prefix}_mean"] = f"{100.0 * ci_row.mean:.6f}"
        row[f"{prefix}_ci95_low"] = f"{100.0 * ci_row.ci95_low:.6f}"
        row[f"{prefix}_ci95_high"] = f"{100.0 * ci_row.ci95_high:.6f}"
    else:
        row[f"{prefix}_mean"] = f"{ci_row.mean:.6f}"
        row[f"{prefix}_ci95_low"] = f"{ci_row.ci95_low:.6f}"
        row[f"{prefix}_ci95_high"] = f"{ci_row.ci95_high:.6f}"
    row[f"{prefix}_n_cases"] = str(ci_row.n_cases)


def build_c1_leaderboard_with_ci(
    leaderboard_path: Path,
    ci_rows: Sequence[ConfidenceIntervalRow],
) -> list[dict[str, str]]:
    """Merge C1 leaderboard point estimates with bootstrap CI columns."""
    if not leaderboard_path.is_file():
        return []
    with leaderboard_path.open(encoding="utf-8", newline="") as handle:
        leaderboard = list(csv.DictReader(handle))
    output: list[dict[str, str]] = []
    for entry in leaderboard:
        tool_id = str(entry.get("tool_id", ""))
        merged = dict(entry)
        for partition in ("cohort_wide", "detectable_only"):
            for metric, prefix, as_percent in (
                ("detection_rate", f"{partition}_detection_rate", True),
                ("complete_repair_rate", f"{partition}_complete_repair_rate", True),
                ("effective_repair_rate", f"{partition}_effective_repair_rate", True),
                ("mean_bpr_delta", f"{partition}_mean_bpr_delta", False),
            ):
                _append_ci_columns(
                    merged,
                    prefix=prefix,
                    ci_row=ci_row_lookup(
                        ci_rows,
                        group="C1",
                        partition=partition,
                        metric=metric,
                        subgroup=tool_id,
                    ),
                    as_percent=as_percent,
                )
        output.append(merged)
    return output


def build_rq3_metrics_with_ci(ci_rows: Sequence[ConfidenceIntervalRow]) -> list[dict[str, str]]:
    """Build long-format RQ3 localization metrics with CI columns."""
    rows: list[dict[str, str]] = []
    for partition in ("detectable_only", "localized_cases", "cohort_wide"):
        for metric, as_percent in (
            ("detection_rate", True),
            ("mean_bpr_delta", False),
            ("top_1_hit_rate", True),
            ("top_3_hit_rate", True),
            ("top_5_hit_rate", True),
            ("mrr", False),
        ):
            ci_row = ci_row_lookup(
                ci_rows,
                group="RQ3",
                partition=partition,
                metric=metric,
            )
            if ci_row is None:
                continue
            row = {
                "partition": partition,
                "metric": metric,
                "n_cases": str(ci_row.n_cases),
            }
            _append_ci_columns(row, prefix="value", ci_row=ci_row, as_percent=as_percent)
            rows.append(row)
    return rows


def build_rq4_summary_with_ci(ci_rows: Sequence[ConfidenceIntervalRow]) -> list[dict[str, str]]:
    """Build long-format RQ4 order metrics with CI columns."""
    rows: list[dict[str, str]] = []
    for order_label in ("order_1", "order_2", "order_3", "fo_subset", "ho_orders_2_3"):
        for partition in ("cohort_wide", "detectable_only"):
            for metric, as_percent in (
                ("detection_rate", True),
                ("complete_repair_rate", True),
                ("effective_repair_rate", True),
                ("mean_bpr_delta", False),
            ):
                ci_row = ci_row_lookup(
                    ci_rows,
                    group="RQ4",
                    partition=partition,
                    metric=metric,
                    subgroup=order_label,
                )
                if ci_row is None:
                    continue
                row = {
                    "mutation_order": order_label,
                    "partition": partition,
                    "metric": metric,
                    "n_cases": str(ci_row.n_cases),
                }
                _append_ci_columns(row, prefix="value", ci_row=ci_row, as_percent=as_percent)
                rows.append(row)
    return rows


def _write_csv_dict_rows(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def render_rq3_metrics_with_ci_tex(rows: Sequence[dict[str, str]]) -> str:
    lines = [
        "% Auto-generated by fsmrepairbench.paper_confidence_intervals",
        "\\begin{table}[t]",
        "\\caption{RQ3 localization metrics with bootstrap 95\\% confidence intervals.}",
        "\\label{tab:rq3-metrics-with-ci}",
        "\\small",
        "\\begin{tabular}{@{}llrrrr@{}}",
        "\\toprule",
        "Partition & Metric & $n$ & Mean & CI low & CI high \\\\",
        "\\midrule",
    ]
    for row in rows:
        metric = str(row["metric"]).replace("_", "\\_")
        partition = str(row["partition"]).replace("_", "\\_")
        if metric in {"top\\_1\\_hit\\_rate", "top\\_3\\_hit\\_rate", "top\\_5\\_hit\\_rate", "detection\\_rate"}:
            mean = float(row["value_mean"])
            low = float(row["value_ci95_low"])
            high = float(row["value_ci95_high"])
            lines.append(
                f"{partition} & {metric} & {row['n_cases']} & "
                f"{mean:.2f}\\% & {low:.2f}\\% & {high:.2f}\\% \\\\"
            )
        else:
            mean = float(row["value_mean"])
            low = float(row["value_ci95_low"])
            high = float(row["value_ci95_high"])
            lines.append(
                f"{partition} & {metric} & {row['n_cases']} & "
                f"{mean:.4f} & {low:.4f} & {high:.4f} \\\\"
            )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)


def export_per_campaign_confidence_intervals(
    *,
    paper_results_root: Path,
    rows: Sequence[ConfidenceIntervalRow],
    paired_rows: Sequence[PairedConfidenceIntervalRow],
) -> dict[str, Path]:
    """Sync C1/RQ3/RQ4 campaign directories with consolidated CI exports."""
    written: dict[str, Path] = {}
    for group, (dir_name, campaign_label) in CAMPAIGN_RESULT_DIRS.items():
        campaign_dir = paper_results_root / dir_name
        campaign_dir.mkdir(parents=True, exist_ok=True)
        campaign_rows = filter_ci_rows_by_group(
            rows,
            group=group,
            metrics=sorted(CAMPAIGN_CI_METRICS),
        )
        write_confidence_interval_exports(
            campaign_dir,
            campaign=campaign_label,
            rows=campaign_rows,
            paper_export_dir=campaign_dir,
            tex_label=f"tab:{dir_name.replace('_', '-')}-confidence-intervals",
        )
        written[f"{group.lower()}_confidence_intervals"] = campaign_dir / "confidence_intervals.csv"

        group_paired = filter_paired_ci_rows_by_group(paired_rows, group=group)
        if group_paired:
            paired_path = write_paired_confidence_interval_exports(
                campaign_dir,
                campaign=campaign_label,
                rows=group_paired,
                paper_export_dir=campaign_dir,
            )
            written[f"{group.lower()}_paired_confidence_intervals"] = paired_path

        tables_dir = campaign_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        if group == "C1":
            leaderboard_with_ci = build_c1_leaderboard_with_ci(
                campaign_dir / "leaderboard.csv",
                campaign_rows,
            )
            if leaderboard_with_ci:
                out_path = campaign_dir / "leaderboard_with_ci.csv"
                fieldnames = list(leaderboard_with_ci[0].keys())
                _write_csv_dict_rows(out_path, fieldnames, leaderboard_with_ci)
                written["c1_leaderboard_with_ci"] = out_path
        elif group == "RQ3":
            rq3_metrics = build_rq3_metrics_with_ci(list(rows))
            if rq3_metrics:
                out_path = campaign_dir / "localization_metrics_with_ci.csv"
                fieldnames = list(rq3_metrics[0].keys())
                _write_csv_dict_rows(out_path, fieldnames, rq3_metrics)
                (tables_dir / "table_localization_metrics_with_ci.tex").write_text(
                    render_rq3_metrics_with_ci_tex(rq3_metrics),
                    encoding="utf-8",
                )
                written["rq3_localization_metrics_with_ci"] = out_path
        elif group == "RQ4":
            rq4_summary = build_rq4_summary_with_ci(campaign_rows)
            if rq4_summary:
                out_path = campaign_dir / "summary_metrics_with_ci.csv"
                fieldnames = list(rq4_summary[0].keys())
                _write_csv_dict_rows(out_path, fieldnames, rq4_summary)
                written["rq4_summary_metrics_with_ci"] = out_path
    return written


def export_paper_confidence_intervals(
    output_dir: Path | None = None,
    *,
    paper_export_dir: Path | None = None,
    paths: PaperConfidenceIntervalPaths | None = None,
    repo_root: Path | None = None,
) -> PaperConfidenceIntervalResult:
    """Write consolidated CI CSV/JSON exports and the headline LaTeX table."""
    base = repo_root or Path(__file__).resolve().parents[2]
    out = output_dir or (base / DEFAULT_PAPER_CI_RELATIVE)
    paper_dir = paper_export_dir or (base / DEFAULT_PAPER_EXPORT_RELATIVE)
    resolved_paths = paths or default_paper_ci_paths(base)
    paper_results_root = resolved_paths.c1_per_case_csv.parent.parent

    rows, paired_rows = collect_paper_confidence_intervals(paths=resolved_paths, repo_root=base)
    main_rows = filter_paper_main_ci_rows(rows)
    campaign_rows = filter_campaign_ci_rows(rows)

    export_result = write_confidence_interval_exports(
        out,
        campaign="paper-headline-metrics",
        rows=rows,
        paper_export_dir=None,
    )

    paired_csv_path = out / "paired_confidence_intervals.csv"
    paired_json_path = out / "paired_confidence_intervals.json"
    paired_dict_rows = paired_confidence_interval_rows_to_dicts(paired_rows)
    with paired_csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PAIRED_CONFIDENCE_INTERVAL_CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(paired_dict_rows)
    paired_json_path.write_text(
        json.dumps(
            {
                "campaign": "paper-paired-comparisons",
                "method": "percentile_case_resample_paired_difference",
                "seed": BOOTSTRAP_SEED,
                "comparisons": paired_dict_rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    paper_dir.mkdir(parents=True, exist_ok=True)
    paper_csv_path = paper_dir / "confidence_intervals.csv"
    paper_csv_path.write_text(export_result.csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    paper_json_path = paper_dir / "confidence_intervals.json"
    paper_json_path.write_text(export_result.json_path.read_text(encoding="utf-8"), encoding="utf-8")
    paper_paired_csv_path = paper_dir / "paired_confidence_intervals.csv"
    paper_paired_csv_path.write_text(paired_csv_path.read_text(encoding="utf-8"), encoding="utf-8")

    per_campaign_paths = export_per_campaign_confidence_intervals(
        paper_results_root=paper_results_root,
        rows=rows,
        paired_rows=paired_rows,
    )

    tables_dir = paper_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    out_tables_dir = out / "tables"
    out_tables_dir.mkdir(parents=True, exist_ok=True)

    main_tex_content = render_paper_main_ci_tex(main_rows)
    campaign_tex_content = render_campaign_ci_tex(campaign_rows)
    paired_tex_content = render_paired_ci_tex(paired_rows)

    main_tex_path = out_tables_dir / "table_ci_main_results.tex"
    main_tex_path.write_text(main_tex_content, encoding="utf-8")
    campaign_tex_path = out_tables_dir / "table_ci_campaign_metrics.tex"
    campaign_tex_path.write_text(campaign_tex_content, encoding="utf-8")
    paired_tex_path = out_tables_dir / "table_ci_paired_comparisons.tex"
    paired_tex_path.write_text(paired_tex_content, encoding="utf-8")

    paper_main_tex_path = tables_dir / "table_ci_main_results.tex"
    paper_main_tex_path.write_text(main_tex_content, encoding="utf-8")
    paper_campaign_tex_path = tables_dir / "table_ci_campaign_metrics.tex"
    paper_campaign_tex_path.write_text(campaign_tex_content, encoding="utf-8")
    paper_paired_tex_path = tables_dir / "table_ci_paired_comparisons.tex"
    paper_paired_tex_path.write_text(paired_tex_content, encoding="utf-8")

    report_path = out / "report.md"
    report_lines = [
        "# Paper headline bootstrap confidence intervals",
        "",
        f"Seed: {BOOTSTRAP_SEED}. Schema: `{', '.join(CONFIDENCE_INTERVAL_CSV_COLUMNS)}`.",
        "",
        f"- Full export: `{export_result.csv_path}`",
        f"- Paired export: `{paired_csv_path}`",
        f"- Headline LaTeX table: `{main_tex_path}`",
        f"- Campaign LaTeX table: `{campaign_tex_path}`",
        f"- Paired LaTeX table: `{paired_tex_path}`",
        "",
        "Per-campaign synced exports:",
    ]
    for label, path in sorted(per_campaign_paths.items()):
        report_lines.append(f"- `{label}`: `{path}`")
    report_lines.extend(
        [
            "",
            f"Headline metrics exported: {len(main_rows)} of {len(rows)} total CI rows.",
            f"Paired comparisons exported: {len(paired_rows)}.",
            "",
        ]
    )
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    return PaperConfidenceIntervalResult(
        output_dir=out,
        csv_path=export_result.csv_path,
        json_path=export_result.json_path,
        paired_csv_path=paired_csv_path,
        main_tex_path=main_tex_path,
        campaign_tex_path=campaign_tex_path,
        paired_tex_path=paired_tex_path,
        paper_csv_path=paper_csv_path,
        paper_paired_csv_path=paper_paired_csv_path,
        paper_main_tex_path=paper_main_tex_path,
        paper_campaign_tex_path=paper_campaign_tex_path,
        paper_paired_tex_path=paper_paired_tex_path,
        rows=tuple(rows),
        paired_rows=tuple(paired_rows),
        main_rows=tuple(main_rows),
        campaign_rows=tuple(campaign_rows),
    )
