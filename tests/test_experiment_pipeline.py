"""Tests for the end-to-end experiment pipeline."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.experiment_pipeline import (
    ExperimentPipelineConfig,
    run_experiment_pipeline,
)

runner = CliRunner()


def test_run_experiment_pipeline_writes_outputs(tmp_path: Path) -> None:
    config = ExperimentPipelineConfig(
        output_root=tmp_path / "pipeline",
        seed=7,
        fsm_count=2,
        num_states=4,
        num_events=3,
        mutants_per_fsm=3,
        optimizers=("random_search",),
        optimizer_iterations=8,
        optimizer_population_size=6,
        optimizer_generations=3,
        models=("reference", "missing-transition"),
        generate_plots=False,
    )
    result = run_experiment_pipeline(config)

    assert result.instance_count == 2
    assert result.metrics_csv.exists()
    assert result.model_summary_csv.exists()
    assert result.statistics_csv.exists()
    assert result.model_summary_tex.exists()
    assert result.statistics_tex.exists()
    assert result.pipeline_report_json.exists()
    assert result.pipeline_report_md.exists()
    assert (result.results_dir / "fsms").is_dir()
    assert (result.results_dir / "mutants").is_dir()
    assert (result.results_dir / "oracles").is_dir()
    assert (result.results_dir / "optimized_suites").is_dir()

    with result.metrics_csv.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 4

    with result.statistics_csv.open(encoding="utf-8") as handle:
        stats = list(csv.DictReader(handle))
    tests = {row["test"] for row in stats}
    assert "mann_whitney" in tests
    assert "wilcoxon" in tests
    assert "cliffs_delta" in tests
    assert "cohens_d" in tests


def test_run_experiment_pipeline_cli(tmp_path: Path) -> None:
    output_root = tmp_path / "cli_pipeline"
    result = runner.invoke(
        app,
        [
            "run-experiment-pipeline",
            "--output-root",
            str(output_root),
            "--fsm-count",
            "1",
            "--num-states",
            "4",
            "--num-events",
            "3",
            "--mutants-per-fsm",
            "2",
            "--optimizer",
            "random_search",
            "--optimizer-iterations",
            "5",
            "--optimizer-population-size",
            "4",
            "--optimizer-generations",
            "2",
            "--skip-plots",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (output_root / "tables" / "instance_metrics.csv").exists()
    assert (output_root / "reports" / "pipeline_report.json").exists()


@pytest.mark.parametrize("generate_plots", [False, True])
def test_run_experiment_pipeline_optional_plots(tmp_path: Path, generate_plots: bool) -> None:
    pytest.importorskip("matplotlib")
    config = ExperimentPipelineConfig(
        output_root=tmp_path / f"plots_{generate_plots}",
        seed=11,
        fsm_count=1,
        num_states=4,
        num_events=3,
        mutants_per_fsm=2,
        optimizers=("random_search",),
        optimizer_iterations=5,
        optimizer_population_size=4,
        optimizer_generations=2,
        models=("reference",),
        generate_plots=generate_plots,
    )
    result = run_experiment_pipeline(config)
    png_files = list(result.figures_dir.glob("**/*.png"))
    if generate_plots:
        assert png_files
    else:
        assert not png_files
