"""Tests for the v0.3.0 multi-family external-validity pilot cohort."""

from __future__ import annotations

import csv
import json
import textwrap
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.generators.stratified_specs import load_dataset_plan, total_planned_cases
from fsmrepairbench.multifamily_analysis import (
    DETECTION_BY_FAMILY_COLUMNS,
    FAMILY_SUMMARY_COLUMNS,
    MULTIFAMILY_TARGET_FAMILIES,
    OPERATOR_BY_FAMILY_COLUMNS,
    analyze_multifamily_cohort,
    planned_counts_by_family,
)
from fsmrepairbench.stratified_builder import build_stratified_dataset

runner = CliRunner()
PLAN_PATH = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_multifamily_v0_3_smoke_plan.yaml"
PILOT_PLAN_PATH = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_multifamily_pilot_plan.yaml"


def _smoke_build_plan_yaml() -> str:
    return textwrap.dedent(
        """
        name: multifamily-smoke-test
        version: "0.3.0"
        seed: 46
        cells:
          - machine_type: plain_fsm
            determinism: deterministic
            completeness: partial
            arity_class: low
            size_class: tiny
            guard_complexity: none
            time_features: [none]
            graph_structure: [acyclic]
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
            bug_type: action_corruption
            count: 1
          - machine_type: moore
            determinism: deterministic
            completeness: partial
            arity_class: low
            size_class: tiny
            guard_complexity: none
            time_features: [none]
            graph_structure: [acyclic]
            oracle_depth: shallow
            bug_type: wrong_initial_state
            count: 1
          - machine_type: efsm
            determinism: deterministic
            completeness: complete
            arity_class: low
            size_class: tiny
            guard_complexity: compound
            time_features: [none]
            graph_structure: [acyclic]
            oracle_depth: shallow
            bug_type: guard_weaken
            count: 1
          - machine_type: timed_fsm
            determinism: deterministic
            completeness: complete
            arity_class: low
            size_class: tiny
            guard_complexity: simple
            time_features: [timeout]
            graph_structure: [acyclic]
            oracle_depth: shallow
            bug_type: timeout_corruption
            count: 1
        """
    ).strip()


def test_multifamily_pilot_plan_loads_and_balances_families() -> None:
    plan = load_dataset_plan(PILOT_PLAN_PATH)
    assert plan.name == "fsmrepairbench_multifamily_pilot"
    assert plan.version == "0.3.0-pilot"
    assert plan.seed == 46
    assert total_planned_cases(plan) == 20
    by_family = planned_counts_by_family(plan)
    assert set(by_family) == set(MULTIFAMILY_TARGET_FAMILIES)
    assert all(count == 4 for count in by_family.values())


def test_multifamily_v0_3_smoke_plan_loads_and_balances_families() -> None:
    plan = load_dataset_plan(PLAN_PATH)
    assert plan.name == "fsmrepairbench_multifamily_v0_3_smoke"
    assert plan.version == "0.3.0"
    assert plan.seed == 46
    assert total_planned_cases(plan) == 500
    by_family = planned_counts_by_family(plan)
    assert set(by_family) == set(MULTIFAMILY_TARGET_FAMILIES)
    assert all(count == 100 for count in by_family.values())


def test_build_multifamily_smoke_generates_non_plain_families(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_smoke_build_plan_yaml() + "\n", encoding="utf-8")
    output_dir = tmp_path / "dataset"
    result = build_stratified_dataset(plan_path, output_dir)

    assert len(result.cases) == 5
    families = {features.machine_type.value for features in result.cases}
    assert "plain_fsm" in families
    assert "mealy" in families
    assert "moore" in families
    assert "efsm" in families
    assert "timed_fsm" in families

    for case_id in ("case_000001", "case_000002", "case_000003", "case_000004", "case_000005"):
        case_dir = output_dir / "cases" / case_id
        assert (case_dir / "reference_fsm.json").is_file()
        assert (case_dir / "faulty_fsm.json").is_file()
        assert (case_dir / "oracle_suite.json").is_file()
        assert (case_dir / "bug_metadata.json").is_file()
        assert (case_dir / "case_features.json").is_file()


def test_analyze_multifamily_cohort_export_schema(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_smoke_build_plan_yaml() + "\n", encoding="utf-8")
    dataset_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, dataset_dir)

    out = tmp_path / "results"
    paper_dir = tmp_path / "paper"
    result = analyze_multifamily_cohort(
        dataset_dir,
        plan_path=plan_path,
        output_dir=out,
        paper_export_dir=paper_dir,
    )

    assert result.family_summary_path.is_file()
    assert result.operator_by_family_path.is_file()
    assert result.detection_by_family_path.is_file()
    assert result.report_path.is_file()
    assert result.manifest_path.is_file()
    assert (result.figures_dir / "family_case_counts.png").is_file()
    assert (result.tables_dir / "table_family_summary.tex").is_file()
    assert (paper_dir / "tables" / "table_family_summary.tex").is_file()

    family_rows = list(csv.DictReader(result.family_summary_path.open(encoding="utf-8")))
    assert list(family_rows[0].keys()) == list(FAMILY_SUMMARY_COLUMNS)
    assert len(family_rows) == len(MULTIFAMILY_TARGET_FAMILIES)

    operator_rows = list(csv.DictReader(result.operator_by_family_path.open(encoding="utf-8")))
    assert list(operator_rows[0].keys()) == list(OPERATOR_BY_FAMILY_COLUMNS)

    detection_rows = list(csv.DictReader(result.detection_by_family_path.open(encoding="utf-8")))
    assert list(detection_rows[0].keys()) == list(DETECTION_BY_FAMILY_COLUMNS)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["replaces_v0_2_analysis"] is False
    assert manifest["release_label"] == "v0.3.0-external-validity-pilot"
    assert "output_sha256" not in manifest or isinstance(manifest.get("output_sha256"), dict)


def test_analyze_multifamily_pilot_exports_coverage_and_manifest_hashes(tmp_path: Path) -> None:
    plan_path = tmp_path / "pilot_plan.yaml"
    plan_path.write_text(_smoke_build_plan_yaml().replace("multifamily-smoke-test", "fsmrepairbench_multifamily_pilot") + "\n", encoding="utf-8")
    dataset_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, dataset_dir)

    out = tmp_path / "results"
    result = analyze_multifamily_cohort(
        dataset_dir,
        plan_path=plan_path,
        output_dir=out,
        paper_export_dir=tmp_path / "paper",
    )

    assert result.coverage_dir is not None
    assert (result.coverage_dir / "dimension_summary.csv").is_file()
    assert (result.coverage_dir / "coverage_by_mutation_operator.csv").is_file()
    assert (result.coverage_dir / "coverage_by_complexity_tier.csv").is_file()
    assert (result.coverage_dir / "coverage_by_fsm_family.csv").is_file()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_label"] == "v0.3.0-multifamily-pilot"
    assert manifest["frozen_v0_2_reference"]["zenodo_doi"] == "10.5281/zenodo.20602528"
    assert isinstance(manifest["output_sha256"], dict)
    assert manifest["output_sha256"]["family_summary.csv"]
    assert manifest["regeneration_commands"]


def test_analyze_multifamily_cohort_cli(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_smoke_build_plan_yaml() + "\n", encoding="utf-8")
    dataset_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, dataset_dir)
    out = tmp_path / "out"

    result = runner.invoke(
        app,
        [
            "analyze-multifamily-cohort",
            str(dataset_dir),
            "--out",
            str(out),
            "--plan",
            str(plan_path),
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "family_summary.csv").is_file()
    assert (out / "detection_by_family.csv").is_file()
