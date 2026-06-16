"""Published SBFL coefficient comparison on transition-localizable ground truth."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.fault_localization import collect_scenario_spectra
from fsmrepairbench.localization_baselines import (
    BASELINE_COMPARISON_COLUMNS,
    BASELINE_METHOD_LABELS,
    BaselineMethodResult,
    PUBLISHED_SBFL_METHODS,
    aggregate_baseline_metrics,
    compute_baseline_confidence_intervals,
    localize_case_baseline,
    _ci_lookup,
    _mrr_with_ci,
    _pct_with_ci,
)
from fsmrepairbench.localization_campaign import CaseLocalizationResult
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

PARTITION_STRUCTURALLY_LOCALIZABLE = "transition_localizable_gt"
PARTITION_SPECTRALLY_PARTICIPATING = "spectrally_participating_gt"

PARTITION_LABELS: dict[str, str] = {
    PARTITION_STRUCTURALLY_LOCALIZABLE: "Structurally localizable",
    PARTITION_SPECTRALLY_PARTICIPATING: "Spectrally participating ($e_f{+}e_p>0$)",
}


@dataclass(frozen=True)
class SbflComparisonExports:
    """Paths written by published SBFL coefficient comparison."""

    comparison_csv: Path
    participation_csv: Path
    table_tex: Path
    figure_path: Path


def target_transition_spectrum_counts(case_dir: Path, *, target: str) -> tuple[int, int]:
    """Return failed-cover and passed-cover counts for *target* on shallow oracle spectra."""
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if faulty_path is None or oracle_path is None:
        return 0, 0
    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    spectra = collect_scenario_spectra(faulty, oracle)
    ef = sum(
        1
        for spectrum in spectra
        if not spectrum.passed and target in spectrum.covered_transitions
    )
    ep = sum(
        1
        for spectrum in spectra
        if spectrum.passed and target in spectrum.covered_transitions
    )
    return ef, ep


def is_spectrally_participating(case_dir: Path, *, target: str) -> bool:
    """True when the injected transition appears in at least one observed scenario."""
    ef, ep = target_transition_spectrum_counts(case_dir, target=target)
    return ef + ep > 0


def filter_spectrally_participating_rows(
    dataset_dir: Path,
    localizable_case_rows: list[CaseLocalizationResult],
) -> list[CaseLocalizationResult]:
    """Retain structurally localizable cases whose GT transition participates in spectra."""
    filtered: list[CaseLocalizationResult] = []
    for row in localizable_case_rows:
        case_dir = dataset_dir / "cases" / row.case_id
        if is_spectrally_participating(case_dir, target=row.changed_transition_id):
            filtered.append(row)
    return filtered


def write_participation_csv(
    path: Path,
    dataset_dir: Path,
    localizable_case_rows: list[CaseLocalizationResult],
) -> None:
    """Write per-case GT transition spectrum participation for the localizable partition."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | int]] = []
    for row in localizable_case_rows:
        case_dir = dataset_dir / "cases" / row.case_id
        ef, ep = target_transition_spectrum_counts(case_dir, target=row.changed_transition_id)
        rows.append(
            {
                "case_id": row.case_id,
                "changed_transition_id": row.changed_transition_id,
                "target_ef": ef,
                "target_ep": ep,
                "spectrally_participating": int(ef + ep > 0),
                "spectrally_absent": int(ef == 0 and ep == 0),
            }
        )
    fieldnames = [
        "case_id",
        "changed_transition_id",
        "target_ef",
        "target_ep",
        "spectrally_participating",
        "spectrally_absent",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def run_published_sbfl_comparison(
    dataset_dir: Path,
    *,
    localizable_case_rows: list[CaseLocalizationResult],
    partition: str = PARTITION_STRUCTURALLY_LOCALIZABLE,
) -> list[BaselineMethodResult]:
    """Evaluate published SBFL coefficients on one localizable partition."""
    case_ids = {row.case_id for row in localizable_case_rows}
    case_dir_by_id = {case_id: dataset_dir / "cases" / case_id for case_id in case_ids}

    results: list[BaselineMethodResult] = []
    for method in PUBLISHED_SBFL_METHODS:
        if method == "ochiai":
            method_rows = list(localizable_case_rows)
        else:
            method_rows = [
                localize_case_baseline(case_dir_by_id[row.case_id], method=method)
                for row in localizable_case_rows
            ]

        metrics = aggregate_baseline_metrics(method_rows)
        cis = compute_baseline_confidence_intervals(
            method_rows,
            group="RQ3",
            subgroup=f"{method}_{partition}",
        )
        results.append(
            BaselineMethodResult(
                method=method,
                display_name=BASELINE_METHOD_LABELS[method],
                case_rows=tuple(method_rows),
                metrics=metrics,
                confidence_intervals=tuple(cis),
            )
        )
    return results


def build_dual_partition_sbfl_results(
    dataset_dir: Path,
    *,
    localizable_case_rows: list[CaseLocalizationResult],
) -> list[tuple[str, BaselineMethodResult]]:
    """Build SBFL comparison for structurally localizable and spectrally participating pools."""
    participating_rows = filter_spectrally_participating_rows(
        dataset_dir,
        localizable_case_rows,
    )
    combined: list[tuple[str, BaselineMethodResult]] = []
    for partition, rows in (
        (PARTITION_STRUCTURALLY_LOCALIZABLE, localizable_case_rows),
        (PARTITION_SPECTRALLY_PARTICIPATING, participating_rows),
    ):
        for result in run_published_sbfl_comparison(
            dataset_dir,
            localizable_case_rows=rows,
            partition=partition,
        ):
            combined.append((partition, result))
    return combined


def write_sbfl_comparison_csv(
    path: Path,
    combined_results: list[tuple[str, BaselineMethodResult]],
) -> None:
    """Write dual-partition SBFL comparison metrics with bootstrap CIs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | float | int]] = []
    for partition, result in combined_results:
        ci = _ci_lookup(result.confidence_intervals)
        rows.append(
            {
                "method": result.method,
                "partition": partition,
                "n_cases": int(result.metrics["localized_cases"]),
                "top1_hit_rate": float(result.metrics["top1_hit_rate"]),
                "top3_hit_rate": float(result.metrics["top3_hit_rate"]),
                "top5_hit_rate": float(result.metrics["top5_hit_rate"]),
                "mrr": float(result.metrics["mrr"]),
                "top1_ci95_low": ci["top_1_hit_rate"].ci95_low,
                "top1_ci95_high": ci["top_1_hit_rate"].ci95_high,
                "top3_ci95_low": ci["top_3_hit_rate"].ci95_low,
                "top3_ci95_high": ci["top_3_hit_rate"].ci95_high,
                "top5_ci95_low": ci["top_5_hit_rate"].ci95_low,
                "top5_ci95_high": ci["top_5_hit_rate"].ci95_high,
                "mrr_ci95_low": ci["mrr"].ci95_low,
                "mrr_ci95_high": ci["mrr"].ci95_high,
            }
        )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BASELINE_COMPARISON_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def write_sbfl_comparison_tex(
    path: Path,
    combined_results: list[tuple[str, BaselineMethodResult]],
    *,
    structurally_localizable_n: int,
    spectrally_participating_n: int,
    spectrally_absent_n: int,
) -> None:
    """Write LaTeX table comparing SBFL coefficients on both participation strata."""
    lines = [
        "% Auto-generated by sbfl_coefficient_comparison",
        "\\begin{table}[t]",
        "\\caption{Published spectrum-based fault-localisation coefficients under identical "
        "faults and oracle traces. \\textbf{Structurally localizable} "
        f"($n={structurally_localizable_n}$): injected transition present in the faulty FSM "
        "(\\texttt{transition\\_localizable\\_gt}). "
        f"\\textbf{{Spectrally participating}} ($n={spectrally_participating_n}$): "
        f"GT transition appears in at least one scenario ($e_f{{+}}e_p>0$); "
        f"{spectrally_absent_n} structurally localizable cases are spectrally absent "
        "($e_f=e_p=0$). Ochiai structurally-localizable rows match \\Tab{tab:localization-headline}. "
        "Bracketed ranges: bootstrap 95\\% CIs (10{,}000 resamples; seed~44).}",
        "\\label{tab:sbfl-comparison}",
        "\\tablefit{%",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}llrrrrr@{}}",
        "\\toprule",
        "Method & Partition & $n$ & Top-1 & Top-3 & Top-5 & MRR \\\\",
        "\\midrule",
    ]
    for partition, result in combined_results:
        ci = _ci_lookup(result.confidence_intervals)
        label = PARTITION_LABELS.get(partition, partition)
        lines.append(
            f"{result.display_name} & {label} & {int(result.metrics['localized_cases'])} & "
            f"{_pct_with_ci(float(result.metrics['top1_hit_rate']), ci.get('top_1_hit_rate'))} & "
            f"{_pct_with_ci(float(result.metrics['top3_hit_rate']), ci.get('top_3_hit_rate'))} & "
            f"{_pct_with_ci(float(result.metrics['top5_hit_rate']), ci.get('top_5_hit_rate'))} & "
            f"{_mrr_with_ci(float(result.metrics['mrr']), ci.get('mrr'))} \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            "}",
            "\\par\\footnotesize Aggregate rows mix structurally eligible faults with "
            f"{spectrally_absent_n} spectrally absent ground-truth transitions; "
            "spectrally participating rows isolate faults the oracle suite actually exercises.",
            "\\end{table}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_sbfl_comparison_figure(
    path: Path,
    combined_results: list[tuple[str, BaselineMethodResult]],
) -> None:
    """Grouped bar chart: Top-1 and MRR by partition across SBFL coefficients."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        msg = f"Plotting dependencies missing for SBFL comparison figure: {exc}"
        raise RuntimeError(msg) from exc

    partitions = [
        PARTITION_STRUCTURALLY_LOCALIZABLE,
        PARTITION_SPECTRALLY_PARTICIPATING,
    ]
    partition_titles = {
        PARTITION_STRUCTURALLY_LOCALIZABLE: "Structurally localizable",
        PARTITION_SPECTRALLY_PARTICIPATING: "Spectrally participating",
    }
    lookup = {
        (partition, result.method): result
        for partition, result in combined_results
    }
    methods = list(PUBLISHED_SBFL_METHODS)
    metric_specs = (
        ("Top-1 hit rate (%)", "top1_hit_rate", 100.0),
        ("MRR (%)", "mrr", 100.0),
    )

    figure, axes = plt.subplots(1, 2, figsize=(11, 4.5), sharey=False)
    x = np.arange(len(methods))
    width = 0.35

    for axis, metric_label, metric_key, scale in zip(
        axes,
        ["Top-1 hit rate (%)", "MRR (%)"],
        ["top1_hit_rate", "mrr"],
        [100.0, 100.0],
        strict=True,
    ):
        for index, part in enumerate(partitions):
            offset = (index - 0.5) * width
            values = [
                float(lookup[(part, method)].metrics[metric_key]) * scale
                for method in methods
            ]
            n_cases = int(lookup[(part, methods[0])].metrics["localized_cases"])
            axis.bar(
                x + offset,
                values,
                width,
                label=f"{partition_titles[part]} ($n$={n_cases})",
                color=["#5B7DB1", "#C55A11"][index],
                alpha=0.88,
                edgecolor="white",
                linewidth=0.5,
            )
        axis.set_title(metric_label)
        axis.set_xlabel("Coefficient")
        axis.set_ylabel(metric_label)
        axis.set_xticks(x)
        axis.set_xticklabels([BASELINE_METHOD_LABELS[m] for m in methods], rotation=20, ha="right")
        if metric_key == "top1_hit_rate":
            axis.set_ylim(0, 105)
        else:
            axis.set_ylim(0, 95)
        axis.legend(fontsize=8, loc="upper right")

    figure.suptitle(
        "SBFL coefficients: structurally localizable vs spectrally participating GT",
        fontsize=11,
    )
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120)
    plt.close(figure)


