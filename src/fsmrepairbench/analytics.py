"""Benchmark dataset analytics and reporting."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import load_cohort_manifest
from fsmrepairbench.dataset_builder import DatasetBuilderError, DatasetCaseRow, load_dataset_cases
from fsmrepairbench.difficulty import category_for_score
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.statistics import (
    append_ci_section_to_report,
    compute_rq2_confidence_intervals,
    write_confidence_interval_exports,
)

ANALYTICS_DIR_NAME = "analytics"
SUMMARY_COLUMNS: tuple[str, ...] = ("metric", "bucket", "count", "fraction")
ANALYSIS_SUMMARY_COLUMNS: tuple[str, ...] = ("metric", "value")
DISTRIBUTION_COLUMNS: tuple[str, ...] = ("metric", "bucket", "count", "fraction")
CORRELATION_COLUMNS: tuple[str, ...] = ("feature_x", "feature_y", "pearson_r", "n")
NUMERIC_CASE_FEATURES: tuple[str, ...] = (
    "state_count",
    "transition_count",
    "event_count",
    "oracle_state_coverage",
    "oracle_transition_coverage",
    "oracle_event_coverage",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "difficulty_score",
)
REPAIR_DIFFICULTY_TARGETS: tuple[str, ...] = ("difficulty_score", "bpr_delta")


class AnalyticsError(RuntimeError):
    """Raised when benchmark analytics cannot be generated."""


def _pyplot():
    """Import matplotlib lazily so core CLI commands avoid plotting dependencies."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        msg = (
            "Analytics plotting dependencies are missing. "
            f"Install them with: pip install -e '.[analytics]' ({exc})"
        )
        raise AnalyticsError(msg) from exc
    return plt


@dataclass(frozen=True)
class BenchmarkAnalytics:
    """Computed diversity metrics for a benchmark dataset."""

    case_count: int
    state_distribution: dict[int, int]
    transition_distribution: dict[int, int]
    mutation_frequencies: dict[str, int]
    difficulty_category_distribution: dict[str, int]
    difficulty_score_values: tuple[float, ...]
    oracle_state_coverage_distribution: dict[str, int]
    oracle_transition_coverage_distribution: dict[str, int]
    oracle_event_coverage_distribution: dict[str, int]


@dataclass(frozen=True)
class AnalyticsReportResult:
    """Paths written by a benchmark analytics run."""

    dataset_dir: Path
    analytics_dir: Path
    summary_path: Path
    report_path: Path
    plots_dir: Path
    analytics: BenchmarkAnalytics


@dataclass(frozen=True)
class AnalysisReportResult:
    """Paths written by a publication-oriented benchmark analysis run."""

    dataset_dir: Path
    output_dir: Path
    summary_path: Path
    distributions_path: Path
    correlations_path: Path
    figures_dir: Path
    markdown_path: Path
    case_count: int


def _coverage_key(value: float) -> str:
    return f"{value:.4f}"


def compute_benchmark_analytics(cases: list[DatasetCaseRow]) -> BenchmarkAnalytics:
    """Compute diversity metrics from benchmark case rows."""
    if not cases:
        msg = "Cannot compute analytics for an empty dataset"
        raise AnalyticsError(msg)

    state_distribution = Counter(case.state_count for case in cases)
    transition_distribution = Counter(case.transition_count for case in cases)
    mutation_frequencies = Counter(case.mutation_operator for case in cases)
    difficulty_categories = Counter(category_for_score(case.difficulty_score) for case in cases)
    difficulty_scores = tuple(case.difficulty_score for case in cases)
    oracle_state = Counter(_coverage_key(case.oracle_state_coverage) for case in cases)
    oracle_transition = Counter(_coverage_key(case.oracle_transition_coverage) for case in cases)
    oracle_event = Counter(_coverage_key(case.oracle_event_coverage) for case in cases)

    for operator in MUTATION_OPERATORS:
        mutation_frequencies.setdefault(operator, 0)

    return BenchmarkAnalytics(
        case_count=len(cases),
        state_distribution=dict(sorted(state_distribution.items())),
        transition_distribution=dict(sorted(transition_distribution.items())),
        mutation_frequencies=dict(sorted(mutation_frequencies.items())),
        difficulty_category_distribution=dict(
            sorted(difficulty_categories.items(), key=lambda item: item[0])
        ),
        difficulty_score_values=difficulty_scores,
        oracle_state_coverage_distribution=dict(sorted(oracle_state.items())),
        oracle_transition_coverage_distribution=dict(sorted(oracle_transition.items())),
        oracle_event_coverage_distribution=dict(sorted(oracle_event.items())),
    )


