"""Tests for oracle-surface rescoring."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.dataset_builder import load_dataset_cases
from fsmrepairbench.oracle_surface import (
    OracleSurfaceId,
    PROGRESSIVE_SURFACE_ORDER,
    SURFACE_PROFILES,
    score_oracle_suite_with_surface,
)
from fsmrepairbench.oracle_surface_sensitivity import run_oracle_surface_sensitivity
from fsmrepairbench.observability_boundary_study import run_observability_boundary_study
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

DATASET_1K = Path(__file__).resolve().parents[1] / "data" / "fsmrepairbench_1k"


@pytest.mark.skipif(not DATASET_1K.is_dir(), reason="1k dataset not present")
def test_s0_rescoring_matches_published_index() -> None:
    cases = load_dataset_cases(DATASET_1K)
    mismatches = 0
    for case in cases[:50]:
        case_dir = DATASET_1K / "cases" / case.case_id
        reference = load_fsm_json(case_dir / "reference_fsm.json")
        faulty = load_fsm_json(case_dir / "faulty_fsm.json")
        oracle = load_oracle_suite(case_dir / "oracle_suite.json")
        profile = SURFACE_PROFILES[OracleSurfaceId.S0_PUBLISHED]
        rescored_faulty = score_oracle_suite_with_surface(
            faulty,
            oracle,
            reference=reference,
            profile=profile,
        ).bpr
        if abs(rescored_faulty - case.faulty_bpr) > 1e-5:
            mismatches += 1
    assert mismatches == 0


@pytest.mark.skipif(not DATASET_1K.is_dir(), reason="1k dataset not present")
def test_oracle_surface_sensitivity_runs(tmp_path: Path) -> None:
    result = run_oracle_surface_sensitivity(DATASET_1K, tmp_path)
    assert result.case_count == 1000
    assert result.summary_path.is_file()
    assert result.partition_changes_path.is_file()


@pytest.mark.skipif(not DATASET_1K.is_dir(), reason="1k dataset not present")
def test_progressive_surfaces_s0_through_s3_differ() -> None:
    case_dir = DATASET_1K / "cases" / "case_000001"
    reference = load_fsm_json(case_dir / "reference_fsm.json")
    faulty = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle = load_oracle_suite(case_dir / "oracle_suite.json")
    scores = {
        surface.value: score_oracle_suite_with_surface(
            faulty,
            oracle,
            reference=reference,
            profile=SURFACE_PROFILES[surface],
        ).bpr
        for surface in PROGRESSIVE_SURFACE_ORDER
    }
    assert len(scores) == 4
    assert scores[OracleSurfaceId.S0_PUBLISHED.value] >= scores[OracleSurfaceId.S3_EVENT_EXTENDED.value]


@pytest.mark.skipif(not DATASET_1K.is_dir(), reason="1k dataset not present")
def test_observability_boundary_study_runs(tmp_path: Path) -> None:
    result = run_observability_boundary_study(
        dataset_dir=DATASET_1K,
        output_dir=tmp_path,
        repair_runs_dir=None,
    )
    assert result.surface_count == 4
    assert result.summary_path.is_file()
    assert result.interpretation_path.is_file()
