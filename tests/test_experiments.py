"""Tests for experiment orchestration."""

from __future__ import annotations

import csv
import json
import textwrap
from pathlib import Path

import pytest

from fsmrepairbench.experiments import (
    PROGRESS_COLUMNS,
    SUMMARY_COLUMNS,
    ExperimentConfig,
    load_existing_summary_row,
    load_experiment_config,
    result_path,
    run_experiment,
)
from tests.helpers import fake_repair_runner, setup_cases_root


def test_load_experiment_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            models:
              - qwen2.5-coder:7b
              - llama3.1:8b
            cases_dir: data/generated/cases
            iterations: 3
            temperature: 0.0
            output_dir: results/raw/exp001
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_experiment_config(config_path)
    assert config.models == ["qwen2.5-coder:7b", "llama3.1:8b"]
    assert config.cases_dir == Path("data/generated/cases")
    assert config.iterations == 3
    assert config.output_dir == Path("results/raw/exp001")


def test_run_experiment_writes_results_and_csv(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a", "model-b"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )

    result = run_experiment(config, repair_runner=fake_repair_runner)

    assert result.summary_path.exists()
    assert result.progress_path.exists()
    assert len(result.rows) == 4

    result_file = result_path(output_dir, "case_000001", "model-a")
    assert result_file.exists()
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["complete_repair"] is True
    assert payload["final_bpr"] == pytest.approx(1.0)

    with result.summary_path.open(encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert list(summary_rows[0].keys()) == list(SUMMARY_COLUMNS)
    assert len(summary_rows) == 4
    assert all(row["complete_repair"] == "True" for row in summary_rows)

    with result.progress_path.open(encoding="utf-8", newline="") as handle:
        progress_rows = list(csv.DictReader(handle))
    assert list(progress_rows[0].keys()) == list(PROGRESS_COLUMNS)


def test_run_experiment_resume_skips_completed_pairs(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )

    calls = {"count": 0}

    def counting_runner(
        faulty_fsm: FSM,
        oracle_suite: OracleSuite,
        model: str,
        max_iterations: int,
        temperature: float,
    ) -> RepairResult:
        calls["count"] += 1
        return fake_repair_runner(
            faulty_fsm,
            oracle_suite,
            model,
            max_iterations,
            temperature,
        )

    run_experiment(config, repair_runner=counting_runner)
    assert calls["count"] == 2

    run_experiment(config, repair_runner=counting_runner)
    assert calls["count"] == 2

    skipped = load_existing_summary_row(result_path(output_dir, "case_000001", "model-a"))
    assert skipped is not None
    assert skipped.status == "skipped"


def test_run_experiment_no_resume_reruns_all(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )

    calls = {"count": 0}

    def counting_runner(
        faulty_fsm: FSM,
        oracle_suite: OracleSuite,
        model: str,
        max_iterations: int,
        temperature: float,
    ) -> RepairResult:
        calls["count"] += 1
        return fake_repair_runner(
            faulty_fsm,
            oracle_suite,
            model,
            max_iterations,
            temperature,
        )

    run_experiment(config, repair_runner=counting_runner)
    run_experiment(config, repair_runner=counting_runner, resume=False)
    assert calls["count"] == 4
