"""Tests for oracle depth ablation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.oracle_depth_ablation import (
    ABLATION_DEPTHS,
    OracleDepthAblationError,
    RELEASE_LABEL,
    refresh_oracle_depth_manifest,
    run_oracle_depth_ablation,
    score_case_at_depth,
    select_ablation_cohort,
    write_ablation_cohort_manifest,
)

runner = CliRunner()
FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_select_ablation_cohort_from_fixture_dataset(tmp_path: Path) -> None:
    manifest = tmp_path / "cohort.txt"
    manifest.write_text("case_000002\n", encoding="utf-8")
    cohort = select_ablation_cohort(
        FIXTURE_DATASET,
        cohort_manifest=manifest,
        size=1,
    )
    assert len(cohort) == 1
    assert (FIXTURE_DATASET / "cases" / cohort[0]).is_dir()


def test_write_ablation_cohort_manifest(tmp_path: Path) -> None:
    txt, manifest = write_ablation_cohort_manifest(tmp_path, ["case_000001", "case_000002"])
    assert txt.is_file()
    assert manifest.is_file()
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    assert payload["cohort_size"] == 2
    assert payload["experiment"] == "C3-oracle-depth-ablation"
    assert payload["depth_presets"] == {"shallow": 5, "medium": 12, "deep": 25}


def test_score_case_at_depth_on_fixture_case() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    for depth in ABLATION_DEPTHS:
        result = score_case_at_depth(case_dir, depth)
        assert result.reference_bpr == 1.0
        assert result.depth == depth
        assert 0.0 <= result.faulty_bpr <= 1.0


def test_run_oracle_depth_ablation_on_fixture_dataset(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    result = run_oracle_depth_ablation(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        write_cohort=False,
    )
    assert result.case_count == 1
    assert result.depth_summary_path.is_file()
    assert result.summary_path.is_file()
    assert result.distributions_path.is_file()
    assert result.report_path.is_file()
    assert (result.figures_dir / "detection_rate_by_depth.png").is_file()
    assert (result.tables_dir / "table_depth_summary.tex").is_file()

    depth_rows = list(csv.DictReader(result.depth_summary_path.open(encoding="utf-8")))
    assert len(depth_rows) == len(ABLATION_DEPTHS)
    assert "overall_detection_rate" in depth_rows[0]
    assert depth_rows[0]["declared_max_steps"] == "5"
    assert "max_path_length" in depth_rows[0]
    assert "mean_max_path_length" in depth_rows[0]

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_label"] == RELEASE_LABEL
    assert manifest["zenodo_doi"] == "10.5281/zenodo.20602528"
    assert manifest["cohort_sha256"]
    assert manifest["regeneration_commands"]
    assert manifest["case_count"] == 1
    assert manifest["oracle_depths"] == list(ABLATION_DEPTHS)


def test_refresh_oracle_depth_manifest_preserves_depth_summaries(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    run_oracle_depth_ablation(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        write_cohort=False,
    )
    before = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    summaries_before = before["depth_summaries"]
    refresh_oracle_depth_manifest(out)
    after = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert after["depth_summaries"] == summaries_before
    assert after["release_label"] == RELEASE_LABEL
    assert after["zenodo_doi"] == "10.5281/zenodo.20602528"
    assert after["regeneration_commands"]


def test_run_oracle_depth_ablation_cli(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run-oracle-depth-ablation",
            str(FIXTURE_DATASET),
            "--out",
            str(out),
            "--cohort-file",
            str(cohort_path),
            "--no-write-cohort",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "report.md").is_file()


def test_select_ablation_cohort_requires_enough_cases(tmp_path: Path) -> None:
    manifest = tmp_path / "cohort.txt"
    manifest.write_text("case_000002\n", encoding="utf-8")
    with pytest.raises(OracleDepthAblationError):
        select_ablation_cohort(FIXTURE_DATASET, cohort_manifest=manifest, size=100)
