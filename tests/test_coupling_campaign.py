"""Tests for RQ4 higher-order coupling campaign."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.coupling_campaign import (
    CouplingCampaignError,
    build_operator_chain,
    case_ho_seed,
    load_cohort_manifest,
    run_coupling_campaign,
)

runner = CliRunner()
FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_build_operator_chain_is_deterministic() -> None:
    chain_a = build_operator_chain("wrong_target", 3, "case_000001", 44)
    chain_b = build_operator_chain("wrong_target", 3, "case_000001", 44)
    assert chain_a == chain_b
    assert chain_a[0] == "wrong_target"
    assert len(chain_a) == 3


def test_case_ho_seed_is_stable() -> None:
    assert case_ho_seed("case_000001", 2, 44) == case_ho_seed("case_000001", 2, 44)


def test_run_coupling_campaign_on_fixture_cohort(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    subset = tmp_path / "subset"
    result = run_coupling_campaign(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        subset_dir=subset,
        campaign_seed=44,
        use_symlinks=False,
    )
    assert result.cohort_size == 1
    assert result.case_count >= 1
    assert result.summary_path.is_file()
    assert result.coupling_metrics_path.is_file()
    assert result.per_case_path.is_file()
    assert result.report_path.is_file()
    assert (result.figures_dir / "detection_rate_by_order.png").is_file()
    assert (result.figures_dir / "effective_repair_rate_by_order.png").is_file()
    assert (result.figures_dir / "mean_bpr_delta_by_order.png").is_file()
    assert (result.tables_dir / "table_coupling_summary.tex").is_file()
    assert (out / "coupling_report.json").is_file()
    assert result.manifest_path.is_file()

    summary = {
        row["metric"]: row["value"]
        for row in csv.DictReader(result.summary_path.open(encoding="utf-8"))
    }
    assert summary["campaign_seed"] == "44"
    assert int(summary["first_order_case_count"]) >= 1
    assert "coupling_effect_estimate" in summary

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["zenodo_doi"] == "10.5281/zenodo.20602528"
    assert manifest["campaign_seed"] == 44
    assert manifest["regeneration_commands"]


def test_run_coupling_campaign_cli(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "out"
    subset = tmp_path / "subset"
    result = runner.invoke(
        app,
        [
            "run-coupling-campaign",
            str(FIXTURE_DATASET),
            "--out",
            str(out),
            "--subset-dir",
            str(subset),
            "--cohort-file",
            str(cohort_path),
            "--seed",
            "44",
            "--copy-cases",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "report.md").is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["experiment"] == "RQ4-higher-order-coupling-250"
    assert manifest["release_label"] == "v0.2.0-analysis"
    assert manifest["cohort_sha256"]


def test_run_coupling_campaign_requires_dataset(tmp_path: Path) -> None:
    with pytest.raises(CouplingCampaignError):
        run_coupling_campaign(tmp_path / "missing")


def test_load_cohort_manifest_validates_pinned_sha256(tmp_path: Path) -> None:
    cohort_txt = tmp_path / "cohort.txt"
    cohort_txt.write_text("case_a\n", encoding="utf-8")
    cohort_json = tmp_path / "cohort.json"
    cohort_json.write_text(
        json.dumps({"sha256": "deadbeef" * 8, "case_ids": ["case_a"]}),
        encoding="utf-8",
    )
    with pytest.raises(CouplingCampaignError, match="sha256 mismatch"):
        load_cohort_manifest(cohort_txt)


def test_run_coupling_campaign_exports_detectable_operator_metrics(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    subset = tmp_path / "subset"
    result = run_coupling_campaign(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        subset_dir=subset,
        campaign_seed=44,
        use_symlinks=False,
    )
    metrics = list(csv.DictReader(result.coupling_metrics_path.open(encoding="utf-8")))
    detectable_rows = [
        row
        for row in metrics
        if row["metric"] == "complete_repair_rate_detectable" and row["primary_operator"]
    ]
    assert detectable_rows
    assert (result.tables_dir / "table_repair_detectable_by_operator_order.tex").is_file()
