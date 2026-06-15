"""Reusable bootstrap confidence interval utilities for empirical campaigns."""

from __future__ import annotations

import csv
import json
import math
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
    "partition",
    "subgroup",
    "n_cases",
    "mean",
    "ci95_low",
    "ci95_high",
)

PAIRED_CONFIDENCE_INTERVAL_CSV_COLUMNS: tuple[str, ...] = (
    "metric",
    "group",
    "partition",
    "tool_a",
    "tool_b",
    "n_pairs",
    "mean_a",
    "mean_b",
    "mean_diff",
    "ci95_low",
    "ci95_high",
    "mcnemar_p_value",
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
    partition: str = ""
    subgroup: str = ""
    n_cases: int = 0


@dataclass(frozen=True)
class PairedConfidenceIntervalRow:
    """Bootstrap CI for a paired mean difference on matched cases."""

    metric: str
    mean_a: float
    mean_b: float
    mean_diff: float
    ci95_low: float
    ci95_high: float
    group: str = ""
    partition: str = ""
    tool_a: str = ""
    tool_b: str = ""
    n_pairs: int = 0
    mcnemar_p_value: float | None = None


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
    partition: str = "",
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
            partition=partition,
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
        partition=partition,
        subgroup=subgroup,
        n_cases=len(numeric),
    )


