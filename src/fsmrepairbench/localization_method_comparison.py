"""RQ3 spectral-method comparison exports (Ochiai vs Tarantula vs Jaccard)."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.analytics import _save_bar_plot
from fsmrepairbench.localization_baselines import (
    BASELINE_COMPARISON_COLUMNS,
    BASELINE_METHOD_LABELS,
    BASELINE_METHODS,
    BaselineMethodResult,
    LocalizationBaselineMethod,
    aggregate_baseline_metrics,
    compute_baseline_confidence_intervals,
    localize_case_baseline,
    run_localization_baseline_comparison,
)
from fsmrepairbench.localization_campaign import (
    CaseLocalizationResult,
    LocalizationCampaignError,
)

SpectralMethod = Literal["ochiai", "tarantula", "jaccard"]

SPECTRAL_METHODS: tuple[SpectralMethod, ...] = ("ochiai", "tarantula", "jaccard")

METHOD_BY_OPERATOR_COLUMNS: tuple[str, ...] = (
    "partition",
    "mutation_operator",
    "method",
    "n_cases",
    "top1_hit_rate",
    "top3_hit_rate",
    "top5_hit_rate",
    "mrr",
)


@dataclass(frozen=True)
class MethodComparisonExports:
    """Paths written by spectral method comparison export."""

    baseline_comparison_csv: Path
    method_by_operator_csv: Path
    localizable_baseline_results: tuple[BaselineMethodResult, ...]
    figures_dir: Path
    tables_dir: Path


def _evaluate_methods_on_cases(
    dataset_dir: Path,
    case_rows: list[CaseLocalizationResult],
    *,
    methods: tuple[LocalizationBaselineMethod, ...] = BASELINE_METHODS,
) -> dict[str, list[CaseLocalizationResult]]:
    case_ids = {row.case_id for row in case_rows}
    case_dir_by_id = {case_id: dataset_dir / "cases" / case_id for case_id in case_ids}
    method_rows: dict[str, list[CaseLocalizationResult]] = {}
    for method in methods:
        if method == "ochiai":
            ochiai_by_id = {row.case_id: row for row in case_rows}
            method_rows[method] = [ochiai_by_id[row.case_id] for row in case_rows]
            continue
        method_rows[method] = [
            localize_case_baseline(case_dir_by_id[row.case_id], method=method)
            for row in case_rows
        ]
    return method_rows


def _operator_aggregate_rows(
    method_rows: dict[str, list[CaseLocalizationResult]],
    *,
    partition: str,
    methods: tuple[str, ...] | None = None,
) -> list[dict[str, str | float | int]]:
    selected = methods or tuple(method_rows)
    grouped: dict[tuple[str, str], list[CaseLocalizationResult]] = defaultdict(list)
    for method in selected:
        for row in method_rows.get(method, []):
            if row.localized and row.mutation_operator:
                grouped[(row.mutation_operator, method)].append(row)

    rows: list[dict[str, str | float | int]] = []
    for (operator, method), operator_rows in sorted(grouped.items()):
        metrics = aggregate_baseline_metrics(operator_rows)
        rows.append(
            {
                "partition": partition,
                "mutation_operator": operator,
                "method": method,
                "n_cases": int(metrics["localized_cases"]),
                "top1_hit_rate": float(metrics["top1_hit_rate"]),
                "top3_hit_rate": float(metrics["top3_hit_rate"]),
                "top5_hit_rate": float(metrics["top5_hit_rate"]),
                "mrr": float(metrics["mrr"]),
            }
        )
    return rows


def _baseline_results_for_partition(
    dataset_dir: Path,
    case_rows: list[CaseLocalizationResult],
    *,
    partition: str,
) -> list[BaselineMethodResult]:
    if partition == "transition_localizable_gt":
        return run_localization_baseline_comparison(
            dataset_dir,
            localizable_case_rows=case_rows,
        )

    method_rows_map = _evaluate_methods_on_cases(dataset_dir, case_rows)
    results: list[BaselineMethodResult] = []
    for method in BASELINE_METHODS:
        method_rows = method_rows_map[method]
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


def build_combined_baseline_comparison_rows(
    dataset_dir: Path,
    *,
    detectable_case_rows: list[CaseLocalizationResult],
    localizable_case_rows: list[CaseLocalizationResult],
) -> list[tuple[str, BaselineMethodResult]]:
    """Build baseline comparison for detectable (495) and localizable (376) partitions."""
    combined: list[tuple[str, BaselineMethodResult]] = []
    for partition, rows in (
        ("all_detectable", detectable_case_rows),
        ("transition_localizable_gt", localizable_case_rows),
    ):
        for result in _baseline_results_for_partition(dataset_dir, rows, partition=partition):
            combined.append((partition, result))
    return combined


def write_combined_baseline_comparison_csv(
    path: Path,
    results: list[tuple[str, BaselineMethodResult]],
) -> None:
    """Write multi-partition baseline comparison CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | float | int]] = []
    for partition, result in results:
        ci = {row.metric: row for row in result.confidence_intervals}
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