def export_sbfl_coefficient_comparison(
    dataset_dir: Path,
    *,
    output_dir: Path,
    localizable_case_rows: list[CaseLocalizationResult],
) -> SbflComparisonExports:
    """Write CSV, LaTeX table, and figure for dual-stratum SBFL comparison."""
    participating_rows = filter_spectrally_participating_rows(
        dataset_dir,
        localizable_case_rows,
    )
    combined_results = build_dual_partition_sbfl_results(
        dataset_dir,
        localizable_case_rows=localizable_case_rows,
    )

    comparison_csv = output_dir / "sbfl_coefficient_comparison.csv"
    write_sbfl_comparison_csv(comparison_csv, combined_results)

    participation_csv = output_dir / "sbfl_target_participation.csv"
    write_participation_csv(participation_csv, dataset_dir, localizable_case_rows)

    tables_dir = output_dir / "tables"
    table_tex = tables_dir / "table_sbfl_coefficient_comparison.tex"
    write_sbfl_comparison_tex(
        table_tex,
        combined_results,
        structurally_localizable_n=len(localizable_case_rows),
        spectrally_participating_n=len(participating_rows),
        spectrally_absent_n=len(localizable_case_rows) - len(participating_rows),
    )

    figures_dir = output_dir / "figures"
    figure_path = figures_dir / "sbfl_coefficient_comparison.png"
    write_sbfl_comparison_figure(figure_path, combined_results)

    return SbflComparisonExports(
        comparison_csv=comparison_csv,
        participation_csv=participation_csv,
        table_tex=table_tex,
        figure_path=figure_path,
    )