def bootstrap_rate_ci(
    flags: Sequence[bool],
    metric: str,
    *,
    group: str = "",
    partition: str = "",
    subgroup: str = "",
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> ConfidenceIntervalRow:
    """Bootstrap CI for a binary rate expressed as the mean of 0/1 values."""
    return bootstrap_mean_ci(
        [1.0 if flag else 0.0 for flag in flags],
        metric,
        group=group,
        partition=partition,
        subgroup=subgroup,
        n_resamples=n_resamples,
        bootstrap_seed=bootstrap_seed,
    )


def _mcnemar_exact_p_value(
    discordant_ab: int,
    discordant_ba: int,
) -> float:
    """Two-sided exact McNemar *p*-value for paired binary outcomes."""
    discordant = discordant_ab + discordant_ba
    if discordant == 0:
        return 1.0
    k = min(discordant_ab, discordant_ba)
    probability = 0.0
    for index in range(k + 1):
        probability += math.comb(discordant, index) * (0.5**discordant)
    return min(1.0, 2.0 * probability)


def bootstrap_paired_diff_ci(
    values_a: Sequence[float],
    values_b: Sequence[float],
    metric: str,
    *,
    group: str = "",
    partition: str = "",
    tool_a: str = "",
    tool_b: str = "",
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> PairedConfidenceIntervalRow | None:
    """Bootstrap CI for the paired mean difference (A minus B) on matched cases."""
    if len(values_a) != len(values_b) or not values_a:
        return None

    numeric_a = [float(value) for value in values_a]
    numeric_b = [float(value) for value in values_b]
    diffs = [left - right for left, right in zip(numeric_a, numeric_b, strict=True)]
    mean_a = statistics.mean(numeric_a)
    mean_b = statistics.mean(numeric_b)
    mean_diff = statistics.mean(diffs)

    rng = random.Random(bootstrap_seed)
    boot_diffs: list[float] = []
    sample_size = len(diffs)
    for _ in range(n_resamples):
        draw = [diffs[rng.randrange(sample_size)] for _ in range(sample_size)]
        boot_diffs.append(statistics.mean(draw))
    boot_diffs.sort()
    alpha = (1.0 - BOOTSTRAP_CI) / 2.0
    low_index = max(0, int(alpha * n_resamples))
    high_index = min(len(boot_diffs) - 1, int((1.0 - alpha) * n_resamples) - 1)
    low = boot_diffs[low_index]
    high = boot_diffs[high_index]

    mcnemar_p: float | None = None
    if all(value in (0.0, 1.0) for value in numeric_a) and all(value in (0.0, 1.0) for value in numeric_b):
        discordant_ab = sum(1 for left, right in zip(numeric_a, numeric_b, strict=True) if left and not right)
        discordant_ba = sum(1 for left, right in zip(numeric_a, numeric_b, strict=True) if right and not left)
        mcnemar_p = round(_mcnemar_exact_p_value(discordant_ab, discordant_ba), 6)

    return PairedConfidenceIntervalRow(
        metric=metric,
        mean_a=round(mean_a, 6),
        mean_b=round(mean_b, 6),
        mean_diff=round(mean_diff, 6),
        ci95_low=round(low, 6),
        ci95_high=round(high, 6),
        group=group,
        partition=partition,
        tool_a=tool_a,
        tool_b=tool_b,
        n_pairs=len(diffs),
        mcnemar_p_value=mcnemar_p,
    )


def confidence_interval_rows_to_dicts(rows: Sequence[ConfidenceIntervalRow]) -> list[dict[str, Any]]:
    """Convert CI rows to CSV/JSON-serializable dicts."""
    return [
        {
            "metric": row.metric,
            "group": row.group,
            "partition": row.partition,
            "subgroup": row.subgroup,
            "n_cases": row.n_cases,
            "mean": row.mean,
            "ci95_low": row.ci95_low,
            "ci95_high": row.ci95_high,
        }
        for row in rows
    ]


def paired_confidence_interval_rows_to_dicts(
    rows: Sequence[PairedConfidenceIntervalRow],
) -> list[dict[str, Any]]:
    """Convert paired CI rows to CSV/JSON-serializable dicts."""
    return [
        {
            "metric": row.metric,
            "group": row.group,
            "partition": row.partition,
            "tool_a": row.tool_a,
            "tool_b": row.tool_b,
            "n_pairs": row.n_pairs,
            "mean_a": row.mean_a,
            "mean_b": row.mean_b,
            "mean_diff": row.mean_diff,
            "ci95_low": row.ci95_low,
            "ci95_high": row.ci95_high,
            "mcnemar_p_value": row.mcnemar_p_value,
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


def ci_row_lookup(
    rows: Sequence[ConfidenceIntervalRow],
    *,
    group: str,
    partition: str,
    metric: str,
    subgroup: str = "",
) -> ConfidenceIntervalRow | None:
    """Return the first matching CI row, if any."""
    for row in rows:
        if (
            row.group == group
            and row.partition == partition
            and row.metric == metric
            and row.subgroup == subgroup
        ):
            return row
    return None


def filter_ci_rows_by_group(
    rows: Sequence[ConfidenceIntervalRow],
    *,
    group: str,
    metrics: Sequence[str] | None = None,
) -> list[ConfidenceIntervalRow]:
    """Return CI rows for one campaign group."""
    allowed = set(metrics) if metrics is not None else None
    return [
        row
        for row in rows
        if row.group == group and (allowed is None or row.metric in allowed)
    ]


def filter_paired_ci_rows_by_group(
    rows: Sequence[PairedConfidenceIntervalRow],
    *,
    group: str,
) -> list[PairedConfidenceIntervalRow]:
    """Return paired CI rows for one campaign group."""
    return [row for row in rows if row.group == group]


def write_confidence_interval_exports(
    output_dir: Path,
    *,
    campaign: str,
    rows: Sequence[ConfidenceIntervalRow],
    paper_export_dir: Path | None = None,
    tex_caption: str | None = None,
    repo_root: Path | None = None,
    tex_label: str = "tab:confidence-intervals",
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
        tex_content = render_campaign_metrics_ci_tex(
            rows,
            campaign=campaign,
            caption=caption,
            label=tex_label,
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


def write_paired_confidence_interval_exports(
    output_dir: Path,
    *,
    campaign: str,
    rows: Sequence[PairedConfidenceIntervalRow],
    paper_export_dir: Path | None = None,
    repo_root: Path | None = None,
) -> Path:
    """Write paired bootstrap CI CSV/JSON exports."""
    output_dir.mkdir(parents=True, exist_ok=True)
    csv_path = output_dir / "paired_confidence_intervals.csv"
    json_path = output_dir / "paired_confidence_intervals.json"
    dict_rows = paired_confidence_interval_rows_to_dicts(rows)
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PAIRED_CONFIDENCE_INTERVAL_CSV_COLUMNS))
        writer.writeheader()
        writer.writerows(dict_rows)
    json_path.write_text(
        json.dumps(
            {
                **bootstrap_metadata(campaign=campaign),
                "comparisons": dict_rows,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    resolved_paper_dir = paper_export_dir
    if resolved_paper_dir is None:
        rel = DEFAULT_PAPER_EXPORT_DIRS.get(campaign)
        if rel is not None:
            base = repo_root or Path(__file__).resolve().parents[2]
            resolved_paper_dir = base / rel
    if resolved_paper_dir is not None:
        resolved_paper_dir.mkdir(parents=True, exist_ok=True)
        (resolved_paper_dir / "paired_confidence_intervals.csv").write_text(
            csv_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    return csv_path


def render_campaign_metrics_ci_tex(
    rows: Sequence[ConfidenceIntervalRow],
    *,
    campaign: str,
    caption: str,
    label: str = "tab:confidence-intervals",
) -> str:
    """Render a campaign CI table with partition and subgroup columns."""
    lines = [
        "% Auto-generated from fsmrepairbench.statistics",
        "\\begin{table}[t]",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}llllrrrr@{}}",
        "\\toprule",
        "Metric & Partition & Subgroup & $n$ & Mean & CI low & CI high \\\\",
        "\\midrule",
    ]
    for row in rows:
        metric_label = row.metric.replace("_", "\\_")
        partition = (row.partition or "---").replace("_", "\\_")
        subgroup = (row.subgroup or "---").replace("_", "\\_")
        lines.append(
            f"{metric_label} & {partition} & {subgroup} & {row.n_cases} & "
            f"{row.mean:.4f} & {row.ci95_low:.4f} & {row.ci95_high:.4f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)


def compute_rq2_confidence_intervals(cases: Sequence[Any]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for v0.2.0-analysis / RQ2 detection and BPR metrics."""
    detected = [case.bpr_delta > 0.0 for case in cases]
    faulty_bpr = [float(case.faulty_bpr) for case in cases]
    bpr_delta = [float(case.bpr_delta) for case in cases]
    return [
        bootstrap_rate_ci(detected, "overall_detection_rate", group="RQ2", partition="cohort_wide"),
        bootstrap_mean_ci(faulty_bpr, "mean_faulty_bpr", group="RQ2", partition="cohort_wide"),
        bootstrap_mean_ci(bpr_delta, "mean_bpr_delta", group="RQ2", partition="cohort_wide"),
    ]


C1_BASELINE_TOOL_IDS: tuple[str, ...] = (
    "baseline_missing_transition",
    "baseline_wrong_target",
    "baseline_random",
    "baseline_search_bpr",
    "baseline_oracle_composite",
    "baseline_llm_template",
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
    """Bootstrap CIs for C1 detection, repair, and mean Delta-BPR by tool."""
    ci_rows: list[ConfidenceIntervalRow] = []
    for tool_id in tool_ids:
        rows = [row for row in tool_rows if _row_value(row, "tool_id") == tool_id]
        if not rows:
            continue

        detectable_rows = [row for row in rows if _csv_case_id(row) in detectable_case_ids]
        for partition, subset in (
            ("cohort_wide", rows),
            ("detectable_only", detectable_rows),
        ):
            if not subset:
                continue
            ci_rows.extend(
                [
                    bootstrap_rate_ci(
                        [_csv_bool(row, "oracle_detected") for row in subset],
                        "detection_rate",
                        group="C1",
                        partition=partition,
                        subgroup=tool_id,
                    ),
                    bootstrap_rate_ci(
                        [_csv_bool(row, "complete_repair") for row in subset],
                        "complete_repair_rate",
                        group="C1",
                        partition=partition,
                        subgroup=tool_id,
                    ),
                    bootstrap_rate_ci(
                        [_csv_bool(row, "effective_repair") for row in subset],
                        "effective_repair_rate",
                        group="C1",
                        partition=partition,
                        subgroup=tool_id,
                    ),
                    bootstrap_mean_ci(
                        [_csv_float(row, "delta_bpr") for row in subset],
                        "mean_bpr_delta",
                        group="C1",
                        partition=partition,
                        subgroup=tool_id,
                    ),
                ]
            )
    return ci_rows


def compute_c1_paired_confidence_intervals(
    tool_rows: Sequence[Any],
    *,
    detectable_case_ids: set[str],
    tool_pairs: Sequence[tuple[str, str]] | None = None,
) -> list[PairedConfidenceIntervalRow]:
    """Paired bootstrap CIs for C1 tool comparisons on detectable faults."""
    pairs = tool_pairs or (
        ("baseline_missing_transition", "baseline_wrong_target"),
        ("baseline_missing_transition", "baseline_random"),
        ("baseline_wrong_target", "baseline_random"),
    )
    by_case_tool: dict[tuple[str, str], Any] = {}
    for row in tool_rows:
        case_id = _csv_case_id(row)
        if case_id not in detectable_case_ids:
            continue
        by_case_tool[(case_id, str(_row_value(row, "tool_id")))] = row

    ci_rows: list[PairedConfidenceIntervalRow] = []
    for tool_a, tool_b in pairs:
        matched_cases = [
            case_id
            for case_id in detectable_case_ids
            if (case_id, tool_a) in by_case_tool and (case_id, tool_b) in by_case_tool
        ]
        if not matched_cases:
            continue
        for metric, extractor in (
            ("complete_repair_rate", lambda row: 1.0 if _csv_bool(row, "complete_repair") else 0.0),
            ("effective_repair_rate", lambda row: 1.0 if _csv_bool(row, "effective_repair") else 0.0),
            ("mean_bpr_delta", lambda row: _csv_float(row, "delta_bpr")),
        ):
            values_a = [extractor(by_case_tool[(case_id, tool_a)]) for case_id in matched_cases]
            values_b = [extractor(by_case_tool[(case_id, tool_b)]) for case_id in matched_cases]
            paired = bootstrap_paired_diff_ci(
                values_a,
                values_b,
                metric,
                group="C1",
                partition="detectable_only",
                tool_a=tool_a,
                tool_b=tool_b,
            )
            if paired is not None:
                ci_rows.append(paired)
    return ci_rows


def _rq3_localization_metric_rows(
    subset: Sequence[Any],
    *,
    partition: str,
) -> list[ConfidenceIntervalRow]:
    if not subset:
        return []
    return [
        bootstrap_rate_ci(
            [_csv_bool(row, "top1_hit") for row in subset],
            "top_1_hit_rate",
            group="RQ3",
            partition=partition,
        ),
        bootstrap_rate_ci(
            [_csv_bool(row, "top3_hit") for row in subset],
            "top_3_hit_rate",
            group="RQ3",
            partition=partition,
        ),
        bootstrap_rate_ci(
            [_csv_bool(row, "top5_hit") for row in subset],
            "top_5_hit_rate",
            group="RQ3",
            partition=partition,
        ),
        bootstrap_mean_ci(
            [_csv_float(row, "reciprocal_rank") for row in subset],
            "mrr",
            group="RQ3",
            partition=partition,
        ),
    ]


def compute_rq3_confidence_intervals(
    rows: Sequence[Any],
    *,
    detectable_case_ids: set[str] | None = None,
) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for RQ3 localization metrics by analysis partition."""
    localized = [row for row in rows if _csv_bool(row, "localized")]
    if not localized:
        localized = list(rows)

    ci_rows = _rq3_localization_metric_rows(localized, partition="localized_cases")
    if detectable_case_ids is not None:
        detectable_localized = [
            row for row in localized if _csv_case_id(row) in detectable_case_ids
        ]
        ci_rows.extend(_rq3_localization_metric_rows(detectable_localized, partition="detectable_only"))
    return ci_rows


def compute_rq3_cohort_confidence_intervals(cases: Sequence[Any]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for oracle detection and mean Delta-BPR on the RQ3 cohort."""
    detected = [case.bpr_delta > 0.0 for case in cases]
    bpr_delta = [float(case.bpr_delta) for case in cases]
    return [
        bootstrap_rate_ci(detected, "detection_rate", group="RQ3", partition="cohort_wide"),
        bootstrap_mean_ci(bpr_delta, "mean_bpr_delta", group="RQ3", partition="cohort_wide"),
    ]


def compute_rq4_confidence_intervals(rows: Sequence[Any]) -> list[ConfidenceIntervalRow]:
    """Bootstrap CIs for RQ4 coupling metrics by mutation order."""
    ci_rows: list[ConfidenceIntervalRow] = []
    for order in (1, 2, 3):
        group_rows = [
            row
            for row in rows
            if int(_row_value(row, "mutation_order", 0)) == order
        ]
        if not group_rows:
            continue

        order_label = f"order_{order}"
        detectable = [row for row in group_rows if _csv_bool(row, "fault_detected")]
        ci_rows.extend(
            [
                bootstrap_rate_ci(
                    [_csv_bool(row, "fault_detected") for row in group_rows],
                    "detection_rate",
                    group="RQ4",
                    partition="cohort_wide",
                    subgroup=order_label,
                ),
                bootstrap_rate_ci(
                    [_csv_bool(row, "complete_repair") for row in group_rows],
                    "complete_repair_rate",
                    group="RQ4",
                    partition="cohort_wide",
                    subgroup=order_label,
                ),
                bootstrap_rate_ci(
                    [_csv_bool(row, "effective_repair") for row in group_rows],
                    "effective_repair_rate",
                    group="RQ4",
                    partition="cohort_wide",
                    subgroup=order_label,
                ),
                bootstrap_mean_ci(
                    [_csv_float(row, "bpr_delta") for row in group_rows],
                    "mean_bpr_delta",
                    group="RQ4",
                    partition="cohort_wide",
                    subgroup=order_label,
                ),
            ]
        )
        if detectable:
            ci_rows.extend(
                [
                    bootstrap_rate_ci(
                        [_csv_bool(row, "complete_repair") for row in detectable],
                        "complete_repair_rate",
                        group="RQ4",
                        partition="detectable_only",
                        subgroup=order_label,
                    ),
                    bootstrap_rate_ci(
                        [_csv_bool(row, "effective_repair") for row in detectable],
                        "effective_repair_rate",
                        group="RQ4",
                        partition="detectable_only",
                        subgroup=order_label,
                    ),
                    bootstrap_mean_ci(
                        [_csv_float(row, "bpr_delta") for row in detectable],
                        "mean_bpr_delta",
                        group="RQ4",
                        partition="detectable_only",
                        subgroup=order_label,
                    ),
                ]
            )

    fo_group = [row for row in rows if int(_row_value(row, "mutation_order", 0)) == 1]
    ho_group = [row for row in rows if int(_row_value(row, "mutation_order", 0)) in (2, 3)]
    if fo_group:
        ci_rows.append(
            bootstrap_rate_ci(
                [_csv_bool(row, "fault_detected") for row in fo_group],
                "detection_rate",
                group="RQ4",
                partition="cohort_wide",
                subgroup="fo_subset",
            )
        )
    if ho_group:
        ci_rows.append(
            bootstrap_rate_ci(
                [_csv_bool(row, "fault_detected") for row in ho_group],
                "detection_rate",
                group="RQ4",
                partition="cohort_wide",
                subgroup="ho_orders_2_3",
            )
        )
    return ci_rows


def _rq4_row_index(rows: Sequence[Any]) -> dict[tuple[str, int], Any]:
    indexed: dict[tuple[str, int], Any] = {}
    for row in rows:
        source = str(_row_value(row, "source_case_id", _row_value(row, "case_id")))
        order = int(_row_value(row, "mutation_order", 0))
        indexed[(source, order)] = row
    return indexed


def compute_rq4_paired_confidence_intervals(rows: Sequence[Any]) -> list[PairedConfidenceIntervalRow]:
    """Paired bootstrap CIs comparing RQ4 mutation orders on matched source cases."""
    indexed = _rq4_row_index(rows)
    source_ids = sorted({source for source, _order in indexed})
    comparisons = (
        (1, 2, "order_1_vs_order_2"),
        (1, 3, "order_1_vs_order_3"),
        (2, 3, "order_2_vs_order_3"),
    )
    ci_rows: list[PairedConfidenceIntervalRow] = []
    for order_a, order_b, label in comparisons:
        matched_sources = [
            source
            for source in source_ids
            if (source, order_a) in indexed and (source, order_b) in indexed
        ]
        if not matched_sources:
            continue
        for partition, predicate in (
            ("cohort_wide", lambda _row: True),
            ("detectable_only", lambda row: _csv_bool(row, "fault_detected")),
        ):
            for metric, extractor in (
                ("detection_rate", lambda row: 1.0 if _csv_bool(row, "fault_detected") else 0.0),
                ("complete_repair_rate", lambda row: 1.0 if _csv_bool(row, "complete_repair") else 0.0),
                ("effective_repair_rate", lambda row: 1.0 if _csv_bool(row, "effective_repair") else 0.0),
                ("mean_bpr_delta", lambda row: _csv_float(row, "bpr_delta")),
            ):
                if partition == "detectable_only" and metric == "detection_rate":
                    matched = [
                        source
                        for source in matched_sources
                        if predicate(indexed[(source, order_a)])
                    ]
                elif partition == "detectable_only":
                    matched = [
                        source
                        for source in matched_sources
                        if predicate(indexed[(source, order_a)])
                    ]
                else:
                    matched = matched_sources
                if not matched:
                    continue
                values_a = [extractor(indexed[(source, order_a)]) for source in matched]
                values_b = [extractor(indexed[(source, order_b)]) for source in matched]
                paired = bootstrap_paired_diff_ci(
                    values_a,
                    values_b,
                    metric,
                    group="RQ4",
                    partition=partition,
                    tool_a=f"order_{order_a}",
                    tool_b=f"order_{order_b}",
                )
                if paired is not None:
                    ci_rows.append(
                        PairedConfidenceIntervalRow(
                            metric=paired.metric,
                            mean_a=paired.mean_a,
                            mean_b=paired.mean_b,
                            mean_diff=paired.mean_diff,
                            ci95_low=paired.ci95_low,
                            ci95_high=paired.ci95_high,
                            group=paired.group,
                            partition=f"{partition}:{label}",
                            tool_a=paired.tool_a,
                            tool_b=paired.tool_b,
                            n_pairs=paired.n_pairs,
                            mcnemar_p_value=paired.mcnemar_p_value,
                        )
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
                    partition="cohort_wide",
                    subgroup=depth,
                ),
                bootstrap_mean_ci(
                    [_csv_float(row, "faulty_bpr") for row in rows],
                    "mean_faulty_bpr",
                    group="C3",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
                bootstrap_mean_ci(
                    [_csv_float(row, "bpr_delta") for row in rows],
                    "mean_bpr_delta",
                    group="C3",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
            ]
        )
    return ci_rows


PAPER_MAIN_CI_METRICS: frozenset[tuple[str, str, str, str]] = frozenset(
    {
        ("RQ2", "cohort_wide", "", "overall_detection_rate"),
        ("RQ2", "cohort_wide", "", "mean_faulty_bpr"),
        ("RQ2", "cohort_wide", "", "mean_bpr_delta"),
        ("C1", "detectable_only", "baseline_missing_transition", "complete_repair_rate"),
        ("C1", "detectable_only", "baseline_missing_transition", "effective_repair_rate"),
        ("C1", "detectable_only", "baseline_wrong_target", "complete_repair_rate"),
        ("C1", "detectable_only", "baseline_wrong_target", "effective_repair_rate"),
        ("C1", "detectable_only", "baseline_random", "complete_repair_rate"),
        ("C1", "detectable_only", "baseline_random", "effective_repair_rate"),
        ("RQ3", "localized_cases", "", "top_1_hit_rate"),
        ("RQ3", "localized_cases", "", "top_3_hit_rate"),
        ("RQ3", "localized_cases", "", "top_5_hit_rate"),
        ("RQ3", "localized_cases", "", "mrr"),
        ("RQ4", "cohort_wide", "order_1", "detection_rate"),
        ("RQ4", "cohort_wide", "order_2", "detection_rate"),
        ("RQ4", "cohort_wide", "order_3", "detection_rate"),
        ("C3", "cohort_wide", "shallow", "detection_rate"),
        ("C3", "cohort_wide", "medium", "detection_rate"),
        ("C3", "cohort_wide", "deep", "detection_rate"),
    }
)

CAMPAIGN_CI_GROUPS: frozenset[str] = frozenset({"C1", "RQ3", "RQ4"})
CAMPAIGN_CI_METRICS: frozenset[str] = frozenset(
    {
        "detection_rate",
        "complete_repair_rate",
        "effective_repair_rate",
        "mean_bpr_delta",
        "top_1_hit_rate",
        "top_3_hit_rate",
        "top_5_hit_rate",
        "mrr",
    }
)


def filter_paper_main_ci_rows(
    rows: Sequence[ConfidenceIntervalRow],
) -> list[ConfidenceIntervalRow]:
    """Return headline paper metrics in stable presentation order."""
    ordered: list[ConfidenceIntervalRow] = []
    for row in rows:
        key = (row.group, row.partition, row.subgroup, row.metric)
        if key in PAPER_MAIN_CI_METRICS:
            ordered.append(row)

    def _sort_key(row: ConfidenceIntervalRow) -> tuple[int, int, int, int]:
        metric_order = {
            "overall_detection_rate": 0,
            "mean_faulty_bpr": 1,
            "mean_bpr_delta": 2,
            "complete_repair_rate": 3,
            "effective_repair_rate": 4,
            "top_1_hit_rate": 5,
            "top_3_hit_rate": 6,
            "top_5_hit_rate": 7,
            "mrr": 8,
            "detection_rate": 9,
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
        partition_order = {
            "": 0,
            "localized_cases": 1,
            "detectable_only": 2,
            "cohort_wide": 3,
        }
        group_order = {"RQ2": 0, "C1": 1, "RQ3": 2, "RQ4": 3, "C3": 4}
        return (
            group_order.get(row.group, 99),
            partition_order.get(row.partition, 99),
            subgroup_order.get(row.subgroup, 99),
            metric_order.get(row.metric, 99),
        )

    return sorted(ordered, key=_sort_key)


def filter_campaign_ci_rows(rows: Sequence[ConfidenceIntervalRow]) -> list[ConfidenceIntervalRow]:
    """Return C1/RQ3/RQ4 detection, repair, and Delta-BPR intervals."""
    filtered = [
        row
        for row in rows
        if row.group in CAMPAIGN_CI_GROUPS and row.metric in CAMPAIGN_CI_METRICS
    ]

    def _sort_key(row: ConfidenceIntervalRow) -> tuple[int, int, int, int]:
        group_order = {"C1": 0, "RQ3": 1, "RQ4": 2}
        metric_order = {
            "detection_rate": 0,
            "complete_repair_rate": 1,
            "effective_repair_rate": 2,
            "mean_bpr_delta": 3,
            "top_1_hit_rate": 4,
            "top_3_hit_rate": 5,
            "top_5_hit_rate": 6,
            "mrr": 7,
        }
        partition_order = {"detectable_only": 0, "localized_cases": 1, "cohort_wide": 2, "": 3}
        subgroup_order = {
            "baseline_missing_transition": 0,
            "baseline_wrong_target": 1,
            "baseline_random": 2,
            "order_1": 3,
            "order_2": 4,
            "order_3": 5,
            "fo_subset": 6,
            "ho_orders_2_3": 7,
            "": 8,
        }
        return (
            group_order.get(row.group, 99),
            partition_order.get(row.partition, 99),
            subgroup_order.get(row.subgroup, 99),
            metric_order.get(row.metric, 99),
        )

    return sorted(filtered, key=_sort_key)


def _tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def render_paper_main_ci_tex(rows: Sequence[ConfidenceIntervalRow]) -> str:
    """Render the consolidated headline CI table for the STVR manuscript."""
    lines = [
        "% Auto-generated by fsmrepairbench.paper_confidence_intervals",
        "\\begin{table}[t]",
        "\\caption{Bootstrap 95\\% confidence intervals for headline empirical results "
        f"(non-parametric case resampling; {BOOTSTRAP_RESAMPLES:,} resamples; seed {BOOTSTRAP_SEED}). "
        "C1 repair rows use detectable-only partitions ($n=495$). Full campaign metrics with cohort-wide "
        "and detectable-only partitions appear in \\Tab{tab:ci-campaign-metrics}; paired comparisons in "
        "\\Tab{tab:ci-paired-comparisons}.}",
        "\\label{tab:ci-main-results}",
        "\\small",
        "\\begin{tabular}{@{}llllrrrr@{}}",
        "\\toprule",
        "Campaign & Partition & Metric & Subgroup & $n$ & Mean & CI low & CI high \\\\",
        "\\midrule",
    ]
    for row in rows:
        campaign = _tex_escape(row.group) if row.group else "---"
        partition = _tex_escape(row.partition) if row.partition else "---"
        metric = _tex_escape(row.metric)
        subgroup = _tex_escape(row.subgroup) if row.subgroup else "---"
        lines.append(
            f"{campaign} & {partition} & {metric} & {subgroup} & {row.n_cases} & "
            f"{row.mean:.4f} & {row.ci95_low:.4f} & {row.ci95_high:.4f} \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            r"\par\footnotesize Source: frozen export \texttt{"
            + _tex_escape("paper1/results/confidence_intervals/confidence_intervals.csv")
            + "}.",
            "\\end{table}",
            "",
        ]
    )
    return "\n".join(lines)


def render_campaign_ci_tex(rows: Sequence[ConfidenceIntervalRow]) -> str:
    """Render bootstrap CIs for C1, RQ3, and RQ4 core metrics."""
    lines = [
        "% Auto-generated by fsmrepairbench.paper_confidence_intervals",
        "\\begin{table}[t]",
        "\\caption{Bootstrap 95\\% confidence intervals for detection, complete repair, effective repair, "
        f"mean $\\Delta$BPR, and localization MRR in campaigns C1, RQ3, and RQ4 (10{{,}}000 case resamples; seed {BOOTSTRAP_SEED}). "
        "C1 rows report deterministic baseline engines on the 1{,}000-case cohort. "
        "RQ3 detection and $\\Delta$BPR derive from oracle scoring on the localization cohort; "
        "Top-$k$ and MRR rows use localized cases and detectable-only partitions. "
        "RQ4 rows use the pinned 250-case subset with deterministic HO chaining (seed~44). "
        "Detectable-only partitions are primary for repair claims; cohort-wide totals are transparency-only.}",
        "\\label{tab:ci-campaign-metrics}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}llllrrrr@{}}",
        "\\toprule",
        "Campaign & Partition & Metric & Subgroup & $n$ & Mean & CI low & CI high \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{_tex_escape(row.group)} & {_tex_escape(row.partition or '---')} & "
            f"{_tex_escape(row.metric)} & {_tex_escape(row.subgroup or '---')} & {row.n_cases} & "
            f"{row.mean:.4f} & {row.ci95_low:.4f} & {row.ci95_high:.4f} \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            r"\par\scriptsize Source: \texttt{"
            + _tex_escape("paper1/results/confidence_intervals/confidence_intervals.csv")
            + "}.",
            "\\end{table}",
            "",
        ]
    )
    return "\n".join(lines)


def render_paired_ci_tex(rows: Sequence[PairedConfidenceIntervalRow]) -> str:
    """Render paired bootstrap difference CIs for matched-case comparisons."""
    lines = [
        "% Auto-generated by fsmrepairbench.paper_confidence_intervals",
        "\\begin{table}[t]",
        "\\caption{Paired bootstrap 95\\% confidence intervals for matched-case mean differences "
        f"(A minus B; 10{{,}}000 resamples; seed {BOOTSTRAP_SEED}). "
        "C1 compares deterministic repair engines on detectable faults ($n=495$). "
        "RQ4 compares mutation orders on matched \\texttt{source\\_case\\_id} records in the pinned subset. "
        "Exact McNemar $p$-values accompany binary paired metrics. "
        "Intervals excluding zero indicate bootstrap-distinguishable paired differences on this cohort.}",
        "\\label{tab:ci-paired-comparisons}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}llllrrrrrrrl@{}}",
        "\\toprule",
        "Campaign & Partition & Metric & A & B & $n$ & Mean A & Mean B & Diff & CI low & CI high & McNemar $p$ \\\\",
        "\\midrule",
    ]
    for row in rows:
        p_value = "---" if row.mcnemar_p_value is None else f"{row.mcnemar_p_value:.4f}"
        lines.append(
            f"{_tex_escape(row.group)} & {_tex_escape(row.partition)} & {_tex_escape(row.metric)} & "
            f"{_tex_escape(row.tool_a)} & {_tex_escape(row.tool_b)} & {row.n_pairs} & "
            f"{row.mean_a:.4f} & {row.mean_b:.4f} & {row.mean_diff:.4f} & "
            f"{row.ci95_low:.4f} & {row.ci95_high:.4f} & {p_value} \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            r"\par\scriptsize Source: \texttt{"
            + _tex_escape("paper1/results/confidence_intervals/paired_confidence_intervals.csv")
            + "}.",
            "\\end{table}",
            "",
        ]
    )
    return "\n".join(lines)