def write_method_by_operator_csv(
    path: Path,
    rows: list[dict[str, str | float | int]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METHOD_BY_OPERATOR_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


PARTITION_FOOTNOTE_LATEX = (
    r"\par\footnotesize \textbf{Primary localization metrics use detectable-only "
    r"eligibility} (\textbf{505/1{,}000} oracle-saturated cases excluded). "
    r"Transition-localizable ground truth ($n=376$) is the construct-valid partition; "
    r"all-detectable ($n=495$) mixes rankable and non-rankable faults."
)


def write_dual_partition_spectral_baseline_tex(
    path: Path,
    combined_results: list[tuple[str, BaselineMethodResult]],
) -> None:
    """LaTeX table: Ochiai/Tarantula/Jaccard on all-detectable and localizable partitions."""
    lines = [
        "% Auto-generated by localization_method_comparison",
        "\\begin{table}[t]",
        "\\caption{Spectral localization baselines on oracle-detectable faults: "
        "all-detectable pool ($n=495$) versus transition-localizable ground truth "
        "($n=376$). \\textbf{Primary headline metrics use the localizable partition}; "
        "the all-detectable row is a conservative transparency total. "
        "Bracketed ranges are bootstrap 95\\% confidence intervals (10{,}000 resamples; seed~44).}",
        "\\label{tab:localization-baselines-dual}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}llrrrrr@{}}",
        "\\toprule",
        "Method & Partition & $n$ & Top-1 & Top-3 & Top-5 & MRR \\\\",
        "\\midrule",
    ]
    for partition, result in combined_results:
        if result.method not in SPECTRAL_METHODS:
            continue
        ci = {row.metric: row for row in result.confidence_intervals}
        label = "Localizable GT" if partition == "transition_localizable_gt" else "All detectable"
        lines.append(
            f"{result.display_name} & {label} & {int(result.metrics['localized_cases'])} & "
            f"{_pct_with_ci(float(result.metrics['top1_hit_rate']), ci.get('top_1_hit_rate'))} & "
            f"{_pct_with_ci(float(result.metrics['top3_hit_rate']), ci.get('top_3_hit_rate'))} & "
            f"{_pct_with_ci(float(result.metrics['top5_hit_rate']), ci.get('top_5_hit_rate'))} & "
            f"{_mrr_with_ci(float(result.metrics['mrr']), ci.get('mrr'))} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", PARTITION_FOOTNOTE_LATEX, "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _pct_with_ci(rate: float, ci_row) -> str:
    if ci_row is None:
        return _pct(rate)
    return (
        f"{_pct(rate)} "
        f"[{100.0 * ci_row.ci95_low:.1f}--{100.0 * ci_row.ci95_high:.1f}]"
    )


def _mrr_with_ci(mrr: float, ci_row) -> str:
    if ci_row is None:
        return f"{mrr:.3f}"
    return f"{mrr:.3f} [{ci_row.ci95_low:.3f}--{ci_row.ci95_high:.3f}]"


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def write_method_by_operator_tex(
    path: Path,
    rows: list[dict[str, str | float | int]],
    *,
    partition: str = "transition_localizable_gt",
) -> None:
    """LaTeX table: Ochiai vs Tarantula vs Jaccard top-5 by operator (localizable GT)."""
    partition_rows = [
        row for row in rows if row["partition"] == partition and int(row["n_cases"]) > 0
    ]
    operators = sorted({str(row["mutation_operator"]) for row in partition_rows})
    if not operators:
        return

    lines = [
        "% Auto-generated by localization_method_comparison",
        "\\begin{table}[t]",
        "\\caption{Spectral localization top-5 hit rate by mutation operator on "
        "transition-localizable ground truth ($n=376$ of 495 detectable; shallow-oracle spectra). "
        "Ochiai, Tarantula, and Jaccard share the same detectable case pool per operator.}",
        "\\label{tab:localization-method-by-operator}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lrrr@{}}",
        "\\toprule",
        "Operator & Ochiai & Tarantula & Jaccard \\\\",
        "\\midrule",
    ]
    lookup = {
        (str(row["mutation_operator"]), str(row["method"])): float(row["top5_hit_rate"])
        for row in partition_rows
    }
    for operator in operators:
        safe = operator.replace("_", "\\_")
        cells = [_pct(lookup.get((operator, method), 0.0)) for method in SPECTRAL_METHODS]
        lines.append(f"{safe} & {' & '.join(cells)} \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _grouped_bar_plot(
    path: Path,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    group_labels: list[str],
    series: dict[str, list[float]],
) -> None:
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError as exc:
        msg = f"Plotting dependencies missing for method comparison figures: {exc}"
        raise LocalizationCampaignError(msg) from exc

    methods = list(series)
    x = np.arange(len(group_labels))
    width = 0.8 / max(len(methods), 1)
    colors = {"ochiai": "#4472C4", "tarantula": "#ED7D31", "jaccard": "#70AD47"}
    figure, axis = plt.subplots(figsize=(10, 5))
    for index, method in enumerate(methods):
        offset = (index - (len(methods) - 1) / 2) * width
        axis.bar(
            x + offset,
            series[method],
            width,
            label=BASELINE_METHOD_LABELS.get(method, method),
            color=colors.get(method, None),
        )
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.set_xticks(x)
    axis.set_xticklabels(group_labels, rotation=45, ha="right")
    axis.legend()
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def write_method_comparison_figures(
    figures_dir: Path,
    *,
    localizable_results: list[BaselineMethodResult],
    operator_rows: list[dict[str, str | float | int]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    spectral = [result for result in localizable_results if result.method in SPECTRAL_METHODS]
    if spectral:
        _grouped_bar_plot(
            figures_dir / "method_comparison_topk_localizable.png",
            title="Spectral Method Top-k Hit Rates (Localizable GT, n=376)",
            xlabel="Metric",
            ylabel="Hit Rate (%)",
            group_labels=["Top-1", "Top-3", "Top-5"],
            series={
                result.method: [
                    100.0 * float(result.metrics["top1_hit_rate"]),
                    100.0 * float(result.metrics["top3_hit_rate"]),
                    100.0 * float(result.metrics["top5_hit_rate"]),
                ]
                for result in spectral
            },
        )
        _save_bar_plot(
            figures_dir / "method_comparison_mrr_localizable.png",
            title="Spectral Method MRR (Localizable GT, n=376)",
            xlabel="Method",
            ylabel="MRR",
            labels=[result.display_name for result in spectral],
            values=[float(result.metrics["mrr"]) for result in spectral],
        )

    partition_rows = [
        row
        for row in operator_rows
        if row["partition"] == "transition_localizable_gt" and int(row["n_cases"]) > 0
    ]
    operators = sorted({str(row["mutation_operator"]) for row in partition_rows})
    if operators:
        lookup = {
            (str(row["mutation_operator"]), str(row["method"])): float(row["top5_hit_rate"])
            for row in partition_rows
        }
        _grouped_bar_plot(
            figures_dir / "method_comparison_top5_by_operator_localizable.png",
            title="Top-5 Hit Rate by Operator (Localizable GT)",
            xlabel="Mutation Operator",
            ylabel="Top-5 Hit Rate (%)",
            group_labels=[operator.replace("_", " ") for operator in operators],
            series={
                method: [100.0 * lookup.get((operator, method), 0.0) for operator in operators]
                for method in SPECTRAL_METHODS
            },
        )


def export_localization_method_comparison(
    dataset_dir: Path,
    *,
    output_dir: Path,
    detectable_case_rows: list[CaseLocalizationResult],
    localizable_case_rows: list[CaseLocalizationResult],
    paper_export_dir: Path | None = None,
) -> MethodComparisonExports:
    """Write spectral method comparison CSVs, tables, and figures."""
    combined_results = build_combined_baseline_comparison_rows(
        dataset_dir,
        detectable_case_rows=detectable_case_rows,
        localizable_case_rows=localizable_case_rows,
    )
    localizable_results = [
        result for partition, result in combined_results if partition == "transition_localizable_gt"
    ]

    detectable_method_rows = _evaluate_methods_on_cases(
        dataset_dir,
        detectable_case_rows,
        methods=SPECTRAL_METHODS,
    )
    localizable_method_rows = _evaluate_methods_on_cases(
        dataset_dir,
        localizable_case_rows,
        methods=SPECTRAL_METHODS,
    )
    operator_rows = _operator_aggregate_rows(
        detectable_method_rows,
        partition="all_detectable",
        methods=SPECTRAL_METHODS,
    )
    operator_rows.extend(
        _operator_aggregate_rows(
            localizable_method_rows,
            partition="transition_localizable_gt",
            methods=SPECTRAL_METHODS,
        )
    )

    baseline_csv = output_dir / "localization_baseline_comparison.csv"
    write_combined_baseline_comparison_csv(baseline_csv, combined_results)

    operator_csv = output_dir / "localization_method_by_operator.csv"
    write_method_by_operator_csv(operator_csv, operator_rows)

    figures_dir = output_dir / "figures"
    tables_dir = output_dir / "tables"
    write_method_comparison_figures(
        figures_dir,
        localizable_results=localizable_results,
        operator_rows=operator_rows,
    )
    write_method_by_operator_tex(
        tables_dir / "table_localization_method_by_operator.tex",
        operator_rows,
    )
    write_dual_partition_spectral_baseline_tex(
        tables_dir / "table_localization_baselines_dual.tex",
        combined_results,
    )

    resolved_paper = paper_export_dir
    if resolved_paper is None:
        monorepo_root = output_dir.parent.parent.parent
        candidate = monorepo_root / "paper1" / "results" / output_dir.name
        if candidate.parent.is_dir():
            resolved_paper = candidate

    if resolved_paper is not None:
        resolved_paper.mkdir(parents=True, exist_ok=True)
        write_combined_baseline_comparison_csv(
            resolved_paper / "localization_baseline_comparison.csv",
            combined_results,
        )
        write_method_by_operator_csv(
            resolved_paper / "localization_method_by_operator.csv",
            operator_rows,
        )
        write_method_comparison_figures(
            resolved_paper / "figures",
            localizable_results=localizable_results,
            operator_rows=operator_rows,
        )
        write_method_by_operator_tex(
            resolved_paper / "tables" / "table_localization_method_by_operator.tex",
            operator_rows,
        )
        write_dual_partition_spectral_baseline_tex(
            resolved_paper / "tables" / "table_localization_baselines_dual.tex",
            combined_results,
        )

    return MethodComparisonExports(
        baseline_comparison_csv=baseline_csv,
        method_by_operator_csv=operator_csv,
        localizable_baseline_results=tuple(localizable_results),
        figures_dir=figures_dir,
        tables_dir=tables_dir,
    )
