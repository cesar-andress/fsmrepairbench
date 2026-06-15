"""Tests for consolidated paper bootstrap confidence interval exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from fsmrepairbench.paper_confidence_intervals import (
    collect_paper_confidence_intervals,
    export_paper_confidence_intervals,
    load_progress_cases,
)
from fsmrepairbench.statistics import (
    BOOTSTRAP_SEED,
    CONFIDENCE_INTERVAL_CSV_COLUMNS,
    bootstrap_mean_ci,
    filter_paper_main_ci_rows,
    render_paper_main_ci_tex,
)


def _write_progress_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "reference_bpr",
                "faulty_bpr",
                "bpr_delta",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_c1_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "tool_id",
                "complete_repair",
                "effective_repair",
                "delta_bpr",
                "oracle_detected",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_minimal_campaign_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fixture_paths(tmp_path: Path):
    from fsmrepairbench.paper_confidence_intervals import PaperConfidenceIntervalPaths

    dataset_dir = tmp_path / "data/fsmrepairbench_1k"
    dataset_dir.mkdir(parents=True, exist_ok=True)
    cohort_file = dataset_dir / "analysis_cohort_1k.txt"
    cohort_file.write_text("case_a\ncase_b\n", encoding="utf-8")

    progress_csv = dataset_dir / "progress.csv"
    _write_progress_csv(
        progress_csv,
        [
            {
                "case_id": "case_a",
                "reference_bpr": "1.0",
                "faulty_bpr": "0.9",
                "bpr_delta": "0.1",
                "status": "completed",
            },
            {
                "case_id": "case_b",
                "reference_bpr": "1.0",
                "faulty_bpr": "1.0",
                "bpr_delta": "0.0",
                "status": "completed",
            },
        ],
    )

    c1_csv = tmp_path / "results/baseline_repair_C1/per_case_results.csv"
    _write_c1_csv(
        c1_csv,
        [
            {
                "case_id": "case_a",
                "tool_id": "baseline_missing_transition",
                "complete_repair": "True",
                "effective_repair": "True",
                "delta_bpr": "0.1",
                "oracle_detected": "True",
            },
            {
                "case_id": "case_a",
                "tool_id": "baseline_wrong_target",
                "complete_repair": "False",
                "effective_repair": "False",
                "delta_bpr": "0.0",
                "oracle_detected": "True",
            },
            {
                "case_id": "case_a",
                "tool_id": "baseline_random",
                "complete_repair": "False",
                "effective_repair": "False",
                "delta_bpr": "0.0",
                "oracle_detected": "True",
            },
        ],
    )

    rq3_csv = tmp_path / "results/rq3_localization_1k/per_case_results.csv"
    _write_minimal_campaign_csv(
        rq3_csv,
        [
            "case_id",
            "localized",
            "top1_hit",
            "top3_hit",
            "top5_hit",
            "reciprocal_rank",
        ],
        [
            {
                "case_id": "case_a",
                "localized": "True",
                "top1_hit": "True",
                "top3_hit": "True",
                "top5_hit": "True",
                "reciprocal_rank": "1.0",
            }
        ],
    )

    rq4_csv = tmp_path / "results/rq4_coupling_250/per_case_results.csv"
    _write_minimal_campaign_csv(
        rq4_csv,
        [
            "case_id",
            "mutation_order",
            "source_case_id",
            "fault_detected",
            "complete_repair",
            "effective_repair",
            "bpr_delta",
        ],
        [
            {
                "case_id": "case_a",
                "source_case_id": "case_a",
                "mutation_order": "1",
                "fault_detected": "True",
                "complete_repair": "True",
                "effective_repair": "True",
                "bpr_delta": "0.1",
            },
            {
                "case_id": "case_a__ho2",
                "source_case_id": "case_a",
                "mutation_order": "2",
                "fault_detected": "False",
                "complete_repair": "False",
                "effective_repair": "False",
                "bpr_delta": "0.0",
            },
        ],
    )

    c3_csv = tmp_path / "results/oracle_depth_ablation/per_case_results.csv"
    _write_minimal_campaign_csv(
        c3_csv,
        ["case_id", "oracle_depth", "fault_detected", "faulty_bpr", "bpr_delta"],
        [
            {
                "case_id": "case_a",
                "oracle_depth": "shallow",
                "fault_detected": "True",
                "faulty_bpr": "0.9",
                "bpr_delta": "0.1",
            },
            {
                "case_id": "case_a",
                "oracle_depth": "medium",
                "fault_detected": "True",
                "faulty_bpr": "0.9",
                "bpr_delta": "0.1",
            },
            {
                "case_id": "case_a",
                "oracle_depth": "deep",
                "fault_detected": "True",
                "faulty_bpr": "0.9",
                "bpr_delta": "0.1",
            },
        ],
    )

    return PaperConfidenceIntervalPaths(
        rq2_progress_csv=progress_csv,
        analysis_cohort_file=cohort_file,
        c1_per_case_csv=c1_csv,
        rq3_per_case_csv=rq3_csv,
        rq4_per_case_csv=rq4_csv,
        c3_per_case_csv=c3_csv,
    )


def test_bootstrap_mean_ci_is_deterministic_with_seed_44() -> None:
    values = [0.45, 0.50, 0.55, 0.48, 0.52, 0.49, 0.51, 0.47, 0.53, 0.46]
    row_a = bootstrap_mean_ci(values, "mean_faulty_bpr", bootstrap_seed=BOOTSTRAP_SEED)
    row_b = bootstrap_mean_ci(values, "mean_faulty_bpr", bootstrap_seed=BOOTSTRAP_SEED)
    assert row_a == row_b


def test_bootstrap_mean_ci_handles_identical_values() -> None:
    row = bootstrap_mean_ci([0.5, 0.5, 0.5, 0.5], "overall_detection_rate")
    assert row.mean == 0.5
    assert row.ci95_low == 0.5
    assert row.ci95_high == 0.5


def test_bootstrap_mean_ci_handles_empty_values() -> None:
    row = bootstrap_mean_ci([], "mean_bpr_delta")
    assert row.n_cases == 0
    assert row.mean == 0.0
    assert row.ci95_low == 0.0
    assert row.ci95_high == 0.0


def test_collect_paper_confidence_intervals_is_deterministic(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    rows_a, paired_a = collect_paper_confidence_intervals(paths=paths, repo_root=tmp_path)
    rows_b, paired_b = collect_paper_confidence_intervals(paths=paths, repo_root=tmp_path)
    assert rows_a == rows_b
    assert paired_a == paired_b
    assert any(row.metric == "overall_detection_rate" and row.group == "RQ2" for row in rows_a)
    assert any(
        row.metric == "complete_repair_rate"
        and row.partition == "detectable_only"
        and row.subgroup == "baseline_missing_transition"
        for row in rows_a
    )


def test_export_paper_confidence_intervals_schema_and_tex(tmp_path: Path) -> None:
    paths = _fixture_paths(tmp_path)
    out = tmp_path / "results/confidence_intervals"
    paper_out = tmp_path / "paper1/results/confidence_intervals"
    result = export_paper_confidence_intervals(
        out,
        paper_export_dir=paper_out,
        paths=paths,
        repo_root=tmp_path,
    )

    assert result.csv_path.is_file()
    assert result.json_path.is_file()
    assert result.paired_csv_path.is_file()
    assert result.main_tex_path.is_file()
    assert result.campaign_tex_path.is_file()
    assert result.paired_tex_path.is_file()
    assert result.paper_main_tex_path is not None
    assert result.paper_main_tex_path.is_file()
    assert result.paper_campaign_tex_path is not None
    assert result.paper_campaign_tex_path.is_file()
    assert result.paper_paired_tex_path is not None
    assert result.paper_paired_tex_path.is_file()

    with result.csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(CONFIDENCE_INTERVAL_CSV_COLUMNS)

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["seed"] == BOOTSTRAP_SEED
    assert payload["method"] == "percentile_case_resample"
    assert payload["metrics"]

    tex = result.main_tex_path.read_text(encoding="utf-8")
    assert "\\label{tab:ci-main-results}" in tex
    assert "overall\\_detection\\_rate" in tex
    assert result.campaign_tex_path.read_text(encoding="utf-8").find("\\label{tab:ci-campaign-metrics}") >= 0
    assert result.paired_tex_path.read_text(encoding="utf-8").find("\\label{tab:ci-paired-comparisons}") >= 0

    c1_ci = tmp_path / "results/baseline_repair_C1/confidence_intervals.csv"
    assert c1_ci.is_file()
    rq3_ci = tmp_path / "results/rq3_localization_1k/localization_metrics_with_ci.csv"
    assert rq3_ci.is_file()
    rq4_paired = tmp_path / "results/rq4_coupling_250/paired_confidence_intervals.csv"
    assert rq4_paired.is_file()

    main_rows = filter_paper_main_ci_rows(result.rows)
    assert render_paper_main_ci_tex(main_rows) == tex


def test_load_progress_cases_respects_cohort_filter(tmp_path: Path) -> None:
    progress = tmp_path / "progress.csv"
    _write_progress_csv(
        progress,
        [
            {
                "case_id": "case_a",
                "reference_bpr": "1.0",
                "faulty_bpr": "0.9",
                "bpr_delta": "0.1",
                "status": "completed",
            },
            {
                "case_id": "case_extra",
                "reference_bpr": "1.0",
                "faulty_bpr": "0.8",
                "bpr_delta": "0.2",
                "status": "completed",
            },
        ],
    )
    cases = load_progress_cases(progress, cohort_ids={"case_a"})
    assert len(cases) == 1
