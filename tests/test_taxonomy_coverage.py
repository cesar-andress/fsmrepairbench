"""Tests for taxonomy coverage reporting."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.taxonomy_coverage import (
    TaxonomyCoverageError,
    generate_taxonomy_coverage_report,
    load_cohort_case_ids,
    load_taxonomy_feature_rows,
)
from tests.helpers import write_minimal_matrix

runner = CliRunner()


def test_load_cohort_case_ids_from_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "cohort.txt"
    manifest.write_text("case_000001\ncase_000002\n", encoding="utf-8")
    case_ids = load_cohort_case_ids(tmp_path, cohort_path=manifest)
    assert case_ids == ["case_000001", "case_000002"]


def test_generate_taxonomy_coverage_from_feature_matrix(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    write_minimal_matrix(dataset_dir / "feature_matrix.csv")
    cohort = tmp_path / "cohort.txt"
    cohort.write_text("case_000001\ncase_000002\ncase_000003\n", encoding="utf-8")
    out = tmp_path / "results"

    result = generate_taxonomy_coverage_report(
        dataset_dir,
        output_dir=out,
        cohort_path=cohort,
    )
    assert result.case_count == 3
    assert result.report_path.is_file()
    assert result.summary_path.is_file()
    assert (result.figures_dir / "dimension_coverage_ratio.png").is_file()
    assert (result.tables_dir / "table_dimension_coverage.tex").is_file()

    summary = list(csv.DictReader(result.summary_path.open(encoding="utf-8")))
    assert any(row["metric"] == "mutation_operators_present" for row in summary)
    payload = json.loads((out / "feature_space_report.json").read_text(encoding="utf-8"))
    assert payload["case_count"] == 3


def test_generate_taxonomy_coverage_cli(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    write_minimal_matrix(dataset_dir / "feature_matrix.csv")
    cohort = tmp_path / "cohort.txt"
    cohort.write_text("case_000001\ncase_000002\ncase_000003\n", encoding="utf-8")
    out = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "generate-taxonomy-coverage",
            str(dataset_dir),
            "--out",
            str(out),
            "--cohort-file",
            str(cohort),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "taxonomy_coverage_report.md").is_file()


def test_load_taxonomy_feature_rows_requires_complete_cases(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "cases").mkdir()
    with pytest.raises(TaxonomyCoverageError):
        load_taxonomy_feature_rows(dataset_dir, ["case_000001"])
