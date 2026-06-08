"""Tests for specification-based coverage criteria."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.coverage import (
    compute_coverage_report,
    coverage_report_to_dict,
    write_coverage_json,
)
from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_compute_coverage_report_includes_all_criteria() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    report = compute_coverage_report(fsm, suite, sequence_depth=2)

    assert report.state.coverage == 1.0
    assert report.transition.coverage == 1.0
    assert report.transition_pair.coverage >= 0.0
    assert report.transition_sequence.coverage >= 0.0
    assert report.guard is None
    assert report.timeout is None


def test_guard_coverage_for_efsm() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    suite = OracleSuite(
        id="guard_suite",
        fsm_id=fsm.id,
        scenarios=[
            OracleScenario(
                id="reach_valid_ticket",
                steps=[
                    OracleStep(
                        event="car_arrives",
                        guard="ticket_valid",
                        expected_state="open",
                    )
                ],
            )
        ],
    )

    report = compute_coverage_report(fsm, suite, sequence_depth=1)

    assert report.guard is not None
    assert report.guard.covered == 1
    assert report.guard.total == 2
    assert report.guard.coverage == 0.5


def test_timeout_coverage_for_timed_fsm() -> None:
    fsm = FSM.model_validate(
        {
            "id": "timed_gate",
            "name": "Timed Gate",
            "states": [{"id": "closed"}, {"id": "open"}],
            "initial_state": "closed",
            "events": ["open", "timeout"],
            "transitions": [
                {
                    "id": "t_open",
                    "source": "closed",
                    "event": "open",
                    "target": "open",
                },
                {
                    "id": "t_timeout",
                    "source": "open",
                    "event": "timeout",
                    "target": "closed",
                    "timeout": 5.0,
                },
            ],
        }
    )
    suite = OracleSuite(
        id="timed_suite",
        fsm_id=fsm.id,
        scenarios=[
            OracleScenario(
                id="close_on_timeout",
                steps=[
                    OracleStep(event="open", expected_state="open"),
                    OracleStep(event="timeout", expected_state="closed"),
                ],
            )
        ],
    )

    report = compute_coverage_report(fsm, suite, sequence_depth=2)

    assert report.timeout is not None
    assert report.timeout.coverage == 1.0
    assert "t_timeout" in report.timeout.covered_items


def test_write_coverage_json(tmp_path: Path) -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")
    report = compute_coverage_report(fsm, suite)

    out_path = tmp_path / "coverage.json"
    write_coverage_json(out_path, report)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["fsm_id"] == "toggle_001"
    assert "state" in payload["criteria"]
    assert payload["criteria"]["transition"]["coverage"] == 1.0


def test_coverage_report_to_dict_is_json_serialisable() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")
    report = compute_coverage_report(fsm, suite)

    json.dumps(coverage_report_to_dict(report))


def test_compute_coverage_report_requires_positive_sequence_depth() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    with pytest.raises(ValueError, match="sequence_depth"):
        compute_coverage_report(fsm, suite, sequence_depth=0)


def test_cli_coverage_writes_json(tmp_path: Path) -> None:
    out_path = tmp_path / "coverage.json"
    result = runner.invoke(
        app,
        [
            "coverage",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "simple_oracle.json"),
            "--out",
            str(out_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    assert "OK" in result.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["criteria"]["state"]["coverage"] == 1.0
