"""Tests for benchmark feature-space coverage analysis."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.coverage_optimizer import (
    COVERAGE_REPORT_FILENAME,
    analyze_feature_coverage,
    generate_coverage_report,
    load_feature_matrix,
    suggest_additional_cases,
)
from fsmrepairbench.stratified_builder import build_stratified_dataset

runner = CliRunner()


def _write_minimal_matrix(path: Path) -> None:
    path.write_text(
        textwrap.dedent(
            """
            case_id,machine_type,determinism,completeness,arity_class,size_class,guard_complexity,time_features,graph_structure,oracle_depth,bug_type,num_states,num_events,num_transitions,avg_out_degree,max_out_degree,num_guards,num_timed_guards,num_timeouts,num_cycles,scc_count,seed
            case_000001,plain_fsm,deterministic,complete,low,tiny,none,none,acyclic,shallow,missing_transition,3,2,2,1.0,1,0,0,0,0,1,42
            case_000002,mealy,deterministic,complete,medium,small,simple,none,sparse,medium,wrong_target,5,3,4,1.5,2,2,0,0,0,1,43
            case_000003,efsm,deterministic,complete,high,medium,compound,none,dense,deep,guard_flip,10,5,12,2.0,4,8,0,0,1,2,44
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def test_load_feature_matrix_and_analyze(tmp_path: Path) -> None:
    matrix_path = tmp_path / "feature_matrix.csv"
    _write_minimal_matrix(matrix_path)

    rows = load_feature_matrix(matrix_path)
    report = analyze_feature_coverage(matrix_path, suggestion_count=200)

    assert len(rows) == 3
    assert report["case_count"] == 3
    assert report["unique_feature_combinations"]["unique_count"] == 3
    assert "machine_type" in report["feature_entropy"]
    assert "machine_type__bug_type" in report["pairwise_coverage"]
    assert report["triple_coverage"]["observed_triples"] >= 1
    assert isinstance(report["rare_combinations"], list)
    assert report["missing_combinations"]["missing_count"] > 0
    assert report["suggestions"]["target_additional_cases"] == 200
    assert "generate 200 additional cases" in report["suggestions"]["message"]


def test_generate_coverage_report_from_stratified_dataset(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        textwrap.dedent(
            """
            name: coverage-test
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

    result = generate_coverage_report(output_dir, suggestion_count=50)
    assert result.report_path.is_file()
    payload = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert payload["case_count"] == 2
    assert payload["suggestions"]["target_additional_cases"] == 50


def test_suggest_additional_cases_returns_regions(tmp_path: Path) -> None:
    matrix_path = tmp_path / "feature_matrix.csv"
    _write_minimal_matrix(matrix_path)
    suggestion = suggest_additional_cases(load_feature_matrix(matrix_path), target_count=200)
    assert suggestion["regions"]
    assert suggestion["recommended_total_cases"] > 0


def test_cli_coverage_optimizer(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    dataset_dir.mkdir()
    _write_minimal_matrix(dataset_dir / "feature_matrix.csv")

    result = runner.invoke(
        app,
        ["coverage-optimizer", str(dataset_dir), "--suggest-count", "200"],
    )
    assert result.exit_code == 0
    assert (dataset_dir / COVERAGE_REPORT_FILENAME).is_file()
    assert "generate 200 additional cases" in result.stdout
