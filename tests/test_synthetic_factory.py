"""Tests for synthetic FSM generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.generators.synthetic_factory import (
    SyntheticFactoryError,
    SyntheticGenerationParams,
    assert_reachability_requirements,
    complexity_presets,
    export_fsm_json,
    generate_synthetic_fsm,
    params_from_complexity,
    reachable_state_ids,
)
from fsmrepairbench.validators import is_valid_fsm, load_fsm_json, validate_fsm

runner = CliRunner()


def test_generated_fsm_is_valid_and_reproducible() -> None:
    params = SyntheticGenerationParams(
        num_states=12,
        num_events=4,
        branching_factor=3,
        seed=42,
    )
    first = generate_synthetic_fsm(params)
    second = generate_synthetic_fsm(params)

    assert first.model_dump() == second.model_dump()
    assert is_valid_fsm(first)
    assert len(first.states) == 12
    assert len(first.events) == 4


def test_reachable_states_have_paths_from_initial() -> None:
    params = SyntheticGenerationParams(num_states=15, num_events=6, seed=7)
    fsm = generate_synthetic_fsm(params)
    reachable = reachable_state_ids(fsm)

    assert fsm.initial_state in reachable
    assert_reachability_requirements(fsm, allow_dead_states=False)
    for state_id in reachable:
        assert state_id in {state.id for state in fsm.states}


def test_allow_dead_states_creates_unreachable_states() -> None:
    params = SyntheticGenerationParams(
        num_states=12,
        num_events=4,
        seed=99,
        allow_dead_states=True,
    )
    fsm = generate_synthetic_fsm(params)
    reachable = reachable_state_ids(fsm)

    assert len(reachable) < len(fsm.states)
    assert_reachability_requirements(fsm, allow_dead_states=True)


def test_deterministic_fsm_has_no_conflicting_triples() -> None:
    params = SyntheticGenerationParams(
        num_states=20,
        num_events=8,
        branching_factor=4,
        deterministic=True,
        seed=5,
    )
    fsm = generate_synthetic_fsm(params)
    assert validate_fsm(fsm) == []


def test_nondeterministic_fsm_can_be_generated() -> None:
    params = SyntheticGenerationParams(
        num_states=10,
        num_events=4,
        branching_factor=4,
        deterministic=False,
        seed=3,
    )
    fsm = generate_synthetic_fsm(params)
    assert validate_fsm(fsm, allow_nondeterminism=True) == []


@pytest.mark.parametrize("level", ["small", "medium", "large", "very_large"])
def test_complexity_presets_generate_valid_fsms(level: str) -> None:
    params = params_from_complexity(level, seed=11)  # type: ignore[arg-type]
    fsm = generate_synthetic_fsm(params)
    preset = complexity_presets()[level]

    assert len(fsm.states) == preset["num_states"]
    assert len(fsm.events) == preset["num_events"]
    assert is_valid_fsm(fsm)


def test_export_fsm_json_writes_benchmark_format(tmp_path: Path) -> None:
    params = SyntheticGenerationParams(num_states=6, num_events=3, seed=1)
    fsm = generate_synthetic_fsm(params)
    output = tmp_path / "fsm.json"

    export_fsm_json(fsm, output)
    loaded = load_fsm_json(output)

    assert loaded.id == fsm.id
    assert loaded.initial_state == fsm.initial_state


def test_invalid_params_raise() -> None:
    with pytest.raises(SyntheticFactoryError):
        generate_synthetic_fsm(
            SyntheticGenerationParams(num_states=0, num_events=1, seed=1)
        )


def test_cli_generate_fsm(tmp_path: Path) -> None:
    output = tmp_path / "fsm.json"
    result = runner.invoke(
        app,
        [
            "generate-fsm",
            "--states",
            "20",
            "--events",
            "10",
            "--seed",
            "42",
            "--out",
            str(output),
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["id"] == "synthetic_42_20_10"
    assert len(payload["states"]) == 20
    assert len(payload["events"]) == 10
