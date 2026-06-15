"""Cross-campaign paired comparison on the pinned RQ4 250-case cohort."""

from __future__ import annotations

import csv
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import _pyplot
from fsmrepairbench.baseline_repair_campaign import RELEASE_LABEL as C1_RELEASE_LABEL
from fsmrepairbench.campaign_partitions import resolve_results_dir
from fsmrepairbench.freeze import sha256_file

DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_1k")
DEFAULT_COHORT_MANIFEST = DEFAULT_DATASET_DIR / "coupling_campaign_250.txt"
DEFAULT_OUTPUT_DIR = Path("results/campaign_paired_comparison")
DEFAULT_PAPER_EXPORT_DIR = Path("../paper1/results/campaign_paired_comparison")
ZENODO_DOI = "10.5281/zenodo.20602528"
C1_TOOL_ID = "baseline_missing_transition"
RQ4_REPAIR_ENGINE = "missing-transition"

PAIRED_CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "mutation_operator",
    "complexity_tier",
    "c1_oracle_detected",
    "c1_faulty_bpr",
    "c1_bpr_delta_pre_repair",
    "c1_initial_bpr",
    "c1_final_bpr",
    "c1_repair_delta_bpr",
    "c1_complete_repair",
    "c1_effective_repair",
    "rq4_fo_fault_detected",
    "rq4_fo_bpr_delta",
    "rq4_fo_complete_repair",
    "rq4_fo_effective_repair",
    "rq4_fo_repair_delta_bpr",
    "rq4_ho_mutation_order",
    "rq4_ho_fault_detected",
    "rq4_ho_bpr_delta",
    "rq4_ho_complete_repair",
    "rq4_ho_effective_repair",
    "rq4_ho_repair_delta_bpr",
    "rq3_transition_localizable",
    "rq3_top1_hit",
    "detection_gained_fo_to_ho",
    "repair_complete_lost_fo_to_ho",
)

SUMMARY_COLUMNS: tuple[str, ...] = (
    "campaign_lane",
    "construct",
    "metric",
    "partition",
    "n_cases",
    "value",
)

LANE_LABELS: dict[str, str] = {
    "c1_missing_transition": "C1 missing-transition",
    "rq4_first_order": "RQ4 FO",
    "rq4_higher_order": "RQ4 HO (max order)",
    "rq3_ochiai": "RQ3 Ochiai",
}


class CampaignPairedComparisonError(ValueError):
    """Raised when paired cross-campaign comparison inputs are invalid."""


@dataclass(frozen=True)
class CampaignPairedComparisonResult:
    output_dir: Path
    case_csv_path: Path
    summary_csv_path: Path
    transitions_csv_path: Path
    figure_path: Path
    tex_path: Path
    manifest_path: Path
    paper_output_dir: Path | None = None


def load_paired_cohort_case_ids(
    cohort_manifest: Path | None = None,
) -> list[str]:
    path = (cohort_manifest or DEFAULT_COHORT_MANIFEST).resolve()
    if not path.is_file():
        msg = f"Paired cohort manifest not found: {path}"
        raise CampaignPairedComparisonError(msg)
    case_ids = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not case_ids:
        msg = f"Paired cohort manifest is empty: {path}"
        raise CampaignPairedComparisonError(msg)
    return case_ids


def _load_c1_rows(path: Path) -> dict[str, dict[str, str]]:
    rows: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        if row["tool_id"] != C1_TOOL_ID:
            continue
        rows[row["case_id"]] = row
    return rows


def _load_rq3_rows(
    per_case_path: Path,
    audit_path: Path,
) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    per_case = {row["case_id"]: row for row in csv.DictReader(per_case_path.open(encoding="utf-8"))}
    audit = {row["case_id"]: row for row in csv.DictReader(audit_path.open(encoding="utf-8"))}
    return per_case, audit


def _load_rq4_rows(path: Path) -> tuple[dict[str, dict[str, str]], dict[str, dict[str, str]]]:
    first_order: dict[str, dict[str, str]] = {}
    higher_order: dict[str, dict[str, str]] = {}
    for row in csv.DictReader(path.open(encoding="utf-8")):
        source_id = row["source_case_id"]
        order = int(row["mutation_order"])
        if order == 1:
            first_order[source_id] = row
            continue
        previous = higher_order.get(source_id)
        if previous is None or order > int(previous["mutation_order"]):
            higher_order[source_id] = row
    return first_order, higher_order


def _as_bool(raw: str) -> bool:
    return str(raw).strip().lower() in {"1", "true", "t", "yes"}


