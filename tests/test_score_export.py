"""Tests for machine-readable score export."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import ScenarioResult, ScoreResult
from fsmrepairbench.scorer import SCORE_CSV_COLUMNS, write_score_csv, write_score_json
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_write_score_json_writes_full_result(tmp_path: Path) -> None:
    result = ScoreResult(
        bpr=0.5,
        passed_steps=1,
        total_steps=2,
        passed_scenarios=0,
        total_scenarios=1,
        scenarios=[
            ScenarioResult(
                scenario_id="scenario_a",
                passed=False,
                passed_steps=1,
                total_steps=2,
            )
        ],
    )
    out_path = tmp_path / "score.json"
    write_score_json(out_path, result)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["bpr"] == 0.5
    assert payload["scenarios"][0]["scenario_id"] == "scenario_a"


def test_write_score_csv_writes_scenario_rows(tmp_path: Path) -> None:
    result = ScoreResult(
        bpr=1.0,
        passed_steps=2,
        total_steps=2,
        passed_scenarios=1,
        total_scenarios=1,
        scenarios=[
            ScenarioResult(
                scenario_id="scenario_a",
                passed=True,
                passed_steps=2,
                total_steps=2,
            )
        ],
    )
    out_path = tmp_path / "score.csv"
    write_score_csv(
        out_path,
        fsm_id="toggle_001",
        oracle_suite_id="toggle_oracles",
        result=result,
    )

    with out_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(SCORE_CSV_COLUMNS)
        rows = list(reader)

    assert len(rows) == 1
    assert rows[0]["fsm_id"] == "toggle_001"
    assert rows[0]["oracle_suite_id"] == "toggle_oracles"
    assert rows[0]["scenario_id"] == "scenario_a"
    assert rows[0]["passed"] == "True"
    assert rows[0]["passed_steps"] == "2"
    assert rows[0]["total_steps"] == "2"
    assert rows[0]["bpr"] == "1.000000"


def test_cli_score_writes_json_and_csv_outputs(tmp_path: Path) -> None:
    json_path = tmp_path / "score.json"
    csv_path = tmp_path / "score.csv"
    result = runner.invoke(
        app,
        [
            "score",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "simple_oracle.json"),
            "--out-json",
            str(json_path),
            "--out-csv",
            str(csv_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    assert "OK" in result.stdout
    assert "BPR" in result.stdout
    assert "Scenario Results" not in result.stdout

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["bpr"] == 1.0
    assert payload["total_scenarios"] == len(payload["scenarios"])

    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")
    assert len(rows) == len(suite.scenarios)
    assert all(row["fsm_id"] == fsm.id for row in rows)
    assert all(row["oracle_suite_id"] == suite.id for row in rows)


def test_cli_score_default_output_unchanged() -> None:
    result = runner.invoke(
        app,
        [
            "score",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "simple_oracle.json"),
        ],
    )

    assert result.exit_code == 0
    assert "Scenario Results" in result.stdout
    assert "100.00%" in result.stdout
