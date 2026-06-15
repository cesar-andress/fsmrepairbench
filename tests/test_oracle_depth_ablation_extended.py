"""Tests for extended C3 oracle depth ablation."""

from __future__ import annotations

import csv
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.oracle_depth_ablation_extended import (
    EXTENDED_PER_CASE_COLUMNS,
    compute_extended_paired_detection_changes,
    run_oracle_depth_ablation_extended,
    score_extended_case_at_depth,
)
from fsmrepairbench.oracle_generator import EXTENDED_ABLATION_DEPTHS, generate_oracle_suite
from fsmrepairbench.validators import load_fsm_json

runner = CliRunner()
FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"
FIXTURE_CASE = FIXTURE_DATASET / "cases" / "case_000002"


def test_extended_depth_forced_presets_monotonically_lengthen() -> None:
    fsm = load_fsm_json(FIXTURE_CASE / "reference_fsm.json")
    lengths = [
        generate_oracle_suite(fsm, depth=depth, policy="depth-forced").mean_scenario_length
        for depth in EXTENDED_ABLATION_DEPTHS
    ]
    for left, right in zip(lengths, lengths[1:], strict=False):
        assert right >= left - 1e-9
    assert lengths[-1] > lengths[0]


def test_score_extended_case_includes_repair_fields() -> None:
    result = score_extended_case_at_depth(FIXTURE_CASE, "medium", scenario_policy="depth-forced")
    payload = result.to_dict()
    assert payload["fault_detected"] in {True, False}
    assert "complete_repair" in payload
    assert "effective_repair" in payload
    assert "repair_delta_bpr" in payload
    assert payload["mean_scenario_length"] > 0


def test_compute_extended_paired_detection_changes_all_depths() -> None:
    rows_by_depth = {
        depth: [
            type("Row", (), {"case_id": "a", "fault_detected": True})(),
            type("Row", (), {"case_id": "b", "fault_detected": False})(),
        ]
        for depth in EXTENDED_ABLATION_DEPTHS
    }
    paired = compute_extended_paired_detection_changes(
        rows_by_depth,  # type: ignore[arg-type]
        depths=EXTENDED_ABLATION_DEPTHS,
    )
    assert len(paired) == len(EXTENDED_ABLATION_DEPTHS) - 1


def test_run_extended_ablation_on_fixture_dataset(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort.txt"
    cohort.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "extended"
    result = run_oracle_depth_ablation_extended(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort,
        write_cohort=False,
        depths=("shallow", "medium"),
    )
    assert result.per_case_path.is_file()
    with result.per_case_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(EXTENDED_PER_CASE_COLUMNS)
        assert sum(1 for _ in reader) == 2


def test_cli_run_oracle_depth_ablation_extended(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort.txt"
    cohort.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "extended"
    result = runner.invoke(
        app,
        [
            "run-oracle-depth-ablation-extended",
            str(FIXTURE_DATASET),
            "--out",
            str(out),
            "--cohort-file",
            str(cohort),
            "--no-write-cohort",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "depth_summary.csv").is_file()
    assert (out / "tables" / "table_extended_depth_summary.tex").is_file()
