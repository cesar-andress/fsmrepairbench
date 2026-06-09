"""Tests for adversarial FSM generation."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.adversarial_fsm import (
    AdversarialFSMError,
    SUPPORTED_ADVERSARIAL_PATTERNS,
    compute_difficulty_rank,
    generate_adversarial_dataset,
    generate_adversarial_fsm,
    rank_label,
)
from fsmrepairbench.cli import app
from fsmrepairbench.validators import is_valid_fsm, validate_fsm

runner = CliRunner()


@pytest.mark.parametrize("pattern", SUPPORTED_ADVERSARIAL_PATTERNS)
def test_each_adversarial_pattern_generates_valid_fsm(pattern: str) -> None:
    fsm, difficulty = generate_adversarial_fsm(pattern, seed=99)  # type: ignore[arg-type]
    assert is_valid_fsm(fsm)
    assert 1 <= difficulty.rank <= 10
    assert difficulty.label == rank_label(difficulty.rank)
    assert difficulty.pattern == pattern
    assert difficulty.llm_trap_signals


def test_difficulty_rank_is_bounded() -> None:
    fsm, difficulty = generate_adversarial_fsm("dense_transitions", seed=1)
    metadata = compute_difficulty_rank(fsm, "dense_transitions", scale=2.0, extra_adjustment=5)
    assert 1 <= metadata.rank <= 10


def test_generate_adversarial_dataset_writes_metadata(tmp_path: Path) -> None:
    result = generate_adversarial_dataset(output_dir=tmp_path / "adv", seed=7)
    assert len(result.records) == len(SUPPORTED_ADVERSARIAL_PATTERNS)
    assert result.metadata_csv_path.is_file()
    assert (result.output_dir / "dataset_manifest.json").is_file()

    with result.metadata_csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == len(SUPPORTED_ADVERSARIAL_PATTERNS)
    for row in rows:
        rank = int(row["difficulty_rank"])
        assert 1 <= rank <= 10
        fsm_path = result.output_dir / row["filename"]
        meta_path = result.output_dir / row["metadata_filename"]
        assert fsm_path.is_file()
        assert meta_path.is_file()
        payload = json.loads(meta_path.read_text(encoding="utf-8"))
        assert payload["difficulty"]["rank"] == rank
        assert payload["pattern"] == row["pattern"]


def test_temporal_pattern_sets_semantics_mode() -> None:
    fsm, difficulty = generate_adversarial_fsm("temporal_constraints", seed=3)
    assert fsm.semantics_mode == "timed_discrete"
    assert difficulty.features.get("semantics_mode") == "timed_discrete"
    errors = validate_fsm(fsm)
    assert not errors


def test_dataset_count_override(tmp_path: Path) -> None:
    result = generate_adversarial_dataset(
        output_dir=tmp_path / "subset",
        count=3,
        seed=5,
        patterns=("sparse_transitions", "dense_transitions"),
    )
    assert len(result.records) == 3


def test_cli_generate_adversarial_fsm(tmp_path: Path) -> None:
    out = tmp_path / "adv.json"
    meta = tmp_path / "adv_metadata.json"
    result = runner.invoke(
        app,
        [
            "generate-adversarial-fsm",
            "--out",
            str(out),
            "--metadata",
            str(meta),
            "--pattern",
            "hidden_cycles",
            "--seed",
            "42",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(meta.read_text(encoding="utf-8"))
    assert payload["pattern"] == "hidden_cycles"
    assert 1 <= payload["difficulty"]["rank"] <= 10


def test_cli_generate_adversarial_fsms(tmp_path: Path) -> None:
    out_dir = tmp_path / "dataset"
    result = runner.invoke(
        app,
        [
            "generate-adversarial-fsms",
            "--out",
            str(out_dir),
            "--count",
            "2",
            "--pattern",
            "equivalent_states",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    assert (out_dir / "metadata.csv").is_file()


def test_unknown_pattern_raises() -> None:
    with pytest.raises(AdversarialFSMError):
        generate_adversarial_fsm("not_a_pattern", seed=1)  # type: ignore[arg-type]
