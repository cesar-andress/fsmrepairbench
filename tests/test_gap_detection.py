"""Tests for benchmark gap detection."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.coverage_optimizer import load_feature_matrix
from fsmrepairbench.gap_detection import (
    GAP_FILL_PLAN_FILENAME,
    GAP_REPORT_FILENAME,
    MISSING_CELLS_FILENAME,
    detect_benchmark_gaps,
    detect_gap_cells,
)
from fsmrepairbench.generators.stratified_specs import load_dataset_plan
from tests.helpers import write_minimal_matrix

runner = CliRunner()


def test_detect_gap_cells_identifies_missing_and_underrepresented(tmp_path: Path) -> None:
    matrix_path = tmp_path / "feature_matrix.csv"
    write_minimal_matrix(matrix_path)
    rows = load_feature_matrix(matrix_path)

    gaps = detect_gap_cells(rows, expected_count=1)

    assert gaps
    assert all(gap.expected_count == 1 for gap in gaps)
    assert all(gap.suggested_count >= 1 for gap in gaps)
    assert any(gap.gap_type == "missing" for gap in gaps)
    assert gaps[0].current_count <= gaps[0].expected_count


def test_detect_benchmark_gaps_writes_artifacts(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    write_minimal_matrix(dataset_dir / "feature_matrix.csv")

    result = detect_benchmark_gaps(dataset_dir, expected_count=1, max_plan_cells=5)

    assert result.missing_cells_path.is_file()
    assert result.gap_fill_plan_path.is_file()
    assert result.report_path.is_file()

    with result.missing_cells_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    assert rows
    assert {"expected_count", "current_count", "suggested_count", "gap_type"}.issubset(
        set(reader.fieldnames or [])
    )
    assert int(rows[0]["suggested_count"]) >= 1

    plan = load_dataset_plan(result.gap_fill_plan_path)
    assert len(plan.cells) <= 5
    assert sum(cell.count for cell in plan.cells) >= len(plan.cells)

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["generation_plan_cells"] == len(plan.cells)


def test_gap_fill_plan_is_valid_yaml(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    write_minimal_matrix(dataset_dir / "feature_matrix.csv")

    result = detect_benchmark_gaps(dataset_dir, expected_count=1, max_plan_cells=3)
    payload = yaml.safe_load(result.gap_fill_plan_path.read_text(encoding="utf-8"))
    assert payload["name"] == "gap_fill_plan"
    assert payload["seed"] == 42
    assert len(payload["cells"]) == 3


def test_cli_detect_gaps(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    write_minimal_matrix(dataset_dir / "feature_matrix.csv")

    result = runner.invoke(
        app,
        ["detect-gaps", str(dataset_dir), "--expected-count", "1", "--max-plan-cells", "4"],
    )
    assert result.exit_code == 0
    assert (dataset_dir / MISSING_CELLS_FILENAME).is_file()
    assert (dataset_dir / GAP_FILL_PLAN_FILENAME).is_file()
    assert (dataset_dir / GAP_REPORT_FILENAME).is_file()
    assert "Suggested additional cases" in result.stdout
