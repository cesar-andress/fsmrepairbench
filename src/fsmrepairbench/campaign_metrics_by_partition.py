"""Unified long-format metrics export with explicit partition columns for C1/RQ3/RQ4."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.campaign_partitions import resolve_results_dir

DEFAULT_OUTPUT_DIR = Path("results/campaign_metrics_by_partition")
DEFAULT_PAPER_EXPORT_DIR = Path("../paper1/results/campaign_metrics_by_partition")
ZENODO_DOI = "10.5281/zenodo.20602577"

METRICS_BY_PARTITION_COLUMNS: tuple[str, ...] = (
    "campaign",
    "release_label",
    "construct",
    "metric",
    "partition",
    "subgroup",
    "n_cases",
    "value",
    "ci95_low",
    "ci95_high",
)


class CampaignMetricsExportError(ValueError):
    """Raised when partition metric export inputs are missing or invalid."""


@dataclass(frozen=True)
class MetricPartitionRow:
    campaign: str
    release_label: str
    construct: str
    metric: str
    partition: str
    subgroup: str
    n_cases: int
    value: float
    ci95_low: float | None = None
    ci95_high: float | None = None

    def to_dict(self) -> dict[str, str | int | float]:
        payload: dict[str, str | int | float] = {
            "campaign": self.campaign,
            "release_label": self.release_label,
            "construct": self.construct,
            "metric": self.metric,
            "partition": self.partition,
            "subgroup": self.subgroup,
            "n_cases": self.n_cases,
            "value": round(self.value, 6),
        }
        if self.ci95_low is not None:
            payload["ci95_low"] = round(self.ci95_low, 6)
        if self.ci95_high is not None:
            payload["ci95_high"] = round(self.ci95_high, 6)
        return payload


@dataclass(frozen=True)
class CampaignMetricsExportResult:
    output_dir: Path
    csv_path: Path
    c1_csv_path: Path
    rq3_csv_path: Path
    rq4_csv_path: Path
    tex_path: Path | None
    paper_csv_path: Path | None


def _append_row(
    rows: list[MetricPartitionRow],
    *,
    campaign: str,
    release_label: str,
    construct: str,
    metric: str,
    partition: str,
    subgroup: str,
    n_cases: int,
    value: float,
    ci95_low: float | None = None,
    ci95_high: float | None = None,
) -> None:
    rows.append(
        MetricPartitionRow(
            campaign=campaign,
            release_label=release_label,
            construct=construct,
            metric=metric,
            partition=partition,
            subgroup=subgroup,
            n_cases=n_cases,
            value=value,
            ci95_low=ci95_low,
            ci95_high=ci95_high,
        )
    )


def _read_confidence_intervals(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _ci_lookup(
    rows: Sequence[dict[str, str]],
    *,
    metric: str,
    partition: str,
    subgroup: str = "",
) -> tuple[float | None, float | None]:
    for row in rows:
        if row.get("metric") != metric:
            continue
        if row.get("partition") != partition:
            continue
        if subgroup and row.get("subgroup") != subgroup:
            continue
        low = row.get("ci95_low") or row.get("value_ci95_low")
        high = row.get("ci95_high") or row.get("value_ci95_high")
        if low is None or high is None:
            return None, None
        return float(low), float(high)
    return None, None


def _build_c1_rows(
    c1_dir: Path,
    *,
    ci_rows: list[dict[str, str]],
) -> list[MetricPartitionRow]:
    rows: list[MetricPartitionRow] = []
    leaderboard = c1_dir / "leaderboard.csv"
    if not leaderboard.is_file():
        return rows

    for row in csv.DictReader(leaderboard.open(encoding="utf-8")):
        tool_id = str(row["tool_id"])
        n_total = int(float(row["cases"]))
        n_detectable = int(float(row["detectable_cases"]))
        for metric, detect_key, cohort_key in (
            ("complete_repair_rate", "complete_repair_rate_detectable_only", "complete_repair_rate"),
            ("effective_repair_rate", "effective_repair_rate_detectable_only", "effective_repair_rate"),
        ):
            cohort_val = row.get(cohort_key) or row.get(f"{cohort_key}_cohort_wide")
            _append_row(
                rows,
                campaign="C1-baseline-repair",
                release_label="C1-baseline-repair",
                construct="repair",
                metric=metric,
                partition="detectable_only",
                subgroup=tool_id,
                n_cases=n_detectable,
                value=float(row[detect_key]),
                ci95_low=_ci_lookup(ci_rows, metric=metric, partition="detectable_only", subgroup=tool_id)[0],
                ci95_high=_ci_lookup(ci_rows, metric=metric, partition="detectable_only", subgroup=tool_id)[1],
            )
            _append_row(
                rows,
                campaign="C1-baseline-repair",
                release_label="C1-baseline-repair",
                construct="repair",
                metric=metric,
                partition="cohort_wide",
                subgroup=tool_id,
                n_cases=n_total,
                value=float(cohort_val),
                ci95_low=_ci_lookup(ci_rows, metric=metric, partition="cohort_wide", subgroup=tool_id)[0],
                ci95_high=_ci_lookup(ci_rows, metric=metric, partition="cohort_wide", subgroup=tool_id)[1],
            )
        _append_row(
            rows,
            campaign="C1-baseline-repair",
            release_label="C1-baseline-repair",
            construct="repair",
            metric="mean_delta_bpr",
            partition="cohort_wide",
            subgroup=tool_id,
            n_cases=n_total,
            value=float(row.get("mean_delta_bpr") or row.get("mean_delta_bpr_cohort_wide", 0)),
            ci95_low=_ci_lookup(ci_rows, metric="mean_bpr_delta", partition="cohort_wide", subgroup=tool_id)[0],
            ci95_high=_ci_lookup(ci_rows, metric="mean_bpr_delta", partition="cohort_wide", subgroup=tool_id)[1],
        )
        detectable_mean = None
        with_ci_path = c1_dir / "leaderboard_with_ci.csv"
        if with_ci_path.is_file():
            for ci_row in csv.DictReader(with_ci_path.open(encoding="utf-8")):
                if ci_row.get("tool_id") == tool_id:
                    detectable_mean = float(ci_row.get("detectable_only_mean_bpr_delta_mean", "") or 0)
                    break
        _append_row(
            rows,
            campaign="C1-baseline-repair",
            release_label="C1-baseline-repair",
            construct="repair",
            metric="mean_delta_bpr",
            partition="detectable_only",
            subgroup=tool_id,
            n_cases=n_detectable,
            value=detectable_mean if detectable_mean is not None else float(row.get("mean_delta_bpr") or row.get("mean_delta_bpr_cohort_wide", 0)),
            ci95_low=_ci_lookup(ci_rows, metric="mean_bpr_delta", partition="detectable_only", subgroup=tool_id)[0],
            ci95_high=_ci_lookup(ci_rows, metric="mean_bpr_delta", partition="detectable_only", subgroup=tool_id)[1],
        )
    return rows


def _build_rq3_rows(rq3_dir: Path) -> list[MetricPartitionRow]:
    rows: list[MetricPartitionRow] = []
    with_ci = rq3_dir / "localization_metrics_with_ci.csv"
    if with_ci.is_file():
        for row in csv.DictReader(with_ci.open(encoding="utf-8")):
            partition = str(row["partition"])
            metric = str(row["metric"])
            construct = "detection" if metric == "detection_rate" else "localization"
            if partition == "localized_cases":
                partition = "audit_detectable_pool"
            if partition == "detectable_only" and construct == "localization":
                partition = "audit_detectable_pool"
            _append_row(
                rows,
                campaign="RQ3-localization-ochiai-1k",
                release_label="RQ3-localization-ochiai-1k",
                construct=construct,
                metric=metric,
                partition=partition,
                subgroup="ochiai",
                n_cases=int(float(row["n_cases"])),
                value=float(row["value_mean"]) / (100.0 if "hit_rate" in metric else 1.0),
                ci95_low=float(row["value_ci95_low"]) / (100.0 if "hit_rate" in metric else 1.0),
                ci95_high=float(row["value_ci95_high"]) / (100.0 if "hit_rate" in metric else 1.0),
            )

    localizable = rq3_dir / "localization_baseline_comparison.csv"
    if localizable.is_file():
        for row in csv.DictReader(localizable.open(encoding="utf-8")):
            if row.get("partition") != "transition_localizable_gt":
                continue
            method = str(row["method"])
            n_cases = int(float(row["n_cases"]))
            for metric, key, low_key, high_key in (
                ("top_1_hit_rate", "top1_hit_rate", "top1_ci95_low", "top1_ci95_high"),
                ("top_3_hit_rate", "top3_hit_rate", "top3_ci95_low", "top3_ci95_high"),
                ("top_5_hit_rate", "top5_hit_rate", "top5_ci95_low", "top5_ci95_high"),
                ("mrr", "mrr", "mrr_ci95_low", "mrr_ci95_high"),
            ):
                _append_row(
                    rows,
                    campaign="RQ3-localization-ochiai-1k",
                    release_label="RQ3-localization-ochiai-1k",
                    construct="localization",
                    metric=metric,
                    partition="transition_localizable_gt",
                    subgroup=method,
                    n_cases=n_cases,
                    value=float(row[key]),
                    ci95_low=float(row[low_key]) if row.get(low_key) else None,
                    ci95_high=float(row[high_key]) if row.get(high_key) else None,
                )
    return rows


def _build_rq4_rows(rq4_dir: Path) -> list[MetricPartitionRow]:
    rows: list[MetricPartitionRow] = []
    with_ci = rq4_dir / "summary_metrics_with_ci.csv"
    if not with_ci.is_file():
        return rows
    for row in csv.DictReader(with_ci.open(encoding="utf-8")):
        metric = str(row["metric"])
        partition = str(row["partition"])
        order = str(row["mutation_order"])
        construct = "detection" if metric == "detection_rate" else "repair"
        _append_row(
            rows,
            campaign="RQ4-higher-order-coupling-250",
            release_label="RQ4-higher-order-coupling-250",
            construct=construct,
            metric=metric,
            partition=partition,
            subgroup=order,
            n_cases=int(float(row["n_cases"])),
            value=float(row["value_mean"]) / 100.0 if metric != "mean_bpr_delta" else float(row["value_mean"]),
            ci95_low=float(row["value_ci95_low"]) / 100.0 if metric != "mean_bpr_delta" else float(row["value_ci95_low"]),
            ci95_high=float(row["value_ci95_high"]) / 100.0 if metric != "mean_bpr_delta" else float(row["value_ci95_high"]),
        )
    return rows


def _build_detection_rows(analysis_dir: Path, ci_path: Path | None = None) -> list[MetricPartitionRow]:
    rows: list[MetricPartitionRow] = []
    summary = analysis_dir / "summary.csv"
    if not summary.is_file():
        return rows
    metrics = {row["metric"]: row["value"] for row in csv.DictReader(summary.open(encoding="utf-8"))}
    ci_rows = _read_confidence_intervals(ci_path) if ci_path else []
    detection = float(metrics.get("overall_detection_rate", 0))
    low, high = _ci_lookup(ci_rows, metric="detection_rate", partition="cohort_wide")
    _append_row(
        rows,
        campaign="v0.2.0-analysis",
        release_label="v0.2.0-analysis",
        construct="detection",
        metric="detection_rate",
        partition="cohort_wide",
        subgroup="all_cases",
        n_cases=1000,
        value=detection,
        ci95_low=low,
        ci95_high=high,
    )
    detectable = round(1000 * detection)
    _append_row(
        rows,
        campaign="v0.2.0-analysis",
        release_label="v0.2.0-analysis",
        construct="detection",
        metric="detection_rate",
        partition="detectable_only",
        subgroup="oracle_detected",
        n_cases=495,
        value=1.0,
    )
    return rows


def build_campaign_metrics_by_partition_rows(
    *,
    repo_root: Path | None = None,
    result_overrides: dict[str, Path] | None = None,
) -> list[MetricPartitionRow]:
    base = repo_root or Path(__file__).resolve().parents[2]
    rows: list[MetricPartitionRow] = []

    analysis_dir = resolve_results_dir("v0.2.0-analysis", repo_root=base, overrides=result_overrides)
    rows.extend(_build_detection_rows(analysis_dir, analysis_dir / "confidence_intervals.csv"))

    c1_dir = resolve_results_dir("C1-baseline-repair", repo_root=base, overrides=result_overrides)
    rows.extend(_build_c1_rows(c1_dir, ci_rows=_read_confidence_intervals(c1_dir / "confidence_intervals.csv")))

    rq3_dir = resolve_results_dir("RQ3-localization", repo_root=base, overrides=result_overrides)
    rows.extend(_build_rq3_rows(rq3_dir))

    rq4_dir = resolve_results_dir("RQ4-coupling", repo_root=base, overrides=result_overrides)
    rows.extend(_build_rq4_rows(rq4_dir))
    return rows


def _write_csv(path: Path, rows: Sequence[MetricPartitionRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METRICS_BY_PARTITION_COLUMNS))
        writer.writeheader()
        for row in rows:
            payload = row.to_dict()
            for key in METRICS_BY_PARTITION_COLUMNS:
                payload.setdefault(key, "")
            writer.writerow(payload)


def render_metrics_by_partition_tex(rows: Sequence[MetricPartitionRow]) -> str:
    """Render a compact LaTeX table of headline metrics by construct and partition."""
    headline = [
        ("C1-baseline-repair", "repair", "complete_repair_rate", "detectable_only", "baseline_missing_transition"),
        ("C1-baseline-repair", "repair", "complete_repair_rate", "cohort_wide", "baseline_missing_transition"),
        ("RQ3-localization-ochiai-1k", "localization", "top_1_hit_rate", "transition_localizable_gt", "ochiai"),
        ("RQ4-higher-order-coupling-250", "detection", "detection_rate", "cohort_wide", "order_1"),
        ("RQ4-higher-order-coupling-250", "repair", "complete_repair_rate", "detectable_only", "order_1"),
        ("RQ4-higher-order-coupling-250", "repair", "complete_repair_rate", "cohort_wide", "order_1"),
    ]
    lookup = {
        (row.campaign, row.construct, row.metric, row.partition, row.subgroup): row
        for row in rows
    }
    lines = [
        "% Auto-generated from campaign_metrics_by_partition",
        "\\begin{table}[t]",
        "\\caption{Headline metrics by measurement construct and reporting partition. "
        "Detection (RQ2/RQ4), localization (RQ3), and repair (C1/RQ4) are separate constructs; "
        "detectable-only and transition-localizable partitions are primary; cohort-wide totals are transparency-only.}",
        "\\label{tab:construct-metric-partitions}",
        "\\scriptsize",
        "\\begin{tabular}{@{}llllrr@{}}",
        "\\toprule",
        "Campaign & Construct & Metric & Partition & $n$ & Value \\\\",
        "\\midrule",
    ]
    for key in headline:
        row = lookup.get(key)
        if row is None:
            continue
        value = row.value * 100.0 if row.metric != "mrr" and row.metric != "mean_delta_bpr" else row.value
        if row.metric.endswith("_rate") or row.metric.endswith("hit_rate"):
            value_str = f"{value:.1f}\\%"
        elif row.metric == "mrr":
            value_str = f"{value:.3f}"
        else:
            value_str = f"{value:.3f}"
        lines.append(
            f"{row.release_label.replace('_', '\\_')} & {row.construct} & "
            f"{row.metric.replace('_', '\\_')} & {row.partition.replace('_', '\\_')} & "
            f"{row.n_cases} & {value_str} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)


def export_campaign_metrics_by_partition(
    *,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    repo_root: Path | None = None,
    result_overrides: dict[str, Path] | None = None,
) -> CampaignMetricsExportResult:
    """Write unified and per-campaign partition-aware metric CSV exports."""
    base = repo_root or Path(__file__).resolve().parents[2]
    out = (output_dir or DEFAULT_OUTPUT_DIR).resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows = build_campaign_metrics_by_partition_rows(
        repo_root=base,
        result_overrides=result_overrides,
    )
    if not rows:
        msg = "No partition metric rows could be built from campaign exports"
        raise CampaignMetricsExportError(msg)

    csv_path = out / "metrics_by_partition.csv"
    _write_csv(csv_path, rows)

    c1_rows = [row for row in rows if row.campaign == "C1-baseline-repair"]
    rq3_rows = [row for row in rows if row.campaign == "RQ3-localization-ochiai-1k"]
    rq4_rows = [row for row in rows if row.campaign == "RQ4-higher-order-coupling-250"]
    c1_csv = out / "c1_metrics_by_partition.csv"
    rq3_csv = out / "rq3_metrics_by_partition.csv"
    rq4_csv = out / "rq4_metrics_by_partition.csv"
    _write_csv(c1_csv, c1_rows)
    _write_csv(rq3_csv, rq3_rows)
    _write_csv(rq4_csv, rq4_rows)

    manifest = {
        "zenodo_doi": ZENODO_DOI,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "columns": list(METRICS_BY_PARTITION_COLUMNS),
        "row_count": len(rows),
        "constructs": sorted({row.construct for row in rows}),
        "partitions": sorted({row.partition for row in rows}),
        "output_files": [
            "metrics_by_partition.csv",
            "c1_metrics_by_partition.csv",
            "rq3_metrics_by_partition.csv",
            "rq4_metrics_by_partition.csv",
        ],
        "regeneration_commands": [
            "python ../paper1/scripts/generate_campaign_metrics_by_partition_outputs.py",
        ],
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_dir = (paper_export_dir or DEFAULT_PAPER_EXPORT_DIR).resolve()
    paper_dir.mkdir(parents=True, exist_ok=True)
    paper_csv = paper_dir / "metrics_by_partition.csv"
    paper_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    for name, source in (
        ("c1_metrics_by_partition.csv", c1_csv),
        ("rq3_metrics_by_partition.csv", rq3_csv),
        ("rq4_metrics_by_partition.csv", rq4_csv),
    ):
        (paper_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    (paper_dir / "manifest.json").write_text(
        (out / "manifest.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    tables_dir = paper_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    tex_path = tables_dir / "table_construct_metric_partitions.tex"
    tex_path.write_text(render_metrics_by_partition_tex(rows), encoding="utf-8")

    return CampaignMetricsExportResult(
        output_dir=out,
        csv_path=csv_path,
        c1_csv_path=c1_csv,
        rq3_csv_path=rq3_csv,
        rq4_csv_path=rq4_csv,
        tex_path=tex_path,
        paper_csv_path=paper_csv,
    )