def _mean(values: Sequence[float]) -> float:
    if not values:
        return float("nan")
    return statistics.fmean(values)


def _rate(flags: Sequence[bool]) -> float:
    if not flags:
        return float("nan")
    return sum(1 for flag in flags if flag) / len(flags)


def build_paired_case_rows(
    *,
    case_ids: Sequence[str],
    c1_rows: dict[str, dict[str, str]],
    rq3_rows: dict[str, dict[str, str]],
    rq3_audit: dict[str, dict[str, str]],
    rq4_first_order: dict[str, dict[str, str]],
    rq4_higher_order: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    paired: list[dict[str, Any]] = []
    missing: list[str] = []
    for case_id in case_ids:
        c1 = c1_rows.get(case_id)
        fo = rq4_first_order.get(case_id)
        ho = rq4_higher_order.get(case_id)
        if c1 is None or fo is None or ho is None:
            missing.append(case_id)
            continue
        rq3 = rq3_rows.get(case_id, {})
        audit = rq3_audit.get(case_id, {})
        fo_detected = _as_bool(fo["fault_detected"])
        ho_detected = _as_bool(ho["fault_detected"])
        localizable = audit.get("ground_truth_localizable") == "True"
        paired.append(
            {
                "case_id": case_id,
                "mutation_operator": c1["mutation_operator"],
                "complexity_tier": c1["complexity_tier"],
                "c1_oracle_detected": _as_bool(c1["oracle_detected"]),
                "c1_faulty_bpr": float(c1["faulty_bpr"]),
                "c1_bpr_delta_pre_repair": float(c1["bpr_delta_pre_repair"]),
                "c1_initial_bpr": float(c1["initial_bpr"]),
                "c1_final_bpr": float(c1["final_bpr"]),
                "c1_repair_delta_bpr": float(c1["delta_bpr"]),
                "c1_complete_repair": _as_bool(c1["complete_repair"]),
                "c1_effective_repair": _as_bool(c1["effective_repair"]),
                "rq4_fo_fault_detected": fo_detected,
                "rq4_fo_bpr_delta": float(fo["bpr_delta"]),
                "rq4_fo_complete_repair": _as_bool(fo["complete_repair"]),
                "rq4_fo_effective_repair": _as_bool(fo["effective_repair"]),
                "rq4_fo_repair_delta_bpr": float(fo["repair_delta_bpr"]),
                "rq4_ho_mutation_order": int(ho["mutation_order"]),
                "rq4_ho_fault_detected": ho_detected,
                "rq4_ho_bpr_delta": float(ho["bpr_delta"]),
                "rq4_ho_complete_repair": _as_bool(ho["complete_repair"]),
                "rq4_ho_effective_repair": _as_bool(ho["effective_repair"]),
                "rq4_ho_repair_delta_bpr": float(ho["repair_delta_bpr"]),
                "rq3_transition_localizable": localizable,
                "rq3_top1_hit": _as_bool(rq3.get("top1_hit", "False")),
                "detection_gained_fo_to_ho": (not fo_detected) and ho_detected,
                "repair_complete_lost_fo_to_ho": _as_bool(fo["complete_repair"]) and not _as_bool(
                    ho["complete_repair"]
                ),
            }
        )
    if missing:
        msg = f"Missing paired campaign rows for {len(missing)} cohort cases (first: {missing[0]})"
        raise CampaignPairedComparisonError(msg)
    return paired


def _append_summary(
    rows: list[dict[str, Any]],
    *,
    campaign_lane: str,
    construct: str,
    metric: str,
    partition: str,
    n_cases: int,
    value: float,
) -> None:
    rows.append(
        {
            "campaign_lane": campaign_lane,
            "construct": construct,
            "metric": metric,
            "partition": partition,
            "n_cases": n_cases,
            "value": round(value, 6),
        }
    )


def compute_paired_summary_rows(case_rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Aggregate headline metrics for each campaign lane and partition."""
    summary: list[dict[str, Any]] = []
    cohort = list(case_rows)
    detectable = [row for row in cohort if row["c1_oracle_detected"]]
    localizable_detectable = [
        row for row in detectable if row["rq3_transition_localizable"]
    ]

    lane_specs: tuple[tuple[str, dict[str, Any]], ...] = (
        (
            "c1_missing_transition",
            {
                "detected": lambda row: row["c1_oracle_detected"],
                "bpr_delta_pre": lambda row: row["c1_bpr_delta_pre_repair"],
                "repair_delta": lambda row: row["c1_repair_delta_bpr"],
                "complete": lambda row: row["c1_complete_repair"],
                "effective": lambda row: row["c1_effective_repair"],
            },
        ),
        (
            "rq4_first_order",
            {
                "detected": lambda row: row["rq4_fo_fault_detected"],
                "bpr_delta_pre": lambda row: row["rq4_fo_bpr_delta"],
                "repair_delta": lambda row: row["rq4_fo_repair_delta_bpr"],
                "complete": lambda row: row["rq4_fo_complete_repair"],
                "effective": lambda row: row["rq4_fo_effective_repair"],
            },
        ),
        (
            "rq4_higher_order",
            {
                "detected": lambda row: row["rq4_ho_fault_detected"],
                "bpr_delta_pre": lambda row: row["rq4_ho_bpr_delta"],
                "repair_delta": lambda row: row["rq4_ho_repair_delta_bpr"],
                "complete": lambda row: row["rq4_ho_complete_repair"],
                "effective": lambda row: row["rq4_ho_effective_repair"],
            },
        ),
    )

    for partition_name, subset in (
        ("cohort_wide", cohort),
        ("detectable_only", detectable),
    ):
        for lane, accessors in lane_specs:
            if not subset:
                continue
            _append_summary(
                summary,
                campaign_lane=lane,
                construct="detection",
                metric="detection_rate",
                partition=partition_name,
                n_cases=len(subset),
                value=_rate([accessors["detected"](row) for row in subset]),
            )
            _append_summary(
                summary,
                campaign_lane=lane,
                construct="detection",
                metric="mean_bpr_delta_pre_repair",
                partition=partition_name,
                n_cases=len(subset),
                value=_mean([accessors["bpr_delta_pre"](row) for row in subset]),
            )
            _append_summary(
                summary,
                campaign_lane=lane,
                construct="repair",
                metric="mean_repair_delta_bpr",
                partition=partition_name,
                n_cases=len(subset),
                value=_mean([accessors["repair_delta"](row) for row in subset]),
            )
            _append_summary(
                summary,
                campaign_lane=lane,
                construct="repair",
                metric="complete_repair_rate",
                partition=partition_name,
                n_cases=len(subset),
                value=_rate([accessors["complete"](row) for row in subset]),
            )
            _append_summary(
                summary,
                campaign_lane=lane,
                construct="repair",
                metric="effective_repair_rate",
                partition=partition_name,
                n_cases=len(subset),
                value=_rate([accessors["effective"](row) for row in subset]),
            )

    if localizable_detectable:
        _append_summary(
            summary,
            campaign_lane="rq3_ochiai",
            construct="localization",
            metric="top_1_hit_rate",
            partition="transition_localizable_gt",
            n_cases=len(localizable_detectable),
            value=_rate([row["rq3_top1_hit"] for row in localizable_detectable]),
        )
        _append_summary(
            summary,
            campaign_lane="c1_missing_transition",
            construct="repair",
            metric="complete_repair_rate",
            partition="transition_localizable_gt",
            n_cases=len(localizable_detectable),
            value=_rate([row["c1_complete_repair"] for row in localizable_detectable]),
        )
        _append_summary(
            summary,
            campaign_lane="rq4_higher_order",
            construct="repair",
            metric="complete_repair_rate",
            partition="transition_localizable_gt",
            n_cases=len(localizable_detectable),
            value=_rate([row["rq4_ho_complete_repair"] for row in localizable_detectable]),
        )

    _append_summary(
        summary,
        campaign_lane="rq4_higher_order",
        construct="detection",
        metric="detection_gain_fo_to_ho_rate",
        partition="cohort_wide",
        n_cases=len(cohort),
        value=_rate([row["detection_gained_fo_to_ho"] for row in cohort]),
    )
    _append_summary(
        summary,
        campaign_lane="rq4_higher_order",
        construct="repair",
        metric="complete_repair_loss_fo_to_ho_rate",
        partition="cohort_wide",
        n_cases=len(cohort),
        value=_rate([row["repair_complete_lost_fo_to_ho"] for row in cohort]),
    )
    return summary


def compute_detection_repair_transitions(
    case_rows: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Per-case FO→HO transitions for detectability and repair on the paired pin."""
    transitions: list[dict[str, Any]] = []
    for row in case_rows:
        transitions.append(
            {
                "case_id": row["case_id"],
                "mutation_operator": row["mutation_operator"],
                "fo_detected": row["rq4_fo_fault_detected"],
                "ho_detected": row["rq4_ho_fault_detected"],
                "fo_bpr_delta": row["rq4_fo_bpr_delta"],
                "ho_bpr_delta": row["rq4_ho_bpr_delta"],
                "delta_bpr_change_ho_minus_fo": row["rq4_ho_bpr_delta"] - row["rq4_fo_bpr_delta"],
                "fo_complete_repair": row["rq4_fo_complete_repair"],
                "ho_complete_repair": row["rq4_ho_complete_repair"],
                "detection_gained_fo_to_ho": row["detection_gained_fo_to_ho"],
                "repair_complete_lost_fo_to_ho": row["repair_complete_lost_fo_to_ho"],
            }
        )
    return transitions


def _summary_lookup(
    rows: Sequence[dict[str, Any]],
) -> dict[tuple[str, str, str], dict[str, Any]]:
    return {
        (row["campaign_lane"], row["metric"], row["partition"]): row
        for row in rows
    }


def write_paired_comparison_figure(
    path: Path,
    *,
    summary_rows: Sequence[dict[str, Any]],
    case_rows: Sequence[dict[str, Any]],
) -> Path:
    """Write a four-panel figure comparing C1, RQ4 FO/HO, and RQ3 on the paired pin."""
    plt = _pyplot()
    import numpy as np

    lookup = _summary_lookup(summary_rows)
    lanes = ("c1_missing_transition", "rq4_first_order", "rq4_higher_order")
    lane_titles = [LANE_LABELS[lane].replace(" (max order)", "") for lane in lanes]
    colors = ("#4472C4", "#ED7D31", "#A5A5A5")

    fig, axes = plt.subplots(2, 2, figsize=(11.0, 8.0))

    def _metric_values(metric: str, partition: str) -> list[float]:
        values: list[float] = []
        for lane in lanes:
            row = lookup.get((lane, metric, partition))
            values.append(float(row["value"]) if row else float("nan"))
        return values

    x = np.arange(len(lanes))
    width = 0.35

    axis = axes[0, 0]
    cohort_vals = [value * 100.0 for value in _metric_values("detection_rate", "cohort_wide")]
    detect_vals = [value * 100.0 for value in _metric_values("detection_rate", "detectable_only")]
    axis.bar(x - width / 2, cohort_vals, width, label="cohort-wide ($n=250$)", color=colors)
    axis.bar(x + width / 2, detect_vals, width, label="detectable-only ($n=118$)", color="#70AD47")
    axis.set_xticks(x)
    axis.set_xticklabels(lane_titles, fontsize=8)
    axis.set_ylabel("Detection rate (%)")
    axis.set_title("Detectability on the same 250-case pin")
    axis.set_ylim(0, 105)
    axis.legend(fontsize=7)

    axis = axes[0, 1]
    cohort_vals = [value * 100.0 for value in _metric_values("complete_repair_rate", "cohort_wide")]
    detect_vals = [value * 100.0 for value in _metric_values("complete_repair_rate", "detectable_only")]
    axis.bar(x - width / 2, cohort_vals, width, label="cohort-wide", color=colors)
    axis.bar(x + width / 2, detect_vals, width, label="detectable-only", color="#70AD47")
    axis.set_xticks(x)
    axis.set_xticklabels(lane_titles, fontsize=8)
    axis.set_ylabel("Complete repair (%)")
    axis.set_title(f"Repair ({RQ4_REPAIR_ENGINE} engine on RQ4)")
    axis.set_ylim(0, 105)
    axis.legend(fontsize=7)

    axis = axes[1, 0]
    fo_ho_x = np.arange(2)
    fo_vals = [
        lookup[("rq4_first_order", "mean_bpr_delta_pre_repair", "cohort_wide")]["value"],
        lookup[("rq4_higher_order", "mean_bpr_delta_pre_repair", "cohort_wide")]["value"],
    ]
    axis.bar(fo_ho_x, fo_vals, color=["#ED7D31", "#A5A5A5"])
    axis.set_xticks(fo_ho_x)
    axis.set_xticklabels(["RQ4 FO", "RQ4 HO"], fontsize=8)
    axis.set_ylabel("Mean pre-repair $\\Delta$BPR")
    axis.set_title("Fault exposure rises under HO coupling")
    for index, value in enumerate(fo_vals):
        axis.text(index, value + 0.01, f"{value:.3f}", ha="center", fontsize=8)

    axis = axes[1, 1]
    loc_row = lookup.get(("rq3_ochiai", "top_1_hit_rate", "transition_localizable_gt"))
    loc_n = int(loc_row["n_cases"]) if loc_row else 0
    loc_rate = float(loc_row["value"]) * 100.0 if loc_row else 0.0
    c1_loc_repair = lookup.get(
        ("c1_missing_transition", "complete_repair_rate", "transition_localizable_gt")
    )
    ho_loc_repair = lookup.get(
        ("rq4_higher_order", "complete_repair_rate", "transition_localizable_gt")
    )
    labels = [
        f"RQ3 top-1\n($n={loc_n}$)",
        f"C1 complete\n($n={loc_n}$)",
        f"RQ4 HO complete\n($n={loc_n}$)",
    ]
    values = [
        loc_rate,
        float(c1_loc_repair["value"]) * 100.0 if c1_loc_repair else 0.0,
        float(ho_loc_repair["value"]) * 100.0 if ho_loc_repair else 0.0,
    ]
    axis.bar(np.arange(3), values, color=["#FFC000", "#4472C4", "#A5A5A5"])
    axis.set_xticks(np.arange(3))
    axis.set_xticklabels(labels, fontsize=8)
    axis.set_ylabel("Rate (%)")
    axis.set_title("Localization vs repair on localizable detectable subset")
    axis.set_ylim(0, max(values + [5.0]) * 1.15)

    gain_rate = lookup[("rq4_higher_order", "detection_gain_fo_to_ho_rate", "cohort_wide")]["value"]
    loss_rate = lookup[("rq4_higher_order", "complete_repair_loss_fo_to_ho_rate", "cohort_wide")]["value"]
    fig.suptitle(
        "Cross-campaign paired comparison on coupling pin "
        f"($n=250$; FO→HO detection gain {gain_rate * 100:.1f}\\%; "
        f"complete-repair loss {loss_rate * 100:.1f}\\%)",
        fontsize=11,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return path


def render_paired_comparison_tex(summary_rows: Sequence[dict[str, Any]]) -> str:
    lookup = _summary_lookup(summary_rows)
    headline = [
        ("c1_missing_transition", "detection_rate", "cohort_wide"),
        ("c1_missing_transition", "detection_rate", "detectable_only"),
        ("c1_missing_transition", "complete_repair_rate", "cohort_wide"),
        ("c1_missing_transition", "complete_repair_rate", "detectable_only"),
        ("rq4_first_order", "detection_rate", "cohort_wide"),
        ("rq4_first_order", "complete_repair_rate", "detectable_only"),
        ("rq4_higher_order", "detection_rate", "cohort_wide"),
        ("rq4_higher_order", "mean_bpr_delta_pre_repair", "cohort_wide"),
        ("rq4_higher_order", "complete_repair_rate", "detectable_only"),
        ("rq3_ochiai", "top_1_hit_rate", "transition_localizable_gt"),
    ]
    lines = [
        "% Auto-generated from campaign_paired_comparison",
        "\\begin{table}[t]",
        "\\caption{Cross-campaign metrics on the paired RQ4 coupling pin "
        "(\\texttt{coupling\\_campaign\\_250.txt}; $n=250$ matched \\texttt{source\\_case\\_id} records). "
        f"HO coupling raises max-order detectability to "
        f"{lookup[('rq4_higher_order', 'detection_rate', 'cohort_wide')]['value'] * 100:.1f}\\% "
        f"while detectable-only complete repair falls from "
        f"{lookup[('rq4_first_order', 'complete_repair_rate', 'detectable_only')]['value'] * 100:.1f}\\% "
        f"to {lookup[('rq4_higher_order', 'complete_repair_rate', 'detectable_only')]['value'] * 100:.1f}\\%. "
        "RQ3 Ochiai top-1 is reported on the transition-localizable detectable subset ($n=90$).}",
        "\\label{tab:paired-cohort-cross-campaign}",
        "\\scriptsize",
        "\\begin{tabular}{@{}lllrr@{}}",
        "\\toprule",
        "Lane & Metric & Partition & $n$ & Value \\\\",
        "\\midrule",
    ]
    for lane, metric, partition in headline:
        row = lookup.get((lane, metric, partition))
        if row is None:
            continue
        value = float(row["value"])
        if metric.endswith("_rate"):
            value_str = f"{value * 100:.1f}\\%"
        else:
            value_str = f"{value:.3f}"
        lane_tex = LANE_LABELS[lane].replace("_", "\\_")
        lines.append(
            f"{lane_tex} & {metric.replace('_', '\\_')} & {partition.replace('_', '\\_')} & "
            f"{row['n_cases']} & {value_str} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)


def _write_csv(path: Path, rows: Sequence[dict[str, Any]], columns: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            payload = {column: row.get(column, "") for column in columns}
            writer.writerow(payload)


def export_campaign_paired_comparison(
    *,
    repo_root: Path | None = None,
    cohort_manifest: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    result_overrides: dict[str, Path] | None = None,
) -> CampaignPairedComparisonResult:
    """Build paired cross-campaign exports for C1, RQ3, and RQ4 on the 250-case pin."""
    base = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    cohort_path = (cohort_manifest or base / DEFAULT_COHORT_MANIFEST).resolve()
    case_ids = load_paired_cohort_case_ids(cohort_path)

    c1_dir = resolve_results_dir("C1-baseline-repair", repo_root=base, overrides=result_overrides)
    rq3_dir = resolve_results_dir("RQ3-localization", repo_root=base, overrides=result_overrides)
    rq4_dir = resolve_results_dir("RQ4-coupling", repo_root=base, overrides=result_overrides)

    c1_rows = _load_c1_rows(c1_dir / "per_case_results.csv")
    rq3_rows, rq3_audit = _load_rq3_rows(
        rq3_dir / "per_case_results.csv",
        rq3_dir / "localizability_audit.csv",
    )
    rq4_first_order, rq4_higher_order = _load_rq4_rows(rq4_dir / "per_case_results.csv")

    paired_cases = build_paired_case_rows(
        case_ids=case_ids,
        c1_rows=c1_rows,
        rq3_rows=rq3_rows,
        rq3_audit=rq3_audit,
        rq4_first_order=rq4_first_order,
        rq4_higher_order=rq4_higher_order,
    )
    summary_rows = compute_paired_summary_rows(paired_cases)
    transition_rows = compute_detection_repair_transitions(paired_cases)

    out = (output_dir or base / DEFAULT_OUTPUT_DIR).resolve()
    figures_dir = out / "figures"
    tables_dir = out / "tables"
    figures_dir.mkdir(parents=True, exist_ok=True)
    tables_dir.mkdir(parents=True, exist_ok=True)

    case_csv = out / "paired_cohort_case_metrics.csv"
    summary_csv = out / "paired_cohort_summary.csv"
    transitions_csv = out / "paired_fo_ho_transitions.csv"
    figure_path = figures_dir / "paired_cohort_cross_campaign.png"
    tex_path = tables_dir / "table_paired_cohort_cross_campaign.tex"

    _write_csv(case_csv, paired_cases, PAIRED_CASE_COLUMNS)
    _write_csv(summary_csv, summary_rows, SUMMARY_COLUMNS)
    _write_csv(
        transitions_csv,
        transition_rows,
        tuple(transition_rows[0].keys()) if transition_rows else ("case_id",),
    )
    write_paired_comparison_figure(
        figure_path,
        summary_rows=summary_rows,
        case_rows=paired_cases,
    )
    tex_path.write_text(render_paired_comparison_tex(summary_rows), encoding="utf-8")

    manifest = {
        "zenodo_doi": ZENODO_DOI,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "paired_cohort_manifest": cohort_path.name,
        "paired_cohort_sha256": sha256_file(cohort_path),
        "paired_case_count": len(paired_cases),
        "campaign_lanes": list(LANE_LABELS.keys()),
        "c1_release_label": C1_RELEASE_LABEL,
        "rq4_repair_engine": RQ4_REPAIR_ENGINE,
        "output_files": [
            "paired_cohort_case_metrics.csv",
            "paired_cohort_summary.csv",
            "paired_fo_ho_transitions.csv",
            "figures/paired_cohort_cross_campaign.png",
            "tables/table_paired_cohort_cross_campaign.tex",
        ],
        "regeneration_commands": [
            "python ../paper1/scripts/generate_campaign_paired_comparison_outputs.py",
        ],
    }
    manifest_path = out / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_dir: Path | None = None
    if paper_export_dir is not None:
        import shutil

        paper_dir = paper_export_dir.resolve()
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
        shutil.copytree(out, paper_dir)

    return CampaignPairedComparisonResult(
        output_dir=out,
        case_csv_path=case_csv,
        summary_csv_path=summary_csv,
        transitions_csv_path=transitions_csv,
        figure_path=figure_path,
        tex_path=tex_path,
        manifest_path=manifest_path,
        paper_output_dir=paper_dir,
    )
