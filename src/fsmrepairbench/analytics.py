"""Benchmark dataset analytics and reporting."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from fsmrepairbench.dataset_builder import DatasetCaseRow, is_case_complete, load_case_row
from fsmrepairbench.difficulty import category_for_score
from fsmrepairbench.mutators import MUTATION_OPERATORS

ANALYTICS_DIR_NAME = "analytics"
SUMMARY_COLUMNS: tuple[str, ...] = ("metric", "bucket", "count", "fraction")


class AnalyticsError(RuntimeError):
    """Raised when benchmark analytics cannot be generated."""


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


def load_dataset_cases(dataset_dir: Path) -> list[DatasetCaseRow]:
    """Load benchmark cases from *dataset_dir* index or case metadata."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise AnalyticsError(msg)

    index_path = dataset_dir / "index.csv"
    if index_path.is_file():
        return _load_cases_from_index(index_path)

    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"No index.csv or cases/ directory found in {dataset_dir}"
        raise AnalyticsError(msg)

    rows: list[DatasetCaseRow] = []
    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        if is_case_complete(case_dir):
            rows.append(load_case_row(case_dir))

    if not rows:
        msg = f"No complete benchmark cases found under {cases_root}"
        raise AnalyticsError(msg)

    return rows


def _load_cases_from_index(index_path: Path) -> list[DatasetCaseRow]:
    rows: list[DatasetCaseRow] = []
    with index_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"Index CSV has no header: {index_path}"
            raise AnalyticsError(msg)

        for record in reader:
            rows.append(
                DatasetCaseRow(
                    case_id=str(record["case_id"]),
                    reference_fsm_id=str(record["reference_fsm_id"]),
                    faulty_fsm_id=str(record["faulty_fsm_id"]),
                    complexity=str(record["complexity"]),  # type: ignore[arg-type]
                    state_count=int(record["state_count"]),
                    transition_count=int(record["transition_count"]),
                    event_count=int(record["event_count"]),
                    mutation_operator=str(record["mutation_operator"]),
                    difficulty_score=float(record["difficulty_score"]),
                    oracle_state_coverage=float(record["oracle_state_coverage"]),
                    oracle_transition_coverage=float(record["oracle_transition_coverage"]),
                    oracle_event_coverage=float(record["oracle_event_coverage"]),
                    reference_bpr=float(record["reference_bpr"]),
                    faulty_bpr=float(record["faulty_bpr"]),
                    bpr_delta=float(record["bpr_delta"]),
                    valid_reference=_parse_bool(record["valid_reference"]),
                    valid_faulty=_parse_bool(record["valid_faulty"]),
                )
            )
    return rows


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


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
    values: list[int],
) -> None:
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


def generate_benchmark_report(
    dataset_dir: Path,
    *,
    analytics_dir: Path | None = None,
) -> AnalyticsReportResult:
    """Generate analytics summary, report, and plots for *dataset_dir*."""
    cases = load_dataset_cases(dataset_dir)
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
