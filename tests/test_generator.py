"""Tests for benchmark generation."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from fsmrepairbench.generator import (
    SUMMARY_COLUMNS,
    BenchmarkGenerationError,
    discover_oracle_suites,
    discover_reference_fsm_files,
    discover_reference_fsm_paths,
    discover_reference_fsms,
    generate_benchmark,
)
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"


def _setup_input_dir(root: Path) -> Path:
    input_dir = root / "input"
    input_dir.mkdir()
    shutil.copy(FIXTURES / "valid_fsm.json", input_dir / "valid_fsm.json")
    oracles_dir = input_dir / "oracles"
    oracles_dir.mkdir()
    shutil.copy(FIXTURES / "valid_oracle.json", oracles_dir / "valid_oracle.json")
    return input_dir


def test_discover_reference_and_oracle_paths(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)

    reference_paths = discover_reference_fsm_paths(input_dir)
    oracle_suites = discover_oracle_suites(input_dir)

    assert reference_paths == [input_dir / "valid_fsm.json"]
    assert set(oracle_suites) == {"parking_gate_001"}
    assert oracle_suites["parking_gate_001"].id == "parking_gate_oracles"


def test_discover_reference_fsms_skips_oracle_json(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    shutil.copy(FIXTURES / "valid_fsm.json", input_dir / "valid_fsm.json")
    shutil.copy(FIXTURES / "valid_oracle.json", input_dir / "valid_oracle.json")

    discovery = discover_reference_fsm_files(input_dir)

    assert discovery.reference_paths == (input_dir / "valid_fsm.json",)
    assert len(discovery.skipped_files) == 1
    assert discovery.skipped_files[0][0].name == "valid_oracle.json"
    assert discover_reference_fsms(input_dir) == [input_dir / "valid_fsm.json"]


def test_discover_reference_fsms_on_fixtures_directory() -> None:
    discovery = discover_reference_fsm_files(FIXTURES)

    reference_names = {path.name for path in discovery.reference_paths}
    skipped_names = {path.name for path, _ in discovery.skipped_files}

    assert reference_names == {"simple_fsm.json", "valid_fsm.json"}
    assert "valid_oracle.json" in skipped_names
    assert "simple_oracle.json" in skipped_names
    assert "invalid_fsm.json" in skipped_names


def test_generate_benchmark_on_fixtures_directory(tmp_path: Path) -> None:
    output_dir = tmp_path / "generated_smoke"

    result = generate_benchmark(FIXTURES, output_dir, bugs_per_fsm=3, seed=42)

    assert len(result.cases) == 6
    assert result.skipped_input_files
    assert (output_dir / "summary.csv").is_file()
    assert (output_dir / "cases" / "case_000001").is_dir()


def test_generate_benchmark_writes_case_structure(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)
    output_dir = tmp_path / "generated"

    result = generate_benchmark(input_dir, output_dir, bugs_per_fsm=3, seed=123)

    assert result.summary_path == output_dir / "summary.csv"
    assert len(result.cases) == 3

    case_dir = output_dir / "cases" / "case_000001"
    assert case_dir.is_dir()
    assert (case_dir / "reference_fsm.json").is_file()
    assert (case_dir / "faulty_fsm.json").is_file()
    assert (case_dir / "bug_metadata.json").is_file()
    assert (case_dir / "oracle_suite.json").is_file()

    reference = load_fsm_json(case_dir / "reference_fsm.json")
    faulty = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle = load_oracle_suite(case_dir / "oracle_suite.json")
    metadata = json.loads((case_dir / "bug_metadata.json").read_text(encoding="utf-8"))

    assert reference.id == "parking_gate_001"
    assert faulty.id != reference.id
    assert oracle.id == "parking_gate_oracles"
    assert metadata["reference_fsm_id"] == reference.id
    assert metadata["faulty_fsm_id"] == faulty.id


def test_generate_benchmark_summary_csv(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)
    output_dir = tmp_path / "generated"

    generate_benchmark(input_dir, output_dir, bugs_per_fsm=4, seed=123)

    with (output_dir / "summary.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert list(rows[0].keys()) == list(SUMMARY_COLUMNS)
    assert len(rows) == 4
    assert rows[0]["case_id"] == "case_000001"
    assert rows[0]["reference_fsm_id"] == "parking_gate_001"
    assert rows[0]["valid_reference"] == "True"
    assert rows[0]["reference_bpr"] == "1.000000"
    assert rows[0]["faulty_bpr"] != ""
    assert rows[0]["bpr_delta"] != ""


def test_generate_benchmark_operator_rotation(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)
    output_dir = tmp_path / "generated"

    result = generate_benchmark(
        input_dir,
        output_dir,
        bugs_per_fsm=len(MUTATION_OPERATORS),
        seed=123,
    )

    operators = [case.mutation_operator for case in result.cases]
    assert operators == list(MUTATION_OPERATORS)


def test_generate_benchmark_reference_beats_faulty_bpr(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)
    output_dir = tmp_path / "generated"

    result = generate_benchmark(input_dir, output_dir, bugs_per_fsm=5, seed=123)

    for case in result.cases:
        assert case.reference_bpr == pytest.approx(1.0)
        assert case.faulty_bpr is not None
        assert case.bpr_delta is not None
        assert case.faulty_bpr <= case.reference_bpr
        assert case.bpr_delta >= 0.0


def test_generate_benchmark_marks_invalid_faulty_fsm(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)
    output_dir = tmp_path / "generated"

    result = generate_benchmark(
        input_dir,
        output_dir,
        bugs_per_fsm=len(MUTATION_OPERATORS),
        seed=123,
    )

    duplicate_case = next(
        case for case in result.cases if case.mutation_operator == "duplicate_transition"
    )
    assert duplicate_case.valid_faulty is False
    assert duplicate_case.valid_reference is True


def test_generate_benchmark_without_oracles(tmp_path: Path) -> None:
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    shutil.copy(FIXTURES / "simple_fsm.json", input_dir / "simple_fsm.json")
    output_dir = tmp_path / "generated"

    result = generate_benchmark(input_dir, output_dir, bugs_per_fsm=2, seed=7)

    case_dir = output_dir / "cases" / "case_000001"
    assert not (case_dir / "oracle_suite.json").exists()
    assert result.cases[0].reference_bpr is None
    assert result.cases[0].faulty_bpr is None
    assert result.cases[0].bpr_delta is None


def test_generate_benchmark_requires_reference_fsms(tmp_path: Path) -> None:
    input_dir = tmp_path / "empty"
    input_dir.mkdir()

    with pytest.raises(BenchmarkGenerationError, match="No reference FSM"):
        generate_benchmark(input_dir, tmp_path / "generated")


def test_generate_benchmark_rejects_non_positive_bug_count(tmp_path: Path) -> None:
    input_dir = _setup_input_dir(tmp_path)

    with pytest.raises(BenchmarkGenerationError, match="bugs_per_fsm"):
        generate_benchmark(input_dir, tmp_path / "generated", bugs_per_fsm=0)


def test_cli_generate_benchmark_on_fixtures(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from fsmrepairbench.cli import app

    output_dir = tmp_path / "generated_smoke"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "generate-benchmark",
            str(FIXTURES),
            str(output_dir),
            "--bugs-per-fsm",
            "3",
            "--seed",
            "42",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "summary.csv").exists()
    assert "Skipped" in result.stdout


def test_cli_generate_benchmark(tmp_path: Path) -> None:
    from typer.testing import CliRunner

    from fsmrepairbench.cli import app

    input_dir = _setup_input_dir(tmp_path)
    output_dir = tmp_path / "generated"
    runner = CliRunner()

    result = runner.invoke(
        app,
        [
            "generate-benchmark",
            str(input_dir),
            str(output_dir),
            "--bugs-per-fsm",
            "2",
            "--seed",
            "99",
        ],
    )

    assert result.exit_code == 0
    assert (output_dir / "summary.csv").exists()
    assert (output_dir / "cases" / "case_000001").exists()
    assert "Generated 2 cases" in result.stdout
