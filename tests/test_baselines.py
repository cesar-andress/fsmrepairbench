"""Tests for baseline repair engines."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM
from fsmrepairbench.mutators import mutate
from fsmrepairbench.patch import apply_patch, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    OracleGuidedMissingTransitionRepair,
    OracleGuidedWrongTargetRepair,
    RandomRepair,
    collect_oracle_failures,
    propose_baseline_patch,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import is_valid_fsm, load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _toggle_reference() -> FSM:
    return load_fsm(FIXTURES / "simple_fsm.json")


def _toggle_oracle():
    return load_oracle_suite(FIXTURES / "simple_oracle.json")


def _faulty_missing_transition(reference: FSM) -> FSM:
    return reference.model_copy(
        update={
            "transitions": [
                transition for transition in reference.transitions if transition.id != "t2"
            ]
        }
    )


def test_missing_transition_engine_detects_failures() -> None:
    reference = _toggle_reference()
    oracle = _toggle_oracle()
    faulty = _faulty_missing_transition(reference)

    failures = collect_oracle_failures(faulty, oracle)
    assert any(failure.failure_reason == "no_matching_transition" for failure in failures)


def test_missing_transition_repair_improves_bpr() -> None:
    reference = _toggle_reference()
    oracle = _toggle_oracle()
    faulty = _faulty_missing_transition(reference)

    assert score_oracle_suite(faulty, oracle).bpr < 1.0

    engine = OracleGuidedMissingTransitionRepair()
    patch = engine.propose_patch(faulty, oracle)
    assert validate_patch(faulty, patch) == []

    repaired = apply_patch(faulty, patch)
    assert is_valid_fsm(repaired)
    assert score_oracle_suite(repaired, oracle).bpr == pytest.approx(1.0)


def test_wrong_target_repair_improves_bpr() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, _ = mutate(reference, "wrong_target", 42)

    assert score_oracle_suite(faulty, oracle).bpr < 1.0

    engine = OracleGuidedWrongTargetRepair()
    patch = engine.propose_patch(faulty, oracle)
    assert validate_patch(faulty, patch) == []

    repaired = apply_patch(faulty, patch)
    assert score_oracle_suite(repaired, oracle).bpr == pytest.approx(1.0)


def test_random_repair_produces_valid_patch() -> None:
    reference = _toggle_reference()
    oracle = _toggle_oracle()
    engine = RandomRepair(seed=7)

    patch = engine.propose_patch(reference, oracle)
    assert patch.target_fsm_id == reference.id
    assert validate_patch(reference, patch) == []


def test_propose_baseline_patch_helper() -> None:
    reference = _toggle_reference()
    oracle = _toggle_oracle()
    faulty = _faulty_missing_transition(reference)

    patch = propose_baseline_patch(
        faulty,
        oracle,
        engine="missing-transition",
    )
    repaired = apply_patch(faulty, patch)
    assert score_oracle_suite(repaired, oracle).bpr == pytest.approx(1.0)


def test_cli_baseline_repair_writes_patch(tmp_path: Path) -> None:
    reference = _toggle_reference()
    faulty = _faulty_missing_transition(reference)
    faulty_path = tmp_path / "faulty.json"
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")

    patch_path = tmp_path / "patch.json"
    result = runner.invoke(
        app,
        [
            "baseline-repair",
            str(faulty_path),
            str(FIXTURES / "simple_oracle.json"),
            "--engine",
            "missing-transition",
            "--out",
            str(patch_path),
        ],
    )

    assert result.exit_code == 0
    assert patch_path.exists()
    payload = json.loads(patch_path.read_text(encoding="utf-8"))
    assert payload["target_fsm_id"] == faulty.id
    assert payload["operations"]
