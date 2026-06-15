"""Benchmark health scorecard for FSMRepairBench release audits."""

from __future__ import annotations

import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RELEASE_LABEL = "v0.2.0-analysis"
COHORT_SIZE = 1000
MUTATION_OPERATORS_TOTAL = 19
COMPLEXITY_TIERS_TOTAL = 4

PILLAR_NAMES: tuple[str, ...] = (
    "operator_balance",
    "complexity_tier_balance",
    "oracle_health",
    "localization_coverage",
    "coupling_coverage",
    "taxonomy_coverage",
)

PILLAR_LABELS: dict[str, str] = {
    "operator_balance": "Operator balance",
    "complexity_tier_balance": "Complexity tier balance",
    "oracle_health": "Oracle health",
    "localization_coverage": "Localization coverage",
    "coupling_coverage": "Coupling coverage",
    "taxonomy_coverage": "Taxonomy coverage",
}


@dataclass(frozen=True)
class BenchmarkHealthExportResult:
    """Paths written by :func:`write_benchmark_health_exports`."""

    json_path: Path
    tex_path: Path
    figure_path: Path
    paper_json_path: Path | None = None
    paper_tex_path: Path | None = None
    paper_figure_path: Path | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        msg = f"Missing CSV: {path}"
        raise FileNotFoundError(msg)
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _read_summary(path: Path) -> dict[str, float]:
    summary: dict[str, float] = {}
    for row in _read_csv(path):
        key = row["metric"]
        value = row["value"]
        try:
            summary[key] = float(value)
        except ValueError:
            continue
    return summary


def _balance_score(counts: list[int]) -> dict[str, Any]:
    """Return balance metrics; score in [0,1] where 1 is perfectly balanced."""
    if not counts:
        return {"score": 0.0, "case_counts": counts, "coefficient_of_variation": 1.0}
    if len(counts) == 1:
        return {"score": 1.0, "case_counts": counts, "coefficient_of_variation": 0.0}
    mean = statistics.mean(counts)
    stdev = statistics.pstdev(counts)
    cv = stdev / mean if mean else 1.0
    score = max(0.0, 1.0 - min(1.0, cv / 0.25))
    return {
        "score": round(score, 6),
        "case_counts": counts,
        "min_cases": min(counts),
        "max_cases": max(counts),
        "mean_cases": round(mean, 3),
        "coefficient_of_variation": round(cv, 6),
    }


