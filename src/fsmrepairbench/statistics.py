"""Reusable bootstrap confidence interval utilities for empirical campaigns."""

from __future__ import annotations

import csv
import json
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 44
BOOTSTRAP_CI = 0.95
BOOTSTRAP_METHOD = "percentile_case_resample"

CONFIDENCE_INTERVAL_CSV_COLUMNS: tuple[str, ...] = (
    "metric",
    "group",
    "subgroup",
    "n_cases",
    "mean",
    "ci95_low",
    "ci95_high",
)

DEFAULT_PAPER_EXPORT_DIRS: dict[str, str] = {
    "v0.2.0-analysis": "../paper1/results/v0_2_analysis",
    "C1-baseline-repair": "../paper1/results/baseline_repair_C1",
    "RQ3-localization": "../paper1/results/rq3_localization_1k",
    "RQ4-coupling": "../paper1/results/rq4_coupling_250",
    "C3-oracle-depth-ablation": "../paper1/results/oracle_depth_ablation",
}


def _row_value(row: Any, name: str, default: Any = None) -> Any:
    if isinstance(row, dict):
        return row.get(name, default)
    return getattr(row, name, default)


@dataclass(frozen=True)
class ConfidenceIntervalRow:
    """One bootstrap confidence interval for a cohort metric."""

    metric: str
    mean: float
    ci95_low: float
    ci95_high: float
    group: str = ""
    subgroup: str = ""
    n_cases: int = 0


@dataclass(frozen=True)
class ConfidenceIntervalExportResult:
    """Paths written by :func:`write_confidence_interval_exports`."""

    csv_path: Path
    json_path: Path
    tex_path: Path | None = None
    paper_csv_path: Path | None = None
    paper_tex_path: Path | None = None


