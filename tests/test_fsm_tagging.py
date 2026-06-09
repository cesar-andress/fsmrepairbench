"""Tests for FSM structural tagging."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.fsm_tagging import (
    FSMTaggingError,
    METADATA_CSV_COLUMNS,
    SUPPORTED_FSM_TAGS,
    analyze_fsm_tags,
    tag_fsm_directory,
)
from fsmrepairbench.models import FSM
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_analyze_valid_fsm_assigns_core_tags() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    record = analyze_fsm_tags(
        fsm,
        filename="valid_fsm.json",
        compute_mutation_score=False,
    )

    assert record.size_tag == "small"
    assert record.determinism_tag == "deterministic"
    assert record.graph_tag in {"acyclic", "cyclic"}
    assert record.graph_tag in record.tags
    assert "small" in record.tags
    assert "deterministic" in record.tags
    assert record.tag_flags["small"] is True


def test_analyze_hierarchical_document() -> None:
    payload = json.loads((FIXTURES / "hierarchical_web.json").read_text(encoding="utf-8"))
    from fsmrepairbench.hierarchical_fsm import HierarchicalFSM, flatten_hierarchical_fsm

    hierarchical = HierarchicalFSM.model_validate(payload)
    fsm = flatten_hierarchical_fsm(hierarchical)
    record = analyze_fsm_tags(
        fsm,
        filename="hierarchical_web.json",
        source_kind="hierarchical_fsm",
        is_hierarchical=True,
        compute_mutation_score=False,
    )
    assert "hierarchical" in record.tags


def test_tag_directory_writes_metadata_csv(tmp_path: Path) -> None:
    source_dir = tmp_path / "fsms"
    source_dir.mkdir()
    for name in ("simple_fsm.json", "valid_fsm.json"):
        (source_dir / name).write_text(
            (FIXTURES / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    result = tag_fsm_directory(
        source_dir,
        compute_mutation_score=False,
        seed=1,
    )
    assert result.metadata_csv_path.is_file()
    assert len(result.records) == 2

    with result.metadata_csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(METADATA_CSV_COLUMNS)
        rows = list(reader)
    assert len(rows) == 2
    assert all(tag in rows[0] for tag in SUPPORTED_FSM_TAGS)
    assert rows[0]["tags"]


def test_timed_and_nondeterministic_tags() -> None:
    fsm = FSM.model_validate(
        {
            "id": "timed_nfa",
            "name": "Timed NFA",
            "states": [{"id": "s0"}, {"id": "s1"}, {"id": "s2"}],
            "initial_state": "s0",
            "events": ["go"],
            "transitions": [
                {
                    "id": "t1",
                    "source": "s0",
                    "event": "go",
                    "target": "s1",
                    "timeout": 2.0,
                },
                {
                    "id": "t2",
                    "source": "s0",
                    "event": "go",
                    "target": "s2",
                    "timeout": 2.0,
                },
            ],
        }
    )
    record = analyze_fsm_tags(
        fsm,
        filename="timed_nfa.json",
        compute_mutation_score=False,
    )
    assert record.determinism_tag == "non_deterministic"
    assert "timed" in record.tags
    assert "non_deterministic" in record.tags


def test_tag_benchmark_case_directory(parking_case: Path, tmp_path: Path) -> None:
    out = tmp_path / "metadata.csv"
    result = tag_fsm_directory(
        parking_case.parent,
        output_path=out,
        compute_mutation_score=False,
    )
    assert len(result.records) >= 1
    assert out.is_file()


@pytest.fixture
def parking_case(tmp_path: Path) -> Path:
    from fsmrepairbench.mutators import mutate
    from fsmrepairbench.validators import load_oracle_suite

    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle_suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 42)
    case_dir = tmp_path / "cases" / "case_000001"
    case_dir.mkdir(parents=True)
    (case_dir / "reference_fsm.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "faulty_fsm.json").write_text(
        faulty.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "oracle_suite.json").write_text(
        oracle_suite.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "bug_metadata.json").write_text(
        metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    return case_dir


def test_cli_tag_fsms(tmp_path: Path) -> None:
    source_dir = tmp_path / "fsms"
    source_dir.mkdir()
    (source_dir / "toggle.json").write_text(
        (FIXTURES / "simple_fsm.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out = tmp_path / "metadata.csv"
    result = runner.invoke(
        app,
        [
            "tag-fsms",
            str(source_dir),
            "--out",
            str(out),
            "--skip-mutation-score",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    assert out.is_file()


def test_tag_directory_raises_when_empty(tmp_path: Path) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(FSMTaggingError):
        tag_fsm_directory(empty)
