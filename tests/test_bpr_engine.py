"""Tests for the BPR scoring engine."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.bpr_engine import (
    BPRScoreInput,
    CandidatePrediction,
    ScenarioPrediction,
    load_candidate_prediction,
    score_bpr_benchmark,
    write_bpr_csv_summaries,
    write_bpr_score_json,
)
from fsmrepairbench.literature_mutation import generate_literature_mutants
from fsmrepairbench.oracle_selection import MutantRecord
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _first_order_mutants(reference_path: Path) -> tuple[MutantRecord, ...]:
    reference = load_fsm(reference_path)
    report = generate_literature_mutants(
        reference,
        seed=42,
        first_order_count=5,
        second_order_count=0,
        higher_order_count=0,
        include_fsm=True,
    )
    return tuple(
        MutantRecord(mutant_id=record.mutant_id, fsm=record.fsm)
        for record in report.mutants
        if record.fsm is not None
    )


def test_score_reference_candidate_achieves_full_bpr() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    report = score_bpr_benchmark(
        BPRScoreInput(
            reference=reference,
            oracle=oracle,
            candidate=CandidatePrediction(candidate_fsm=reference.model_copy(deep=True)),
        )
    )

    assert report.bpr == pytest.approx(1.0)
    assert report.oracle_accuracy == pytest.approx(1.0)
    assert report.coverage.state == pytest.approx(1.0)
    assert report.coverage.transition == pytest.approx(1.0)


def test_score_faulty_candidate_reports_lower_bpr() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty = load_fsm(FIXTURES / "valid_fsm.json")
    faulty = faulty.model_copy(deep=True)
    faulty.initial_state = "open" if faulty.initial_state != "open" else "closed"
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")

    report = score_bpr_benchmark(
        BPRScoreInput(
            reference=reference,
            oracle=oracle,
            candidate=CandidatePrediction(candidate_fsm=faulty),
        )
    )

    assert report.bpr < 1.0


def test_mutation_score_with_mutants() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = _first_order_mutants(FIXTURES / "valid_fsm.json")

    report = score_bpr_benchmark(
        BPRScoreInput(
            reference=reference,
            oracle=oracle,
            candidate=CandidatePrediction(candidate_fsm=reference.model_copy(deep=True)),
            mutants=mutants,
        )
    )

    assert report.mutation_score > 0.0
    assert len(report.mutants) == len(mutants)
    assert report.execution_cost > 0


def test_explicit_predictions_oracle_accuracy() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    predictions = [
        ScenarioPrediction(
            scenario_id=scenario.id,
            expected_states=[step.expected_state for step in scenario.steps],
            expected_outputs=[None for _ in scenario.steps],
        )
        for scenario in oracle.scenarios
    ]

    report = score_bpr_benchmark(
        BPRScoreInput(
            reference=reference,
            oracle=oracle,
            candidate=CandidatePrediction(scenario_predictions=predictions),
        )
    )

    assert report.oracle_accuracy == pytest.approx(1.0)
    assert report.bpr == pytest.approx(1.0)


def test_write_bpr_outputs(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    report = score_bpr_benchmark(
        BPRScoreInput(
            reference=reference,
            oracle=oracle,
            candidate=CandidatePrediction(candidate_fsm=reference.model_copy(deep=True)),
        )
    )

    json_path = tmp_path / "bpr_score.json"
    write_bpr_score_json(json_path, report)
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "bpr" in payload
    assert "coverage" in payload
    assert "mutation_score" in payload
    assert "oracle_accuracy" in payload

    write_bpr_csv_summaries(tmp_path, report)
    assert (tmp_path / "bpr_summary.csv").exists()
    assert (tmp_path / "bpr_scenarios.csv").exists()
    assert (tmp_path / "bpr_mutants.csv").exists()


def test_load_candidate_prediction_from_fsm_json(tmp_path: Path) -> None:
    source = FIXTURES / "simple_fsm.json"
    candidate_path = tmp_path / "candidate.json"
    candidate_path.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    candidate = load_candidate_prediction(candidate_path)
    assert candidate.candidate_fsm is not None
    assert candidate.candidate_fsm.id == "toggle_001"


def test_cli_score_bpr(tmp_path: Path) -> None:
    out_dir = tmp_path / "results"
    result = runner.invoke(
        app,
        [
            "score-bpr",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "simple_oracle.json"),
            str(FIXTURES / "simple_fsm.json"),
            "--out",
            str(out_dir),
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    assert (out_dir / "bpr_summary.csv").exists()
    assert (out_dir / "bpr_score.json").exists()
