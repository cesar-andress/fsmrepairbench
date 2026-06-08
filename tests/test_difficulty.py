"""Tests for FSM difficulty estimation."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.difficulty import (
    category_for_score,
    compute_difficulty_metrics,
    estimate_difficulty,
    estimate_difficulty_from_path,
)
from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_compute_difficulty_metrics_for_toggle_fsm() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    metrics = compute_difficulty_metrics(fsm)

    assert metrics.state_count == 2
    assert metrics.transition_count == 2
    assert metrics.branching_factor == 1.0
    assert metrics.average_path_length == 1.0
    assert metrics.cycles == 1
    assert metrics.strongly_connected_components == 1


def test_estimate_difficulty_score_is_bounded() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    estimate = estimate_difficulty(fsm)

    assert 0.0 <= estimate.difficulty_score <= 100.0
    assert estimate.category == "easy"
    assert estimate.to_metadata()["category"] == "easy"


def test_category_thresholds() -> None:
    assert category_for_score(10.0) == "easy"
    assert category_for_score(25.0) == "easy"
    assert category_for_score(26.0) == "medium"
    assert category_for_score(50.0) == "medium"
    assert category_for_score(51.0) == "hard"
    assert category_for_score(75.0) == "hard"
    assert category_for_score(76.0) == "expert"


def test_estimate_difficulty_from_generated_case(tmp_path: Path) -> None:
    from fsmrepairbench.dataset_builder import CaseBuildSpec, build_single_case

    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)

    case_dir = output_dir / "cases" / "case_000001"
    estimate = estimate_difficulty_from_path(case_dir)
    metadata = json.loads((case_dir / "case_metadata.json").read_text(encoding="utf-8"))

    assert 0.0 <= estimate.difficulty_score <= 100.0
    assert metadata["difficulty"]["difficulty_score"] == estimate.difficulty_score
    assert metadata["difficulty"]["category"] == estimate.category
    assert metadata["difficulty"]["metrics"]["state_count"] >= 1


def test_larger_fsm_scores_higher_than_toggle() -> None:
    toggle = load_fsm(FIXTURES / "simple_fsm.json")
    larger = FSM(
        id="larger",
        name="Larger",
        states=[State(id=f"s{i}") for i in range(10)],
        initial_state="s0",
        events=["e0", "e1", "e2"],
        transitions=[
            Transition(
                id=f"t{i}",
                source=f"s{i}",
                event=f"e{i % 3}",
                target=f"s{(i + 1) % 10}",
            )
            for i in range(10)
        ],
    )

    larger_score = estimate_difficulty(larger).difficulty_score
    toggle_score = estimate_difficulty(toggle).difficulty_score
    assert larger_score > toggle_score


def test_cli_estimate_difficulty(tmp_path: Path) -> None:
    output = tmp_path / "difficulty.json"
    result = runner.invoke(
        app,
        [
            "estimate-difficulty",
            str(FIXTURES / "simple_fsm.json"),
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    assert "easy" in result.stdout
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["category"] == "easy"
    assert "metrics" in payload
