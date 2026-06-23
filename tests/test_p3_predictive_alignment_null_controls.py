"""Tests for P3 predictive alignment and null-control analyses."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.null_control_analysis import run_null_control_analysis
from fsmrepairbench.predictive_alignment_analysis import run_predictive_alignment_analysis

REPO = Path(__file__).resolve().parents[1]
PER_CASE_1K = REPO / "results/oracle_surface_sensitivity/per_case_scores.csv"
NEG_CONTROLS = REPO / "results/negative_controls/per_case_results.csv"


@pytest.mark.skipif(not PER_CASE_1K.is_file(), reason="frozen oracle-surface export missing")
def test_predictive_alignment_runs(tmp_path: Path) -> None:
    result = run_predictive_alignment_analysis(
        output_dir=tmp_path / "results",
        table_dir=tmp_path / "tables",
        per_case_1k=PER_CASE_1K,
        per_case_multifamily=REPO
        / "results/oracle_surface_sensitivity_multifamily_v0_3/per_case_scores.csv",
    )
    assert result.family_summary_path.is_file()
    assert result.model_path.is_file()
    assert result.report_path.is_file()


@pytest.mark.skipif(not NEG_CONTROLS.is_file(), reason="negative-control export missing")
def test_null_control_analysis_runs(tmp_path: Path) -> None:
    result = run_null_control_analysis(
        output_dir=tmp_path / "results",
        table_dir=tmp_path / "tables",
        campaign_results_dir=REPO / "results/negative_controls",
    )
    assert result.summary_path.is_file()
    assert result.case_count == 100
