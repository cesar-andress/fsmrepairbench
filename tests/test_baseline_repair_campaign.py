"""Tests for C1 baseline repair campaign exports and multi-seed analysis."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.baseline_repair_campaign import (
    BOOTSTRAP_SEED,
    C1_MANIFEST_REQUIRED_FIELDS,
    CAMPAIGN_LABEL,
    RELEASE_LABEL,
    ZENODO_DOI,
    bootstrap_ci,
    build_c1_manifest,
    compute_multi_seed_statistics,
    export_c1_multi_seed_analysis,
    flatten_multi_seed_statistics,
    multiseed_summary_column_names,
    parse_random_seeds,
    parse_seeds,
    publish_c1_manifests,
    run_multi_seed_random_analysis,
    summarize_random_rows,
    write_random_multiseed_exports,
)
from fsmrepairbench.cli import app
from fsmrepairbench.freeze import sha256_file
from fsmrepairbench.tool_runner import ToolRunSummaryRow
from tests.helpers import setup_cases_root

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools" / "baselines_c1"
runner = CliRunner()


def _cohort_file(dataset_dir: Path, case_ids: list[str]) -> Path:
    path = dataset_dir / "analysis_cohort_1k.txt"
    path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    return path


def test_parse_random_seeds_accepts_count_and_csv() -> None:
    assert parse_random_seeds("5") == (0, 1, 2, 3, 4)
    assert parse_random_seeds("1,3,5") == (1, 3, 5)
    assert parse_random_seeds(None) == tuple(range(10))
    assert parse_random_seeds("0,1,2,3,4,5,6,7,8,9") == tuple(range(10))


def test_parse_seeds_alias_matches_parse_random_seeds() -> None:
    assert parse_seeds("3") == parse_random_seeds("3")
    assert parse_seeds("2,4") == parse_random_seeds("2,4")


def test_bootstrap_ci_returns_ordered_bounds() -> None:
    values = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
    low, high = bootstrap_ci(values, n_resamples=2000, rng=__import__("random").Random(0))
    assert low <= high
    assert 0.0 <= low <= 1.0
    assert 0.0 <= high <= 1.0


def test_bootstrap_ci_is_deterministic_with_bootstrap_seed() -> None:
    values = [0.45, 0.50, 0.55, 0.48, 0.52, 0.49, 0.51, 0.47, 0.53, 0.46]
    rng_a = __import__("random").Random(BOOTSTRAP_SEED)
    rng_b = __import__("random").Random(BOOTSTRAP_SEED)
    ci_a = bootstrap_ci(values, n_resamples=5000, rng=rng_a)
    ci_b = bootstrap_ci(values, n_resamples=5000, rng=rng_b)
    assert ci_a == ci_b


def test_compute_multi_seed_statistics_includes_ci_fields() -> None:
    per_seed = [
        {
            "complete_repair_rate": 0.5,
            "effective_repair_rate": 0.6,
            "mean_delta_bpr": 0.01,
            "regression_rate": 0.02,
        },
        {
            "complete_repair_rate": 0.55,
            "effective_repair_rate": 0.62,
            "mean_delta_bpr": 0.02,
            "regression_rate": 0.03,
        },
        {
            "complete_repair_rate": 0.48,
            "effective_repair_rate": 0.58,
            "mean_delta_bpr": 0.015,
            "regression_rate": 0.01,
        },
    ]
    stats = compute_multi_seed_statistics(per_seed, bootstrap_resamples=500, bootstrap_seed=1)
    for metric in (
        "complete_repair_rate",
        "effective_repair_rate",
        "mean_delta_bpr",
        "regression_rate",
    ):
        assert stats[metric]["ci95_low"] <= stats[metric]["ci95_high"]
        assert "std" in stats[metric]


def test_multiseed_summary_columns_match_flattened_export() -> None:
    aggregate = compute_multi_seed_statistics(
        [
            {
                "complete_repair_rate": 0.5,
                "effective_repair_rate": 0.01,
                "mean_delta_bpr": -0.02,
                "regression_rate": 0.03,
            },
            {
                "complete_repair_rate": 0.52,
                "effective_repair_rate": 0.02,
                "mean_delta_bpr": -0.01,
                "regression_rate": 0.04,
            },
        ],
        bootstrap_resamples=200,
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    flat = flatten_multi_seed_statistics(aggregate, seed_count=2)
    assert tuple(flat.keys()) == multiseed_summary_column_names()
    assert flat["seed_count"] == 2
    assert flat["complete_repair_rate_mean"] == aggregate["complete_repair_rate"]["mean"]
    assert flat["regression_rate_ci95_low"] == aggregate["regression_rate"]["ci95_low"]


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


def test_build_c1_manifest_required_fields(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    manifest = build_c1_manifest(
        dataset_path=dataset_dir,
        cohort_file=cohort,
        tools_dir=TOOLS_DIR,
        workers=4,
        number_of_cases=2,
        output_files=["leaderboard.csv", "per_case_results.csv", "manifest.json"],
        repo_root=REPO_ROOT,
    )
    for field in C1_MANIFEST_REQUIRED_FIELDS:
        assert field in manifest, field
    assert manifest["release_label"] == RELEASE_LABEL
    assert manifest["campaign_label"] == CAMPAIGN_LABEL
    assert manifest["zenodo_doi"] == ZENODO_DOI
    assert manifest["number_of_cases"] == 2
    assert manifest["cohort_sha256"] == sha256_file(cohort)
    assert "leaderboard.csv" in manifest["output_files"]
    assert "per_case_results.csv" in manifest["output_files"]
    assert len(manifest["regeneration_commands"]) >= 2


def test_publish_c1_manifests_writes_raw_and_paper_manifests(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    raw_dir = tmp_path / "raw_runs"
    raw_dir.mkdir()
    (raw_dir / "summary.csv").write_text("case_id\n", encoding="utf-8")
    (raw_dir / "leaderboard.csv").write_text("tool\n", encoding="utf-8")
    paper_dir = tmp_path / "paper_export"
    paper_dir.mkdir()
    (paper_dir / "leaderboard.csv").write_text("tool\n", encoding="utf-8")
    (paper_dir / "per_case_results.csv").write_text("case_id\n", encoding="utf-8")

    result = publish_c1_manifests(
        dataset_dir=dataset_dir,
        cohort_file=cohort,
        tools_dir=TOOLS_DIR,
        raw_runs_dir=raw_dir,
        paper_export_dir=paper_dir,
        workers=4,
        repo_root=REPO_ROOT,
    )

    assert result.raw_manifest_path.is_file()
    assert result.paper_manifest_path.is_file()
    raw_manifest = json.loads(result.raw_manifest_path.read_text(encoding="utf-8"))
    paper_manifest = json.loads(result.paper_manifest_path.read_text(encoding="utf-8"))
    for field in C1_MANIFEST_REQUIRED_FIELDS:
        assert field in raw_manifest
        assert field in paper_manifest
    assert raw_manifest["cohort_sha256"] == sha256_file(cohort)
    assert paper_manifest["cohort_sha256"] == raw_manifest["cohort_sha256"]
    assert "leaderboard.csv" in paper_manifest["output_files"]
    assert "per_case_results.csv" in paper_manifest["output_files"]


def test_write_random_multiseed_exports_writes_required_files(tmp_path: Path) -> None:
    raw_dir = tmp_path / "raw"
    paper_dir = tmp_path / "paper"
    per_seed = [
        {
            "seed": 0,
            "cases": 2,
            "complete_repair_rate": 0.5,
            "effective_repair_rate": 0.01,
            "mean_delta_bpr": -0.02,
            "regression_rate": 0.03,
        },
        {
            "seed": 1,
            "cases": 2,
            "complete_repair_rate": 0.52,
            "effective_repair_rate": 0.02,
            "mean_delta_bpr": -0.01,
            "regression_rate": 0.04,
        },
    ]
    aggregate = compute_multi_seed_statistics(per_seed, bootstrap_resamples=200, bootstrap_seed=BOOTSTRAP_SEED)
    result = write_random_multiseed_exports(
        raw_runs_dir=raw_dir,
        paper_export_dir=paper_dir,
        per_seed=per_seed,
        aggregate=aggregate,
        seeds=(0, 1),
    )
    assert result.summary_csv_path.is_file()
    assert result.summary_json_path.is_file()
    assert result.per_seed_csv_path.is_file()
    assert result.tex_table_path.is_file()
    assert result.report_path.is_file()
    payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert payload["bootstrap"]["seed"] == BOOTSTRAP_SEED
    assert payload["bootstrap"]["method"] == "percentile"


def test_export_c1_multi_seed_analysis_writes_manifest(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    raw_dir = tmp_path / "raw_runs"
    raw_dir.mkdir()
    out_dir = tmp_path / "baseline_repair_C1"
    out_dir.mkdir()
    (out_dir / "leaderboard.csv").write_text("tool\n", encoding="utf-8")
    (out_dir / "per_case_results.csv").write_text("case_id\n", encoding="utf-8")

    result = export_c1_multi_seed_analysis(
        dataset_dir,
        cohort,
        TOOLS_DIR,
        out_dir,
        seeds=(0, 1, 2),
        workers=1,
        write_per_seed_runs=False,
        raw_runs_dir=raw_dir,
    )

    assert (raw_dir / "manifest.json").is_file()
    assert (out_dir / "manifest.json").is_file()
    assert result.summary_csv_path.is_file()
    assert result.tex_table_path.is_file()
    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["campaign_label"] == CAMPAIGN_LABEL
    assert manifest["number_of_cases"] == 2


def test_multiseed_analysis_is_reproducible_across_runs(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort = _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    case_ids = {"case_000001", "case_000002"}
    seeds = (0, 1, 2)

    per_seed_a, aggregate_a = run_multi_seed_random_analysis(
        dataset_dir,
        TOOLS_DIR,
        case_ids,
        seeds,
        workers=1,
    )
    per_seed_b, aggregate_b = run_multi_seed_random_analysis(
        dataset_dir,
        TOOLS_DIR,
        case_ids,
        seeds,
        workers=1,
    )

    assert per_seed_a == per_seed_b
    assert aggregate_a == aggregate_b


def test_cli_write_c1_manifest(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    (raw_dir / "summary.csv").write_text("x\n", encoding="utf-8")
    paper_dir = tmp_path / "paper"
    paper_dir.mkdir()
    (paper_dir / "leaderboard.csv").write_text("x\n", encoding="utf-8")
    (paper_dir / "per_case_results.csv").write_text("x\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "write-c1-manifest",
            "--dataset",
            str(dataset_dir),
            "--raw-runs-dir",
            str(raw_dir),
            "--paper-export-dir",
            str(paper_dir),
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (raw_dir / "manifest.json").is_file()
    assert (paper_dir / "manifest.json").is_file()


def test_cli_export_c1_baseline_repair(tmp_path: Path) -> None:
    dataset_dir = tmp_path / "dataset"
    setup_cases_root(dataset_dir)
    cohort_path = _cohort_file(dataset_dir, ["case_000001", "case_000002"])
    out_dir = tmp_path / "export"

    run_result = runner.invoke(
        app,
        [
            "run-tools",
            str(dataset_dir),
            str(TOOLS_DIR),
            "--out",
            str(out_dir),
            "--cohort-file",
            str(cohort_path),
            "--workers",
            "1",
            "--quiet",
        ],
    )
    assert run_result.exit_code == 0, run_result.stdout

    result = runner.invoke(
        app,
        [
            "export-c1-baseline-repair",
            str(dataset_dir),
            "--out",
            str(out_dir),
            "--cohort-file",
            str(cohort_path),
            "--random-seeds",
            "2",
            "--workers",
            "1",
            "--no-per-seed-runs",
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out_dir / "manifest.json").is_file()
    assert (out_dir / "random_multiseed_summary.csv").is_file()
    assert (out_dir / "tables" / "table_random_multiseed.tex").is_file()
    assert (out_dir / "tables" / "table_baseline_leaderboard.tex").is_file()
    assert (out_dir / "figures" / "repair_success_histogram.png").is_file()
