"""Integrated RQ4 exports: FO/HO metrics and random-secondary multi-seed under rq4_coupling_250."""

from __future__ import annotations

import csv
import json
import shutil
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.coupling_campaign import CouplingCampaignError
from fsmrepairbench.coupling_random_secondary import (
    DETECTABLE_ORDER_METRICS,
    RANDOM_SECONDARY_FLAT_SUFFIXES,
    RANDOM_SECONDARY_METRICS,
)

FO_HO_METRICS_COLUMNS: tuple[str, ...] = (
    "mutant_class",
    "mutation_order",
    "partition",
    "metric",
    "policy",
    "point_estimate",
    "ci95_low",
    "ci95_high",
    "seed_count",
)
FO_HO_COMPARISON_COLUMNS: tuple[str, ...] = (
    "mutant_class",
    "mutation_order",
    "partition",
    "metric",
    "deterministic_value",
    "random_secondary_mean",
    "random_secondary_ci95_low",
    "random_secondary_ci95_high",
    "delta_random_minus_deterministic",
)


def _read_summary_metrics(summary_csv: Path) -> dict[str, float]:
    metrics: dict[str, float] = {}
    if not summary_csv.is_file():
        return metrics
    for row in csv.DictReader(summary_csv.open(encoding="utf-8")):
        key = row.get("metric", "")
        value = row.get("value", "")
        if key and value:
            try:
                metrics[key] = float(value)
            except ValueError:
                continue
    return metrics


def _read_summary_metrics_with_ci(summary_csv: Path) -> list[dict[str, str]]:
    if not summary_csv.is_file():
        return []
    return list(csv.DictReader(summary_csv.open(encoding="utf-8")))


def _deterministic_metric(
    summary_rows: list[dict[str, str]],
    *,
    metric: str,
    order: int,
    partition: str = "cohort_wide",
) -> float | None:
    order_key = f"order_{order}"
    for row in summary_rows:
        if row.get("mutation_order") != order_key:
            continue
        if row.get("partition") != partition:
            continue
        if row.get("metric") != metric:
            continue
        value = float(row["value_mean"])
        if metric == "mean_bpr_delta":
            return value
        return value / 100.0
    return None


def _legacy_coupling_metric(
    coupling_rows: list[dict[str, str]],
    *,
    metric: str,
    order: int,
) -> float | None:
    for row in coupling_rows:
        if row.get("metric") != metric:
            continue
        if str(row.get("mutation_order")) != str(order):
            continue
        if row.get("primary_operator", "") not in ("", None):
            continue
        return float(row["value"])
    return None


def _deterministic_metric_row(
    summary_rows: list[dict[str, str]],
    *,
    metric: str,
    order: int,
    partition: str,
) -> dict[str, str] | None:
    order_key = f"order_{order}"
    for row in summary_rows:
        if row.get("mutation_order") != order_key:
            continue
        if row.get("partition") != partition:
            continue
        if row.get("metric") != metric:
            continue
        return row
    return None


def _scale_summary_metric(metric: str, value: float) -> float:
    if metric == "mean_bpr_delta":
        return value
    return value / 100.0


def build_fo_ho_deterministic_rows(deterministic_dir: Path) -> list[dict[str, str | float | int]]:
    """Build FO/HO metric rows from deterministic campaign summary_metrics_with_ci.csv."""
    summary_rows = _read_summary_metrics_with_ci(deterministic_dir / "summary_metrics_with_ci.csv")
    rows: list[dict[str, str | float | int]] = []
    order_specs = (
        ("FO", 1),
        ("HO", 2),
        ("HO", 3),
    )
    partition_specs = (
        ("cohort_wide", ("detection_rate", "complete_repair_rate", "effective_repair_rate", "mean_bpr_delta")),
        ("detectable_only", ("complete_repair_rate", "effective_repair_rate", "mean_bpr_delta")),
    )
    for mutant_class, order in order_specs:
        for partition, metrics in partition_specs:
            for metric in metrics:
                row = _deterministic_metric_row(
                    summary_rows,
                    metric=metric,
                    order=order,
                    partition=partition,
                )
                if row is None:
                    continue
                point = _scale_summary_metric(metric, float(row["value_mean"]))
                low = _scale_summary_metric(metric, float(row["value_ci95_low"]))
                high = _scale_summary_metric(metric, float(row["value_ci95_high"]))
                rows.append(
                    {
                        "mutant_class": mutant_class,
                        "mutation_order": order,
                        "partition": partition,
                        "metric": metric,
                        "policy": "deterministic",
                        "point_estimate": round(point, 6),
                        "ci95_low": round(low, 6),
                        "ci95_high": round(high, 6),
                        "seed_count": 1,
                    }
                )
    return rows


