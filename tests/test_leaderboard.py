"""Tests for benchmark leaderboard generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.experiments import ExperimentConfig, result_path, run_experiment
from fsmrepairbench.leaderboard import (
    LEADERBOARD_COLUMNS,
    LeaderboardError,
    compute_leaderboard_entries,
    generate_leaderboard,
    load_case_result_records,
)
from tests.test_experiments import _fake_repair_runner, _setup_cases_root

runner = CliRunner()


def test_compute_leaderboard_entries_from_experiment_results(tmp_path: Path) -> None:
    cases_dir = _setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a", "model-b"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )
    run_experiment(config, repair_runner=_fake_repair_runner)

    records = load_case_result_records(output_dir)
    entries = compute_leaderboard_entries(records)

    assert len(entries) == 2
    assert entries[0].rank == 1
    assert entries[0].complete_repair_rate == 1.0
    assert entries[0].repair_success_rate == 1.0
    assert entries[0].avg_bpr_improvement > 0.0


def test_generate_leaderboard_writes_csv_and_markdown(tmp_path: Path) -> None:
    cases_dir = _setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )
    run_experiment(config, repair_runner=_fake_repair_runner)

    result_path(output_dir, "case_000001", "model-a")
    result = generate_leaderboard(output_dir)

    assert result.csv_path.is_file()
    assert result.markdown_path.is_file()
    assert "# FSMRepairBench Leaderboard" in result.markdown_path.read_text(encoding="utf-8")

    with result.csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(LEADERBOARD_COLUMNS)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["model"] == "model-a"


def test_generate_leaderboard_uses_runtime_seconds(tmp_path: Path) -> None:
    output_dir = tmp_path / "results"
    output_dir.mkdir()
    payload = {
        "case_id": "case_000001",
        "model": "model-a",
        "mutation_operator": "missing_transition",
        "initial_bpr": 0.5,
        "final_bpr": 1.0,
        "delta_bpr": 0.5,
        "complete_repair": True,
        "effective_repair": True,
        "regression": False,
        "patch_parse_failures": 0,
        "patch_validation_failures": 0,
        "patch_application_failures": 0,
        "iterations_completed": 2,
        "runtime_seconds": 12.5,
        "repair_result": {
            "bug_id": "bug",
            "passed": True,
            "score": 1.0,
            "details": {"runtime_seconds": 12.5, "iterations": []},
        },
    }
    (output_dir / "case_000001__model-a.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )

    entries = compute_leaderboard_entries(load_case_result_records(output_dir))
    assert entries[0].avg_runtime_seconds == 12.5
    assert entries[0].avg_iterations == 2.0


def test_generate_leaderboard_requires_results(tmp_path: Path) -> None:
    try:
        generate_leaderboard(tmp_path / "missing")
        raised = False
    except LeaderboardError:
        raised = True
    assert raised


def test_cli_leaderboard(tmp_path: Path) -> None:
    cases_dir = _setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )
    run_experiment(config, repair_runner=_fake_repair_runner)

    result = runner.invoke(app, ["leaderboard", str(output_dir)])
    assert result.exit_code == 0
    assert (output_dir / "leaderboard.csv").is_file()
    assert (output_dir / "leaderboard.md").is_file()
    assert "Generated leaderboard" in result.stdout