def compute_benchmark_health(
    *,
    taxonomy_summary_path: Path,
    operator_coverage_path: Path,
    tier_coverage_path: Path,
    v02_summary_path: Path,
    localization_metrics_path: Path,
    coupling_summary_path: Path,
    cohort_size: int = COHORT_SIZE,
) -> dict[str, Any]:
    """Compute benchmark health pillars and composite scorecard."""
    taxonomy_summary = _read_summary(taxonomy_summary_path)
    v02_summary = _read_summary(v02_summary_path)
    coupling_summary = _read_summary(coupling_summary_path)

    operator_rows = [
        row
        for row in _read_csv(operator_coverage_path)
        if row.get("present_in_cohort", "").strip().lower() == "true"
    ]
    operator_counts = [int(row["case_count"]) for row in operator_rows]
    operator_balance = _balance_score(operator_counts)
    operators_present = int(taxonomy_summary.get("mutation_operators_present", len(operator_rows)))
    operators_total = int(taxonomy_summary.get("mutation_operators_total", MUTATION_OPERATORS_TOTAL))
    operator_presence_ratio = operators_present / operators_total if operators_total else 0.0
    operator_balance_score = round(
        0.7 * operator_balance["score"] + 0.3 * operator_presence_ratio,
        6,
    )

    tier_rows = _read_csv(tier_coverage_path)
    tier_counts = [int(row["case_count"]) for row in tier_rows]
    tier_balance = _balance_score(tier_counts)
    tiers_present = int(taxonomy_summary.get("complexity_tiers_present", len(tier_rows)))
    tier_presence_ratio = tiers_present / COMPLEXITY_TIERS_TOTAL
    tier_balance_score = round(
        0.8 * tier_balance["score"] + 0.2 * tier_presence_ratio,
        6,
    )

    detectable_cases = round(v02_summary.get("overall_detection_rate", 0.0) * cohort_size)
    oracle_saturated_cases = cohort_size - int(detectable_cases)
    saturation_rate = oracle_saturated_cases / cohort_size
    oracle_health_score = round(1.0 - saturation_rate, 6)

    loc_rows = {
        (row["partition"], row["metric"]): row for row in _read_csv(localization_metrics_path)
    }
    localizable_cases = int(float(loc_rows[("transition_localizable_gt", "localized_cases")]["value"]))
    detectable_localized = int(float(loc_rows[("all_detectable", "localized_cases")]["value"]))
    localization_coverage_score = round(localizable_cases / cohort_size, 6)
    localization_detectable_score = round(detectable_localized / cohort_size, 6)

    coupling_cohort = int(coupling_summary.get("cohort_size", 250))
    coupling_coverage_score = round(coupling_cohort / cohort_size, 6)

    taxonomy_score = round(taxonomy_summary.get("mean_dimension_coverage_ratio", 0.0), 6)
    operator_catalog_score = round(taxonomy_summary.get("mutation_operator_coverage_ratio", 0.0), 6)
    fsm_family_score = round(
        taxonomy_summary.get("fsm_families_present", 1.0)
        / max(1.0, taxonomy_summary.get("fsm_families_total", 8.0))
        if "fsm_families_total" in taxonomy_summary
        else taxonomy_summary.get("fsm_families_present", 1.0) / 8.0,
        6,
    )

    pillars: dict[str, Any] = {
        "operator_balance": {
            "score": operator_balance_score,
            "operators_present": operators_present,
            "operators_total": operators_total,
            "presence_ratio": round(operator_presence_ratio, 6),
            "count_balance": operator_balance,
            "missing_operators": [
                row["group_value"]
                for row in _read_csv(operator_coverage_path)
                if row.get("present_in_cohort", "").strip().lower() != "true"
            ],
        },
        "complexity_tier_balance": {
            "score": tier_balance_score,
            "tiers_present": tiers_present,
            "tiers_total": COMPLEXITY_TIERS_TOTAL,
            "count_balance": tier_balance,
        },
        "oracle_health": {
            "score": oracle_health_score,
            "detectable_cases": int(detectable_cases),
            "oracle_saturated_cases": oracle_saturated_cases,
            "saturation_rate": round(saturation_rate, 6),
            "overall_detection_rate": round(v02_summary.get("overall_detection_rate", 0.0), 6),
            "interpretation": (
                "Lower saturation is healthier for detectability/localization/repair measurement; "
                "505/1,000 oracle-saturated cases confound cohort-wide repair metrics."
            ),
        },
        "localization_coverage": {
            "score": localization_coverage_score,
            "transition_localizable_cases": localizable_cases,
            "detectable_cases": detectable_localized,
            "detectable_fraction": round(localization_detectable_score, 6),
            "skipped_cases": cohort_size - localizable_cases,
            "primary_partition": "transition_localizable_gt",
        },
        "coupling_coverage": {
            "score": coupling_coverage_score,
            "pinned_subset_cases": coupling_cohort,
            "full_cohort_cases": cohort_size,
            "campaign_label": coupling_summary.get("experiment", "RQ4-higher-order-coupling-250"),
            "first_order_detection_rate_subset": round(
                coupling_summary.get("first_order_detection_rate", 0.0),
                6,
            ),
        },
        "taxonomy_coverage": {
            "score": taxonomy_score,
            "mean_dimension_coverage_ratio": taxonomy_score,
            "mutation_operator_coverage_ratio": operator_catalog_score,
            "fsm_family_coverage_ratio": fsm_family_score,
            "unique_taxonomy_combinations": int(taxonomy_summary.get("unique_taxonomy_combinations", 0)),
            "pairwise_mean_coverage_ratio": round(
                taxonomy_summary.get("pairwise_mean_coverage_ratio", 0.0),
                6,
            ),
        },
    }

    pillar_scores = [pillars[name]["score"] for name in PILLAR_NAMES]
    composite_score = round(statistics.mean(pillar_scores), 6)

    recommendations = _build_recommendations(pillars, composite_score)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "release_label": RELEASE_LABEL,
        "cohort_size": cohort_size,
        "composite_health_score": composite_score,
        "composite_grade": _health_grade(composite_score),
        "pillars": pillars,
        "pillar_scores": {name: pillars[name]["score"] for name in PILLAR_NAMES},
        "recommendations_v0_3_plus": recommendations,
    }


def _health_grade(score: float) -> str:
    if score >= 0.75:
        return "good"
    if score >= 0.55:
        return "fair"
    if score >= 0.40:
        return "limited"
    return "critical"


