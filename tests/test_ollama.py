"""Tests for Ollama LLM repair integration."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.llm.ollama import (
    OllamaError,
    build_repair_prompt,
    extract_json_object,
    parse_patch_response,
    run_llm_repair_case,
    run_ollama,
)
from fsmrepairbench.models import FSM
from fsmrepairbench.repair_engines.baselines import OracleGuidedMissingTransitionRepair
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

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


def test_extract_json_object_from_plain_text() -> None:
    payload = extract_json_object('{"patch_id": "p1", "target_fsm_id": "x", "operations": []}')
    assert payload["patch_id"] == "p1"


def test_extract_json_object_from_fenced_block() -> None:
    text = """Here is the patch:
```json
{"patch_id": "p2", "target_fsm_id": "x", "operations": []}
```
"""
    payload = extract_json_object(text)
    assert payload["patch_id"] == "p2"


def test_extract_json_object_rejects_invalid_text() -> None:
    with pytest.raises(ValueError, match="No JSON object found"):
        extract_json_object("not json")


def test_build_repair_prompt_requests_patch_only() -> None:
    reference = _toggle_reference()
    oracle = _toggle_oracle()
    faulty = _faulty_missing_transition(reference)
    score = score_oracle_suite(faulty, oracle)

    prompt = build_repair_prompt(faulty, oracle, score)

    assert "Return ONLY one valid JSON object" in prompt
    assert "FSMPatch schema example" in prompt
    assert "no_matching_transition" in prompt
    assert '"id": "toggle_001"' in prompt


def test_run_ollama_uses_injected_runner() -> None:
    def fake_runner(model: str, prompt: str, temperature: float) -> str:
        assert model == "test-model"
        assert prompt == "hello"
        assert temperature == 0.0
        return "response"

    assert run_ollama("test-model", "hello", runner=fake_runner) == "response"


def test_run_ollama_http_error_raises() -> None:
    with patch(
        "fsmrepairbench.llm.ollama._call_ollama_http",
        side_effect=OllamaError("down"),
    ):
        with pytest.raises(OllamaError, match="down"):
            run_ollama("model", "prompt")


def test_run_llm_repair_case_with_mocked_ollama() -> None:
    reference = _toggle_reference()
    oracle = _toggle_oracle()
    faulty = _faulty_missing_transition(reference)
    baseline_patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)

    call_count = {"value": 0}

    def fake_ollama(model: str, prompt: str, temperature: float) -> str:
        _ = model, prompt, temperature
        call_count["value"] += 1
        return baseline_patch.model_dump_json()

    result = run_llm_repair_case(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=3,
        temperature=0.0,
        ollama_runner=fake_ollama,
    )

    assert call_count["value"] == 1
    assert result.passed is True
    assert result.score == pytest.approx(1.0)
    assert len(result.details["iterations"]) == 1
    assert result.details["iterations"][0]["patch_applied"] is True


def test_run_llm_repair_case_records_invalid_patch() -> None:
    faulty = _faulty_missing_transition(_toggle_reference())
    oracle = _toggle_oracle()

    def fake_ollama(model: str, prompt: str, temperature: float) -> str:
        _ = model, prompt, temperature
        return json.dumps(
            {
                "patch_id": "bad",
                "target_fsm_id": faulty.id,
                "operations": [
                    {"op": "remove_transition", "transition_id": "missing"},
                ],
            }
        )

    result = run_llm_repair_case(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=2,
        ollama_runner=fake_ollama,
    )

    assert result.passed is False
    assert len(result.details["iterations"]) == 2
    assert result.details["iterations"][0]["patch_valid"] is False


def test_parse_patch_response_sets_target_fsm_id() -> None:
    patch = parse_patch_response(
        '{"patch_id": "p", "operations": []}',
        target_fsm_id="toggle_001",
    )
    assert patch.target_fsm_id == "toggle_001"


def test_cli_llm_repair_with_mocked_runner(tmp_path: Path) -> None:
    reference = _toggle_reference()
    faulty = _faulty_missing_transition(reference)
    oracle = _toggle_oracle()
    baseline_patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)

    faulty_path = tmp_path / "faulty.json"
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(oracle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    out_path = tmp_path / "result.json"

    def fake_ollama(model: str, prompt: str, temperature: float) -> str:
        _ = model, prompt, temperature
        return baseline_patch.model_dump_json()

    with patch("fsmrepairbench.llm.ollama.run_ollama", side_effect=fake_ollama):
        result = runner.invoke(
            app,
            [
                "llm-repair",
                str(faulty_path),
                str(oracle_path),
                "--model",
                "mock-model",
                "--iterations",
                "2",
                "--out",
                str(out_path),
            ],
        )

    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["passed"] is True
    assert payload["score"] == pytest.approx(1.0)