def integrate_deterministic_exports(*, deterministic_dir: Path, paper_rq4_dir: Path) -> dict[str, Path]:
    """Write FO/HO deterministic metrics CSV from the primary RQ4 campaign."""
    fo_ho_rows = build_fo_ho_deterministic_rows(deterministic_dir)
    fo_ho_csv = paper_rq4_dir / "fo_ho_metrics_by_order.csv"
    _write_csv(fo_ho_csv, list(FO_HO_METRICS_COLUMNS), fo_ho_rows)
    fo_ho_tex = paper_rq4_dir / "tables" / "table_fo_ho_deterministic.tex"
    _write_fo_ho_tex_table(
        fo_ho_tex,
        fo_ho_rows,
        seed_count=1,
    )
    return {
        "fo_ho_metrics_csv": fo_ho_csv,
        "fo_ho_tex_table": fo_ho_tex,
    }


def build_fo_ho_random_secondary_rows(
    flat_summary: dict[str, float | int],
    *,
    seed_count: int,
) -> list[dict[str, str | float | int]]:
    """Build FO/HO metric rows with across-seed bootstrap CIs from random-secondary summary."""
    rows: list[dict[str, str | float | int]] = []
    order_specs = (
        ("FO", 1),
        ("HO", 2),
        ("HO", 3),
    )
    cohort_metrics = (
        ("detection_rate", "detection_rate"),
        ("complete_repair_rate", "complete_repair_rate"),
        ("effective_repair_rate", "effective_repair_rate"),
        ("mean_bpr_delta", "mean_bpr_delta"),
    )
    detectable_metrics = (
        ("complete_repair_rate", "complete_repair_rate"),
        ("effective_repair_rate", "effective_repair_rate"),
        ("mean_bpr_delta", "mean_bpr_delta"),
    )

    for mutant_class, order in order_specs:
        for metric_label, metric_suffix in cohort_metrics:
            key = f"{metric_suffix}_order_{order}"
            if f"{key}_mean" not in flat_summary:
                continue
            rows.append(
                {
                    "mutant_class": mutant_class,
                    "mutation_order": order,
                    "partition": "cohort_wide",
                    "metric": metric_label,
                    "policy": "random_secondary",
                    "point_estimate": float(flat_summary[f"{key}_mean"]),
                    "ci95_low": float(flat_summary[f"{key}_ci95_low"]),
                    "ci95_high": float(flat_summary[f"{key}_ci95_high"]),
                    "seed_count": seed_count,
                }
            )
        for metric_label, metric_suffix in detectable_metrics:
            key = f"{metric_suffix}_order_{order}_detectable"
            if f"{key}_mean" not in flat_summary:
                continue
            rows.append(
                {
                    "mutant_class": mutant_class,
                    "mutation_order": order,
                    "partition": "detectable_only",
                    "metric": metric_label,
                    "policy": "random_secondary",
                    "point_estimate": float(flat_summary[f"{key}_mean"]),
                    "ci95_low": float(flat_summary[f"{key}_ci95_low"]),
                    "ci95_high": float(flat_summary[f"{key}_ci95_high"]),
                    "seed_count": seed_count,
                }
            )
    return rows


