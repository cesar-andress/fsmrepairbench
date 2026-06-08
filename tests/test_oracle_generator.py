"""Tests for automatic oracle generation."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.oracle_generator import (
    OracleGeneratorError,
    compute_coverage,
    export_oracle_json,
    generate_oracle_suite,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm
from fsmrepairbench.validators import load_oracle_suite as load_oracle_from_disk

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_generate_oracle_suite_covers_toggle_fsm() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    result = generate_oracle_suite(fsm, depth="shallow")

    assert result.suite.fsm_id == "toggle_001"
    assert result.coverage.state_coverage == 1.0
    assert result.coverage.transition_coverage == 1.0
    assert result.coverage.event_coverage == 1.0
    assert len(result.suite.scenarios) >= 2


def test_generated_scenarios_pass_on_reference_fsm() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    result = generate_oracle_suite(fsm, depth="medium")

    for scenario in result.suite.scenarios:
        scenario_result = execute_scenario(fsm, scenario)
        assert scenario_result.passed is True

    score = score_oracle_suite(fsm, result.suite)
    assert score.bpr == 1.0


def test_compute_coverage_reports_partial_suite() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_from_disk(FIXTURES / "simple_oracle.json")
    coverage = compute_coverage(fsm, suite)

    assert coverage.total_states == 2
    assert coverage.total_transitions == 2
    assert coverage.event_coverage == 1.0


def test_export_oracle_json_writes_benchmark_format(tmp_path: Path) -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    result = generate_oracle_suite(fsm, depth="shallow")
    output = tmp_path / "oracle.json"

    export_oracle_json(result.suite, output)
    loaded = load_oracle_from_disk(output)

    assert loaded.id == result.suite.id
    assert loaded.fsm_id == fsm.id
    assert loaded.scenarios


def test_depth_presets_change_path_budget() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    shallow = generate_oracle_suite(fsm, depth="shallow")
    deep = generate_oracle_suite(fsm, depth="deep")

    assert shallow.coverage.transition_coverage == 1.0
    assert deep.coverage.transition_coverage == 1.0
    assert len(deep.suite.scenarios) >= len(shallow.suite.scenarios)


def test_generate_oracle_suite_raises_for_empty_fsm() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json").model_copy(update={"transitions": []})
    try:
        generate_oracle_suite(fsm, depth="shallow")
        raised = False
    except OracleGeneratorError:
        raised = True
    assert raised


def test_cli_generate_oracles(tmp_path: Path) -> None:
    output = tmp_path / "oracle.json"
    result = runner.invoke(
        app,
        [
            "generate-oracles",
            str(FIXTURES / "simple_fsm.json"),
            "--depth",
            "deep",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["fsm_id"] == "toggle_001"
    assert payload["scenarios"]
    assert "Coverage" in result.stdout
