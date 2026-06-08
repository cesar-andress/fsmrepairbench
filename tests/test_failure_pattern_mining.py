"""Tests for repair failure pattern mining."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.failure_pattern_mining import (
    FAILURE_PATTERNS,
    FAILURE_PATTERNS_COLUMNS,
    FAILURE_PATTERNS_FILENAME,
    FAILURE_PATTERN_REPORT_FILENAME,
    classify_iteration_failure,
    detect_oscillation,
    mine_failure_patterns,
)
from fsmrepairbench.llm.repair import run_llm_repair_with_client
from fsmrepairbench.models import FSM
from fsmrepairbench.repair_trajectory import REPAIR_TRACE_FILENAME, export_repair_trace
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _faulty_toggle() -> FSM:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    return reference.model_copy(
        update={
            "transitions": [
                transition for transition in reference.transitions if transition.id != "t2"
            ]
        }
    )


def _write_trace(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def test_detect_oscillation() -> None:
    assert detect_oscillation([0.2, 0.6, 0.3, 0.7]) is True
    assert detect_oscillation([0.2, 0.4, 0.6]) is False


def test_classify_iteration_failure_patterns() -> None:
    assert classify_iteration_failure({"response": "not json", "patch": None, "score": {"before": {"bpr": 0.5}, "after": {"bpr": 0.5}}}) == "invalid_json"
    assert classify_iteration_failure({"patch": {"operations": []}, "score": {"before": {"bpr": 0.5}, "after": {"bpr": 0.5}}}) == "no_op_patch"
    assert classify_iteration_failure({"patch": {"operations": [{"op": "remove_transition", "transition_id": "t1"}]}, "score": {"before": {"bpr": 0.5}, "after": {"bpr": 0.3}}}) == "regression"
    assert classify_iteration_failure({"patch": {"operations": [{"op": "remove_transition", "transition_id": "t1"}]}, "score": {"before": {"bpr": 0.5}, "after": {"bpr": 0.5}}}) == "wrong_patch"


def test_mine_failure_patterns_from_generated_traces(tmp_path: Path) -> None:
    faulty = _faulty_toggle()
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")

    invalid_result = run_llm_repair_with_client(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=2,
        generate_fn=lambda *_args, **_kwargs: "not-json",
    )
    export_repair_trace(invalid_result, tmp_path / "invalid" / REPAIR_TRACE_FILENAME)

    oscillation_payload = {
        "bug_id": "osc_case",
        "model": "mock-model",
        "passed": False,
        "final_bpr": 0.7,
        "iterations": [
            {"iteration": 1, "response": "{}", "patch": {"operations": [{"op": "remove_transition", "transition_id": "t1"}]}, "score": {"before": {"bpr": 0.2}, "after": {"bpr": 0.2}}},
            {"iteration": 2, "response": "{}", "patch": {"operations": [{"op": "remove_transition", "transition_id": "t2"}]}, "score": {"before": {"bpr": 0.2}, "after": {"bpr": 0.6}}},
            {"iteration": 3, "response": "{}", "patch": {"operations": [{"op": "remove_transition", "transition_id": "t3"}]}, "score": {"before": {"bpr": 0.6}, "after": {"bpr": 0.3}}},
            {"iteration": 4, "response": "{}", "patch": {"operations": [{"op": "remove_transition", "transition_id": "t4"}]}, "score": {"before": {"bpr": 0.3}, "after": {"bpr": 0.7}}},
        ],
    }
    _write_trace(tmp_path / "oscillation" / REPAIR_TRACE_FILENAME, oscillation_payload)

    noop_payload = {
        "bug_id": "noop_case",
        "model": "mock-model",
        "passed": False,
        "final_bpr": 0.5,
        "iterations": [
            {"iteration": 1, "response": "{}", "patch": {"operations": []}, "score": {"before": {"bpr": 0.5}, "after": {"bpr": 0.5}}},
        ],
    }
    _write_trace(tmp_path / "noop" / REPAIR_TRACE_FILENAME, noop_payload)

    result = mine_failure_patterns(tmp_path)

    patterns = {occurrence.pattern for occurrence in result.occurrences}
    assert "invalid_json" in patterns
    assert "oscillation" in patterns
    assert "no_op_patch" in patterns
    assert result.patterns_path.is_file()
    assert result.report_path.is_file()

    with result.patterns_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert set(rows[0]) == set(FAILURE_PATTERNS_COLUMNS)

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["trace_count"] == 3
    assert report["pattern_counts"]["invalid_json"] >= 1


def test_cli_mine_failure_patterns(tmp_path: Path) -> None:
    payload = {
        "bug_id": "cli_case",
        "model": "mock-model",
        "passed": False,
        "final_bpr": 0.4,
        "iterations": [
            {"iteration": 1, "response": "broken", "patch": None, "score": {"before": {"bpr": 0.4}, "after": {"bpr": 0.4}}},
        ],
    }
    _write_trace(tmp_path / REPAIR_TRACE_FILENAME, payload)

    result = runner.invoke(app, ["mine-failure-patterns", str(tmp_path)])
    assert result.exit_code == 0
    assert (tmp_path / FAILURE_PATTERNS_FILENAME).is_file()
    assert (tmp_path / FAILURE_PATTERN_REPORT_FILENAME).is_file()
    assert "Discovered" in result.stdout
