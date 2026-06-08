"""Tests for benchmark difficulty calibration."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.difficulty_calibration import (
    DIFFICULTY_CALIBRATION_FILENAME,
    DIFFICULTY_CALIBRATION_REPORT_FILENAME,
    assign_difficulty_buckets,
    calibrate_benchmark_difficulty,
    calibrate_case_row,
    calibrate_difficulty_rows,
    compute_difficulty_score,
)
from tests.test_coverage_optimizer import _write_minimal_matrix

runner = CliRunner()


def test_compute_difficulty_score_uses_all_factors() -> None:
    easy = compute_difficulty_score(
        num_states=2,
        num_transitions=2,
        num_cycles=0,
        scc_count=1,
        guard_complexity="none",
        oracle_depth="shallow",
    )
    hard = compute_difficulty_score(
        num_states=40,
        num_transitions=200,
        num_cycles=15,
        scc_count=20,
        guard_complexity="nested",
        oracle_depth="exhaustive_like",
    )

    assert 0.0 <= easy <= 100.0
    assert 0.0 <= hard <= 100.0
    assert hard > easy


def test_calibrate_difficulty_rows_assigns_buckets(tmp_path: Path) -> None:
    matrix_path = tmp_path / "feature_matrix.csv"
    _write_minimal_matrix(matrix_path)

    rows = calibrate_difficulty_rows(
        [
            {
                "case_id": "case_000001",
                "num_states": "3",
                "num_transitions": "2",
                "num_cycles": "0",
                "scc_count": "1",
                "guard_complexity": "none",
                "oracle_depth": "shallow",
            },
            {
                "case_id": "case_000002",
                "num_states": "5",
                "num_transitions": "4",
                "num_cycles": "0",
                "scc_count": "1",
                "guard_complexity": "simple",
                "oracle_depth": "medium",
            },
            {
                "case_id": "case_000003",
                "num_states": "10",
                "num_transitions": "12",
                "num_cycles": "1",
                "scc_count": "2",
                "guard_complexity": "compound",
                "oracle_depth": "deep",
            },
            {
                "case_id": "case_000004",
                "num_states": "40",
                "num_transitions": "200",
                "num_cycles": "15",
                "scc_count": "20",
                "guard_complexity": "nested",
                "oracle_depth": "exhaustive_like",
            },
        ]
    )

    buckets = {row.case_id: row.difficulty_bucket for row in rows}
    assert len(set(buckets.values())) >= 2
    assert all(row.difficulty_score >= 0.0 for row in rows)


def test_assign_difficulty_buckets_fixed_thresholds() -> None:
    rows = assign_difficulty_buckets(
        [
            calibrate_case_row(
                {
                    "case_id": "case_000001",
                    "num_states": "2",
                    "num_transitions": "2",
                    "num_cycles": "0",
                    "scc_count": "1",
                    "guard_complexity": "none",
                    "oracle_depth": "shallow",
                }
            )
        ],
        method="fixed",
    )
    assert rows[0].difficulty_bucket == "easy"


def test_calibrate_benchmark_difficulty_writes_artifacts(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    _write_minimal_matrix(dataset_dir / "feature_matrix.csv")

    result = calibrate_benchmark_difficulty(dataset_dir, bucket_method="quantile")

    assert result.calibration_path.is_file()
    assert result.report_path.is_file()
    assert len(result.rows) == 3

    with result.calibration_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        csv_rows = list(reader)
    assert csv_rows
    assert {"difficulty_score", "difficulty_bucket", "guard_complexity", "oracle_depth"}.issubset(
        set(reader.fieldnames or [])
    )

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["case_count"] == 3
    assert report["calibration_method"] == "quantile"
    assert "bucket_distribution" in report


def test_cli_calibrate_difficulty(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    _write_minimal_matrix(dataset_dir / "feature_matrix.csv")

    result = runner.invoke(app, ["calibrate-difficulty", str(dataset_dir)])
    assert result.exit_code == 0
    assert (dataset_dir / DIFFICULTY_CALIBRATION_FILENAME).is_file()
    assert (dataset_dir / DIFFICULTY_CALIBRATION_REPORT_FILENAME).is_file()
    assert "Calibrated difficulty for 3 cases" in result.stdout
