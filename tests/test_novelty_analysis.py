"""Tests for benchmark novelty analysis."""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import CaseBuildSpec, build_single_case
from fsmrepairbench.novelty_analysis import (
    NOVELTY_REPORT_FILENAME,
    analyze_novelty,
    combined_similarity,
    graph_similarity,
    oracle_similarity,
    transition_similarity,
)
from fsmrepairbench.stratified_builder import build_stratified_dataset
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

runner = CliRunner()


def test_analyze_novelty_on_single_case(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)

    result = analyze_novelty(output_dir)

    assert result.report_path.is_file()
    assert result.report["case_count"] == 1
    assert result.report["novelty_summary"]["collapse_risk"] == "low"
    assert result.report["high_similarity_clusters"] == []
    assert not result.collapsed


def test_analyze_novelty_detects_duplicate_cluster(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)
    build_single_case(CaseBuildSpec(case_number=2, base_seed=43), output_dir)

    case_one = output_dir / "cases" / "case_000001" / "reference_fsm.json"
    case_two = output_dir / "cases" / "case_000002" / "reference_fsm.json"
    oracle_one = output_dir / "cases" / "case_000001" / "oracle_suite.json"
    oracle_two = output_dir / "cases" / "case_000002" / "oracle_suite.json"
    shutil.copy2(case_one, case_two)
    shutil.copy2(oracle_one, oracle_two)

    result = analyze_novelty(output_dir)
    summary = result.report["novelty_summary"]

    assert summary["high_similarity_cluster_count"] >= 1
    assert summary["largest_cluster_size"] == 2
    assert summary["mean_combined_similarity"] >= 0.95
    assert result.report["high_similarity_clusters"][0]["case_ids"] == [
        "case_000001",
        "case_000002",
    ]


def test_similarity_metrics_are_deterministic(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)
    build_single_case(CaseBuildSpec(case_number=2, base_seed=43), output_dir)

    case_one_dir = output_dir / "cases" / "case_000001"
    case_two_dir = output_dir / "cases" / "case_000002"
    fsm_one = load_fsm_json(case_one_dir / "reference_fsm.json")
    fsm_two = load_fsm_json(case_two_dir / "reference_fsm.json")
    oracle_one = load_oracle_suite(case_one_dir / "oracle_suite.json")
    oracle_two = load_oracle_suite(case_two_dir / "oracle_suite.json")

    graph = graph_similarity(fsm_one, fsm_two)
    transition = transition_similarity(fsm_one, fsm_two)
    oracle = oracle_similarity(oracle_one, oracle_two)
    combined = combined_similarity(
        graph=graph,
        transition=transition,
        structural=0.5,
        oracle=oracle,
    )

    assert 0.0 <= graph <= 1.0
    assert 0.0 <= transition <= 1.0
    assert 0.0 <= oracle <= 1.0
    assert 0.0 <= combined <= 1.0


def test_analyze_novelty_on_stratified_build(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(
        textwrap.dedent(
            """
            name: novelty-test
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
                count: 3
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    output_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, output_dir)

    result = analyze_novelty(output_dir)

    assert (output_dir / NOVELTY_REPORT_FILENAME).is_file()
    assert result.report["case_count"] == 3
    assert "notable_pairs" in result.report


def test_cli_analyze_novelty(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_single_case(CaseBuildSpec(case_number=1, base_seed=42), output_dir)

    result = runner.invoke(app, ["analyze-novelty", str(output_dir)])
    assert result.exit_code == 0
    assert (output_dir / NOVELTY_REPORT_FILENAME).is_file()
    assert "Novelty report" in result.stdout
