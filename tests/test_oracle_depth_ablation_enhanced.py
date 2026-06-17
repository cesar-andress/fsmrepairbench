"""Tests for enhanced 500-case oracle depth ablation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fsmrepairbench.oracle_depth_ablation import COHORT_FILENAME_500
from fsmrepairbench.oracle_depth_ablation_enhanced import run_oracle_depth_ablation_enhanced
from fsmrepairbench.stratified_builder import build_stratified_dataset

PLAN_PATH = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_v0_smoke_plan.yaml"


@pytest.mark.skipif(not PLAN_PATH.is_file(), reason="smoke plan missing")
def test_enhanced_ablation_produces_varying_scenario_lengths(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset"
    build_stratified_dataset(PLAN_PATH, dataset)
    index_path = dataset / "case_index.csv"
    case_ids = [row["case_id"] for row in csv.DictReader(index_path.open(encoding="utf-8"))][:20]
    cohort = dataset / COHORT_FILENAME_500
    cohort.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    out = tmp_path / "ablation"
    paper = tmp_path / "paper"
    result = run_oracle_depth_ablation_enhanced(
        dataset,
        output_dir=out,
        cohort_path=cohort,
        cohort_size=len(case_ids),
        write_cohort=False,
        paper_export_dir=paper,
    )
    assert result.case_count == len(case_ids)
    depth_rows = list(csv.DictReader((out / "depth_summary.csv").open(encoding="utf-8")))
    assert len(depth_rows) == 3
    lengths = [float(row["mean_scenario_length"]) for row in depth_rows]
    assert max(lengths) - min(lengths) >= 1.0
    assert "mean_complete_repair_rate" in depth_rows[0]

    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_label"] == "C3-oracle-depth-ablation-500"
    assert manifest["zenodo_doi"] == "10.5281/zenodo.20724095"
    assert manifest["git_commit_hash"]
    assert manifest["depth_summary_sha256"]
    assert (paper / "depth_summary.csv").is_file()
