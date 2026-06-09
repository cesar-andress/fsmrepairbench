"""Tests for depth-forced oracle depth ablation (C3 v2)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.oracle_depth_ablation import (
    ABLATION_DEPTHS,
    PAIRED_DETECTION_COLUMNS,
    V2_EXPERIMENT,
    V2_PER_CASE_COLUMNS,
    compute_paired_detection_changes,
    run_oracle_depth_ablation,
    score_case_at_depth,
)
from fsmrepairbench.oracle_generator import generate_oracle_suite
from fsmrepairbench.validators import load_fsm_json

runner = CliRunner()
FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"
FIXTURE_CASE = FIXTURE_DATASET / "cases" / "case_000002"


def test_depth_forced_medium_and_deep_have_longer_or_more_scenarios() -> None:
    fsm = load_fsm_json(FIXTURE_CASE / "reference_fsm.json")
    shallow = generate_oracle_suite(fsm, depth="shallow", policy="depth-forced")
    medium = generate_oracle_suite(fsm, depth="medium", policy="depth-forced")
    deep = generate_oracle_suite(fsm, depth="deep", policy="depth-forced")

    assert medium.mean_scenario_length > shallow.mean_scenario_length
    assert deep.mean_scenario_length > medium.mean_scenario_length
    assert deep.max_scenario_length > shallow.max_scenario_length
    assert len(medium.suite.scenarios) >= len(shallow.suite.scenarios)
    assert len(deep.suite.scenarios) >= len(medium.suite.scenarios)


def test_shortest_path_policy_unchanged_on_fixture_case() -> None:
    fsm = load_fsm_json(FIXTURE_CASE / "reference_fsm.json")
    shallow = generate_oracle_suite(fsm, depth="shallow", policy="shortest-path")
    medium = generate_oracle_suite(fsm, depth="medium", policy="shortest-path")
    deep = generate_oracle_suite(fsm, depth="deep", policy="shortest-path")

    assert shallow.max_scenario_length == medium.max_scenario_length == deep.max_scenario_length
    assert len(shallow.suite.scenarios) == len(medium.suite.scenarios) == len(deep.suite.scenarios)


def test_compute_paired_detection_changes_counts() -> None:
    rows_by_depth = {
        "shallow": [
            type("Row", (), {"case_id": "a", "fault_detected": True})(),
            type("Row", (), {"case_id": "b", "fault_detected": False})(),
            type("Row", (), {"case_id": "c", "fault_detected": True})(),
            type("Row", (), {"case_id": "d", "fault_detected": False})(),
        ],
        "medium": [
            type("Row", (), {"case_id": "a", "fault_detected": True})(),
            type("Row", (), {"case_id": "b", "fault_detected": True})(),
            type("Row", (), {"case_id": "c", "fault_detected": False})(),
            type("Row", (), {"case_id": "d", "fault_detected": False})(),
        ],
        "deep": [
            type("Row", (), {"case_id": "a", "fault_detected": True})(),
            type("Row", (), {"case_id": "b", "fault_detected": True})(),
            type("Row", (), {"case_id": "c", "fault_detected": True})(),
            type("Row", (), {"case_id": "d", "fault_detected": False})(),
        ],
    }
    paired = compute_paired_detection_changes(rows_by_depth)  # type: ignore[arg-type]
    medium = next(row for row in paired if row["comparison_depth"] == "medium")
    deep = next(row for row in paired if row["comparison_depth"] == "deep")

    assert medium["both_detected"] == 1
    assert medium["shallow_only_detected"] == 1
    assert medium["higher_only_detected"] == 1
    assert medium["neither_detected"] == 1
    assert medium["detection_gains"] == 1
    assert medium["detection_losses"] == 1

    assert deep["both_detected"] == 2
    assert deep["shallow_only_detected"] == 0
    assert deep["higher_only_detected"] == 1
    assert deep["neither_detected"] == 1
    assert deep["detection_gains"] == 1
    assert deep["detection_losses"] == 0


def test_run_oracle_depth_ablation_v2_exports_schema(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    paper_dir = tmp_path / "paper"
    result = run_oracle_depth_ablation(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        write_cohort=False,
        scenario_policy="depth-forced",
        paper_export_dir=paper_dir,
    )

    assert result.depth_summary_path.is_file()
    assert result.per_case_path.is_file()
    assert result.paired_detection_path is not None and result.paired_detection_path.is_file()
    assert result.coverage_by_depth_path is not None and result.coverage_by_depth_path.is_file()
    assert result.manifest_path is not None and result.manifest_path.is_file()
    assert (result.tables_dir / "table_depth_forced_summary.tex").is_file()
    assert (paper_dir / "tables" / "table_depth_forced_summary.tex").is_file()

    per_case = list(csv.DictReader(result.per_case_path.open(encoding="utf-8")))
    assert list(per_case[0].keys()) == list(V2_PER_CASE_COLUMNS)

    paired = list(csv.DictReader(result.paired_detection_path.open(encoding="utf-8")))
    assert list(paired[0].keys()) == list(PAIRED_DETECTION_COLUMNS)
    assert len(paired) == 2

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["experiment"] == V2_EXPERIMENT
    assert manifest["scenario_policy"] == "depth-forced"


def test_score_case_at_depth_shortest_path_columns_unchanged() -> None:
    result = score_case_at_depth(FIXTURE_CASE, "medium", scenario_policy="shortest-path")
    payload = result.to_dict()
    assert "scenario_policy" not in payload
    assert payload["max_scenario_steps"] >= 0


def test_run_oracle_depth_ablation_v2_cli(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "out"
    result = runner.invoke(
        app,
        [
            "run-oracle-depth-ablation",
            str(FIXTURE_DATASET),
            "--out",
            str(out),
            "--cohort-file",
            str(cohort_path),
            "--no-write-cohort",
            "--scenario-policy",
            "depth-forced",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "paired_detection_changes.csv").is_file()
    assert (out / "coverage_by_depth.csv").is_file()
