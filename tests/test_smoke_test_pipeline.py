"""Tests for the end-to-end smoke-test pipeline."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.smoke_test_pipeline import (
    LOCALIZATION_PASS_RATE,
    COVERAGE_STATE_THRESHOLD,
    COVERAGE_TRANSITION_THRESHOLD,
    SmokeTestPipelineConfig,
    infer_injected_fault_elements,
    prepare_smoke_test_input,
    prepare_smoke_test_input_from_examples,
    run_smoke_test_pipeline,
    validate_smoke_test_outputs,
)

EXAMPLES = Path(__file__).parent.parent / "examples"
from fsmrepairbench.mutators import mutate
from fsmrepairbench.validators import load_fsm_json

runner = CliRunner()
FIXTURES = Path(__file__).parent / "fixtures"


def test_prepare_smoke_test_input_creates_pairs(tmp_path: Path) -> None:
    input_dir = prepare_smoke_test_input(tmp_path / "input", seed=7, fsm_count=10)
    fsms = sorted((input_dir / "fsms").glob("*.json"))
    oracles = sorted((input_dir / "oracles").glob("*.json"))
    assert len(fsms) == 10
    assert len(oracles) == 10


def test_prepare_smoke_test_input_from_examples(tmp_path: Path) -> None:
    input_dir = prepare_smoke_test_input_from_examples(
        EXAMPLES,
        tmp_path / "input",
        seed=5,
        max_fsm_count=10,
    )
    fsms = sorted((input_dir / "fsms").glob("*.json"))
    oracles = sorted((input_dir / "oracles").glob("*.json"))
    assert len(fsms) == 10
    assert len(oracles) == 10


def test_run_smoke_test_pipeline_from_examples(tmp_path: Path) -> None:
    input_dir = prepare_smoke_test_input_from_examples(
        EXAMPLES,
        tmp_path / "input",
        seed=19,
        max_fsm_count=10,
    )
    output_dir = tmp_path / "results" / "smoke_test"
    config = SmokeTestPipelineConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        seed=19,
        fsm_count=10,
        input_source="examples",
        examples_dir=EXAMPLES,
        use_cli=False,
    )
    result = run_smoke_test_pipeline(config)
    validation = validate_smoke_test_outputs(result.output_dir)
    assert result.fsm_count == 10
    assert validation.all_mutants_scored
    assert validation.coverage_within_threshold


def test_cli_run_smoke_test_from_examples(tmp_path: Path) -> None:
    output_dir = tmp_path / "results" / "smoke_test"
    result = runner.invoke(
        app,
        [
            "run-smoke-test",
            "--from-examples",
            "--examples-dir",
            str(EXAMPLES),
            "--input-dir",
            str(tmp_path / "input"),
            "--output-dir",
            str(output_dir),
            "--seed",
            "23",
            "--fsm-count",
            "10",
            "--prepare-input",
            "--no-use-cli",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (output_dir / "metadata" / "smoke_test_summary.json").exists()


def test_infer_injected_fault_elements_detects_changed_transition() -> None:
    reference = load_fsm_json(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)
    faults = infer_injected_fault_elements(reference, faulty)
    assert metadata.changed_transition_id is not None
    assert ("transition", metadata.changed_transition_id) in faults


def test_run_smoke_test_pipeline_writes_outputs(tmp_path: Path) -> None:
    input_dir = prepare_smoke_test_input(tmp_path / "input", seed=11, fsm_count=10)
    output_dir = tmp_path / "results" / "smoke_test"
    config = SmokeTestPipelineConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        seed=11,
        fsm_count=10,
        first_order_count=1,
        second_order_count=1,
        higher_order_count=1,
        input_source="template",
        use_cli=False,
    )
    result = run_smoke_test_pipeline(config)
    validation = validate_smoke_test_outputs(result.output_dir)

    assert result.fsm_count == 10
    assert result.mutant_count > 0
    assert (output_dir / "coverage").is_dir()
    assert (output_dir / "scoring").is_dir()
    assert (output_dir / "localization").is_dir()
    assert (output_dir / "metadata" / "fsm_metadata.csv").exists()
    assert (output_dir / "metadata" / "mutant_metadata.csv").exists()
    assert (output_dir / "metadata" / "smoke_test_summary.json").exists()
    assert validation.all_mutants_scored
    assert validation.coverage_within_threshold
    assert validation.localization_within_threshold
    assert validation.mean_state_coverage >= COVERAGE_STATE_THRESHOLD
    assert validation.mean_transition_coverage >= COVERAGE_TRANSITION_THRESHOLD
    assert validation.localization_top5_rate >= LOCALIZATION_PASS_RATE


def test_all_mutants_have_scoring_artifacts(tmp_path: Path) -> None:
    input_dir = prepare_smoke_test_input(tmp_path / "input", seed=13, fsm_count=10)
    output_dir = tmp_path / "results" / "smoke_test"
    config = SmokeTestPipelineConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        seed=13,
        fsm_count=10,
        first_order_count=1,
        second_order_count=1,
        higher_order_count=1,
        use_cli=False,
    )
    run_smoke_test_pipeline(config)

    summary_csv = output_dir / "scoring" / "smoke_test_scoring_summary.csv"
    with summary_csv.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    for row in rows:
        score_json = output_dir / "scoring" / row["fsm_id"] / row["mutant_id"] / "bpr_score.json"
        scenario_csv = score_json.parent / "bpr_scenarios.csv"
        assert score_json.exists(), row["mutant_id"]
        assert scenario_csv.exists(), row["mutant_id"]
        payload = json.loads(score_json.read_text(encoding="utf-8"))
        assert "seed" in payload
        assert "timestamp" in payload
        assert "bpr" in payload


def test_cli_prepare_and_run_smoke_test(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "results" / "smoke_test"
    prepare_result = runner.invoke(
        app,
        [
            "prepare-smoke-test-input",
            "--output-dir",
            str(input_dir),
            "--seed",
            "17",
            "--fsm-count",
            "10",
        ],
    )
    assert prepare_result.exit_code == 0, prepare_result.stdout

    run_result = runner.invoke(
        app,
        [
            "run-smoke-test",
            "--input-dir",
            str(input_dir),
            "--output-dir",
            str(output_dir),
            "--seed",
            "17",
            "--fsm-count",
            "10",
            "--no-use-cli",
            "--quiet",
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout
    assert (output_dir / "metadata" / "smoke_test_summary.json").exists()
