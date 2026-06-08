"""Tests for oracle-to-FSM compatibility when scoring derived machines."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM, OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import (
    is_oracle_compatible,
    load_fsm,
    load_oracle_suite,
    oracle_incompatibility_message,
)

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_reference_fsm_scores_with_its_oracle() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    assert is_oracle_compatible(fsm, suite)
    assert score_oracle_suite(fsm, suite).bpr == 1.0

    result = runner.invoke(
        app,
        ["score", str(FIXTURES / "simple_fsm.json"), str(FIXTURES / "simple_oracle.json")],
    )
    assert result.exit_code == 0
    assert "100.00%" in result.stdout


def test_faulty_fsm_with_reference_fsm_id_scores_with_reference_oracle(
    tmp_path: Path,
) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, _ = mutate(reference, "wrong_target", 42)

    assert faulty.reference_fsm_id == reference.id
    assert faulty.parent_fsm_id == reference.id
    assert is_oracle_compatible(faulty, suite)

    faulty_path = tmp_path / "faulty.json"
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["score", str(faulty_path), str(FIXTURES / "valid_oracle.json")],
    )
    assert result.exit_code == 1
    assert "BPR" in result.stdout
    assert score_oracle_suite(faulty, suite).bpr < 1.0


def test_faulty_fsm_legacy_id_prefix_scores_with_reference_oracle() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")
    faulty = reference.model_copy(deep=True)
    faulty.id = f"{reference.id}__faulty__wrong_target__7"
    faulty.reference_fsm_id = None
    faulty.parent_fsm_id = None

    assert is_oracle_compatible(faulty, suite)
    assert score_oracle_suite(faulty, suite).total_steps > 0


def test_unrelated_fsm_fails_compatibility() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")

    assert not is_oracle_compatible(fsm, suite)
    message = oracle_incompatibility_message(fsm, suite)
    assert "toggle_001" in message
    assert "parking_gate_001" in message
    assert "reference_fsm_id=" in message
    assert "parent_fsm_id=" in message

    result = runner.invoke(
        app,
        ["score", str(FIXTURES / "simple_fsm.json"), str(FIXTURES / "valid_oracle.json")],
    )
    assert result.exit_code == 1
    assert "not compatible" in result.stdout


def test_repaired_fsm_id_prefix_is_compatible() -> None:
    suite = OracleSuite(id="suite", fsm_id="ref_001", scenarios=[])
    fsm = FSM(
        id="ref_001__repaired__baseline__1",
        name="Repaired",
        states=[{"id": "a"}],
        initial_state="a",
        events=[],
    )

    assert is_oracle_compatible(fsm, suite)


@pytest.mark.parametrize(
    ("fsm_id", "reference_fsm_id", "parent_fsm_id", "expected"),
    [
        ("ref", "ref", None, True),
        ("faulty", "ref", "ref", True),
        ("ref__faulty__op__1", None, None, True),
        ("ref__repaired__patch__1", None, None, True),
        ("other", None, None, False),
    ],
)
def test_is_oracle_compatible_matrix(
    fsm_id: str,
    reference_fsm_id: str | None,
    parent_fsm_id: str | None,
    expected: bool,
) -> None:
    suite = OracleSuite(id="suite", fsm_id="ref", scenarios=[])
    fsm = FSM(
        id=fsm_id,
        name="Test",
        states=[{"id": "a"}],
        initial_state="a",
        events=[],
        reference_fsm_id=reference_fsm_id,
        parent_fsm_id=parent_fsm_id,
    )

    assert is_oracle_compatible(fsm, suite) is expected
