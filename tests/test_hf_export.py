"""Tests for HuggingFace dataset export."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import build_dataset
from fsmrepairbench.hf_export import (
    HuggingFaceExportError,
    collect_requirements,
    export_huggingface_dataset,
    load_case_record,
    split_records,
)
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _build_sample_dataset(output_dir: Path, *, size: int = 6) -> Path:
    build_dataset(size=size, seed=42, output_dir=output_dir, workers=1, resume=False)
    return output_dir


def test_collect_requirements_from_valid_fsm() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    assert collect_requirements(fsm) == ["R1"]


def test_load_case_record_contains_required_fields(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=1)
    case_dir = dataset_dir / "cases" / "case_000001"
    record = load_case_record(case_dir)

    assert record["case_id"] == "case_000001"
    assert "requirements" in record
    assert "reference_fsm" in record
    assert "faulty_fsm" in record
    assert "bug_metadata" in record
    assert "oracle_suite" in record
    assert record["reference_fsm"]["id"]
    assert record["bug_metadata"]["mutation_operator"]


def test_split_records_cover_all_examples() -> None:
    records = [{"case_id": f"case_{index:06d}"} for index in range(1, 11)]
    train, validation, test = split_records(records, seed=42)

    assert len(train) + len(validation) + len(test) == len(records)
    assert len(train) >= 1


def test_export_huggingface_dataset_writes_jsonl_and_card(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=5)
    result = export_huggingface_dataset(dataset_dir)

    assert result.output_dir == dataset_dir / "dataset"
    assert result.train_path.is_file()
    assert result.validation_path.is_file()
    assert result.test_path.is_file()
    assert result.dataset_card_path.is_file()
    assert sum(result.split_counts.values()) == 5

    train_lines = result.train_path.read_text(encoding="utf-8").strip().splitlines()
    assert train_lines
    first_record = json.loads(train_lines[0])
    assert set(first_record) >= {
        "case_id",
        "requirements",
        "reference_fsm",
        "faulty_fsm",
        "bug_metadata",
        "oracle_suite",
    }

    card = result.dataset_card_path.read_text(encoding="utf-8")
    assert card.startswith("---")
    assert "FSMRepairBench" in card
    assert "train.jsonl" in card


def test_export_huggingface_dataset_requires_dataset(tmp_path: Path) -> None:
    try:
        export_huggingface_dataset(tmp_path / "missing")
        raised = False
    except HuggingFaceExportError:
        raised = True
    assert raised


def test_cli_export_hf(tmp_path: Path) -> None:
    dataset_dir = _build_sample_dataset(tmp_path / "dataset", size=4)
    result = runner.invoke(app, ["export-hf", str(dataset_dir)])

    assert result.exit_code == 0
    assert (dataset_dir / "dataset" / "train.jsonl").is_file()
    assert (dataset_dir / "dataset" / "README.md").is_file()
    assert "Exported HuggingFace dataset" in result.stdout


def test_cli_export_hf_missing_dataset_reports_error(tmp_path: Path) -> None:
    missing_dir = tmp_path / "missing_dataset"
    result = runner.invoke(app, ["export-hf", str(missing_dir)])

    assert result.exit_code == 1
    assert "ERROR" in result.stdout
    assert "Dataset directory not found" in result.stdout
