"""Tests for benchmark campaign orchestration."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.benchmark_campaign import (
    run_benchmark_campaign,
    write_mutation_summary_csv,
)
from fsmrepairbench.cli import app
from fsmrepairbench.stratified_builder import build_stratified_dataset

runner = CliRunner()


def _tiny_campaign_plan_yaml() -> str:
    return textwrap.dedent(
        """
        name: campaign-test
        version: "0.2.0"
        seed: 45
        cells:
          - machine_type: plain_fsm
            determinism: deterministic
            completeness: partial
            arity_class: low
            size_class: tiny
            guard_complexity: none
            time_features: [none]
            graph_structure: [hub_and_spoke]
            oracle_depth: shallow
            bug_type: missing_transition
            count: 1
          - machine_type: mealy
            determinism: deterministic
            completeness: complete
            arity_class: low
            size_class: tiny
            guard_complexity: simple
            time_features: [none]
            graph_structure: [acyclic]
            oracle_depth: shallow
            bug_type: wrong_target
            count: 1
        """
    ).strip()


def test_write_mutation_summary_csv(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_campaign_plan_yaml() + "\n", encoding="utf-8")
    dataset_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, dataset_dir)

    summary_path = write_mutation_summary_csv(dataset_dir, dataset_dir / "mutation_summary.csv")
    assert summary_path.is_file()
    text = summary_path.read_text(encoding="utf-8")
    assert "mutation_operator" in text
    assert "case_000001" in text


def test_run_benchmark_campaign_writes_reports(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_campaign_plan_yaml() + "\n", encoding="utf-8")
    dataset_dir = tmp_path / "dataset"
    output_dir = tmp_path / "campaign"

    result = run_benchmark_campaign(plan_path, dataset_dir, output_dir=output_dir)

    assert result.case_count == 2
    assert result.mutation_summary_path.is_file()
    assert result.summary_json_path.is_file()
    assert result.summary_csv_path.is_file()
    assert result.distributions_csv_path.is_file()
    assert result.benchmark_report_path.is_file()
    assert result.coupling_report_path.is_file()

    summary = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert summary["case_count"] == 2
    assert "behavioural_scoring" in summary
    assert "fault_localization" in summary
    assert "coupling_analysis" in summary
    assert "automata_families" in summary


def test_cli_run_benchmark_campaign(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_campaign_plan_yaml() + "\n", encoding="utf-8")
    dataset_dir = tmp_path / "dataset"
    output_dir = tmp_path / "campaign"

    result = runner.invoke(
        app,
        [
            "run-benchmark-campaign",
            str(plan_path),
            str(dataset_dir),
            "--out",
            str(output_dir),
        ],
    )
    assert result.exit_code == 0
    assert "Completed v0.2 campaign for 2 cases" in result.stdout
    assert (output_dir / "benchmark_report.md").is_file()
