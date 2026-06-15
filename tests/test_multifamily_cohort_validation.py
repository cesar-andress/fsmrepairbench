"""Tests for multi-family cohort validation and analyze-benchmark integration."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.multifamily_cohort_validation import (
    export_dataset_manifest,
    validate_multifamily_dataset,
)
from fsmrepairbench.v0_1k_multifamily_dataset import (
    pin_v0_1k_multifamily_cohorts,
    validate_v0_1k_multifamily_dataset,
)

PLAN_PATH = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_v0_1k_plan.yaml"


@pytest.mark.skipif(not PLAN_PATH.is_file(), reason="v0.1 1k plan missing")
def test_validate_multifamily_dataset_on_built_cohort(tmp_path: Path) -> None:
    from fsmrepairbench.stratified_builder import build_stratified_dataset

    out = tmp_path / "dataset"
    build_stratified_dataset(PLAN_PATH, out)
    pin_v0_1k_multifamily_cohorts(out)

    result = validate_multifamily_dataset(
        out,
        plan_path=PLAN_PATH,
        release_label="v0.3.0-1k-plan-multifamily",
        cases_per_family=200,
        cohort_specs=(
            ("analysis_cohort_1k.txt", "analysis_cohort_1k.json", 1000),
            ("localization_cohort_1k.txt", "localization_cohort_1k.json", 1000),
            ("coupling_campaign_250.txt", "coupling_campaign_250.json", 250),
            ("oracle_depth_ablation_200.txt", "oracle_depth_ablation_200.json", 200),
        ),
    )
    assert not result.errors
    assert result.case_count == 1000
    assert result.cohort_manifests_verified == 4

    manifest = export_dataset_manifest(out, release_label="v0.3.0-1k-plan-multifamily", plan_path=PLAN_PATH)
    assert manifest.is_file()
    assert "sha256" in manifest.read_text(encoding="utf-8")


@pytest.mark.skipif(not PLAN_PATH.is_file(), reason="v0.1 1k plan missing")
def test_analyze_benchmark_respects_cohort_file(tmp_path: Path) -> None:
    from fsmrepairbench.analytics import generate_analysis_report
    from fsmrepairbench.stratified_builder import build_stratified_dataset

    out = tmp_path / "dataset"
    build_stratified_dataset(PLAN_PATH, out)
    pin_v0_1k_multifamily_cohorts(out)
    cohort = out / "analysis_cohort_1k.txt"
    subset = tmp_path / "subset.txt"
    subset.write_text("\n".join(cohort.read_text(encoding="utf-8").splitlines()[:10]) + "\n", encoding="utf-8")

    result = generate_analysis_report(
        out,
        output_dir=tmp_path / "analysis",
        cohort_path=subset,
        release_label="test-multifamily",
    )
    assert result.case_count == 10


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "data" / "fsmrepairbench_1k_multifamily").is_dir(),
    reason="built 1k multifamily dataset not present",
)
def test_validate_existing_1k_multifamily_dataset() -> None:
    repo = Path(__file__).resolve().parents[1]
    result = validate_v0_1k_multifamily_dataset(repo_root=repo)
    assert result.manifest_path.is_file()
