"""Tests for the CLI."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_cli_validate_fsm_success() -> None:
    result = runner.invoke(app, ["validate-fsm", str(FIXTURES / "valid_fsm.json")])
    assert result.exit_code == 0
    assert "Valid FSM" in result.stdout


def test_cli_validate_fsm_failure() -> None:
    result = runner.invoke(app, ["validate-fsm", str(FIXTURES / "invalid_fsm.json")])
    assert result.exit_code == 1
    assert "ERROR" in result.stdout


def test_cli_validate_oracle_success() -> None:
    result = runner.invoke(app, ["validate-oracle", str(FIXTURES / "valid_oracle.json")])
    assert result.exit_code == 0
    assert "parking_gate_oracles" in result.stdout


def test_cli_score_success() -> None:
    result = runner.invoke(
        app,
        [
            "score",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "simple_oracle.json"),
        ],
    )
    assert result.exit_code == 0
    assert "BPR" in result.stdout
    assert "100.00%" in result.stdout


def test_cli_score_fsm_id_mismatch() -> None:
    result = runner.invoke(
        app,
        [
            "score",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "valid_oracle.json"),
        ],
    )
    assert result.exit_code == 1
    assert "does not match" in result.stdout


def test_cli_mutate_writes_outputs(tmp_path: Path) -> None:
    faulty_path = tmp_path / "faulty.json"
    meta_path = tmp_path / "bug.json"
    result = runner.invoke(
        app,
        [
            "mutate",
            str(FIXTURES / "valid_fsm.json"),
            "--operator",
            "wrong_target",
            "--seed",
            "42",
            "--out",
            str(faulty_path),
            "--meta",
            str(meta_path),
        ],
    )
    assert result.exit_code == 0
    assert faulty_path.exists()
    assert meta_path.exists()

    faulty = json.loads(faulty_path.read_text(encoding="utf-8"))
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert faulty["id"] == "parking_gate_001__faulty__wrong_target__42"
    assert metadata["mutation_operator"] == "wrong_target"
    assert metadata["seed"] == 42
