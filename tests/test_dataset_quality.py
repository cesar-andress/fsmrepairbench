"""Tests for automatic benchmark dataset quality validation."""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import build_single_case, CaseBuildSpec
from fsmrepairbench.dataset_quality import (
    QUALITY_REPORT_FILENAME,
    validate_dataset,
)
from fsmrepairbench.stratified_builder import build_stratified_dataset
from tests.test_coverage_optimizer import _write_minimal_matrix

runner = CliRunner()


def test_validate_dataset_on_built_case(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)

    result = validate_dataset(output_dir)

    assert result.report_path.is_file()
    assert result.report["case_count"] == 1
    assert result.report["overall_status"] in {"pass", "warn"}
    assert "duplicate_fsms" in result.report["checks"]
    assert result.passed


def test_validate_dataset_detects_duplicate_fsm(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)
    build_single_case(CaseBuildSpec(case_number=2, base_seed=43), output_dir)

    case_one = output_dir / "cases" / "case_000001" / "reference_fsm.json"
    case_two = output_dir / "cases" / "case_000002" / "reference_fsm.json"
    shutil.copy2(case_one, case_two)

    result = validate_dataset(output_dir)
    duplicate_check = result.report["checks"]["duplicate_fsms"]

    assert duplicate_check["status"] == "warn"
    assert duplicate_check["finding_count"] >= 1


def test_validate_dataset_detects_class_imbalance(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    (dataset_dir / "cases").mkdir()
    _write_minimal_matrix(dataset_dir / "feature_matrix.csv")
    imbalanced = textwrap.dedent(
        """
        case_id,machine_type,determinism,completeness,arity_class,size_class,guard_complexity,time_features,graph_structure,oracle_depth,bug_type,num_states,num_events,num_transitions,avg_out_degree,max_out_degree,num_guards,num_timed_guards,num_timeouts,num_cycles,scc_count,seed
        case_000001,plain_fsm,deterministic,complete,low,tiny,none,none,acyclic,shallow,missing_transition,3,2,2,1.0,1,0,0,0,0,1,42
        case_000002,plain_fsm,deterministic,complete,low,tiny,none,none,acyclic,shallow,missing_transition,4,2,3,1.0,1,0,0,0,0,1,43
        case_000003,plain_fsm,deterministic,complete,low,tiny,none,none,acyclic,shallow,missing_transition,5,2,4,1.0,1,0,0,0,0,1,44
        """
    ).strip() + "\n"
    (dataset_dir / "feature_matrix.csv").write_text(imbalanced, encoding="utf-8")

    for case_id in ("case_000001", "case_000002", "case_000003"):
        case_dir = dataset_dir / "cases" / case_id
        case_dir.mkdir()
        (case_dir / "case_metadata.json").write_text(
            json.dumps({"case_id": case_id, "reference_bpr": 1.0, "faulty_bpr": 0.5}) + "\n",
            encoding="utf-8",
        )

    result = validate_dataset(dataset_dir)
    imbalance = result.report["checks"]["class_imbalance"]

    assert imbalance["finding_count"] >= 1
    assert imbalance["findings"][0]["details"]["feature"] == "bug_type"


def test_validate_dataset_on_stratified_build(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        textwrap.dedent(
            """
            name: quality-test
            version: "1.0"
            seed: 42
            cells:
              - machine_type: plain_fsm
                determinism: deterministic
                completeness: complete
                arity_class: low
                size_class: tiny
                guard_complexity: none
                time_features: [none]
                graph_structure: [acyclic]
                oracle_depth: shallow
                bug_type: missing_transition
                count: 2
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, output_dir)

    result = validate_dataset(output_dir)

    assert (output_dir / QUALITY_REPORT_FILENAME).is_file()
    assert result.report["case_count"] == 2
    assert result.report["feature_matrix_analysis"] is not None


def test_cli_validate_dataset(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)

    result = runner.invoke(app, ["validate-dataset", str(output_dir)])
    assert result.exit_code == 0
    assert (output_dir / QUALITY_REPORT_FILENAME).is_file()
    assert "Quality report" in result.stdout
