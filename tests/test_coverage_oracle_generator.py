"""Tests for multi-criterion coverage oracle generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.coverage_oracle_generator import (
    SUPPORTED_COVERAGE_SUITE_TYPES,
    export_coverage_oracles_directory,
    export_to_oracle_suite,
    generate_all_coverage_oracle_suites,
    generate_coverage_oracles_for_directory,
    scenario_to_test_sequence,
)
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_generate_all_coverage_oracle_suites_structure() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    export = generate_all_coverage_oracle_suites(fsm, seed=42)

    assert export.fsm_id == fsm.id
    assert set(export.suites.keys()) == set(SUPPORTED_COVERAGE_SUITE_TYPES)
    for suite_type, suite in export.suites.items():
        assert suite.suite_type == suite_type
        assert suite.sequence_count == len(suite.sequences)
        assert suite.coverage_ratio <= 1.0
        for sequence in suite.sequences:
            assert len(sequence.inputs) == len(sequence.expected_states)
            assert len(sequence.inputs) == len(sequence.expected_outputs)


def test_transition_and_state_suites_achieve_full_coverage() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    export = generate_all_coverage_oracle_suites(fsm, seed=7)

    assert export.suites["transition_coverage"].coverage_ratio == pytest.approx(1.0)
    assert export.suites["state_coverage"].coverage_ratio == pytest.approx(1.0)


def test_exported_sequences_execute_on_reference_fsm() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    export = generate_all_coverage_oracle_suites(fsm, seed=11)
    transition_suite = export_to_oracle_suite(export.suites["transition_coverage"])

    result = score_oracle_suite(fsm, transition_suite)
    assert result.bpr == pytest.approx(1.0)


def test_scenario_to_test_sequence_encodes_guarded_inputs() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    export = generate_all_coverage_oracle_suites(fsm, seed=3)
    guarded = next(
        sequence
        for sequence in export.suites["transition_coverage"].sequences
        if any("::" in step_input for step_input in sequence.inputs)
    )
    assert guarded.inputs
    assert guarded.expected_states


def test_export_coverage_oracles_directory(tmp_path: Path) -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    export = generate_all_coverage_oracle_suites(fsm, seed=5)
    out_dir = tmp_path / "oracles"
    export_coverage_oracles_directory(out_dir, export)

    assert (out_dir / "manifest.json").exists()
    for suite_type in SUPPORTED_COVERAGE_SUITE_TYPES:
        path = out_dir / f"{suite_type}.json"
        assert path.exists()
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["sequences"]
        assert payload["sequences"][0]["inputs"] is not None


def test_mutation_killing_suite_detects_mutants() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    export = generate_all_coverage_oracle_suites(fsm, seed=13, mutant_count=5)
    suite = export_to_oracle_suite(export.suites["mutation_killing"])
    assert export.suites["mutation_killing"].coverage_ratio > 0.0
    assert all(execute_scenario(fsm, scenario).passed for scenario in suite.scenarios)


def test_generate_coverage_oracles_for_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "dataset"
    output_dir = tmp_path / "oracles"
    input_dir.mkdir()
    source = load_fsm(FIXTURES / "simple_fsm.json")
    fsm_path = input_dir / "fsm_000001.json"
    fsm_path.write_text(source.model_dump_json(indent=2) + "\n", encoding="utf-8")

    manifests = generate_coverage_oracles_for_directory(input_dir, output_dir, seed=42)
    assert len(manifests) == 1
    assert (output_dir / source.id / "transition_coverage.json").exists()


def test_cli_generate_coverage_oracles(tmp_path: Path) -> None:
    out_dir = tmp_path / "oracles"
    result = runner.invoke(
        app,
        [
            "generate-coverage-oracles",
            str(FIXTURES / "simple_fsm.json"),
            "--out",
            str(out_dir),
            "--seed",
            "42",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    assert (out_dir / "manifest.json").exists()
    assert (out_dir / "path_coverage.json").exists()