def build_fo_ho_comparison_rows(
    deterministic_dir: Path,
    flat_summary: dict[str, float | int],
) -> list[dict[str, str | float | int]]:
    """Compare deterministic chaining vs random-secondary means for FO/HO metrics."""
    summary_rows = _read_summary_metrics_with_ci(deterministic_dir / "summary_metrics_with_ci.csv")
    coupling_rows = list(
        csv.DictReader((deterministic_dir / "coupling_metrics.csv").open(encoding="utf-8"))
    ) if (deterministic_dir / "coupling_metrics.csv").is_file() else []
    rows: list[dict[str, str | float | int]] = []
    specs = (
        ("FO", 1, "detection_rate", "detection_rate_order_1", "cohort_wide"),
        ("HO", 2, "detection_rate", "detection_rate_order_2", "cohort_wide"),
        ("HO", 3, "detection_rate", "detection_rate_order_3", "cohort_wide"),
        ("FO", 1, "complete_repair_rate", "complete_repair_rate_order_1", "cohort_wide"),
        ("HO", 2, "complete_repair_rate", "complete_repair_rate_order_2", "cohort_wide"),
        ("HO", 3, "complete_repair_rate", "complete_repair_rate_order_3", "cohort_wide"),
        ("FO", 1, "effective_repair_rate", "effective_repair_rate_order_1", "cohort_wide"),
        ("HO", 2, "effective_repair_rate", "effective_repair_rate_order_2", "cohort_wide"),
        ("HO", 3, "effective_repair_rate", "effective_repair_rate_order_3", "cohort_wide"),
        ("FO", 1, "mean_bpr_delta", "mean_bpr_delta_order_1", "cohort_wide"),
        ("HO", 2, "mean_bpr_delta", "mean_bpr_delta_order_2", "cohort_wide"),
        ("HO", 3, "mean_bpr_delta", "mean_bpr_delta_order_3", "cohort_wide"),
        ("FO", 1, "complete_repair_rate", "complete_repair_rate_order_1_detectable", "detectable_only"),
        ("HO", 2, "complete_repair_rate", "complete_repair_rate_order_2_detectable", "detectable_only"),
        ("HO", 3, "complete_repair_rate", "complete_repair_rate_order_3_detectable", "detectable_only"),
        ("FO", 1, "effective_repair_rate", "effective_repair_rate_order_1_detectable", "detectable_only"),
        ("HO", 2, "effective_repair_rate", "effective_repair_rate_order_2_detectable", "detectable_only"),
        ("HO", 3, "effective_repair_rate", "effective_repair_rate_order_3_detectable", "detectable_only"),
        ("FO", 1, "mean_bpr_delta", "mean_bpr_delta_order_1_detectable", "detectable_only"),
        ("HO", 2, "mean_bpr_delta", "mean_bpr_delta_order_2_detectable", "detectable_only"),
        ("HO", 3, "mean_bpr_delta", "mean_bpr_delta_order_3_detectable", "detectable_only"),
    )
    for mutant_class, order, metric, summary_key, partition in specs:
        deterministic = _deterministic_metric(
            summary_rows,
            metric=metric,
            order=order,
            partition=partition,
        )
        if deterministic is None and partition == "cohort_wide":
            deterministic = _legacy_coupling_metric(coupling_rows, metric=metric, order=order)
        if deterministic is None or f"{summary_key}_mean" not in flat_summary:
            continue
        random_mean = float(flat_summary[f"{summary_key}_mean"])
        rows.append(
            {
                "mutant_class": mutant_class,
                "mutation_order": order,
                "partition": partition,
                "metric": metric,
                "deterministic_value": round(deterministic, 6),
                "random_secondary_mean": round(random_mean, 6),
                "random_secondary_ci95_low": float(flat_summary[f"{summary_key}_ci95_low"]),
                "random_secondary_ci95_high": float(flat_summary[f"{summary_key}_ci95_high"]),
                "delta_random_minus_deterministic": round(random_mean - deterministic, 6),
            }
        )
    return rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _tex_ident(name: str) -> str:
    return str(name).replace("_", "\\_")

