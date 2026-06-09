"""Tests for transition-level localization campaign."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.fault_localization import localize_fault
from fsmrepairbench.localization_campaign import (
    LocalizationCampaignError,
    aggregate_localization_metrics,
    localize_case_transitions,
    rank_bucket,
    rank_distribution,
    ranked_transition_ids,
    run_localization_campaign,
    transition_localization_metrics,
)
from fsmrepairbench.mutators import mutate
from fsmrepairbench.validators import load_fsm, load_oracle_suite

runner = CliRunner()
FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_ranked_transition_ids_filters_non_transition_elements() -> None:
    reference = load_fsm(Path(__file__).parent / "fixtures" / "valid_fsm.json")
    oracle = load_oracle_suite(Path(__file__).parent / "fixtures" / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)
    report = localize_fault(faulty, oracle, method="ochiai")

    ranked = ranked_transition_ids(report)
    assert ranked
    assert metadata.changed_transition_id in ranked
    assert all(
        element.element_type == "transition"
        for element in report.ranked_elements
        if element.element_id in ranked
    )


def test_transition_localization_metrics() -> None:
    rank, reciprocal, top1, top3, top5 = transition_localization_metrics(
        "t2",
        ["t1", "t2", "t3"],
    )
    assert rank == 2
    assert reciprocal == pytest.approx(0.5)
    assert top1 is False
    assert top3 is True
    assert top5 is True


def test_rank_bucket_mapping() -> None:
    assert rank_bucket(1) == "1"
    assert rank_bucket(7) == "6-10"
    assert rank_bucket(15) == "11-20"
    assert rank_bucket(25) == "21+"
    assert rank_bucket(None) == "not_ranked"


def test_localize_case_transitions_on_fixture_case() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    result = localize_case_transitions(case_dir)
    assert result.localized is True
    assert result.changed_transition_id
    assert result.transition_count >= 1


def test_run_localization_campaign_on_fixture_dataset(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    result = run_localization_campaign(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
    )
    assert result.case_count == 1
    assert result.localized_cases == 1
    assert result.summary_path.is_file()
    assert result.leaderboard_path.is_file()
    assert result.localization_metrics_path.is_file()
    assert result.per_case_path.is_file()
    assert result.report_path.is_file()
    assert result.manifest_path.is_file()
    assert (result.figures_dir / "topk_hit_rates.png").is_file()
    assert (result.figures_dir / "topk_hit_histogram.png").is_file()
    assert (result.figures_dir / "topk_rank_histogram.png").is_file()
    assert (result.tables_dir / "table_localization_summary.tex").is_file()
    assert (result.tables_dir / "table_leaderboard.tex").is_file()

    metrics = {
        row["metric"]: row["value"]
        for row in csv.DictReader(result.summary_path.open(encoding="utf-8"))
    }
    assert metrics["method"] == "ochiai"
    assert float(metrics["cohort_size"]) == 1.0
    assert float(metrics["detectable_denominator"]) == 1.0

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["zenodo_doi"] == "10.5281/zenodo.20602528"
    assert manifest["detectable_denominator"] == 1


def test_aggregate_localization_metrics_computes_mrr() -> None:
    rows = [
        localize_case_transitions(FIXTURE_DATASET / "cases" / "case_000002"),
    ]
    metrics = aggregate_localization_metrics(rows)
    assert metrics["localized_cases"] == 1
    assert metrics["mrr"] > 0.0
    distribution = rank_distribution(rows)
    assert sum(int(row["count"]) for row in distribution) == 1


def test_run_localization_campaign_cli(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run-localization-campaign",
            str(FIXTURE_DATASET),
            "--out",
            str(out),
            "--cohort-file",
            str(cohort_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "report.md").is_file()
    assert (out / "leaderboard.csv").is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["experiment"] == "RQ3-localization-ochiai-1k"
    assert manifest["release_label"] == "v0.2.0-analysis"
    assert manifest["cohort_sha256"]
    assert manifest["regeneration_commands"]


def test_run_localization_campaign_requires_dataset(tmp_path: Path) -> None:
    with pytest.raises(LocalizationCampaignError):
        run_localization_campaign(tmp_path / "missing")
