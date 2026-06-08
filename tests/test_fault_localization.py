"""Tests for spectrum-based fault localization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.fault_localization import (
    localize_fault,
    rank_suspicious_elements,
    suspiciousness_score,
    trace_scenario_spectrum,
    write_localization_json,
)
from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_suspiciousness_coefficients() -> None:
    assert suspiciousness_score(
        method="ochiai",
        failed_cover_count=2,
        passed_cover_count=0,
        total_failed_scenarios=2,
        total_passed_scenarios=1,
    ) == pytest.approx(1.0)
    assert suspiciousness_score(
        method="jaccard",
        failed_cover_count=2,
        passed_cover_count=0,
        total_failed_scenarios=2,
        total_passed_scenarios=1,
    ) == pytest.approx(1.0)
    assert suspiciousness_score(
        method="tarantula",
        failed_cover_count=2,
        passed_cover_count=0,
        total_failed_scenarios=2,
        total_passed_scenarios=1,
    ) == pytest.approx(1.0)


def test_trace_scenario_spectrum_records_covered_elements() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    scenario = OracleScenario(
        id="valid_ticket",
        steps=[
            OracleStep(event="car_arrives", guard="ticket_valid", expected_state="open"),
        ],
    )

    spectrum = trace_scenario_spectrum(fsm, scenario)

    assert spectrum.passed is True
    assert "open" in spectrum.covered_states
    assert "t2" in spectrum.covered_transitions
    assert "ticket_valid" in spectrum.covered_guards
    assert "open_gate" in spectrum.covered_actions


def test_ochiai_ranks_faulty_transition_highly() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)

    report = localize_fault(faulty, oracle, method="ochiai")
    transition_rankings = [
        element for element in report.rankings if element.element_type == "transition"
    ]

    assert metadata.changed_transition_id is not None
    top_transition = transition_rankings[0]
    assert top_transition.element_id == metadata.changed_transition_id
    assert top_transition.failed_cover_count >= 2
    assert top_transition.passed_cover_count == 0
    assert top_transition.score > 0.8


def test_localize_fault_requires_failing_scenario() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    with pytest.raises(ValueError, match="failing oracle scenario"):
        localize_fault(fsm, suite)


def test_write_localization_json(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, _ = mutate(reference, "wrong_target", 42)
    report = localize_fault(faulty, oracle, method="ochiai")

    out_path = tmp_path / "localization.json"
    write_localization_json(out_path, report)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["method"] == "ochiai"
    assert payload["rankings"]
    assert payload["rankings"][0]["element_type"] in {
        "state",
        "transition",
        "guard",
        "action",
        "timeout",
    }


def test_cli_localize_fault_writes_json(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, _ = mutate(reference, "wrong_target", 42)
    faulty_path = tmp_path / "faulty.json"
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")
    out_path = tmp_path / "localization.json"

    result = runner.invoke(
        app,
        [
            "localize-fault",
            str(faulty_path),
            str(FIXTURES / "valid_oracle.json"),
            "--method",
            "ochiai",
            "--out",
            str(out_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["total_failed_scenarios"] >= 1
    assert payload["rankings"][0]["score"] > 0.0


def test_rank_suspicious_elements_supports_all_methods() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)
    spectra = tuple(
        trace_scenario_spectrum(faulty, scenario) for scenario in oracle.scenarios
    )

    for method in ("ochiai", "tarantula", "jaccard"):
        rankings = rank_suspicious_elements(faulty, spectra, method=method)
        changed = metadata.changed_transition_id
        assert changed is not None
        matching = [
            item
            for item in rankings
            if item.element_type == "transition" and item.element_id == changed
        ]
        assert matching
        assert matching[0].score >= 0.8
