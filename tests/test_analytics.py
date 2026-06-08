"""Tests for benchmark analytics."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.analytics import (
    SUMMARY_COLUMNS,
    AnalyticsError,
    compute_benchmark_analytics,
    generate_benchmark_report,
)
from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import build_dataset, load_dataset_cases

runner = CliRunner()


def _build_sample_dataset(output_dir: Path, *, size: int = 6) -> Path:
    build_dataset(size=size, seed=42, output_dir=output_dir, workers=1, resume=False)
    return output_dir


def test_load_dataset_cases_from_index(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=4)
    cases = load_dataset_cases(dataset_dir)

    assert len(cases) == 4
    assert cases[0].case_id == "case_000001"


def test_compute_benchmark_analytics_includes_mutation_frequencies(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=9)
    analytics = compute_benchmark_analytics(load_dataset_cases(dataset_dir))

    assert analytics.case_count == 9
    assert analytics.state_distribution
    assert analytics.transition_distribution
    assert sum(analytics.mutation_frequencies.values()) == 9
    assert analytics.difficulty_category_distribution
    assert analytics.oracle_event_coverage_distribution


def test_generate_benchmark_report_writes_outputs(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=5)
    result = generate_benchmark_report(dataset_dir)

    assert result.analytics_dir == dataset_dir / "analytics"
    assert result.summary_path.is_file()
    assert result.report_path.is_file()
    assert (result.plots_dir / "states_distribution.png").is_file()
    assert (result.plots_dir / "transitions_distribution.png").is_file()
    assert (result.plots_dir / "mutation_frequencies.png").is_file()
    assert (result.plots_dir / "difficulty_distribution.png").is_file()
    assert (result.plots_dir / "oracle_coverage_distribution.png").is_file()

    with result.summary_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(SUMMARY_COLUMNS)
        rows = list(reader)
    assert rows
    assert {row["metric"] for row in rows} >= {
        "state_count",
        "transition_count",
        "mutation_operator",
        "difficulty_category",
        "oracle_state_coverage",
    }

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["case_count"] == 5
    assert "distributions" in report
    assert "statistics" in report


def test_generate_benchmark_report_requires_dataset(tmp_path: Path) -> None:
    try:
        generate_benchmark_report(tmp_path / "missing")
        raised = False
    except AnalyticsError:
        raised = True
    assert raised


def test_cli_benchmark_report(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=3)
    result = runner.invoke(app, ["benchmark-report", str(dataset_dir)])

    assert result.exit_code == 0
    assert (dataset_dir / "analytics" / "report.json").is_file()
    assert "Generated analytics for 3 cases" in result.stdout