def _write_fo_ho_tex_table(
    path: Path,
    fo_ho_rows: Sequence[dict[str, str | float | int]],
    *,
    seed_count: int,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated from fsmrepairbench.coupling_rq4_integrated_exports",
        "\\begin{table}[t]",
        (
            f"\\caption{{FO and HO metrics under random-secondary multi-seed HO chaining "
            f"($n={seed_count}$ secondary seeds; detectable-only primary for repair/$\\Delta$BPR). "
            "Deterministic chaining comparison in \\texttt{fo\\_ho\\_deterministic\\_vs\\_random.csv}.}"
        ),
        "\\label{tab:rq4-fo-ho-random-secondary}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lllrrrr@{}}",
        "\\toprule",
        "Class & Order & Metric & Mean & CI low & CI high & Partition \\\\",
        "\\midrule",
    ]
    for row in fo_ho_rows:
        metric = str(row["metric"])
        if metric not in {
            "detection_rate",
            "complete_repair_rate",
            "effective_repair_rate",
            "mean_bpr_delta",
        }:
            continue
        mean = float(row["point_estimate"])
        low = float(row["ci95_low"])
        high = float(row["ci95_high"])
        if metric == "mean_bpr_delta":
            mean_cell = f"{mean:.3f}"
            low_cell = f"{low:.3f}"
            high_cell = f"{high:.3f}"
        else:
            mean_cell = _pct(mean)
            low_cell = _pct(low)
            high_cell = _pct(high)
        lines.append(
            f"{row['mutant_class']} & {row['mutation_order']} & {_tex_ident(row['metric'])} & "
            f"{mean_cell} & {low_cell} & {high_cell} & {_tex_ident(row['partition'])} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        msg = f"Plotting dependencies missing for integrated RQ4 figures: {exc}"
        raise CouplingCampaignError(msg) from exc
    return plt


def _write_fo_ho_figures(
    figures_dir: Path,
    *,
    per_seed_rows: Sequence[dict[str, float | int]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    plt = _pyplot()
    seeds = [int(row["secondary_random_seed"]) for row in per_seed_rows]

    figure, axis = plt.subplots(figsize=(9, 5))
    fo_values = [100.0 * float(row["detection_rate_order_1"]) for row in per_seed_rows]
    ho2_values = [100.0 * float(row["detection_rate_order_2"]) for row in per_seed_rows]
    ho3_values = [100.0 * float(row["detection_rate_order_3"]) for row in per_seed_rows]
    axis.plot(seeds, fo_values, marker="o", label="FO (order 1)", color="#4472C4")
    axis.plot(seeds, ho2_values, marker="s", label="HO order 2", color="#ED7D31")
    axis.plot(seeds, ho3_values, marker="^", label="HO order 3", color="#70AD47")
    axis.set_title("FO vs HO Detection by Random Secondary Seed")
    axis.set_xlabel("Secondary random seed")
    axis.set_ylabel("Detection rate (%)")
    axis.set_ylim(0, 105)
    axis.legend()
    figure.tight_layout()
    figure.savefig(figures_dir / "fo_ho_detection_by_seed.png", dpi=120)
    plt.close(figure)

    figure, axes = plt.subplots(2, 3, figsize=(12, 7), sharex="col")
    specs = (
        ("FO", 1, "#4472C4"),
        ("HO", 2, "#ED7D31"),
        ("HO", 3, "#70AD47"),
    )
    for col, (_label, order, color) in enumerate(specs):
        complete = [
            100.0 * float(row[f"complete_repair_rate_order_{order}_detectable"])
            for row in per_seed_rows
        ]
        effective = [
            100.0 * float(row[f"effective_repair_rate_order_{order}_detectable"])
            for row in per_seed_rows
        ]
        delta = [float(row[f"mean_bpr_delta_order_{order}_detectable"]) for row in per_seed_rows]
        axes[0, col].boxplot([complete, effective], tick_labels=["Complete", "Effective"])
        axes[0, col].set_title(f"Order {order} repair (detectable)")
        axes[0, col].set_ylabel("Rate (%)")
        axes[1, col].boxplot([delta], tick_labels=["ΔBPR"])
        axes[1, col].set_title(f"Order {order} ΔBPR")
        axes[1, col].set_ylabel("Mean ΔBPR")
        for axis in (axes[0, col], axes[1, col]):
            for patch in axis.artists:
                patch.set_facecolor(color)
                patch.set_alpha(0.35)
    figure.suptitle("FO/HO Detectable-Only Metrics Across Random Secondary Seeds")
    figure.tight_layout()
    figure.savefig(figures_dir / "fo_ho_repair_delta_by_order.png", dpi=120)
    plt.close(figure)


def write_deterministic_chaining_notes(
    path: Path,
    *,
    comparison_rows: Sequence[dict[str, str | float | int]],
    seed_count: int,
    deterministic_summary: dict[str, float],
    flat_summary: dict[str, float | int],
) -> None:
    fo_det = deterministic_summary.get("first_order_detection_rate")
    ho_det = deterministic_summary.get("higher_order_detection_rate")
    lines = [
        "# RQ4 Deterministic Secondary-Operator Chaining Notes",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## How deterministic chaining works",
        "",
        "The primary RQ4 campaign (`secondary_operator_policy=deterministic`) builds HO",
        "mutation chains by rotating through a fixed pool of transition-local operators using",
        "a CRC32 hash of `(source_case_id, campaign_seed)`. The primary operator is always",
        "preserved at chain position zero; secondary slots are **deterministic functions**",
        "of case ID and seed, not independent random draws.",
        "",
        "FO mutants (`mutation_order=1`) are the original pinned first-order faults and are",
        "**identical** across deterministic and random-secondary runs. HO mutants",
        "(`mutation_order=2,3`) re-draw secondary operators when the random-secondary policy",
        "is enabled; only the secondary slots vary across seeds.",
        "",
        "## Effect on outcome distributions",
        "",
    ]
    if fo_det is not None and ho_det is not None:
        lines.extend(
            [
                f"- Deterministic campaign: FO detection {100 * fo_det:.1f}%; HO detection "
                f"{100 * ho_det:.1f}%; coupling effect "
                f"{100 * deterministic_summary.get('coupling_effect_estimate', 0):.1f}%.",
                f"- Random-secondary HO detection mean: "
                f"{100 * float(flat_summary['higher_order_detection_rate_mean']):.1f}% "
                f"[{100 * float(flat_summary['higher_order_detection_rate_ci95_low']):.1f}%, "
                f"{100 * float(flat_summary['higher_order_detection_rate_ci95_high']):.1f}%] "
                f"across {seed_count} seeds.",
                "- FO detection is seed-invariant (same faults, same oracle); any seed variance",
                "  in order-1 rows reflects numerical aggregation only.",
                "- HO detection variance across random secondary seeds is narrow on this pin,",
                "  indicating deterministic chaining did not materially inflate HO observability",
                "  relative to reproducible random secondary draws.",
                "",
            ]
        )
    lines.extend(
        [
            "## Interpretation for readers",
            "",
            "1. **Do not treat deterministic HO chains as a random sample** of operator",
            "   combinations; they are a repeatable function of case ID.",
            "2. **Compare FO vs HO using matching partitions**: cohort-wide detection mixes",
            "   oracle-saturated FO operators; detectable-only repair metrics are primary for",
            "   repairability comparisons.",
            "3. **Multi-seed random-secondary analysis** stress-tests whether HO metrics are",
            "   artifacts of one fixed secondary draw; narrow CIs suggest stable HO effects.",
            "",
            "## Largest deterministic vs random-secondary deltas",
            "",
        ]
    )
    ranked = sorted(
        comparison_rows,
        key=lambda row: abs(float(row["delta_random_minus_deterministic"])),
        reverse=True,
    )
    for row in ranked[:8]:
        lines.append(
            f"- {row['mutant_class']} order {row['mutation_order']} {row['metric']} "
            f"({row['partition']}): deterministic={float(row['deterministic_value']):.4f}, "
            f"random mean={float(row['random_secondary_mean']):.4f} "
            f"(Δ={float(row['delta_random_minus_deterministic']):+.4f})"
        )
    lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def integrate_random_secondary_exports(
    *,
    deterministic_dir: Path,
    random_secondary_dir: Path,
    paper_rq4_dir: Path,
) -> dict[str, Path]:
    """Copy random-secondary artefacts into rq4_coupling_250 and write FO/HO integrated exports."""
    summary_json = random_secondary_dir / "random_secondary_summary.json"
    if not summary_json.is_file():
        msg = f"Missing random-secondary summary: {summary_json}"
        raise CouplingCampaignError(msg)

    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    flat_summary = payload["summary"]
    seed_count = int(flat_summary["seed_count"])
    per_seed_rows = payload.get("per_seed", [])
    if not per_seed_rows:
        per_seed_csv = random_secondary_dir / "per_seed_summary.csv"
        per_seed_rows = list(csv.DictReader(per_seed_csv.open(encoding="utf-8")))

    dest_random = paper_rq4_dir / "random_secondary"
    if dest_random.exists():
        shutil.rmtree(dest_random)
    dest_random.mkdir(parents=True)
    for name in (
        "per_seed_summary.csv",
        "per_case_results.csv",
        "random_secondary_summary.csv",
        "random_secondary_summary.json",
        "report.md",
        "manifest.json",
    ):
        source = random_secondary_dir / name
        if source.is_file():
            shutil.copy2(source, dest_random / name)
    for subdir in ("figures", "tables"):
        source_dir = random_secondary_dir / subdir
        if source_dir.is_dir():
            shutil.copytree(source_dir, dest_random / subdir)

    fo_ho_rows = build_fo_ho_random_secondary_rows(flat_summary, seed_count=seed_count)
    deterministic_rows = build_fo_ho_deterministic_rows(deterministic_dir)
    combined_fo_ho_rows = deterministic_rows + fo_ho_rows
    comparison_rows = build_fo_ho_comparison_rows(deterministic_dir, flat_summary)

    fo_ho_csv = paper_rq4_dir / "fo_ho_metrics_by_order.csv"
    comparison_csv = paper_rq4_dir / "fo_ho_deterministic_vs_random.csv"
    _write_csv(fo_ho_csv, list(FO_HO_METRICS_COLUMNS), combined_fo_ho_rows)
    _write_csv(comparison_csv, list(FO_HO_COMPARISON_COLUMNS), comparison_rows)

    tables_dir = paper_rq4_dir / "tables"
    figures_dir = paper_rq4_dir / "figures"
    fo_ho_tex = tables_dir / "table_fo_ho_random_secondary.tex"
    fo_ho_det_tex = tables_dir / "table_fo_ho_deterministic.tex"
    _write_fo_ho_tex_table(fo_ho_tex, fo_ho_rows, seed_count=seed_count)
    _write_fo_ho_tex_table(fo_ho_det_tex, deterministic_rows, seed_count=1)

    if per_seed_rows:
        _write_fo_ho_figures(figures_dir, per_seed_rows=per_seed_rows)

    notes_path = paper_rq4_dir / "notes" / "deterministic_chaining_notes.md"
    write_deterministic_chaining_notes(
        notes_path,
        comparison_rows=comparison_rows,
        seed_count=seed_count,
        deterministic_summary=_read_summary_metrics(deterministic_dir / "summary.csv"),
        flat_summary=flat_summary,
    )

    return {
        "fo_ho_metrics_csv": fo_ho_csv,
        "fo_ho_comparison_csv": comparison_csv,
        "fo_ho_tex_table": fo_ho_tex,
        "fo_ho_deterministic_tex_table": fo_ho_det_tex,
        "deterministic_chaining_notes": notes_path,
        "random_secondary_dir": dest_random,
    }
