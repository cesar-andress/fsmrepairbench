"""Tests for spectrum-based fault localization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.fault_localization import (
    SuspiciousElement,
    localize_fault,
    rank_suspicious_elements,
    suspiciousness_score,
    trace_scenario_spectrum,
    write_localization_json,
)
from fsmrepairbench.models import OracleScenario, OracleStep
from fsmrepairbench.mutators import mutate
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
EXAMPLES = Path(__file__).parent.parent / "examples"
runner = CliRunner()


def _rank_position(
    ranked: tuple[SuspiciousElement, ...],
    *,
    element_type: str,
    element_id: str,
) -> int | None:
    for index, element in enumerate(ranked, start=1):
        if element.element_type == element_type and element.element_id == element_id:
            return index
    return None


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
    assert suspiciousness_score(
        method="dstar",
        failed_cover_count=2,
        passed_cover_count=1,
        total_failed_scenarios=3,
        total_passed_scenarios=1,
    ) == pytest.approx(2.0)
    assert suspiciousness_score(
        method="op2",
        failed_cover_count=2,
        passed_cover_count=0,
        total_failed_scenarios=2,
        total_passed_scenarios=1,
    ) == pytest.approx(2.0)


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


@pytest.mark.parametrize("method", ["ochiai", "tarantula", "jaccard", "dstar", "op2"])
def test_wrong_target_transition_ranked_in_top_five(method: str) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)

    report = localize_fault(faulty, oracle, method=method)  # type: ignore[arg-type]

    assert metadata.changed_transition_id is not None
    rank = _rank_position(
        report.ranked_elements,
        element_type="transition",
        element_id=metadata.changed_transition_id,
    )
    assert rank is not None
    assert rank <= 5


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
    assert payload["ranked_elements"]
    assert payload["ranked_elements"][0]["element_type"] in {
        "state",
        "transition",
        "guard",
        "action",
        "timeout",
    }
    assert "suspiciousness" in payload["ranked_elements"][0]
    assert "score" not in payload["ranked_elements"][0]
    assert "rankings" not in payload


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
    assert payload["ranked_elements"][0]["suspiciousness"] > 0.0


@pytest.mark.skipif(
    not (EXAMPLES / "demo_faulty.json").exists() or not (EXAMPLES / "demo_oracle.json").exists(),
    reason="demo examples not present",
)
def test_cli_demo_localize_fault(tmp_path: Path) -> None:
    out_path = tmp_path / "demo_localization.json"
    result = runner.invoke(
        app,
        [
            "localize-fault",
            str(EXAMPLES / "demo_faulty.json"),
            str(EXAMPLES / "demo_oracle.json"),
            "--method",
            "ochiai",
            "--out",
            str(out_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["method"] == "ochiai"
    assert payload["ranked_elements"]