def _distribution_rows(
    metric: str,
    distribution: dict[Any, int],
    total: int,
) -> list[dict[str, str | float]]:
    rows: list[dict[str, str | float]] = []
    for bucket, count in distribution.items():
        rows.append(
            {
                "metric": metric,
                "bucket": str(bucket),
                "count": count,
                "fraction": round(count / total, 6),
            }
        )
    return rows


def write_summary_csv(path: Path, analytics: BenchmarkAnalytics) -> None:
    """Write distribution summary CSV for *analytics*."""
    total = analytics.case_count
    rows: list[dict[str, str | float]] = []
    rows.extend(_distribution_rows("state_count", analytics.state_distribution, total))
    rows.extend(_distribution_rows("transition_count", analytics.transition_distribution, total))
    rows.extend(_distribution_rows("mutation_operator", analytics.mutation_frequencies, total))
    rows.extend(
        _distribution_rows(
            "difficulty_category",
            analytics.difficulty_category_distribution,
            total,
        )
    )
    rows.extend(
        _distribution_rows(
            "oracle_state_coverage",
            analytics.oracle_state_coverage_distribution,
            total,
        )
    )
    rows.extend(
        _distribution_rows(
            "oracle_transition_coverage",
            analytics.oracle_transition_coverage_distribution,
            total,
        )
    )
    rows.extend(
        _distribution_rows(
            "oracle_event_coverage",
            analytics.oracle_event_coverage_distribution,
            total,
        )
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _numeric_summary(values: tuple[float, ...]) -> dict[str, float]:
    if not values:
        return {"min": 0.0, "max": 0.0, "mean": 0.0}
    return {
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "mean": round(sum(values) / len(values), 4),
    }


def _distribution_values(distribution: dict[Any, int]) -> tuple[float, ...]:
    values: list[float] = []
    for bucket, count in distribution.items():
        values.extend([float(bucket)] * count)
    return tuple(values)


def _float_distribution_values(distribution: dict[str, int]) -> tuple[float, ...]:
    return _distribution_values({float(key): count for key, count in distribution.items()})


def write_report_json(path: Path, *, dataset_dir: Path, analytics: BenchmarkAnalytics) -> None:
    """Write analytics report JSON."""
    payload = {
        "dataset_dir": str(dataset_dir),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "case_count": analytics.case_count,
        "distributions": {
            "state_count": analytics.state_distribution,
            "transition_count": analytics.transition_distribution,
            "mutation_operator": analytics.mutation_frequencies,
            "difficulty_category": analytics.difficulty_category_distribution,
            "oracle_state_coverage": analytics.oracle_state_coverage_distribution,
            "oracle_transition_coverage": analytics.oracle_transition_coverage_distribution,
            "oracle_event_coverage": analytics.oracle_event_coverage_distribution,
        },
        "statistics": {
            "state_count": _numeric_summary(_distribution_values(analytics.state_distribution)),
            "transition_count": _numeric_summary(
                _distribution_values(analytics.transition_distribution)
            ),
            "difficulty_score": _numeric_summary(analytics.difficulty_score_values),
            "oracle_state_coverage": _numeric_summary(
                _float_distribution_values(analytics.oracle_state_coverage_distribution)
            ),
            "oracle_transition_coverage": _numeric_summary(
                _float_distribution_values(analytics.oracle_transition_coverage_distribution)
            ),
            "oracle_event_coverage": _numeric_summary(
                _float_distribution_values(analytics.oracle_event_coverage_distribution)
            ),
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _save_bar_plot(
    path: Path,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    labels: list[str],
    values: list[int] | list[float],
) -> None:
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.bar(labels, values, color="#4472C4")
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    axis.tick_params(axis="x", rotation=45)
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _save_histogram(
    path: Path,
    *,
    title: str,
    xlabel: str,
    values: list[float],
    bins: int = 10,
) -> None:
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(8, 5))
    axis.hist(values, bins=bins, color="#70AD47", edgecolor="white")
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel("Frequency")
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def write_plots(plots_dir: Path, analytics: BenchmarkAnalytics) -> None:
    """Write matplotlib plots describing dataset diversity."""
    plots_dir.mkdir(parents=True, exist_ok=True)

    state_labels = [str(key) for key in analytics.state_distribution]
    state_values = list(analytics.state_distribution.values())
    _save_bar_plot(
        plots_dir / "states_distribution.png",
        title="State Count Distribution",
        xlabel="States",
        ylabel="Cases",
        labels=state_labels,
        values=state_values,
    )

    transition_labels = [str(key) for key in analytics.transition_distribution]
    transition_values = list(analytics.transition_distribution.values())
    _save_bar_plot(
        plots_dir / "transitions_distribution.png",
        title="Transition Count Distribution",
        xlabel="Transitions",
        ylabel="Cases",
        labels=transition_labels,
        values=transition_values,
    )

    mutation_labels = [key for key, count in analytics.mutation_frequencies.items() if count > 0]
    mutation_values = [analytics.mutation_frequencies[label] for label in mutation_labels]
    _save_bar_plot(
        plots_dir / "mutation_frequencies.png",
        title="Mutation Operator Frequencies",
        xlabel="Mutation Operator",
        ylabel="Cases",
        labels=mutation_labels,
        values=mutation_values,
    )

    _save_histogram(
        plots_dir / "difficulty_distribution.png",
        title="Difficulty Score Distribution",
        xlabel="Difficulty Score",
        values=list(analytics.difficulty_score_values),
        bins=min(10, max(3, len(set(analytics.difficulty_score_values)))),
    )

    plt = _pyplot()
    figure, axes = plt.subplots(1, 3, figsize=(12, 4))
    coverage_sets = (
        ("State", analytics.oracle_state_coverage_distribution),
        ("Transition", analytics.oracle_transition_coverage_distribution),
        ("Event", analytics.oracle_event_coverage_distribution),
    )
    for axis, (label, distribution) in zip(axes, coverage_sets, strict=True):
        keys = [float(key) for key in distribution]
        counts = list(distribution.values())
        axis.bar([str(key) for key in keys], counts, color="#ED7D31")
        axis.set_title(f"{label} Oracle Coverage")
        axis.set_xlabel("Coverage")
        axis.set_ylabel("Cases")
        axis.tick_params(axis="x", rotation=45)
    figure.tight_layout()
    figure.savefig(plots_dir / "oracle_coverage_distribution.png", dpi=120)
    plt.close(figure)


def _bpr_bucket(value: float) -> str:
    return f"{value:.2f}"


def _case_numeric_values(case: DatasetCaseRow) -> dict[str, float]:
    return {
        "state_count": float(case.state_count),
        "transition_count": float(case.transition_count),
        "event_count": float(case.event_count),
        "oracle_state_coverage": case.oracle_state_coverage,
        "oracle_transition_coverage": case.oracle_transition_coverage,
        "oracle_event_coverage": case.oracle_event_coverage,
        "reference_bpr": case.reference_bpr,
        "faulty_bpr": case.faulty_bpr,
        "bpr_delta": case.bpr_delta,
        "difficulty_score": case.difficulty_score,
    }


def _pearson_correlation(left: list[float], right: list[float]) -> float:
    if len(left) != len(right) or len(left) < 2:
        return 0.0
    mean_left = sum(left) / len(left)
    mean_right = sum(right) / len(right)
    left_centered = [value - mean_left for value in left]
    right_centered = [value - mean_right for value in right]
    numerator = sum(a * b for a, b in zip(left_centered, right_centered, strict=True))
    left_den = math.sqrt(sum(value * value for value in left_centered))
    right_den = math.sqrt(sum(value * value for value in right_centered))
    denominator = left_den * right_den
    if denominator == 0.0:
        return 0.0
    return numerator / denominator


def compute_mutation_detection_rates(cases: list[DatasetCaseRow]) -> dict[str, float]:
    """Return per-operator oracle detection rates from existing case rows."""
    totals: Counter[str] = Counter()
    detected: Counter[str] = Counter()
    for case in cases:
        operator = case.mutation_operator
        totals[operator] += 1
        if case.bpr_delta > 0.0:
            detected[operator] += 1
    rates: dict[str, float] = {}
    for operator in MUTATION_OPERATORS:
        total = totals[operator]
        rates[operator] = round(detected[operator] / total, 6) if total else 0.0
    for operator, total in sorted(totals.items()):
        if operator not in rates:
            rates[operator] = round(detected[operator] / total, 6)
    return rates


def compute_feature_correlations(cases: list[DatasetCaseRow]) -> list[dict[str, str | float | int]]:
    """Compute Pearson correlations between FSM features and repair-difficulty proxies."""
    values_by_feature = {
        feature: [row[feature] for row in (_case_numeric_values(case) for case in cases)]
        for feature in NUMERIC_CASE_FEATURES
    }
    rows: list[dict[str, str | float | int]] = []
    predictors = [feature for feature in NUMERIC_CASE_FEATURES if feature not in REPAIR_DIFFICULTY_TARGETS]
    for target in REPAIR_DIFFICULTY_TARGETS:
        target_values = values_by_feature[target]
        for feature in predictors:
            rows.append(
                {
                    "feature_x": feature,
                    "feature_y": target,
                    "pearson_r": round(_pearson_correlation(values_by_feature[feature], target_values), 6),
                    "n": len(cases),
                }
            )
    return rows


def _load_machine_type_distribution(dataset_dir: Path) -> dict[str, int] | None:
    feature_matrix = dataset_dir / "feature_matrix.csv"
    if not feature_matrix.is_file():
        return None
    counts: Counter[str] = Counter()
    with feature_matrix.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "machine_type" not in reader.fieldnames:
            return None
        for row in reader:
            counts[str(row["machine_type"])] += 1
    return dict(sorted(counts.items())) if counts else None


def _family_distribution(cases: list[DatasetCaseRow], dataset_dir: Path) -> dict[str, int]:
    machine_types = _load_machine_type_distribution(dataset_dir)
    if machine_types is not None:
        return machine_types
    return dict(Counter(case.complexity for case in cases))


def write_analysis_summary_csv(path: Path, *, cases: list[DatasetCaseRow], analytics: BenchmarkAnalytics) -> None:
    """Write high-level summary metrics for a benchmark analysis run."""
    detection_rates = compute_mutation_detection_rates(cases)
    overall_detected = sum(1 for case in cases if case.bpr_delta > 0.0)
    difficulty_values = [case.difficulty_score for case in cases]
    reference_bpr_values = [case.reference_bpr for case in cases]
    faulty_bpr_values = [case.faulty_bpr for case in cases]
    rows: list[dict[str, str | float]] = [
        {"metric": "case_count", "value": analytics.case_count},
        {"metric": "overall_detection_rate", "value": round(overall_detected / len(cases), 6)},
        {
            "metric": "mean_difficulty_score",
            "value": round(sum(difficulty_values) / len(difficulty_values), 6),
        },
        {
            "metric": "mean_reference_bpr",
            "value": round(sum(reference_bpr_values) / len(reference_bpr_values), 6),
        },
        {
            "metric": "mean_faulty_bpr",
            "value": round(sum(faulty_bpr_values) / len(faulty_bpr_values), 6),
        },
        {
            "metric": "mean_bpr_delta",
            "value": round(sum(case.bpr_delta for case in cases) / len(cases), 6),
        },
    ]
    for operator, rate in sorted(detection_rates.items()):
        if rate > 0.0 or analytics.mutation_frequencies.get(operator, 0) > 0:
            rows.append({"metric": f"detection_rate_{operator}", "value": rate})

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ANALYSIS_SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def write_distributions_csv(
    path: Path,
    *,
    cases: list[DatasetCaseRow],
    analytics: BenchmarkAnalytics,
    dataset_dir: Path,
) -> None:
    """Write bucketed distributions for publication analysis."""
    total = analytics.case_count
    rows: list[dict[str, str | float]] = []
    rows.extend(_distribution_rows("state_count", analytics.state_distribution, total))
    rows.extend(_distribution_rows("transition_count", analytics.transition_distribution, total))
    rows.extend(_distribution_rows("mutation_operator", analytics.mutation_frequencies, total))
    rows.extend(
        _distribution_rows(
            "difficulty_category",
            analytics.difficulty_category_distribution,
            total,
        )
    )
    rows.extend(
        _distribution_rows(
            "oracle_state_coverage",
            analytics.oracle_state_coverage_distribution,
            total,
        )
    )
    rows.extend(
        _distribution_rows(
            "oracle_transition_coverage",
            analytics.oracle_transition_coverage_distribution,
            total,
        )
    )
    rows.extend(
        _distribution_rows(
            "oracle_event_coverage",
            analytics.oracle_event_coverage_distribution,
            total,
        )
    )

    reference_bpr = Counter(_bpr_bucket(case.reference_bpr) for case in cases)
    faulty_bpr = Counter(_bpr_bucket(case.faulty_bpr) for case in cases)
    rows.extend(_distribution_rows("reference_bpr", dict(sorted(reference_bpr.items())), total))
    rows.extend(_distribution_rows("faulty_bpr", dict(sorted(faulty_bpr.items())), total))

    family_distribution = _family_distribution(cases, dataset_dir)
    family_metric = (
        "machine_type" if (dataset_dir / "feature_matrix.csv").is_file() else "complexity_tier"
    )
    rows.extend(_distribution_rows(family_metric, family_distribution, total))

    detection_rates = compute_mutation_detection_rates(cases)
    operator_totals = Counter(case.mutation_operator for case in cases)
    for operator, rate in sorted(detection_rates.items()):
        if operator_totals[operator] == 0:
            continue
        rows.append(
            {
                "metric": "mutation_detection_rate",
                "bucket": operator,
                "count": int(round(rate * operator_totals[operator])),
                "fraction": rate,
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(DISTRIBUTION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def write_correlations_csv(path: Path, cases: list[DatasetCaseRow]) -> None:
    """Write feature-to-difficulty correlation table."""
    rows = compute_feature_correlations(cases)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CORRELATION_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def write_analysis_figures(
    figures_dir: Path,
    *,
    dataset_dir: Path,
    cases: list[DatasetCaseRow],
    analytics: BenchmarkAnalytics,
) -> None:
    """Write publication figures for benchmark analysis."""
    write_plots(figures_dir, analytics)

    reference_values = [case.reference_bpr for case in cases]
    faulty_values = [case.faulty_bpr for case in cases]
    _save_histogram(
        figures_dir / "reference_bpr_distribution.png",
        title="Reference BPR Distribution",
        xlabel="Reference BPR",
        values=reference_values,
        bins=min(10, max(3, len(set(reference_values)))),
    )
    _save_histogram(
        figures_dir / "faulty_bpr_distribution.png",
        title="Faulty BPR Distribution",
        xlabel="Faulty BPR",
        values=faulty_values,
        bins=min(10, max(3, len(set(faulty_values)))),
    )

    detection_rates = compute_mutation_detection_rates(cases)
    active_operators = [
        operator
        for operator, count in analytics.mutation_frequencies.items()
        if count > 0 and operator in detection_rates
    ]
    _save_bar_plot(
        figures_dir / "mutation_detection_rates.png",
        title="Mutation Detection Rates",
        xlabel="Mutation Operator",
        ylabel="Detection Rate",
        labels=active_operators,
        values=[round(detection_rates[operator] * 100.0, 1) for operator in active_operators],
    )

    family_distribution = _family_distribution(cases, dataset_dir)
    _save_bar_plot(
        figures_dir / "fsm_family_distribution.png",
        title="FSM Family Distribution",
        xlabel="Family",
        ylabel="Cases",
        labels=list(family_distribution.keys()),
        values=list(family_distribution.values()),
    )


def write_analysis_markdown(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    cases: list[DatasetCaseRow],
    analytics: BenchmarkAnalytics,
) -> None:
    """Write a publication-ready Markdown analysis report."""
    detection_rates = compute_mutation_detection_rates(cases)
    overall_detected = sum(1 for case in cases if case.bpr_delta > 0.0)
    correlations = compute_feature_correlations(cases)
    top_correlations = sorted(correlations, key=lambda row: abs(float(row["pearson_r"])), reverse=True)[:8]
    family_metric = (
        "machine type"
        if (dataset_dir / "feature_matrix.csv").is_file()
        else "complexity tier"
    )
    family_distribution = _family_distribution(cases, dataset_dir)
    generated_at = datetime.now(tz=UTC).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# FSMRepairBench Dataset Analysis Report",
        "",
        f"**Dataset:** `{dataset_dir}`  ",
        f"**Generated:** {generated_at}  ",
        f"**Cases analyzed:** {analytics.case_count}",
        "",
        "## Abstract",
        "",
        (
            "This report summarizes structural diversity, oracle coverage, mutation "
            "operator usage, behavioural pass rate (BPR) distributions, and "
            "correlations between FSM features and repair-difficulty proxies for "
            "the benchmark dataset. All statistics are derived from existing packaged "
            "case outputs (`case_metadata.json` / index rows) without introducing "
            "new benchmark features."
        ),
        "",
        "## Summary",
        "",
        f"- Overall mutation detection rate: **{overall_detected / len(cases):.2%}**",
        (
            f"- Mean difficulty score: **{sum(case.difficulty_score for case in cases) / len(cases):.2f}**"
        ),
        (
            f"- Mean faulty BPR: **{sum(case.faulty_bpr for case in cases) / len(cases):.4f}**"
        ),
        (
            f"- Mean BPR delta: **{sum(case.bpr_delta for case in cases) / len(cases):.4f}**"
        ),
        "",
        "## Mutation Operator Frequencies",
        "",
        "| Operator | Cases | Share | Detection Rate |",
        "|---|---:|---:|---:|",
    ]
    for operator, count in sorted(analytics.mutation_frequencies.items()):
        if count <= 0:
            continue
        share = count / analytics.case_count
        lines.append(
            f"| `{operator}` | {count} | {share:.2%} | {detection_rates.get(operator, 0.0):.2%} |"
        )

    lines.extend(
        [
            "",
            "## Coverage and BPR Distributions",
            "",
            "Oracle coverage and BPR bucket counts are exported in "
            f"`{output_dir / 'distributions.csv'}`. Key figures:",
            "",
            "![Oracle coverage](figures/oracle_coverage_distribution.png)",
            "",
            "![Reference BPR](figures/reference_bpr_distribution.png)",
            "",
            "![Faulty BPR](figures/faulty_bpr_distribution.png)",
            "",
            f"## FSM Family Distribution ({family_metric})",
            "",
            "| Family | Cases | Share |",
            "|---|---:|---:|",
        ]
    )
    for family, count in family_distribution.items():
        lines.append(f"| `{family}` | {count} | {count / analytics.case_count:.2%} |")

    lines.extend(
        [
            "",
            "![FSM family distribution](figures/fsm_family_distribution.png)",
            "",
            "## Correlations with Repair Difficulty",
            "",
            (
                "Pearson correlations relate structural/oracle features to "
                "`difficulty_score` and `bpr_delta`. Full results: "
                f"`{output_dir / 'correlations.csv'}`."
            ),
            "",
            "| Feature | Target | *r* |",
            "|---|---|---:|",
        ]
    )
    for row in top_correlations:
        lines.append(
            f"| `{row['feature_x']}` | `{row['feature_y']}` | {float(row['pearson_r']):+.3f} |"
        )

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Summary metrics: `{output_dir / 'summary.csv'}`",
            f"- Confidence intervals: `{output_dir / 'confidence_intervals.csv'}`",
            f"- Distributions: `{output_dir / 'distributions.csv'}`",
            f"- Correlations: `{output_dir / 'correlations.csv'}`",
            f"- Figures: `{output_dir / 'figures'}/`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_analysis_report(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    max_cases: int | None = None,
    cohort_path: Path | None = None,
    release_label: str = "v0.2.0-analysis",
) -> AnalysisReportResult:
    """Generate publication-oriented analysis artifacts for *dataset_dir*."""
    try:
        cases = load_dataset_cases(dataset_dir)
    except DatasetBuilderError as exc:
        raise AnalyticsError(str(exc)) from exc

    if cohort_path is not None:
        allowed = set(load_cohort_manifest(cohort_path))
        cases = [case for case in cases if case.case_id in allowed]
        if not cases:
            msg = f"No cases from {dataset_dir} appear in cohort {cohort_path}"
            raise AnalyticsError(msg)

    if max_cases is not None:
        if max_cases < 1:
            msg = "max_cases must be at least 1"
            raise AnalyticsError(msg)
        cases = cases[:max_cases]

    if not cases:
        msg = "Cannot compute analytics for an empty dataset"
        raise AnalyticsError(msg)

    analytics = compute_benchmark_analytics(cases)
    resolved_output = output_dir or Path("results") / "analysis"
    figures_dir = resolved_output / "figures"
    summary_path = resolved_output / "summary.csv"
    distributions_path = resolved_output / "distributions.csv"
    correlations_path = resolved_output / "correlations.csv"
    markdown_path = resolved_output / "report.md"

    write_analysis_summary_csv(summary_path, cases=cases, analytics=analytics)
    write_distributions_csv(
        distributions_path,
        cases=cases,
        analytics=analytics,
        dataset_dir=dataset_dir,
    )
    write_correlations_csv(correlations_path, cases)
    write_analysis_figures(
        figures_dir,
        dataset_dir=dataset_dir,
        cases=cases,
        analytics=analytics,
    )
    write_analysis_markdown(
        markdown_path,
        dataset_dir=dataset_dir,
        output_dir=resolved_output,
        cases=cases,
        analytics=analytics,
    )

    ci_rows = compute_rq2_confidence_intervals(cases)
    write_confidence_interval_exports(
        resolved_output,
        campaign=release_label,
        rows=ci_rows,
    )
    append_ci_section_to_report(markdown_path, ci_rows)

    return AnalysisReportResult(
        dataset_dir=dataset_dir,
        output_dir=resolved_output,
        summary_path=summary_path,
        distributions_path=distributions_path,
        correlations_path=correlations_path,
        figures_dir=figures_dir,
        markdown_path=markdown_path,
        case_count=analytics.case_count,
    )


def generate_benchmark_report(
    dataset_dir: Path,
    *,
    analytics_dir: Path | None = None,
) -> AnalyticsReportResult:
    """Generate analytics summary, report, and plots for *dataset_dir*."""
    try:
        cases = load_dataset_cases(dataset_dir)
    except DatasetBuilderError as exc:
        raise AnalyticsError(str(exc)) from exc
    analytics = compute_benchmark_analytics(cases)

    output_dir = analytics_dir or (dataset_dir / ANALYTICS_DIR_NAME)
    plots_dir = output_dir / "plots"
    summary_path = output_dir / "summary.csv"
    report_path = output_dir / "report.json"

    write_summary_csv(summary_path, analytics)
    write_report_json(report_path, dataset_dir=dataset_dir, analytics=analytics)
    write_plots(plots_dir, analytics)

    return AnalyticsReportResult(
        dataset_dir=dataset_dir,
        analytics_dir=output_dir,
        summary_path=summary_path,
        report_path=report_path,
        plots_dir=plots_dir,
        analytics=analytics,
    )
