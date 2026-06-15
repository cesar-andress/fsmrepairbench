"""Random-secondary sensitivity analysis for the RQ4 coupling campaign."""

from __future__ import annotations

import csv
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.coupling_campaign import (
    DEFAULT_CAMPAIGN_SEED,
    DEFAULT_RANDOM_SECONDARY_OUTPUT,
    DEFAULT_RANDOM_SECONDARY_PAPER_EXPORT,
    DEFAULT_RANDOM_SECONDARY_SEEDS,
    DEFAULT_RANDOM_SECONDARY_SUBSET,
    DEFAULT_REPAIR_ENGINE,
    ZENODO_DOI,
    CaseCouplingCampaignResult,
    CouplingCampaignError,
    _aggregate_metrics,
    load_cohort_manifest,
    materialize_coupling_subset,
)
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.higher_order_mutation import (
    DatasetCouplingReport,
    analyze_dataset_coupling,
    dataset_coupling_report_to_dict,
)
from fsmrepairbench.statistics import BOOTSTRAP_CI, BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, bootstrap_ci

RANDOM_SECONDARY_EXPERIMENT = "RQ4-random-secondary-sensitivity-250"
DETECTABLE_ORDER_METRICS: tuple[str, ...] = (
    "complete_repair_rate",
    "effective_repair_rate",
    "mean_bpr_delta",
)
PER_SEED_SUMMARY_COLUMNS: tuple[str, ...] = (
    "secondary_random_seed",
    "cohort_size",
    "total_cases",
    "first_order_detection_rate",
    "higher_order_detection_rate",
    "coupling_effect_estimate",
    "detection_rate_order_1",
    "detection_rate_order_2",
    "detection_rate_order_3",
    "complete_repair_rate_order_1",
    "complete_repair_rate_order_2",
    "complete_repair_rate_order_3",
    "effective_repair_rate_order_1",
    "effective_repair_rate_order_2",
    "effective_repair_rate_order_3",
    "mean_bpr_delta_order_1",
    "mean_bpr_delta_order_2",
    "mean_bpr_delta_order_3",
    "detectable_count_order_1",
    "detectable_count_order_2",
    "detectable_count_order_3",
    "complete_repair_rate_order_1_detectable",
    "complete_repair_rate_order_2_detectable",
    "complete_repair_rate_order_3_detectable",
    "effective_repair_rate_order_1_detectable",
    "effective_repair_rate_order_2_detectable",
    "effective_repair_rate_order_3_detectable",
    "mean_bpr_delta_order_1_detectable",
    "mean_bpr_delta_order_2_detectable",
    "mean_bpr_delta_order_3_detectable",
    "skipped_ho_generations",
)
PER_CASE_RANDOM_COLUMNS: tuple[str, ...] = (
    "secondary_random_seed",
    "case_id",
    "source_case_id",
    "mutation_order",
    "is_higher_order",
    "primary_operator",
    "mutation_operator",
    "ho_seed",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "fault_detected",
    "first_order_components_detected",
    "first_order_components_total",
    "all_first_order_detected",
    "coupling_eligible",
    "coupling_detected",
    "complete_repair",
    "effective_repair",
    "repair_final_bpr",
    "repair_delta_bpr",
    "generation_status",
)
RANDOM_SECONDARY_METRICS: tuple[str, ...] = (
    "higher_order_detection_rate",
    "coupling_effect_estimate",
    "detection_rate_order_1",
    "detection_rate_order_2",
    "detection_rate_order_3",
    "complete_repair_rate_order_1",
    "complete_repair_rate_order_2",
    "complete_repair_rate_order_3",
    "effective_repair_rate_order_1",
    "effective_repair_rate_order_2",
    "effective_repair_rate_order_3",
    "mean_bpr_delta_order_1",
    "mean_bpr_delta_order_2",
    "mean_bpr_delta_order_3",
    "detectable_count_order_1",
    "detectable_count_order_2",
    "detectable_count_order_3",
    "complete_repair_rate_order_1_detectable",
    "complete_repair_rate_order_2_detectable",
    "complete_repair_rate_order_3_detectable",
    "effective_repair_rate_order_1_detectable",
    "effective_repair_rate_order_2_detectable",
    "effective_repair_rate_order_3_detectable",
    "mean_bpr_delta_order_1_detectable",
    "mean_bpr_delta_order_2_detectable",
    "mean_bpr_delta_order_3_detectable",
)
RANDOM_SECONDARY_FLAT_SUFFIXES: tuple[str, ...] = (
    "mean",
    "std",
    "min",
    "max",
    "ci95_low",
    "ci95_high",
)


