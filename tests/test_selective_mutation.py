"""Tests for selective mutation planning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM
from fsmrepairbench.selective_mutation import (
    SUPPORTED_STRATEGIES,
    SelectiveMutationError,
    enumerate_candidates,
    mutation_plan_to_dict,
    plan_mutations,
    write_mutation_plan_json,
)
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture
def simple_fsm() -> FSM:
    return load_fsm(FIXTURES / "simple_fsm.json")


@pytest.fixture
def valid_fsm() -> FSM:
    return load_fsm(FIXTURES / "valid_fsm.json")


def test_enumerate_candidates_returns_feasible_mutations(simple_fsm: FSM) -> None:
    candidates = enumerate_candidates(simple_fsm)

    assert candidates
    assert all(candidate.operator for candidate in candidates)
    assert all(candidate.location.location_type for candidate in candidates)


@pytest.mark.parametrize("strategy", SUPPORTED_STRATEGIES)
def test_plan_mutations_respects_budget(simple_fsm: FSM, strategy: str) -> None:
    budget = 5
    plan = plan_mutations(simple_fsm, strategy=strategy, budget=budget, seed=7)  # type: ignore[arg-type]

    assert plan.fsm_id == simple_fsm.id
    assert plan.strategy == strategy
    assert plan.budget == budget
    assert len(plan.planned_mutations) <= budget
    assert plan.selected_operators
    assert plan.selected_locations
    assert plan.expected_cost >= 0.0
    assert 0.0 <= plan.expected_diversity <= 1.0
    assert plan.rationale


def test_all_strategy_includes_every_candidate_when_budget_allows(simple_fsm: FSM) -> None:
    candidates = enumerate_candidates(simple_fsm)
    plan = plan_mutations(simple_fsm, strategy="all", budget=len(candidates))

    assert len(plan.planned_mutations) == len(candidates)


def test_balanced_by_operator_spreads_across_operators(simple_fsm: FSM) -> None:
    plan = plan_mutations(simple_fsm, strategy="balanced_by_operator", budget=6)

    operator_counts: dict[str, int] = {}
    for mutation in plan.planned_mutations:
        operator_counts[mutation.operator] = operator_counts.get(mutation.operator, 0) + 1

    assert len(operator_counts) >= 2
    assert max(operator_counts.values()) - min(operator_counts.values()) <= 1


def test_random_sample_is_reproducible_with_seed(simple_fsm: FSM) -> None:
    plan_a = plan_mutations(simple_fsm, strategy="random_sample", budget=4, seed=99)
    plan_b = plan_mutations(simple_fsm, strategy="random_sample", budget=4, seed=99)

    assert [mutation.to_dict() for mutation in plan_a.planned_mutations] == [
        mutation.to_dict() for mutation in plan_b.planned_mutations
    ]


def test_cost_aware_prefers_low_cost_operators(valid_fsm: FSM) -> None:
    plan = plan_mutations(valid_fsm, strategy="cost_aware", budget=3)
    costs = [mutation.operator for mutation in plan.planned_mutations]

    assert costs[0] in {"missing_transition", "wrong_target", "wrong_source", "wrong_event"}


def test_coverage_aware_prioritizes_new_locations(valid_fsm: FSM) -> None:
    plan = plan_mutations(valid_fsm, strategy="coverage_aware", budget=4)
    transition_ids = {
        mutation.location.location_id
        for mutation in plan.planned_mutations
        if mutation.location.location_type == "transition"
    }

    assert len(transition_ids) >= 2


def test_difficulty_aware_uses_difficulty_metadata(valid_fsm: FSM) -> None:
    plan = plan_mutations(valid_fsm, strategy="difficulty_aware", budget=3)

    assert "difficulty score" in plan.rationale.lower()


def test_mutation_plan_to_dict_and_write_json(tmp_path: Path, simple_fsm: FSM) -> None:
    plan = plan_mutations(simple_fsm, strategy="coverage_aware", budget=3)
    payload = mutation_plan_to_dict(plan)

    assert payload["fsm_id"] == simple_fsm.id
    assert payload["strategy"] == "coverage_aware"
    assert payload["budget"] == 3
    assert isinstance(payload["selected_operators"], list)
    assert isinstance(payload["planned_mutations"], list)

    out_path = tmp_path / "mutation_plan.json"
    write_mutation_plan_json(out_path, plan)
    loaded = json.loads(out_path.read_text(encoding="utf-8"))

    assert loaded == payload


def test_plan_mutations_unknown_strategy_raises(simple_fsm: FSM) -> None:
    with pytest.raises(SelectiveMutationError, match="Unknown strategy"):
        plan_mutations(simple_fsm, strategy="unknown", budget=1)  # type: ignore[arg-type]


def test_enumerate_candidates_raises_when_no_feasible_operators(simple_fsm: FSM) -> None:
    with pytest.raises(SelectiveMutationError, match="No applicable mutation candidates"):
        enumerate_candidates(simple_fsm, operators=["not_a_real_operator"])


def test_cli_plan_mutations_writes_json(tmp_path: Path) -> None:
    out_path = tmp_path / "mutation_plan.json"
    result = runner.invoke(
        app,
        [
            "plan-mutations",
            str(FIXTURES / "simple_fsm.json"),
            "--strategy",
            "coverage_aware",
            "--budget",
            "10",
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["strategy"] == "coverage_aware"
    assert payload["budget"] == 10
    assert len(payload["planned_mutations"]) <= 10


def test_cli_plan_mutations_rejects_unknown_strategy(tmp_path: Path) -> None:
    out_path = tmp_path / "mutation_plan.json"
    result = runner.invoke(
        app,
        [
            "plan-mutations",
            str(FIXTURES / "simple_fsm.json"),
            "--strategy",
            "not_a_strategy",
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 1
    assert not out_path.exists()
