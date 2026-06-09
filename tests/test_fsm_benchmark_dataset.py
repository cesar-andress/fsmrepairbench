"""Tests for the 10k FSM benchmark dataset generator."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.generators.fsm_benchmark_dataset import (
    FSMBenchmarkGenerationConfig,
    METADATA_CSV_COLUMNS,
    SUPPORTED_FSM_TYPES,
    compute_determinism_score,
    compute_reachability_score,
    dataset_type_distribution,
    fsm_filename_for_index,
    fsm_type_for_index,
    generate_fsm_benchmark_dataset,
    generate_single_fsm,
)
from fsmrepairbench.validators import load_fsm_json, validate_fsm

runner = CliRunner()


def test_fsm_type_cycles_through_supported_families() -> None:
    types = [fsm_type_for_index(index) for index in range(1, 13)]
    assert types == list(SUPPORTED_FSM_TYPES) * 2


def test_generate_single_fsm_is_reproducible() -> None:
    first_fsm, first_meta = generate_single_fsm(42, base_seed=7)
    second_fsm, second_meta = generate_single_fsm(42, base_seed=7)

    assert first_fsm.model_dump() == second_fsm.model_dump()
    assert first_meta == second_meta
    assert first_meta.type == fsm_type_for_index(42)
    assert validate_fsm(first_fsm, allow_nondeterminism=first_meta.type == "NFA") == []


@pytest.mark.parametrize("index", [1, 2, 3, 4, 5, 6])
def test_each_machine_family_generates_valid_fsm(index: int) -> None:
    fsm, metadata = generate_single_fsm(index, base_seed=99)
    assert metadata.type == SUPPORTED_FSM_TYPES[index - 1]
    assert metadata.filename == fsm_filename_for_index(index)
    assert metadata.num_states == len(fsm.states)
    assert metadata.num_transitions == len(fsm.transitions)
    assert metadata.alphabet_size == len(fsm.events)
    assert 0.0 <= metadata.determinism_score <= 1.0
    assert 0.0 < metadata.reachability_score <= 1.0
    assert metadata.strongly_connected_components >= 1
    assert metadata.dead_states >= 0
    assert metadata.sink_states >= 0
    assert metadata.cycle_count >= 0


def test_nfa_has_lower_determinism_score_than_dfa() -> None:
    _, dfa_meta = generate_single_fsm(1, base_seed=123)
    _, nfa_meta = generate_single_fsm(2, base_seed=123)

    assert dfa_meta.type == "DFA"
    assert nfa_meta.type == "NFA"
    assert dfa_meta.determinism_score == pytest.approx(1.0)
    assert nfa_meta.determinism_score < dfa_meta.determinism_score


def test_generate_dataset_writes_metadata_and_json_files(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    config = FSMBenchmarkGenerationConfig(count=24, seed=42, output_dir=output_dir)
    records = generate_fsm_benchmark_dataset(config)

    assert len(records) == 24
    assert (output_dir / "metadata.csv").exists()
    for index in range(1, 25):
        assert (output_dir / fsm_filename_for_index(index)).exists()

    with (output_dir / "metadata.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 24
    assert list(rows[0].keys()) == list(METADATA_CSV_COLUMNS)
    assert dataset_type_distribution(records) == {fsm_type: 4 for fsm_type in SUPPORTED_FSM_TYPES}


def test_dataset_generation_is_reproducible(tmp_path: Path) -> None:
    first_dir = tmp_path / "run_a"
    second_dir = tmp_path / "run_b"
    config_a = FSMBenchmarkGenerationConfig(count=12, seed=99, output_dir=first_dir)
    config_b = FSMBenchmarkGenerationConfig(count=12, seed=99, output_dir=second_dir)

    generate_fsm_benchmark_dataset(config_a)
    generate_fsm_benchmark_dataset(config_b)

    first_fsm = load_fsm_json(first_dir / "fsm_000006.json")
    second_fsm = load_fsm_json(second_dir / "fsm_000006.json")
    assert first_fsm.model_dump() == second_fsm.model_dump()

    first_csv = (first_dir / "metadata.csv").read_text(encoding="utf-8")
    second_csv = (second_dir / "metadata.csv").read_text(encoding="utf-8")
    assert first_csv == second_csv


def test_mealy_and_moore_outputs_are_present(tmp_path: Path) -> None:
    fsm_mealy, mealy_meta = generate_single_fsm(3, base_seed=5)
    fsm_moore, moore_meta = generate_single_fsm(4, base_seed=5)

    assert mealy_meta.type == "Mealy"
    assert moore_meta.type == "Moore"
    assert any(transition.output for transition in fsm_mealy.transitions)
    assert any(state.state_output for state in fsm_moore.states)


def test_efsm_and_timed_outputs_are_present(tmp_path: Path) -> None:
    fsm_efsm, efsm_meta = generate_single_fsm(5, base_seed=5)
    fsm_timed, timed_meta = generate_single_fsm(6, base_seed=5)

    assert efsm_meta.type == "EFSM"
    assert timed_meta.type == "Timed FSM"
    assert fsm_efsm.variables
    assert any(transition.guard for transition in fsm_efsm.transitions)
    assert any(transition.timeout is not None for transition in fsm_timed.transitions)


def test_metric_helpers_bound_scores() -> None:
    fsm, _ = generate_single_fsm(10, base_seed=0)
    assert 0.0 <= compute_determinism_score(fsm) <= 1.0
    assert 0.0 < compute_reachability_score(fsm) <= 1.0


def test_cli_generate_fsm_dataset(tmp_path: Path) -> None:
    out_dir = tmp_path / "dataset"
    result = runner.invoke(
        app,
        [
            "generate-fsm-dataset",
            "--out",
            str(out_dir),
            "--count",
            "18",
            "--seed",
            "42",
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    assert (out_dir / "metadata.csv").exists()
    payload = json.loads((out_dir / "fsm_000001.json").read_text(encoding="utf-8"))
    assert payload["id"].startswith("fsm_000001_")