@dataclass(frozen=True)
class RandomSecondaryCouplingResult:
    """Paths written by random-secondary RQ4 sensitivity analysis."""

    output_dir: Path
    per_seed_summary_path: Path
    per_case_path: Path
    summary_csv_path: Path
    summary_json_path: Path
    report_path: Path
    manifest_path: Path
    tables_dir: Path
    figures_dir: Path
    paper_export_dir: Path


def _detectable_order_metrics(
    rows: Sequence[CaseCouplingCampaignResult],
    order: int,
) -> dict[str, float | int]:
    detectable = [row for row in rows if row.mutation_order == order and row.fault_detected]
    count = len(detectable)
    if count == 0:
        return {
            f"detectable_count_order_{order}": 0,
            f"complete_repair_rate_order_{order}_detectable": 0.0,
            f"effective_repair_rate_order_{order}_detectable": 0.0,
            f"mean_bpr_delta_order_{order}_detectable": 0.0,
        }
    complete = sum(1 for row in detectable if row.complete_repair) / count
    effective = sum(1 for row in detectable if row.effective_repair) / count
    mean_delta = sum(row.bpr_delta for row in detectable) / count
    return {
        f"detectable_count_order_{order}": count,
        f"complete_repair_rate_order_{order}_detectable": round(complete, 6),
        f"effective_repair_rate_order_{order}_detectable": round(effective, 6),
        f"mean_bpr_delta_order_{order}_detectable": round(mean_delta, 6),
    }


def _metric_by_order(
    metrics: list[dict[str, str | int | float]],
    metric: str,
    order: int,
) -> float:
    for row in metrics:
        if row["metric"] == metric and str(row["mutation_order"]) == str(order):
            return float(row["value"])
    return 0.0


def summarize_seed_run(
    *,
    secondary_random_seed: int,
    rows: Sequence[CaseCouplingCampaignResult],
    dataset_report: DatasetCouplingReport,
    skipped_ho: Sequence[str],
) -> dict[str, float | int]:
    metrics = _aggregate_metrics(list(rows))
    cohort_size = len({row.source_case_id for row in rows if row.generation_status == "source"})
    summary: dict[str, float | int] = {
        "secondary_random_seed": secondary_random_seed,
        "cohort_size": cohort_size,
        "total_cases": len(rows),
        "first_order_detection_rate": round(dataset_report.first_order_detection_rate, 6),
        "higher_order_detection_rate": round(dataset_report.higher_order_detection_rate, 6),
        "coupling_effect_estimate": round(dataset_report.coupling_effect_estimate, 6),
        "detection_rate_order_1": round(_metric_by_order(metrics, "detection_rate", 1), 6),
        "detection_rate_order_2": round(_metric_by_order(metrics, "detection_rate", 2), 6),
        "detection_rate_order_3": round(_metric_by_order(metrics, "detection_rate", 3), 6),
        "complete_repair_rate_order_1": round(_metric_by_order(metrics, "complete_repair_rate", 1), 6),
        "complete_repair_rate_order_2": round(_metric_by_order(metrics, "complete_repair_rate", 2), 6),
        "complete_repair_rate_order_3": round(_metric_by_order(metrics, "complete_repair_rate", 3), 6),
        "effective_repair_rate_order_1": round(_metric_by_order(metrics, "effective_repair_rate", 1), 6),
        "effective_repair_rate_order_2": round(_metric_by_order(metrics, "effective_repair_rate", 2), 6),
        "effective_repair_rate_order_3": round(_metric_by_order(metrics, "effective_repair_rate", 3), 6),
        "mean_bpr_delta_order_1": round(_metric_by_order(metrics, "mean_bpr_delta", 1), 6),
        "mean_bpr_delta_order_2": round(_metric_by_order(metrics, "mean_bpr_delta", 2), 6),
        "mean_bpr_delta_order_3": round(_metric_by_order(metrics, "mean_bpr_delta", 3), 6),
        "skipped_ho_generations": len(skipped_ho),
    }
    for order in (1, 2, 3):
        summary.update(_detectable_order_metrics(rows, order))
    return summary


