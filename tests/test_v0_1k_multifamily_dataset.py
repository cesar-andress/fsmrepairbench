"""Tests for the v0.1 1k-plan multi-family stratified dataset."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pytest

from fsmrepairbench.generators.stratified_specs import load_dataset_plan, total_planned_cases
from fsmrepairbench.stratified_builder import build_stratified_dataset
from fsmrepairbench.v0_1k_multifamily_dataset import (
    V0_1K_MULTIFAMILY_RELEASE,
    export_v0_1k_multifamily_rq1,
    pin_v0_1k_multifamily_cohorts,
)

PLAN_PATH = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_v0_1k_plan.yaml"


@pytest.mark.skipif(not PLAN_PATH.is_file(), reason="v0.1 1k plan missing")
def test_build_v0_1k_plan_produces_five_machine_families(tmp_path: Path) -> None:
    plan = load_dataset_plan(PLAN_PATH)
    assert total_planned_cases(plan) == 1000
    out = tmp_path / "dataset"
    result = build_stratified_dataset(PLAN_PATH, out)
    assert len(result.cases) == 1000

    with (out / "feature_matrix.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    families = Counter(row["machine_type"] for row in rows)
    assert set(families) == {"plain_fsm", "mealy", "moore", "efsm", "timed_fsm"}
    assert all(count == 200 for count in families.values())


@pytest.mark.skipif(not PLAN_PATH.is_file(), reason="v0.1 1k plan missing")
def test_pin_and_rq1_exports(tmp_path: Path) -> None:
    out = tmp_path / "dataset"
    build_stratified_dataset(PLAN_PATH, out)
    manifests = pin_v0_1k_multifamily_cohorts(out)
    assert len(manifests.analysis.case_ids) == 1000
    assert manifests.analysis.txt_path.name == "analysis_cohort_1k.txt"

    rq1 = export_v0_1k_multifamily_rq1(
        dataset_dir=out,
        repo_root=tmp_path,
        output_dir=tmp_path / "taxonomy",
        paper_export_dir=None,
    )
    assert rq1.taxonomy_dir.is_dir()
    summary = rq1.taxonomy_dir / "summary.csv"
    assert summary.is_file()
    metrics = {row["metric"]: row["value"] for row in csv.DictReader(summary.open(encoding="utf-8"))}
    assert float(metrics["fsm_families_present"]) == 5.0

    manifest = rq1.taxonomy_dir / "manifest.json"
    payload = manifest.read_text(encoding="utf-8")
    assert V0_1K_MULTIFAMILY_RELEASE in payload

    gaps = list(csv.DictReader((rq1.taxonomy_dir / "plan_cell_gaps.csv").open(encoding="utf-8")))
    assert sum(int(row["realised_count"]) for row in gaps) == 1000
