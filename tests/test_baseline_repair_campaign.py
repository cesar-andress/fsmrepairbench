"""Tests for C1 baseline repair campaign exports and multi-seed analysis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.baseline_repair_campaign import (
    bootstrap_ci,
    compute_multi_seed_statistics,
    export_c1_multi_seed_analysis,
    finalize_c1_manifest,
    parse_seeds,
    run_random_baseline_for_seed,
    summarize_random_rows,
)
from fsmrepairbench.cli import app
from fsmrepairbench.tool_runner import ToolRunSummaryRow
from tests.helpers import setup_cases_root

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools" / "baselines_c1"
runner = CliRunner()


def _cohort_file(dataset_dir: Path, case_ids: list[str]) -> Path:
    path = dataset_dir / "analysis_cohort_1k.txt"
    path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    return path


def test_parse_seeds_accepts_count_and_csv() -> None:
    assert parse_seeds("5") == (0, 1, 2, 3, 4)
    assert parse_seeds("1,3,5") == (1, 3, 5)
    assert len(parse_seeds(None)) == 10


def test_bootstrap_ci_returns_ordered_bounds() -> None:
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    low, high = bootstrap_ci(values, n_resamples=2000, rng=__import__("random").Random(0))
    assert low <= high
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_compute_multi_seed_statistics_includes_ci_fields() -> None:
    per_seed = [
        {"complete_repair_rate": 0.5, "effective_repair_rate": 0.6, "mean_delta_bpr": 0.01},
        {"complete_repair_rate": 0.55, "effective_repair_rate": 0.62, "mean_delta_bpr": 0.02},
        {"complete_repair_rate": 0.48, "effective_repair_rate": 0.58, "mean_delta_bpr": 0.015},
    ]
    stats = compute_multi_seed_statistics(per_seed, bootstrap_resamples=500, bootstrap_seed=1)
    for metric in ("complete_repair_rate", "effective_repair_rate", "mean_delta_bpr"):
        assert "mean" in stats[metric]
        assert "std_dev" in stats[metric]
        assert "min" in stats[metric]
        assert "max" in stats[metric]
        assert stats[metric]["ci95_low"] <= stats[metric]["ci95_high"]


def test_summarize_random_rows_from_tool_summary() -> None:
    rows = [
        ToolRunSummaryRow(
            case_id="case_000001",
            tool_id="baseline_random",
            tool_type="baseline",
            model="baseline_random",
            mutation_operator="missing_transition",
            status="completed",
            failure_class="complete_repair",
            initial_bpr=0.5,
            final_bpr=1.0,
            delta_bpr=0.5,
            complete_repair=True,
            effective_repair=True,
            regression=False,
            patch_parse_failures=0,
            patch_validation_failures=0,
            patch_application_failures=0,
            iterations_completed=1,
            runtime_seconds=0.1,
        ),
        ToolRunSummaryRow(
            case_id="case_000002",
            tool_id="baseline_random",
            tool_type="baseline",
            model="baseline_random",
            mutation_operator="wrong_target",
            status="completed",
            failure_class="no_improvement",
            initial_bpr=0.8,
            final_bpr=0.8,
            delta_bpr=0.0,
            complete_repair=False,
            effective_repair=False,
            regression=False,
            patch_parse_failures=0,
            patch_validation_failures=0,
            patch_application_failures=0,
            iterations_completed=1,
            runtime_seconds=0.1,
        ),
    ]
    summary = summarize_random_rows(rows)
    assert summary["cases"] == 2
    assert summary["complete_repair_rate"] == 0.5
    assert summary["mean_delta_bpr"] == 0.25


def test_run_random_baseline_for_seed_respects_seed(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001", "case_000002"])

    rows_seed_0 = run_random_baseline_for_seed(
        dataset_dir,
        TOOLS_DIR,
        {"case_000001", "case_000002"},
        seed=0,
        workers=1,
    )
    rows_seed_1 = run_random_baseline_for_seed(
        dataset_dir,
        TOOLS_DIR,
        {"case_000001", "case_000002"},
        seed=1,
        workers=1,
    )
    assert len(rows_seed_0) == 2
    assert len(rows_seed_1) == 2
    assert rows_seed_0[0].delta_bpr != rows_seed_1[0].delta_bpr or rows_seed_0[
        1
    ].delta_bpr != rows_seed_1[1].delta_bpr


def test_export_c1_multi_seed_analysis_writes_manifest(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    out_dir = tmp_path / "baseline_repair_C1"

    result = export_c1_multi_seed_analysis(
        dataset_dir,
        cohort,
        TOOLS_DIR,
        out_dir,
        seeds=(0, 1, 2),
        workers=1,
        write_per_seed_runs=True,
    )

    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["release_label"] == "C1-baseline-repair"
    assert manifest["cohort_path"] == str(cohort)
    assert "cohort_sha256" in manifest
    assert manifest["case_count"] == 2
    assert manifest["workers"] == 1
    assert manifest["random_baseline_seeds"] == [0, 1, 2]
    assert "generated_at_utc" in manifest
    assert "output_files" in manifest
    assert (out_dir / "random_multi_seed_summary.csv").is_file()
    assert (out_dir / "random_multi_seed_aggregate.json").is_file()
    assert (out_dir / "tables" / "table_random_multi_seed_aggregate.tex").is_file()


def test_finalize_c1_manifest_lists_generated_files(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001"])
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    (out_dir / "leaderboard.csv").write_text("tool\n", encoding="utf-8")

    path = finalize_c1_manifest(
        dataset_dir=dataset_dir,
        cohort_path=cohort,
        tools_dir=TOOLS_DIR,
        out_dir=out_dir,
        workers=2,
        case_count=1,
        random_seeds=(0, 1),
        raw_runs_dir=tmp_path / "raw",
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))
    assert "leaderboard.csv" in manifest["output_files"]
    assert "manifest.json" in manifest["output_files"]


def test_cli_export_c1_baseline_repair(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    out_dir = tmp_path / "export"

    result = runner.invoke(
        app,
        [
            "export-c1-baseline-repair",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--seeds",
            "2",
            "--workers",
            "1",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out_dir / "manifest.json").is_file()


def test_baseline_random_seed_from_environment(tmp_path: Path) -> None:
    from fsmrepairbench.tool_runner import (
        ToolConfig,
        _baseline_seed,
        _run_baseline_tool,
        build_tool_tasks,
    )
    from fsmrepairbench.experiments import discover_experiment_cases

    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    tool = ToolConfig(
        tool_id="baseline_random",
        tool_type="baseline",
        command="random",
        environment={"baseline_seed": "42"},
    )
    assert _baseline_seed(tool) == 42

    cases = discover_experiment_cases(dataset_dir / "cases")
    task = build_tool_tasks(cases[:1], [tool])[0]
    repair = _run_baseline_tool(task)
    assert repair.details["baseline_seed"] == 42