def compute_random_secondary_statistics(
    per_seed: Sequence[dict[str, float | int]],
    *,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> dict[str, dict[str, float]]:
    import random

    rng = random.Random(bootstrap_seed)
    stats: dict[str, dict[str, float]] = {}
    for metric in RANDOM_SECONDARY_METRICS:
        values = [float(row[metric]) for row in per_seed]
        low, high = bootstrap_ci(values, n_resamples=bootstrap_resamples, rng=rng)
        stats[metric] = {
            "mean": round(statistics.mean(values), 6),
            "std": round(statistics.pstdev(values), 6) if len(values) > 1 else 0.0,
            "min": round(min(values), 6),
            "max": round(max(values), 6),
            "ci95_low": round(low, 6),
            "ci95_high": round(high, 6),
        }
    return stats


def flatten_random_secondary_summary(
    aggregate: dict[str, dict[str, float]],
    *,
    seed_count: int,
) -> dict[str, float | int]:
    flat: dict[str, float | int] = {"seed_count": seed_count}
    for metric in RANDOM_SECONDARY_METRICS:
        metric_stats = aggregate[metric]
        for suffix in RANDOM_SECONDARY_FLAT_SUFFIXES:
            flat[f"{metric}_{suffix}"] = metric_stats[suffix]
    return flat


def random_secondary_summary_columns() -> tuple[str, ...]:
    columns: list[str] = ["seed_count"]
    for metric in RANDOM_SECONDARY_METRICS:
        for suffix in RANDOM_SECONDARY_FLAT_SUFFIXES:
            columns.append(f"{metric}_{suffix}")
    return tuple(columns)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_per_case_random_csv(path: Path, rows: Sequence[CaseCouplingCampaignResult], seed: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PER_CASE_RANDOM_COLUMNS))
        if write_header:
            writer.writeheader()
        for row in rows:
            payload = row.to_dict()
            payload["secondary_random_seed"] = seed
            writer.writerow(payload)


