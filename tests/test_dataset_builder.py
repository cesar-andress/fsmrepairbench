"""Tests for large-scale dataset builder."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import (
    INDEX_COLUMNS,
    PROGRESS_COLUMNS,
    REQUIRED_CASE_FILES,
    CaseBuildSpec,
    DatasetBuilderError,
    build_dataset,
    build_single_case,
    discover_completed_rows,
    is_case_complete,
)

runner = CliRunner()


def test_build_single_case_writes_packaged_case(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    spec = CaseBuildSpec(case_number=1, base_seed=42)

    row = build_single_case(spec, output_dir)

    case_dir = output_dir / "cases" / "case_000001"
    assert is_case_complete(case_dir)
    assert row.reference_bpr == 1.0
    assert row.difficulty_score > 0.0
    assert row.oracle_state_coverage == 1.0
    assert all((case_dir / name).is_file() for name in REQUIRED_CASE_FILES)


def test_build_dataset_writes_index_and_metadata(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"

    result = build_dataset(size=4, seed=42, output_dir=output_dir, workers=2, resume=False)

    assert result.index_path.is_file()
    assert result.metadata_path.is_file()
    assert result.progress_path.is_file()
    assert len(result.rows) == 4

    with result.index_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(INDEX_COLUMNS)
        rows = list(reader)
    assert len(rows) == 4
    assert rows[0]["case_id"] == "case_000001"
    assert rows[0]["mutation_operator"]
    assert float(rows[0]["difficulty_score"]) > 0.0

    metadata = json.loads(result.metadata_path.read_text(encoding="utf-8"))
    assert metadata["dataset_id"] == "fsmrepairbench_v1"
    assert metadata["seed"] == 42
    assert metadata["target_size"] == 4
    assert metadata["completed_cases"] == 4


def test_build_dataset_resume_skips_completed_cases(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"

    first = build_dataset(size=3, seed=7, output_dir=output_dir, workers=1, resume=False)
    assert len(first.rows) == 3

    second = build_dataset(size=3, seed=7, output_dir=output_dir, workers=1, resume=True)
    assert len(second.rows) == 3
    assert discover_completed_rows(output_dir)[0].status == "skipped"


def test_build_dataset_rejects_non_positive_size(tmp_path: Path) -> None:
    try:
        build_dataset(size=0, seed=42, output_dir=tmp_path / "dataset", workers=1)
        raised = False
    except DatasetBuilderError:
        raised = True
    assert raised


def test_progress_csv_includes_status_column(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    result = build_dataset(size=2, seed=99, output_dir=output_dir, workers=1, resume=False)

    with result.progress_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(PROGRESS_COLUMNS)
        rows = list(reader)
    assert len(rows) == 2
    assert rows[0]["status"] == "completed"


def test_cli_build_dataset(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    result = runner.invoke(
        app,
        [
            "build-dataset",
            "--size",
            "2",
            "--seed",
            "42",
            "--output",
            str(output_dir),
            "--workers",
            "1",
            "--no-resume",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "index.csv").is_file()
    assert (output_dir / "metadata.json").is_file()
    assert "Built dataset with 2 cases" in result.stdout