def bootstrap_ci(
    values: Sequence[float],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    ci: float = BOOTSTRAP_CI,
    rng: random.Random | None = None,
) -> tuple[float, float]:
    """Return a two-sided percentile bootstrap confidence interval for the mean."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        value = float(values[0])
        return (value, value)

    generator = rng or random.Random(BOOTSTRAP_SEED)
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


def bootstrap_mean_ci(
    values: Sequence[float],
    metric: str,
    *,
    group: str = "",
    subgroup: str = "",
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> ConfidenceIntervalRow:
    """Bootstrap CI for the mean of *values*."""
    numeric = [float(value) for value in values]
    if not numeric:
        return ConfidenceIntervalRow(
            metric=metric,
            mean=0.0,
            ci95_low=0.0,
            ci95_high=0.0,
            group=group,
            subgroup=subgroup,
            n_cases=0,
        )
    rng = random.Random(bootstrap_seed)
    low, high = bootstrap_ci(numeric, n_resamples=n_resamples, rng=rng)
    return ConfidenceIntervalRow(
        metric=metric,
        mean=round(statistics.mean(numeric), 6),
        ci95_low=round(low, 6),
        ci95_high=round(high, 6),
        group=group,
        subgroup=subgroup,
        n_cases=len(numeric),
    )


def bootstrap_rate_ci(
    flags: Sequence[bool],
    metric: str,
    *,
    group: str = "",
    subgroup: str = "",
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> ConfidenceIntervalRow:
    """Bootstrap CI for a binary rate expressed as the mean of 0/1 values."""
    return bootstrap_mean_ci(
        [1.0 if flag else 0.0 for flag in flags],
        metric,
        group=group,
        subgroup=subgroup,
        n_resamples=n_resamples,
        bootstrap_seed=bootstrap_seed,
    )


def confidence_interval_rows_to_dicts(rows: Sequence[ConfidenceIntervalRow]) -> list[dict[str, Any]]:
    """Convert CI rows to CSV/JSON-serializable dicts."""
    return [
        {
            "metric": row.metric,
            "group": row.group,
            "subgroup": row.subgroup,
            "n_cases": row.n_cases,
            "mean": row.mean,
            "ci95_low": row.ci95_low,
            "ci95_high": row.ci95_high,
        }
        for row in rows
    ]


def bootstrap_metadata(*, campaign: str) -> dict[str, Any]:
    """Return standard bootstrap metadata for JSON exports."""
    return {
        "campaign": campaign,
        "method": BOOTSTRAP_METHOD,
        "unit": "case",
        "ci": BOOTSTRAP_CI,
        "resamples": BOOTSTRAP_RESAMPLES,
        "seed": BOOTSTRAP_SEED,
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }


def render_confidence_intervals_tex(
    rows: Sequence[ConfidenceIntervalRow],
    *,
    campaign: str,
    caption: str,
    label: str = "tab:confidence-intervals",
) -> str:
    """Render a publication LaTeX table for bootstrap confidence intervals."""
    lines = [
        "% Auto-generated from fsmrepairbench.statistics",
        "\\begin{table}[t]",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        "\\small",
        "\\begin{tabular}{@{}llrrrr@{}}",
        "\\toprule",
        "Metric & Group & $n$ & Mean & CI low & CI high \\\\",
        "\\midrule",
    ]
    for row in rows:
        group_parts = [part for part in (row.group, row.subgroup) if part]
        group_label = " / ".join(group_parts) if group_parts else "---"
        metric_label = row.metric.replace("_", "\\_")
        group_label = group_label.replace("_", "\\_")
        lines.append(
            f"{metric_label} & {group_label} & {row.n_cases} & "
            f"{row.mean:.4f} & {row.ci95_low:.4f} & {row.ci95_high:.4f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)


def format_ci_report_section(rows: Sequence[ConfidenceIntervalRow]) -> list[str]:
    """Return markdown lines documenting bootstrap confidence intervals."""
    lines = [
        "## Bootstrap confidence intervals",
        "",
        "Non-parametric percentile bootstrap over cases "
        f"({BOOTSTRAP_RESAMPLES:,} resamples, {BOOTSTRAP_CI:.0%} CI, seed {BOOTSTRAP_SEED}).",
        "Exports: `confidence_intervals.csv` and `confidence_intervals.json`.",
        "",
    ]
    for row in rows:
        group_parts = [part for part in (row.group, row.subgroup) if part]
        prefix = f"{row.metric}"
        if group_parts:
            prefix += f" ({', '.join(group_parts)})"
        lines.append(
            f"- `{prefix}`: {row.mean:.6f} "
            f"[{row.ci95_low:.6f}, {row.ci95_high:.6f}] (n={row.n_cases})"
        )
    lines.append("")
    return lines


def append_ci_section_to_report(path: Path, rows: Sequence[ConfidenceIntervalRow]) -> None:
    """Append or replace the bootstrap CI section in a campaign report."""
    marker = "## Bootstrap confidence intervals"
    block = "\n".join(format_ci_report_section(rows))
    if path.is_file():
        existing = path.read_text(encoding="utf-8")
        if marker in existing:
            head, _, _tail = existing.partition(marker)
            path.write_text(head.rstrip() + "\n\n" + block, encoding="utf-8")
            return
        path.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(block, encoding="utf-8")


def write_confidence_interval_exports(
    output_dir: Path,
    *,
    campaign: str,
    rows: Sequence[ConfidenceIntervalRow],
    paper_export_dir: Path | None = None,
    tex_caption: str | None = None,
    repo_root: Path | None = None,
) -> ConfidenceIntervalExportResult:
    """Write CSV/JSON CI exports and optional paper-ready copies."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "confidence_intervals.csv"
    json_path = output_dir / "confidence_intervals.json"

    dict_rows = confidence_interval_rows_to_dicts(rows)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CONFIDENCE_INTERVAL_CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(dict_rows)

    payload = {
        **bootstrap_metadata(campaign=campaign),
        "metrics": dict_rows,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    resolved_paper_dir = paper_export_dir
    if resolved_paper_dir is None:
        rel = DEFAULT_PAPER_EXPORT_DIRS.get(campaign)
        if rel is not None:
            base = repo_root or Path(__file__).resolve().parents[2]
            resolved_paper_dir = base / rel

    paper_csv_path: Path | None = None
    paper_tex_path: Path | None = None
    tex_path: Path | None = None
    if resolved_paper_dir is not None:
        resolved_paper_dir.mkdir(parents=True, exist_ok=True)
        paper_csv_path = resolved_paper_dir / "confidence_intervals.csv"
        paper_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

        tables_dir = resolved_paper_dir / "tables"
        tables_dir.mkdir(parents=True, exist_ok=True)
        paper_tex_path = tables_dir / "table_confidence_intervals.tex"
        caption = tex_caption or (
            f"Bootstrap {BOOTSTRAP_CI:.0%} confidence intervals for {campaign} "
            f"(case resampling; seed {BOOTSTRAP_SEED})."
        )
        tex_content = render_confidence_intervals_tex(
            rows,
            campaign=campaign,
            caption=caption,
        )
        paper_tex_path.write_text(tex_content, encoding="utf-8")
        tex_path = paper_tex_path

    return ConfidenceIntervalExportResult(
        csv_path=csv_path,
        json_path=json_path,
        tex_path=tex_path,
        paper_csv_path=paper_csv_path,
        paper_tex_path=paper_tex_path,
    )


def compute_rq2_confidence_intervals(cases: Sequence[Any]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for v0.2.0-analysis / RQ2 detection and BPR metrics."""
    detected = [case.bpr_delta > 0.0 for case in cases]
    faulty_bpr = [float(case.faulty_bpr) for case in cases]
    bpr_delta = [float(case.bpr_delta) for case in cases]
    return [
        bootstrap_rate_ci(detected, "overall_detection_rate", group="RQ2"),
        bootstrap_mean_ci(faulty_bpr, "mean_faulty_bpr", group="RQ2"),
        bootstrap_mean_ci(bpr_delta, "mean_bpr_delta", group="RQ2"),
    ]


C1_BASELINE_TOOL_IDS: tuple[str, ...] = (
    "baseline_missing_transition",
    "baseline_wrong_target",
    "baseline_random",
)


def _csv_bool(row: Any, name: str) -> bool:
    value = _row_value(row, name, False)
    if isinstance(value, str):
        return value.strip().lower() == "true"
    return bool(value)


def _csv_float(row: Any, name: str) -> float:
    return float(_row_value(row, name, 0.0))


def _csv_case_id(row: Any) -> str:
    return str(_row_value(row, "case_id"))


def compute_c1_confidence_intervals(
    tool_rows: Sequence[Any],
    *,
    detectable_case_ids: set[str] | None = None,
    tool_id: str = "baseline_missing_transition",
) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for C1 baseline repair metrics on one tool."""
    rows = [row for row in tool_rows if _row_value(row, "tool_id") == tool_id]
    if not rows:
        return []

    complete = [_csv_bool(row, "complete_repair") for row in rows]
    effective = [_csv_bool(row, "effective_repair") for row in rows]
    delta = [_csv_float(row, "delta_bpr") for row in rows]

    ci_rows = [
        bootstrap_rate_ci(complete, "complete_repair_rate", subgroup=tool_id),
        bootstrap_rate_ci(effective, "effective_repair_rate", subgroup=tool_id),
        bootstrap_mean_ci(delta, "mean_delta_bpr", subgroup=tool_id),
    ]

    if detectable_case_ids is not None:
        detectable_rows = [row for row in rows if _csv_case_id(row) in detectable_case_ids]
        detectable_complete = [_csv_bool(row, "complete_repair") for row in detectable_rows]
        detectable_effective = [_csv_bool(row, "effective_repair") for row in detectable_rows]
        ci_rows.extend(
            [
                bootstrap_rate_ci(
                    detectable_complete,
                    "complete_repair_rate_detectable_only",
                    subgroup=tool_id,
                ),
                bootstrap_rate_ci(
                    detectable_effective,
                    "effective_repair_rate_detectable_only",
                    subgroup=tool_id,
                ),
            ]
        )

    return ci_rows


def compute_c1_detectable_confidence_intervals(
    tool_rows: Sequence[Any],
    *,
    detectable_case_ids: set[str],
    tool_ids: Sequence[str] = C1_BASELINE_TOOL_IDS,
) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for detectable-only C1 complete and effective repair by tool."""
    ci_rows: list[ConfidenceIntervalRow] = []
    for tool_id in tool_ids:
        rows = [
            row
            for row in tool_rows
            if _row_value(row, "tool_id") == tool_id and _csv_case_id(row) in detectable_case_ids
        ]
        if not rows:
            continue
        ci_rows.extend(
            [
                bootstrap_rate_ci(
                    [_csv_bool(row, "complete_repair") for row in rows],
                    "complete_repair_rate_detectable_only",
                    group="C1",
                    subgroup=tool_id,
                ),
                bootstrap_rate_ci(
                    [_csv_bool(row, "effective_repair") for row in rows],
                    "effective_repair_rate_detectable_only",
                    group="C1",
                    subgroup=tool_id,
                ),
            ]
        )
    return ci_rows


def compute_rq3_confidence_intervals(rows: Sequence[Any]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for RQ3 localization metrics among localized cases."""
    localized = [row for row in rows if _csv_bool(row, "localized")]
    if not localized:
        localized = list(rows)

    return [
        bootstrap_rate_ci(
            [_csv_bool(row, "top1_hit") for row in localized],
            "top_1_hit_rate",
            group="RQ3",
        ),
        bootstrap_rate_ci(
            [_csv_bool(row, "top3_hit") for row in localized],
            "top_3_hit_rate",
            group="RQ3",
        ),
        bootstrap_rate_ci(
            [_csv_bool(row, "top5_hit") for row in localized],
            "top_5_hit_rate",
            group="RQ3",
        ),
        bootstrap_mean_ci(
            [_csv_float(row, "reciprocal_rank") for row in localized],
            "mrr",
            group="RQ3",
        ),
    ]


def compute_rq4_confidence_intervals(rows: Sequence[Any]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for RQ4 coupling metrics by mutation order."""
    ci_rows: list[ConfidenceIntervalRow] = []
    for order in (1, 2, 3):
        group = [
            row
            for row in rows
            if int(_row_value(row, "mutation_order", 0)) == order
        ]
        if not group:
            continue

        order_label = f"order_{order}"
        ci_rows.extend(
            [
                bootstrap_rate_ci(
                    [_csv_bool(row, "fault_detected") for row in group],
                    "detection_rate",
                    group="RQ4",
                    subgroup=order_label,
                ),
                bootstrap_rate_ci(
                    [_csv_bool(row, "complete_repair") for row in group],
                    "complete_repair_rate",
                    group="RQ4",
                    subgroup=order_label,
                ),
                bootstrap_rate_ci(
                    [_csv_bool(row, "effective_repair") for row in group],
                    "effective_repair_rate",
                    group="RQ4",
                    subgroup=order_label,
                ),
                bootstrap_mean_ci(
                    [_csv_float(row, "bpr_delta") for row in group],
                    "mean_bpr_delta",
                    group="RQ4",
                    subgroup=order_label,
                ),
            ]
        )
    return ci_rows


def compute_c3_confidence_intervals(depth_rows: dict[str, Sequence[Any]]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for C3 oracle depth ablation metrics by depth preset."""
    ci_rows: list[ConfidenceIntervalRow] = []
    for depth in ("shallow", "medium", "deep"):
        rows = list(depth_rows.get(depth, ()))
        if not rows:
            continue

        ci_rows.extend(
            [
                bootstrap_rate_ci(
                    [_csv_bool(row, "fault_detected") for row in rows],
                    "detection_rate",
                    group="C3",
                    subgroup=depth,
                ),
                bootstrap_mean_ci(
                    [_csv_float(row, "faulty_bpr") for row in rows],
                    "mean_faulty_bpr",
                    group="C3",
                    subgroup=depth,
                ),
                bootstrap_mean_ci(
                    [_csv_float(row, "bpr_delta") for row in rows],
                    "mean_bpr_delta",
                    group="C3",
                    subgroup=depth,
                ),
            ]
        )
    return ci_rows


PAPER_MAIN_CI_METRICS: frozenset[tuple[str, str, str]] = frozenset(
    {
        ("RQ2", "", "overall_detection_rate"),
        ("RQ2", "", "mean_faulty_bpr"),
        ("RQ2", "", "mean_bpr_delta"),
        ("C1", "baseline_missing_transition", "complete_repair_rate_detectable_only"),
        ("C1", "baseline_missing_transition", "effective_repair_rate_detectable_only"),
        ("C1", "baseline_wrong_target", "complete_repair_rate_detectable_only"),
        ("C1", "baseline_wrong_target", "effective_repair_rate_detectable_only"),
        ("C1", "baseline_random", "complete_repair_rate_detectable_only"),
        ("C1", "baseline_random", "effective_repair_rate_detectable_only"),
        ("RQ3", "", "top_1_hit_rate"),
        ("RQ3", "", "top_3_hit_rate"),
        ("RQ3", "", "top_5_hit_rate"),
        ("RQ3", "", "mrr"),
        ("RQ4", "order_1", "detection_rate"),
        ("RQ4", "order_2", "detection_rate"),
        ("RQ4", "order_3", "detection_rate"),
        ("RQ4", "order_1", "complete_repair_rate"),
        ("RQ4", "order_2", "complete_repair_rate"),
        ("RQ4", "order_3", "complete_repair_rate"),
        ("RQ4", "order_1", "effective_repair_rate"),
        ("RQ4", "order_2", "effective_repair_rate"),
        ("RQ4", "order_3", "effective_repair_rate"),
        ("C3", "shallow", "detection_rate"),
        ("C3", "medium", "detection_rate"),
        ("C3", "deep", "detection_rate"),
    }
)


def filter_paper_main_ci_rows(
    rows: Sequence[ConfidenceIntervalRow],
) -> list[ConfidenceIntervalRow]:
    """Return headline paper metrics in stable presentation order."""
    ordered: list[ConfidenceIntervalRow] = []
    for row in rows:
        key = (row.group, row.subgroup, row.metric)
        if key in PAPER_MAIN_CI_METRICS:
            ordered.append(row)

    def _sort_key(row: ConfidenceIntervalRow) -> tuple[str, str, str]:
        metric_order = {
            "overall_detection_rate": 0,
            "mean_faulty_bpr": 1,
            "mean_bpr_delta": 2,
            "complete_repair_rate_detectable_only": 3,
            "effective_repair_rate_detectable_only": 4,
            "top_1_hit_rate": 5,
            "top_3_hit_rate": 6,
            "top_5_hit_rate": 7,
            "mrr": 8,
            "detection_rate": 9,
            "complete_repair_rate": 10,
            "effective_repair_rate": 11,
        }
        subgroup_order = {
            "": 0,
            "baseline_missing_transition": 1,
            "baseline_wrong_target": 2,
            "baseline_random": 3,
            "order_1": 4,
            "order_2": 5,
            "order_3": 6,
            "shallow": 7,
            "medium": 8,
            "deep": 9,
        }
        group_order = {"RQ2": 0, "C1": 1, "RQ3": 2, "RQ4": 3, "C3": 4}
        return (
            group_order.get(row.group, 99),
            subgroup_order.get(row.subgroup, 99),
            metric_order.get(row.metric, 99),
        )

    return sorted(ordered, key=_sort_key)


def render_paper_main_ci_tex(rows: Sequence[ConfidenceIntervalRow]) -> str:
    """Render the consolidated headline CI table for the STVR manuscript."""
    lines = [
        "% Auto-generated by fsmrepairbench.paper_confidence_intervals",
        "\\begin{table}[t]",
        "\\caption{Bootstrap 95\\% confidence intervals for headline empirical results "
        f"(non-parametric case resampling; {BOOTSTRAP_RESAMPLES:,} resamples; seed {BOOTSTRAP_SEED}).}}",
        "\\label{tab:ci-main-results}",
        "\\small",
        "\\begin{tabular}{@{}lllrrrr@{}}",
        "\\toprule",
        "Campaign & Metric & Subgroup & $n$ & Mean & CI low & CI high \\\\",
        "\\midrule",
    ]
    for row in rows:
        campaign = row.group.replace("_", "\\_") if row.group else "---"
        metric = row.metric.replace("_", "\\_")
        subgroup = row.subgroup.replace("_", "\\_") if row.subgroup else "---"
        lines.append(
            f"{campaign} & {metric} & {subgroup} & {row.n_cases} & "
            f"{row.mean:.4f} & {row.ci95_low:.4f} & {row.ci95_high:.4f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)