def _write_random_secondary_report(
    path: Path,
    *,
    cohort_path: Path,
    seeds: Sequence[int],
    flat_summary: dict[str, float | int],
    deterministic_ho_detection: float | None,
) -> None:
    lines = [
        "# RQ4 Random Secondary Operator Sensitivity",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Motivation",
        "",
        "The primary RQ4 campaign chains deterministic secondary operators. This sensitivity "
        "analysis repeats higher-order generation with reproducible random secondary operator "
        "selection across multiple seeds to assess whether deterministic chaining inflates "
        "higher-order detection.",
        "",
        "## Configuration",
        "",
        f"- Cohort: `{cohort_path}`",
        f"- Campaign seed (repair / HO mutation): {DEFAULT_CAMPAIGN_SEED}",
        f"- Secondary operator policy: random",
        f"- Random secondary seeds: {', '.join(str(seed) for seed in seeds)}",
        "",
        "## Bootstrap confidence intervals",
        "",
        "Across-seed percentile bootstrap on seed-level campaign metrics "
        f"({BOOTSTRAP_RESAMPLES:,} resamples, {BOOTSTRAP_CI:.0%} CI, seed {BOOTSTRAP_SEED}).",
        "",
    ]
    if deterministic_ho_detection is not None:
        lines.extend(
            [
                "## Comparison to deterministic RQ4",
                "",
                f"- Deterministic HO detection (primary campaign): {deterministic_ho_detection:.6f}",
                f"- Random-secondary HO detection mean: {flat_summary['higher_order_detection_rate_mean']:.6f}",
                f"- Random-secondary HO detection 95% CI: "
                f"[{flat_summary['higher_order_detection_rate_ci95_low']:.6f}, "
                f"{flat_summary['higher_order_detection_rate_ci95_high']:.6f}]",
                "",
            ]
        )
    lines.append("## Across-seed summary")
    lines.append("")
    for key in random_secondary_summary_columns():
        lines.append(f"- `{key}`: {flat_summary[key]}")
    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            "- `per_seed_summary.csv`",
            "- `per_case_results.csv`",
            "- `random_secondary_summary.csv`",
            "- `random_secondary_summary.json`",
            "- `per_seed_summary.csv`",
            "- `tables/`",
            "- `figures/`",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_random_secondary_tex(
    path: Path,
    flat_summary: dict[str, float | int],
    *,
    seed_count: int,
) -> None:
    rows = [
        ("Higher-order detection", "higher_order_detection_rate"),
        ("Coupling effect", "coupling_effect_estimate"),
        ("Complete repair (order 2)", "complete_repair_rate_order_2"),
        ("Complete repair (order 3)", "complete_repair_rate_order_3"),
        ("Effective repair (order 2)", "effective_repair_rate_order_2"),
        ("Effective repair (order 3)", "effective_repair_rate_order_3"),
        ("Mean $\\Delta$BPR (order 2)", "mean_bpr_delta_order_2"),
        ("Mean $\\Delta$BPR (order 3)", "mean_bpr_delta_order_3"),
    ]
    lines = [
        "% Auto-generated from fsmrepairbench.coupling_random_secondary",
        "\\begin{table}[t]",
        f"\\caption{{Random-secondary RQ4 sensitivity ($n={seed_count}$ seeds). "
        "Across-seed bootstrap 95\\% CIs; deterministic primary RQ4 remains unchanged.}",
        "\\label{tab:rq4-random-secondary-summary}",
        "\\small",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Metric & Mean & Std & CI low & CI high \\\\",
        "\\midrule",
    ]
    for label, key in rows:
        lines.append(
            f"{label} & {flat_summary[f'{key}_mean']:.4f} & {flat_summary[f'{key}_std']:.4f} & "
            f"{flat_summary[f'{key}_ci95_low']:.4f} & {flat_summary[f'{key}_ci95_high']:.4f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _metric_stats(flat_summary: dict[str, float | int], metric: str) -> tuple[float, float, float, float]:
    return (
        float(flat_summary[f"{metric}_mean"]),
        float(flat_summary[f"{metric}_std"]),
        float(flat_summary[f"{metric}_ci95_low"]),
        float(flat_summary[f"{metric}_ci95_high"]),
    )


def _ci_bracket(low: float, high: float, *, percent: bool = False) -> str:
    if percent:
        return f"{{[{100 * low:.1f}--{100 * high:.1f}]}}"
    return f"{{[{low:.3f}--{high:.3f}]}}"


def _pct_cell(mean: float, std: float, low: float, high: float) -> str:
    return (
        f"{100 * mean:.1f}\\% $\\pm$ {100 * std:.1f} "
        f"{_ci_bracket(low, high, percent=True)}"
    )


def _delta_cell(mean: float, std: float, low: float, high: float) -> str:
    return f"{mean:.3f} $\\pm$ {std:.3f} {_ci_bracket(low, high)}"


def _write_random_secondary_detectable_tex(
    path: Path,
    flat_summary: dict[str, float | int],
    *,
    seed_count: int,
) -> None:
    lines = [
        "% Auto-generated from fsmrepairbench.coupling_random_secondary",
        "\\begin{table}[t]",
        (
            f"\\caption{{Detectable-only repair and $\\Delta$BPR by mutation order under random-secondary "
            f"HO chaining ($n={seed_count}$ secondary seeds; campaign seed~44; "
            "\\texttt{missing-transition} baseline). Means $\\pm$ standard deviation across seeds; "
            "bracketed ranges are across-seed bootstrap 95\\% confidence intervals. "
            "Primary deterministic RQ4 appears in \\Tab{tab:coupling-repair-detectable}.}"
        ),
        "\\label{tab:rq4-random-secondary-detectable}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Order & Detectable ($n$) & Complete (detectable-only) & Effective (detectable-only) "
        "& Mean $\\Delta$BPR \\\\",
        "\\midrule",
    ]
    for order in (1, 2, 3):
        n_mean, n_std, n_low, n_high = _metric_stats(flat_summary, f"detectable_count_order_{order}")
        c_mean, c_std, c_low, c_high = _metric_stats(
            flat_summary, f"complete_repair_rate_order_{order}_detectable"
        )
        e_mean, e_std, e_low, e_high = _metric_stats(
            flat_summary, f"effective_repair_rate_order_{order}_detectable"
        )
        d_mean, d_std, d_low, d_high = _metric_stats(
            flat_summary, f"mean_bpr_delta_order_{order}_detectable"
        )
        n_cell = f"{n_mean:.0f} $\\pm$ {n_std:.1f} {{[{n_low:.0f}--{n_high:.0f}]}}"
        lines.append(
            f"{order} & {n_cell} & {_pct_cell(c_mean, c_std, c_low, c_high)} & "
            f"{_pct_cell(e_mean, e_std, e_low, e_high)} & {_delta_cell(d_mean, d_std, d_low, d_high)} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        msg = f"Plotting dependencies missing for random-secondary figures: {exc}"
        raise CouplingCampaignError(msg) from exc
    return plt


def _write_random_secondary_figures(
    figures_dir: Path,
    *,
    per_seed_rows: Sequence[dict[str, float | int]],
    flat_summary: dict[str, float | int],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    plt = _pyplot()
    seeds = [int(row["secondary_random_seed"]) for row in per_seed_rows]

    figure, axis = plt.subplots(figsize=(8, 5))
    for order, color in ((1, "#4472C4"), (2, "#ED7D31"), (3, "#70AD47")):
        values = [100.0 * float(row[f"detection_rate_order_{order}"]) for row in per_seed_rows]
        axis.plot(seeds, values, marker="o", label=f"Order {order}", color=color)
    axis.set_title("Detection Rate by Secondary Random Seed")
    axis.set_xlabel("Secondary random seed")
    axis.set_ylabel("Detection rate (%)")
    axis.set_ylim(0, 105)
    axis.legend()
    figure.tight_layout()
    figure.savefig(figures_dir / "detection_rate_by_seed.png", dpi=120)
    plt.close(figure)

    order_labels = ["Order 1", "Order 2", "Order 3"]
    for metric, title, ylabel, filename in (
        (
            "complete_repair_rate_order_{order}_detectable",
            "Detectable-only Complete Repair by Mutation Order",
            "Complete repair rate (%)",
            "detectable_complete_repair_by_order.png",
        ),
        (
            "effective_repair_rate_order_{order}_detectable",
            "Detectable-only Effective Repair by Mutation Order",
            "Effective repair rate (%)",
            "detectable_effective_repair_by_order.png",
        ),
        (
            "mean_bpr_delta_order_{order}_detectable",
            "Detectable-only Mean $\\Delta$BPR by Mutation Order",
            "Mean $\\Delta$BPR",
            "detectable_mean_bpr_delta_by_order.png",
        ),
    ):
        means: list[float] = []
        stds: list[float] = []
        for order in (1, 2, 3):
            key = metric.format(order=order)
            means.append(
                100.0 * float(flat_summary[f"{key}_mean"])
                if "bpr_delta" not in key
                else float(flat_summary[f"{key}_mean"])
            )
            stds.append(
                100.0 * float(flat_summary[f"{key}_std"])
                if "bpr_delta" not in key
                else float(flat_summary[f"{key}_std"])
            )
        figure, axis = plt.subplots(figsize=(8, 5))
        axis.bar(order_labels, means, yerr=stds, capsize=4, color="#4472C4", alpha=0.85)
        axis.set_title(title)
        axis.set_xlabel("Mutation order")
        axis.set_ylabel(ylabel)
        figure.tight_layout()
        figure.savefig(figures_dir / filename, dpi=120)
        plt.close(figure)


def _experiment_manifest_payload(
    *,
    cohort: Path,
    out: Path,
    subset_base: Path,
    paper_dir: Path,
    campaign_seed: int,
    repair_engine: str,
    random_secondary_seeds: Sequence[int],
) -> dict[str, Any]:
    return {
        "experiment": RANDOM_SECONDARY_EXPERIMENT,
        "design": {
            "complements": "RQ4-higher-order-coupling-250",
            "cohort_manifest": str(cohort),
            "cohort_size": 250,
            "secondary_operator_policy": "random",
            "secondary_operator_pool": [
                "wrong_target",
                "guard_flip",
                "missing_transition",
                "wrong_event",
                "wrong_source",
                "guard_weaken",
                "guard_strengthen",
                "wrong_initial_state",
            ],
            "ho_orders": [2, 3],
            "campaign_seed": campaign_seed,
            "repair_engine": repair_engine,
            "random_secondary_seeds": list(random_secondary_seeds),
            "variance_unit": "secondary_random_seed",
            "primary_metrics": [
                "detection_rate",
                "complete_repair_rate",
                "effective_repair_rate",
                "mean_bpr_delta",
            ],
            "primary_partition": "detectable_only",
        },
        "regeneration": {
            "cli": (
                "fsmrepairbench run-coupling-campaign data/fsmrepairbench_1k "
                "--cohort-file data/fsmrepairbench_1k/coupling_campaign_250.txt "
                "--secondary-operator-policy random "
                "--random-secondary-seeds 10 "
                "--out results/rq4_coupling_250_random_secondary "
                "--subset-dir results/rq4_coupling_subset_random_secondary "
                "--paper-export-dir ../paper1/results/rq4_coupling_250_random_secondary "
                "--seed 44"
            ),
            "paper_wrapper": "python ../paper1/scripts/run_rq4_random_secondary_campaign.py",
            "freeze_paper": "python ../paper1/scripts/generate_rq4_random_secondary_outputs.py",
            "wrap_latex": "python ../paper1/scripts/compile_results_latex.py",
        },
    }


def _read_deterministic_ho_detection(results_dir: Path) -> float | None:
    summary = results_dir / "summary.csv"
    if not summary.is_file():
        return None
    for row in csv.DictReader(summary.open(encoding="utf-8")):
        if row["metric"] == "higher_order_detection_rate":
            return float(row["value"])
    return None


def run_random_secondary_coupling_campaign(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_path: Path | None = None,
    subset_root: Path | None = None,
    paper_export_dir: Path | None = None,
    campaign_seed: int = DEFAULT_CAMPAIGN_SEED,
    repair_engine: str = DEFAULT_REPAIR_ENGINE,
    random_secondary_seeds: Sequence[int] = DEFAULT_RANDOM_SECONDARY_SEEDS,
    use_symlinks: bool = True,
    deterministic_results_dir: Path | None = None,
) -> RandomSecondaryCouplingResult:
    """Run multi-seed random-secondary RQ4 sensitivity analysis."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise CouplingCampaignError(msg)

    cohort = cohort_path or (dataset_dir / "coupling_campaign_250.txt")
    case_ids = load_cohort_manifest(cohort)
    out = output_dir or DEFAULT_RANDOM_SECONDARY_OUTPUT
    subset_base = subset_root or DEFAULT_RANDOM_SECONDARY_SUBSET
    paper_dir = paper_export_dir or DEFAULT_RANDOM_SECONDARY_PAPER_EXPORT
    deterministic_dir = deterministic_results_dir or Path("results/rq4_coupling_250")

    out.mkdir(parents=True, exist_ok=True)
    per_case_path = out / "per_case_results.csv"
    if per_case_path.is_file():
        per_case_path.unlink()

    per_seed_rows: list[dict[str, float | int]] = []
    seed_payloads: list[dict[str, Any]] = []

    for seed in random_secondary_seeds:
        seed_subset = subset_base / f"seed_{seed:04d}"
        rows, skipped_ho = materialize_coupling_subset(
            dataset_dir,
            case_ids,
            seed_subset,
            campaign_seed=campaign_seed,
            repair_engine=repair_engine,
            use_symlinks=use_symlinks,
            secondary_operator_policy="random",
            secondary_random_seed=seed,
        )
        dataset_report = analyze_dataset_coupling(seed_subset)
        seed_summary = summarize_seed_run(
            secondary_random_seed=seed,
            rows=rows,
            dataset_report=dataset_report,
            skipped_ho=skipped_ho,
        )
        per_seed_rows.append(seed_summary)
        seed_payloads.append(
            {
                "secondary_random_seed": seed,
                "subset_dir": str(seed_subset),
                "summary": seed_summary,
                "dataset_coupling": dataset_coupling_report_to_dict(dataset_report),
                "skipped_ho_generations": skipped_ho,
            }
        )
        _write_per_case_random_csv(per_case_path, rows, seed)

    aggregate = compute_random_secondary_statistics(per_seed_rows)
    flat_summary = flatten_random_secondary_summary(aggregate, seed_count=len(random_secondary_seeds))

    per_seed_summary_path = out / "per_seed_summary.csv"
    _write_csv(per_seed_summary_path, list(PER_SEED_SUMMARY_COLUMNS), per_seed_rows)

    summary_csv_path = out / "random_secondary_summary.csv"
    _write_csv(summary_csv_path, list(random_secondary_summary_columns()), [flat_summary])

    summary_json_path = out / "random_secondary_summary.json"
    summary_json_path.write_text(
        json.dumps(
            {
                "experiment": RANDOM_SECONDARY_EXPERIMENT,
                "secondary_operator_policy": "random",
                "campaign_seed": campaign_seed,
                "random_secondary_seeds": list(random_secondary_seeds),
                "summary": flat_summary,
                "aggregate": aggregate,
                "per_seed": per_seed_rows,
                "bootstrap": {
                    "method": "percentile_across_seeds",
                    "ci": BOOTSTRAP_CI,
                    "resamples": BOOTSTRAP_RESAMPLES,
                    "seed": BOOTSTRAP_SEED,
                },
                "generated_at_utc": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    report_path = out / "report.md"
    _write_random_secondary_report(
        report_path,
        cohort_path=cohort,
        seeds=random_secondary_seeds,
        flat_summary=flat_summary,
        deterministic_ho_detection=_read_deterministic_ho_detection(deterministic_dir),
    )

    tables_dir = out / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    _write_random_secondary_tex(
        tables_dir / "table_random_secondary_summary.tex",
        flat_summary,
        seed_count=len(random_secondary_seeds),
    )
    _write_random_secondary_detectable_tex(
        tables_dir / "table_random_secondary_detectable_by_order.tex",
        flat_summary,
        seed_count=len(random_secondary_seeds),
    )

    figures_dir = out / "figures"
    _write_random_secondary_figures(
        figures_dir,
        per_seed_rows=per_seed_rows,
        flat_summary=flat_summary,
    )

    experiment_design = _experiment_manifest_payload(
        cohort=cohort,
        out=out,
        subset_base=subset_base,
        paper_dir=paper_dir,
        campaign_seed=campaign_seed,
        repair_engine=repair_engine,
        random_secondary_seeds=random_secondary_seeds,
    )

    paper_dir.mkdir(parents=True, exist_ok=True)
    paper_tables = paper_dir / "tables"
    paper_figures = paper_dir / "figures"
    paper_tables.mkdir(parents=True, exist_ok=True)
    paper_figures.mkdir(parents=True, exist_ok=True)
    (paper_dir / "random_secondary_summary.csv").write_text(
        summary_csv_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (paper_dir / "random_secondary_summary.json").write_text(
        summary_json_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (paper_dir / "per_seed_summary.csv").write_text(
        per_seed_summary_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (paper_dir / "per_case_results.csv").write_text(
        per_case_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    for name in (
        "table_random_secondary_summary.tex",
        "table_random_secondary_detectable_by_order.tex",
    ):
        (paper_tables / name).write_text((tables_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
    for figure_path in figures_dir.glob("*.png"):
        (paper_figures / figure_path.name).write_bytes(figure_path.read_bytes())
    (paper_dir / "report.md").write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "release_label": RANDOM_SECONDARY_EXPERIMENT,
                "zenodo_doi": ZENODO_DOI,
                **experiment_design,
                "dataset_dir": str(dataset_dir),
                "cohort_path": str(cohort),
                "cohort_sha256": sha256_file(cohort),
                "case_count": len(case_ids),
                "output_dir": str(out),
                "paper_export_dir": str(paper_dir),
                "subset_root": str(subset_base),
                "git_commit_hash": get_git_commit(),
                "seed_runs": seed_payloads,
                "limitations_note": (
                    "Sensitivity complement to deterministic HO chaining on the pinned "
                    "n=250 subset; variance unit is secondary_random_seed, not case resampling."
                ),
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (paper_dir / "manifest.json").write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")

    return RandomSecondaryCouplingResult(
        output_dir=out,
        per_seed_summary_path=per_seed_summary_path,
        per_case_path=per_case_path,
        summary_csv_path=summary_csv_path,
        summary_json_path=summary_json_path,
        report_path=report_path,
        manifest_path=manifest_path,
        tables_dir=tables_dir,
        figures_dir=figures_dir,
        paper_export_dir=paper_dir,
    )