def _build_recommendations(pillars: dict[str, Any], composite_score: float) -> list[dict[str, str]]:
    recs: list[dict[str, str]] = []

    missing_ops = pillars["operator_balance"].get("missing_operators", [])
    if missing_ops:
        recs.append(
            {
                "priority": "high",
                "area": "operator_balance",
                "recommendation": (
                    "Close operator build gaps for "
                    + ", ".join(missing_ops)
                    + " and rebalance quotas so every declared operator reaches the stratification plan minimum."
                ),
            }
        )

    if pillars["oracle_health"]["saturation_rate"] >= 0.45:
        recs.append(
            {
                "priority": "high",
                "area": "oracle_health",
                "recommendation": (
                    "Ship oracle variants that observe actions, timing, guards, and reachability fields; "
                    "target saturation below 30% on the main cohort so detectability and repair partitions "
                    "are not dominated by oracle-invisible faults."
                ),
            }
        )

    if pillars["localization_coverage"]["score"] < 0.50:
        recs.append(
            {
                "priority": "high",
                "area": "localization_coverage",
                "recommendation": (
                    "Expand transition-localizable ground truth and shallow-oracle spectra beyond "
                    f"{pillars['localization_coverage']['transition_localizable_cases']}/{COHORT_SIZE} cases; "
                    "publish operator-specific localization eligibility and richer scenario fields in v0.3."
                ),
            }
        )

    if pillars["coupling_coverage"]["score"] < 0.50:
        recs.append(
            {
                "priority": "medium",
                "area": "coupling_coverage",
                "recommendation": (
                    "Scale HO coupling campaigns from the pinned 250-case subset to a stratified "
                    "500-1000-case pin and document alternative chaining policies so coupling claims "
                    "generalise beyond seed 44."
                ),
            }
        )

    if pillars["taxonomy_coverage"]["score"] < 0.70:
        recs.append(
            {
                "priority": "high",
                "area": "taxonomy_coverage",
                "recommendation": (
                    "Realise under-filled taxonomy cells (mean dimension coverage "
                    f"{pillars['taxonomy_coverage']['mean_dimension_coverage_ratio']:.1%}) and add Mealy, Moore, "
                    "EFSM, and timed machine strata beyond plain_fsm."
                ),
            }
        )

    if pillars["taxonomy_coverage"]["fsm_family_coverage_ratio"] < 0.25:
        recs.append(
            {
                "priority": "high",
                "area": "machine_type_coverage",
                "recommendation": (
                    "Introduce at least one non-plain_fsm family in v0.3 pilot stratum "
                    "(for example Mealy or timed) before claiming cross-family behavioural evaluation."
                ),
            }
        )

    if composite_score < 0.60:
        recs.append(
            {
                "priority": "medium",
                "area": "release_process",
                "recommendation": (
                    "Gate v0.3+ releases on regenerated benchmark health scorecard thresholds: "
                    "composite >= 0.60, oracle saturation <= 0.40, localization coverage >= 0.45."
                ),
            }
        )

    recs.append(
        {
            "priority": "medium",
            "area": "reporting",
            "recommendation": (
                "Continue publishing detectable-only, localizable-only, and pinned-subset partitions "
                "alongside cohort-wide totals in all campaign exports."
            ),
        }
    )
    return recs


def _tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _write_benchmark_health_tex(path: Path, report: dict[str, Any]) -> None:
    rows: list[list[str]] = []
    for name in PILLAR_NAMES:
        pillar = report["pillars"][name]
        rows.append(
            [
                PILLAR_LABELS[name],
                f"{pillar['score']:.3f}",
                _pillar_detail(name, pillar),
            ]
        )
    body = [
        "\\begin{tabular}{@{}p{0.28\\linewidth}rp{0.48\\linewidth}@{}}",
        "\\toprule",
        "Pillar & Score & Key evidence \\\\",
        "\\midrule",
    ]
    for label, score, detail in rows:
        body.append(f"{label} & {score} & {detail} \\\\")
    body.extend(
        [
            "\\midrule",
            f"\\textbf{{Composite health}} & \\textbf{{{report['composite_health_score']:.3f}}} "
            f"& Grade: \\textbf{{{report['composite_grade']}}} (mean of six pillars) \\\\",
            "\\bottomrule",
            "\\end{tabular}",
        ]
    )
    rec_lines = [
        "\\item "
        + item["recommendation"]
        .replace("plain_fsm", "\\texttt{plain\\_fsm}")
        .replace("timed_selective_mutation", "timed\\_selective\\_mutation")
        .replace("variable_intra_class", "variable\\_intra\\_class")
        .replace(">=", "$\\geq$")
        .replace("<=", "$\\leq$")
        for item in report["recommendations_v0_3_plus"][:5]
    ]
    tex = (
        "\\begin{table}[t]\n"
        "\\caption{Benchmark health scorecard for the \\texttt{v0.2.0-analysis} "
        f"1{{,}}000-case \\texttt{{plain\\_fsm}}/shallow-oracle release. "
        f"Composite score $={report['composite_health_score']:.3f}$ ({report['composite_grade']}). "
        "Takeaway: tier and operator \\emph{counts} are balanced, but oracle saturation and partial taxonomy "
        "realisation limit overall health.}\n"
        "\\label{tab:benchmark-health}\n"
        "\\small\n"
        + "\n".join(body)
        + "\n\\par\\footnotesize Regenerate with "
        "\\texttt{paper1/scripts/generate\\_benchmark\\_health\\_outputs.py}.\n"
        "\\end{table}\n\n"
        "\\paragraph{Health recommendations (v0.3+).}\n"
        "\\begin{itemize}[leftmargin=*]\n"
        + "\n".join(rec_lines)
        + "\n\\end{itemize}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")


