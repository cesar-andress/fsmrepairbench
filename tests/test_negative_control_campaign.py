"""Tests for no-fault negative control cohort generation and evaluation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.experiments import discover_experiment_cases
from fsmrepairbench.localization_campaign import localize_case_transitions
from fsmrepairbench.negative_control_campaign import (
    NO_FAULT_OPERATOR,
    PER_CASE_COLUMNS,
    build_negative_control_case,
    run_negative_control_campaign,
    select_negative_control_sources,
    spurious_repair_improvement,
    validate_negative_control_case,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.tool_runner import build_tool_tasks, execute_tool_task, load_tool_configs
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

runner = CliRunner()
FIXTURE_SOURCE = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset" / "cases" / "case_000002"
TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "baselines_c1"
SOURCE_1K = Path(__file__).resolve().parents[1] / "data" / "fsmrepairbench_1k"


def test_select_negative_control_sources_is_reproducible() -> None:
    source_ids = [f"case_{index:06d}" for index in range(1, 201)]
    first = select_negative_control_sources(source_ids, size=100, seed=44)
    second = select_negative_control_sources(source_ids, size=100, seed=44)
    assert first == second
    assert len(first) == 100


def test_build_and_validate_no_fault_case(tmp_path: Path) -> None:
    target = tmp_path / "cases" / "nc_000001"
    build_negative_control_case(
        source_case_dir=FIXTURE_SOURCE,
        target_case_dir=target,
        case_id="nc_000001",
        source_case_id="case_000002",
        seed=44,
    )
    assert validate_negative_control_case(target) == []

    metadata = json.loads((target / "bug_metadata.json").read_text(encoding="utf-8"))
    assert metadata["mutation_operator"] == NO_FAULT_OPERATOR
    assert metadata["is_negative_control"] is True

    reference = load_fsm_json(target / "reference_fsm.json")
    faulty = load_fsm_json(target / "faulty_fsm.json")
    suite = load_oracle_suite(target / "oracle_suite.json")
    assert reference.model_dump() == faulty.model_dump()
    assert score_oracle_suite(reference, suite).bpr == 1.0
    assert score_oracle_suite(faulty, suite).bpr == 1.0


def test_localization_skips_no_fault_case(tmp_path: Path) -> None:
    target = tmp_path / "nc_000001"
    build_negative_control_case(
        source_case_dir=FIXTURE_SOURCE,
        target_case_dir=target,
        case_id="nc_000001",
        source_case_id="case_000002",
        seed=44,
    )
    result = localize_case_transitions(target)
    assert result.localized is False
    assert result.mutation_operator == NO_FAULT_OPERATOR


def test_baseline_repair_does_not_report_spurious_improvement(tmp_path: Path) -> None:
    target = tmp_path / "nc_000001"
    build_negative_control_case(
        source_case_dir=FIXTURE_SOURCE,
        target_case_dir=target,
        case_id="nc_000001",
        source_case_id="case_000002",
        seed=44,
    )
    cases = discover_experiment_cases(tmp_path)
    tools = load_tool_configs(TOOLS_DIR)
    repair_dir = tmp_path / "repair"
    for task in build_tool_tasks(cases, tools):
        summary = execute_tool_task(task, output_dir=repair_dir)
        assert summary.initial_bpr == 1.0
        assert summary.effective_repair is False
        assert summary.regression is False
        assert spurious_repair_improvement(
            complete_repair=summary.complete_repair,
            effective_repair=summary.effective_repair,
            regression=summary.regression,
            patch_applied=False,
        ) is False


@pytest.mark.skipif(not SOURCE_1K.is_dir(), reason="requires built fsmrepairbench_1k dataset")
def test_run_negative_control_campaign_export_schema(tmp_path: Path) -> None:
    out = tmp_path / "results"
    dataset_dir = tmp_path / "dataset"
    paper_dir = tmp_path / "paper"
    result = run_negative_control_campaign(
        SOURCE_1K,
        dataset_dir=dataset_dir,
        output_dir=out,
        paper_export_dir=paper_dir,
        cohort_size=100,
        seed=44,
        rebuild_dataset=True,
    )

    assert result.case_count == 100
    assert result.summary_path.is_file()
    assert result.per_case_path.is_file()
    assert result.report_path.is_file()
    assert result.manifest_path.is_file()
    assert (result.tables_dir / "table_negative_control_summary.tex").is_file()
    assert (paper_dir / "summary.csv").is_file()

    rows = list(csv.DictReader(result.per_case_path.open(encoding="utf-8")))
    assert list(rows[0].keys()) == list(PER_CASE_COLUMNS)
    tool_rows = [row for row in rows if row["tool_id"]]
    assert tool_rows
    assert all(row["mutation_operator"] == NO_FAULT_OPERATOR for row in rows)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["replaces_v0_2_analysis"] is False
    assert manifest["selection_seed"] == 44


def test_run_negative_control_campaign_cli(tmp_path: Path) -> None:
    if not SOURCE_1K.is_dir():
        pytest.skip("requires built fsmrepairbench_1k dataset")
    out = tmp_path / "out"
    dataset_dir = tmp_path / "dataset"
    result = runner.invoke(
        app,
        [
            "run-negative-control-campaign",
            "--source-dataset",
            str(SOURCE_1K),
            "--dataset-dir",
            str(dataset_dir),
            "--out",
            str(out),
            "--cohort-size",
            "100",
            "--seed",
            "44",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "summary.csv").is_file()
