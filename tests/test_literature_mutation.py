"""Tests for literature-inspired FSM mutation operators."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.literature_mutation import (
    LITERATURE_MUTATION_OPERATORS,
    apply_literature_operator,
    generate_literature_mutants,
    generate_literature_mutants_for_directory,
    write_mutant_report_json,
)
from fsmrepairbench.validators import load_fsm, load_fsm_json

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.mark.parametrize("operator", LITERATURE_MUTATION_OPERATORS)
def test_each_literature_operator_applies_on_valid_fsm(operator: str) -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    mutated, description = apply_literature_operator(fsm, operator, seed=42)  # type: ignore[arg-type]
    assert mutated.model_dump() != fsm.model_dump()
    assert description


def test_generate_literature_mutants_counts_and_fields() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    report = generate_literature_mutants(fsm, seed=7)

    assert report.statistics.total_mutants == 30
    assert report.statistics.first_order_count == 10
    assert report.statistics.second_order_count == 10
    assert report.statistics.higher_order_count == 10
    assert len(report.mutants) == 30

    for mutant in report.mutants:
        assert mutant.mutant_id
        assert mutant.parent_id == fsm.id
        assert mutant.mutation_type
        assert mutant.mutation_description
        assert mutant.fsm is not None
        assert mutant.fsm.parent_fsm_id == fsm.id


def test_first_order_mutants_use_single_operator() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    report = generate_literature_mutants(fsm, seed=11)
    first_order = [item for item in report.mutants if item.order_class == "first_order"]
    assert len(first_order) == 10
    assert all(len(item.operators) == 1 for item in first_order)
    assert all(item.mutation_order == 1 for item in first_order)


def test_second_and_higher_order_mutants_chain_operators() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    report = generate_literature_mutants(fsm, seed=13)

    second_order = [item for item in report.mutants if item.order_class == "second_order"]
    higher_order = [item for item in report.mutants if item.order_class == "higher_order"]

    assert all(len(item.operators) == 2 for item in second_order)
    assert all(item.mutation_order == 2 for item in second_order)
    assert all(len(item.operators) == 3 for item in higher_order)
    assert all(item.mutation_order == 3 for item in higher_order)
    assert all("," in item.mutation_type for item in second_order + higher_order)


def test_mutant_generation_is_reproducible() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    first = generate_literature_mutants(fsm, seed=99)
    second = generate_literature_mutants(fsm, seed=99)
    assert [item.mutant_id for item in first.mutants] == [item.mutant_id for item in second.mutants]


def test_write_mutant_report_json(tmp_path: Path) -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    report = generate_literature_mutants(fsm, seed=5, include_fsm=False)
    out_path = tmp_path / "mutants.json"
    write_mutant_report_json(out_path, report, include_fsm=False)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["statistics"]["total_mutants"] == 30
    assert len(payload["mutants"]) == 30
    assert "fsm" not in payload["mutants"][0]
    assert set(payload["mutants"][0].keys()) >= {
        "mutant_id",
        "parent_id",
        "mutation_type",
        "mutation_description",
    }


def test_statistics_include_operator_counts() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    report = generate_literature_mutants(fsm, seed=21)
    assert report.statistics.by_operator
    assert sum(report.statistics.by_operator.values()) >= report.statistics.total_mutants


def test_generate_literature_mutants_for_directory(tmp_path: Path) -> None:
    input_dir = tmp_path / "dataset"
    output_dir = tmp_path / "mutants"
    input_dir.mkdir()
    for index in range(1, 4):
        source = FIXTURES / "simple_fsm.json"
        target = input_dir / f"fsm_{index:06d}.json"
        payload = json.loads(source.read_text(encoding="utf-8"))
        payload["id"] = f"simple_{index:06d}"
        target.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    summary = generate_literature_mutants_for_directory(input_dir, output_dir, seed=42)
    assert summary.fsm_count == 3
    assert summary.total_mutants == 90
    assert (output_dir / "statistics.json").exists()
    assert (output_dir / "fsm_000001_mutants.json").exists()


def test_cli_generate_literature_mutants(tmp_path: Path) -> None:
    out_path = tmp_path / "mutants.json"
    result = runner.invoke(
        app,
        [
            "generate-literature-mutants",
            str(FIXTURES / "valid_fsm.json"),
            "--out",
            str(out_path),
            "--seed",
            "42",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["statistics"]["total_mutants"] == 30
