"""Tests for repair trajectory persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.experiments import result_path, write_case_result
from fsmrepairbench.experiments import ExperimentCase, ExperimentSummaryRow, build_summary_row
from fsmrepairbench.llm.repair import run_llm_repair_with_client
from fsmrepairbench.models import FSM
from fsmrepairbench.repair_trajectory import (
    REPAIR_TRACE_FILENAME,
    build_repair_trace,
    export_repair_trace,
    repair_trace_path_for_result,
)
from fsmrepairbench.repair_engines.baselines import OracleGuidedMissingTransitionRepair
from fsmrepairbench.scorer import score_oracle_suite
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


def test_repair_loop_persists_full_iteration_payload() -> None:
    faulty = _faulty_toggle()
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)

    def fake_generate(model: str, prompt: str, temperature: float) -> str:
        _ = model, prompt, temperature
        return patch.model_dump_json()

    result = run_llm_repair_with_client(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=2,
        generate_fn=fake_generate,
    )

    iteration = result.details["iterations"][0]
    assert iteration["input_fsm"]["id"] == faulty.id
    assert isinstance(iteration["prompt"], str)
    assert isinstance(iteration["response"], str)
    assert iteration["patch"]["patch_id"] == patch.patch_id
    assert iteration["score"]["before"]["bpr"] >= 0.0
    assert iteration["score"]["after"]["bpr"] == pytest.approx(1.0)


def test_build_repair_trace_normalizes_iterations() -> None:
    faulty = _faulty_toggle()
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)

    result = run_llm_repair_with_client(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=1,
        generate_fn=lambda *_args, **_kwargs: patch.model_dump_json(),
    )

    trace = build_repair_trace(result)
    assert trace.bug_id == faulty.id
    assert len(trace.steps) == 1
    step = trace.steps[0]
    assert step.input_fsm is not None
    assert step.prompt is not None
    assert step.response is not None
    assert step.patch is not None
    assert step.score["after"]["bpr"] == pytest.approx(1.0)


def test_export_repair_trace_writes_json(tmp_path: Path) -> None:
    faulty = _faulty_toggle()
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)
    result = run_llm_repair_with_client(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=1,
        generate_fn=lambda *_args, **_kwargs: patch.model_dump_json(),
    )

    trace_path = tmp_path / REPAIR_TRACE_FILENAME
    export_repair_trace(result, trace_path)
    payload = json.loads(trace_path.read_text(encoding="utf-8"))

    assert payload["bug_id"] == faulty.id
    assert len(payload["iterations"]) == 1
    assert set(payload["iterations"][0]) == {
        "iteration",
        "input_fsm",
        "prompt",
        "response",
        "patch",
        "score",
    }
    assert payload["score_progression"][0] == pytest.approx(1.0)


def test_write_case_result_also_writes_repair_trace(tmp_path: Path) -> None:
    faulty = _faulty_toggle()
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)
    result = run_llm_repair_with_client(
        faulty,
        oracle,
        model="mock-model",
        max_iterations=1,
        generate_fn=lambda *_args, **_kwargs: patch.model_dump_json(),
    )
    case = ExperimentCase(
        case_id="case_000001",
        case_dir=tmp_path,
        faulty_fsm=faulty,
        oracle_suite=oracle,
        mutation_operator="missing_transition",
    )
    initial_bpr = score_oracle_suite(faulty, oracle).bpr
    summary = build_summary_row(
        case=case,
        model="mock-model",
        initial_bpr=initial_bpr,
        repair_result=result,
    )
    result_file = result_path(tmp_path / "results", "case_000001", "mock-model")
    write_case_result(
        result_file,
        case=case,
        model="mock-model",
        initial_bpr=initial_bpr,
        repair_result=result,
        summary_row=summary,
    )

    trace_file = repair_trace_path_for_result(result_file)
    assert trace_file.is_file()
    payload = json.loads(trace_file.read_text(encoding="utf-8"))
    assert payload["iterations"][0]["prompt"]


def test_cli_llm_repair_writes_repair_trace(tmp_path: Path) -> None:
    faulty = _faulty_toggle()
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    baseline_patch = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)

    faulty_path = tmp_path / "faulty.json"
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")
    oracle_path = tmp_path / "oracle.json"
    oracle_path.write_text(oracle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    out_path = tmp_path / "result.json"
    trace_path = tmp_path / REPAIR_TRACE_FILENAME

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
                "1",
                "--out",
                str(out_path),
            ],
        )

    assert result.exit_code == 0
    assert trace_path.is_file()
    assert "Repair trace:" in result.stdout