def _pillar_detail(name: str, pillar: dict[str, Any]) -> str:
    if name == "operator_balance":
        return (
            f"{pillar['operators_present']}/{pillar['operators_total']} operators; "
            f"CV={pillar['count_balance']['coefficient_of_variation']:.3f}"
        )
    if name == "complexity_tier_balance":
        return (
            f"{pillar['tiers_present']}/{pillar['tiers_total']} tiers; "
            f"counts {pillar['count_balance']['min_cases']}--{pillar['count_balance']['max_cases']}"
        )
    if name == "oracle_health":
        return (
            f"{pillar['oracle_saturated_cases']}/1{{,}}000 saturated; "
            f"detection {_pct(pillar['overall_detection_rate'])}"
        )
    if name == "localization_coverage":
        return (
            f"{pillar['transition_localizable_cases']}/1{{,}}000 localizable GT; "
            f"{pillar['detectable_cases']} detectable"
        )
    if name == "coupling_coverage":
        return f"{pillar['pinned_subset_cases']}/1{{,}}000 pinned HO subset"
    return (
        f"mean dimension coverage {_pct(pillar['mean_dimension_coverage_ratio'])}; "
        f"{pillar['unique_taxonomy_combinations']} unique cells"
    )


def _write_benchmark_health_radar(path: Path, report: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    labels = [PILLAR_LABELS[name] for name in PILLAR_NAMES]
    scores = [report["pillars"][name]["score"] for name in PILLAR_NAMES]
    angles = np.linspace(0, 2 * math.pi, len(labels), endpoint=False).tolist()
    scores_cycle = scores + scores[:1]
    angles_cycle = angles + angles[:1]

    fig, ax = plt.subplots(figsize=(6.5, 6.5), subplot_kw={"projection": "polar"})
    ax.plot(angles_cycle, scores_cycle, color="#2c7bb6", linewidth=2)
    ax.fill(angles_cycle, scores_cycle, color="#2c7bb6", alpha=0.20)
    ax.set_xticks(angles)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylim(0, 1)
    ax.set_yticks([0.2, 0.4, 0.6, 0.8, 1.0])
    ax.grid(True, linestyle="--", alpha=0.4)
    ax.set_title(
        "Benchmark health scorecard\n"
        f"Composite={report['composite_health_score']:.3f} ({report['composite_grade']})",
        pad=20,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def write_benchmark_health_exports(
    *,
    taxonomy_dir: Path,
    v02_summary_path: Path,
    localization_metrics_path: Path,
    coupling_summary_path: Path,
    out_dir: Path,
    paper_export_dir: Path | None = None,
) -> BenchmarkHealthExportResult:
    """Write benchmark health JSON, LaTeX scorecard, and radar figure."""
    report = compute_benchmark_health(
        taxonomy_summary_path=taxonomy_dir / "summary.csv",
        operator_coverage_path=taxonomy_dir / "coverage_by_mutation_operator.csv",
        tier_coverage_path=taxonomy_dir / "coverage_by_complexity_tier.csv",
        v02_summary_path=v02_summary_path,
        localization_metrics_path=localization_metrics_path,
        coupling_summary_path=coupling_summary_path,
    )

    json_path = out_dir / "benchmark_health.json"
    tex_path = out_dir / "tables" / "benchmark_health.tex"
    figure_path = out_dir / "figures" / "benchmark_health_radar.png"

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_benchmark_health_tex(tex_path, report)
    _write_benchmark_health_radar(figure_path, report)

    paper_json_path = paper_tex_path = paper_figure_path = None
    if paper_export_dir is not None and paper_export_dir.resolve() != out_dir.resolve():
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        paper_json_path = paper_export_dir / json_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_figure_path = paper_export_dir / "figures" / figure_path.name
        paper_json_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_tex_path.parent.mkdir(parents=True, exist_ok=True)
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_figure_path.parent.mkdir(parents=True, exist_ok=True)
        paper_figure_path.write_bytes(figure_path.read_bytes())

    return BenchmarkHealthExportResult(
        json_path=json_path,
        tex_path=tex_path,
        figure_path=figure_path,
        paper_json_path=paper_json_path,
        paper_tex_path=paper_tex_path,
        paper_figure_path=paper_figure_path,
    )
