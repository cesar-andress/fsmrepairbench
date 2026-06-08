"""Tests for error propagation and masking analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.error_propagation import (
    ErrorPropagationError,
    analyze_error_propagation,
    analyze_scenario_propagation,
    error_propagation_report_to_dict,
)
from fsmrepairbench.models import BugMetadata, OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.oracle_generator import generate_oracle_suite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _write_case(case_dir: Path, *, reference, faulty, oracle, metadata: BugMetadata) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "reference_fsm.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "faulty_fsm.json").write_text(
        faulty.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "oracle_suite.json").write_text(
        oracle.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "bug_metadata.json").write_text(
        metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def test_easy_mutant_detected_on_wrong_target(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "wrong_target", 42)
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    case_dir = tmp_path / "case_easy"
    _write_case(case_dir, reference=reference, faulty=faulty, oracle=oracle, metadata=metadata)

    report = analyze_error_propagation(case_dir)

    assert report.summary.easy_mutant
    assert report.summary.detected_count >= 1
    assert any(record.oracle_detected_failure for record in report.records)
    assert not report.summary.equivalent_or_near_equivalent


def test_masked_fault_when_oracle_passes_despite_fault_site() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    faulty = reference.model_copy(deep=True)
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    fault_sites = frozenset({reference.transitions[0].id})

    record = analyze_scenario_propagation(
        reference=reference,
        faulty=faulty,
        scenario=oracle.scenarios[0],
        mutant_id=faulty.id,
        fault_sites=fault_sites,
    )

    assert record.reference_passes
    assert record.faulty_passes
    assert record.activated_fault
    assert record.masked_fault
    assert not record.oracle_detected_failure


def test_equivalent_mutant_on_unreachable_fault(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "unreachable_state_intro", 42)
    oracle = OracleSuite(
        id="narrow_oracle",
        fsm_id=reference.id,
        scenarios=load_oracle_suite(FIXTURES / "valid_oracle.json").scenarios[:1],
    )
    case_dir = tmp_path / "case_equivalent"
    _write_case(case_dir, reference=reference, faulty=faulty, oracle=oracle, metadata=metadata)

    report = analyze_error_propagation(case_dir)

    assert report.summary.equivalent_or_near_equivalent or not report.summary.easy_mutant


def test_analyze_scenario_propagation_fields() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "wrong_target", 42)
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    fault_sites = frozenset({metadata.changed_transition_id or ""})

    record = analyze_scenario_propagation(
        reference=reference,
        faulty=faulty,
        scenario=oracle.scenarios[1],
        mutant_id=faulty.id,
        fault_sites=fault_sites,
    )

    assert record.scenario_id == oracle.scenarios[1].id
    assert record.mutant_id == faulty.id
    assert isinstance(record.activated_fault, bool)
    assert isinstance(record.infected_state, bool)
    assert isinstance(record.propagated_to_observable_state, bool)
    assert isinstance(record.oracle_detected_failure, bool)
    assert isinstance(record.masked_fault, bool)


def test_error_propagation_report_to_dict(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "missing_transition", 7)
    oracle = generate_oracle_suite(reference, depth="shallow").suite
    case_dir = tmp_path / "case_report"
    _write_case(case_dir, reference=reference, faulty=faulty, oracle=oracle, metadata=metadata)

    report = analyze_error_propagation(case_dir)
    payload = error_propagation_report_to_dict(report)

    assert payload["case_id"] == case_dir.name
    assert payload["records"]
    assert "summary" in payload


def test_analyze_error_propagation_missing_files(tmp_path: Path) -> None:
    case_dir = tmp_path / "empty_case"
    case_dir.mkdir()
    with pytest.raises(ErrorPropagationError, match="Missing required case file"):
        analyze_error_propagation(case_dir)


def test_cli_analyze_error_propagation(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "wrong_target", 42)
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    case_dir = tmp_path / "case_cli"
    _write_case(case_dir, reference=reference, faulty=faulty, oracle=oracle, metadata=metadata)
    out_path = tmp_path / "propagation_report.json"

    result = runner.invoke(
        app,
        [
            "analyze-error-propagation",
            str(case_dir),
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["summary"]["scenarios_analyzed"] == len(oracle.scenarios)
