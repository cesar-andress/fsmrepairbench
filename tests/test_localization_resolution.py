"""Tests for shallow-oracle spectral-resolution analysis (RQ3)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.fault_localization import collect_scenario_spectra
from fsmrepairbench.localization_resolution import (
    LOCALIZATION_RESOLUTION_COLUMNS,
    QUARTILE_SUMMARY_COLUMNS,
    build_case_resolution_rows,
    build_quartile_summary_rows,
    compute_resolution_correlations,
    compute_spectral_resolution,
    transition_execution_profile,
    write_localization_resolution_exports,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"
DATASET_1K = Path(__file__).resolve().parents[1] / "data" / "fsmrepairbench_1k"
PAPER_RQ3 = Path(__file__).resolve().parents[2] / "paper1" / "results" / "rq3_localization_1k"


def test_transition_execution_profile_matches_cover_counts() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    faulty = load_fsm_json(resolve_coupling_case_file(case_dir, "faulty_fsm.json"))
    oracle = load_oracle_suite(resolve_coupling_case_file(case_dir, "oracle_suite.json"))
    spectra = collect_scenario_spectra(faulty, oracle)
    profile = transition_execution_profile("t45_16", spectra)
    assert profile.profile == (profile.failed_cover_count, profile.passed_cover_count)


def test_compute_spectral_resolution_on_fixture_case() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    faulty = load_fsm_json(resolve_coupling_case_file(case_dir, "faulty_fsm.json"))
    oracle = load_oracle_suite(resolve_coupling_case_file(case_dir, "oracle_suite.json"))
    spectra = collect_scenario_spectra(faulty, oracle)
    resolution, executed_count = compute_spectral_resolution(spectra)
    assert executed_count == 2
    assert resolution == pytest.approx(1.0, abs=1e-6)


@pytest.mark.skipif(not DATASET_1K.is_dir() or not PAPER_RQ3.is_dir(), reason="1k dataset or RQ3 export missing")
def test_build_case_resolution_rows_matches_frozen_cohort_size() -> None:
    rows = build_case_resolution_rows(DATASET_1K, PAPER_RQ3 / "localizability_audit.csv")
    assert len(rows) == 376


@pytest.mark.skipif(not DATASET_1K.is_dir() or not PAPER_RQ3.is_dir(), reason="1k dataset or RQ3 export missing")
def test_resolution_correlation_is_positive_on_frozen_cohort() -> None:
    rows = build_case_resolution_rows(DATASET_1K, PAPER_RQ3 / "localizability_audit.csv")
    correlation = compute_resolution_correlations(rows)
    assert correlation.n_cases == 376
    assert correlation.spearman_rho == pytest.approx(0.5605, abs=0.01)
    assert correlation.kendall_tau == pytest.approx(0.4358, abs=0.01)
    assert correlation.spearman_pvalue < 0.001
    assert correlation.kendall_pvalue < 0.001


@pytest.mark.skipif(not DATASET_1K.is_dir() or not PAPER_RQ3.is_dir(), reason="1k dataset or RQ3 export missing")
def test_quartile_summary_monotonic_mrr() -> None:
    rows = build_case_resolution_rows(DATASET_1K, PAPER_RQ3 / "localizability_audit.csv")
    quartiles = build_quartile_summary_rows(rows)
    assert len(quartiles) == 4
    assert sum(row.n_cases for row in quartiles) == len(rows)
    assert quartiles[-1].mrr >= quartiles[0].mrr
    assert quartiles[-1].top5_rate >= quartiles[0].top5_rate


@pytest.mark.skipif(not DATASET_1K.is_dir() or not PAPER_RQ3.is_dir(), reason="1k dataset or RQ3 export missing")
def test_write_localization_resolution_exports_schema(tmp_path: Path) -> None:
    rq3_dir = tmp_path / "rq3"
    rq3_dir.mkdir()
    audit_src = PAPER_RQ3 / "localizability_audit.csv"
    (rq3_dir / "localizability_audit.csv").write_text(
        audit_src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = write_localization_resolution_exports(
        DATASET_1K,
        rq3_dir,
        out_dir=rq3_dir,
    )
    with result.csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(LOCALIZATION_RESOLUTION_COLUMNS)
        rows = list(reader)
    assert len(rows) == 376

    with result.quartile_csv_path.open(encoding="utf-8") as handle:
        quartile_reader = csv.DictReader(handle)
        assert quartile_reader.fieldnames == list(QUARTILE_SUMMARY_COLUMNS)
        assert len(list(quartile_reader)) == 4

    assert result.tex_path.is_file()
    assert result.figure_path.is_file()
    assert result.manifest_path.is_file()
