"""Tests for integrated RQ4 FO/HO random-secondary exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fsmrepairbench.coupling_random_secondary import (
    PER_SEED_SUMMARY_COLUMNS,
    RANDOM_SECONDARY_METRICS,
    compute_random_secondary_statistics,
    flatten_random_secondary_summary,
)
from fsmrepairbench.coupling_rq4_integrated_exports import (
    build_fo_ho_comparison_rows,
    build_fo_ho_deterministic_rows,
    build_fo_ho_random_secondary_rows,
    integrate_random_secondary_exports,
)


def _minimal_per_seed(seed: int) -> dict[str, float | int]:
    row: dict[str, float | int] = {metric: 0.0 for metric in RANDOM_SECONDARY_METRICS}
    row.update(
        {
            "secondary_random_seed": seed,
            "higher_order_detection_rate": 0.996,
            "coupling_effect_estimate": 1.0,
            "detection_rate_order_1": 0.472,
            "detection_rate_order_2": 0.992 + 0.001 * seed,
            "detection_rate_order_3": 1.0,
            "complete_repair_rate_order_1_detectable": 0.8 + 0.01 * seed,
            "complete_repair_rate_order_2_detectable": 0.7 + 0.01 * seed,
            "complete_repair_rate_order_3_detectable": 0.6 + 0.01 * seed,
            "effective_repair_rate_order_1_detectable": 0.75 + 0.01 * seed,
            "effective_repair_rate_order_2_detectable": 0.65 + 0.01 * seed,
            "effective_repair_rate_order_3_detectable": 0.55 + 0.01 * seed,
            "mean_bpr_delta_order_1_detectable": 0.05 + 0.01 * seed,
            "mean_bpr_delta_order_2_detectable": 0.25 + 0.01 * seed,
            "mean_bpr_delta_order_3_detectable": 0.35 + 0.01 * seed,
        }
    )
    return row


def _synthetic_flat_summary() -> dict[str, float | int]:
    per_seed = [_minimal_per_seed(0), _minimal_per_seed(1)]
    aggregate = compute_random_secondary_statistics(per_seed, bootstrap_resamples=200, bootstrap_seed=1)
    return flatten_random_secondary_summary(aggregate, seed_count=2)


def test_build_fo_ho_random_secondary_rows_includes_fo_and_ho() -> None:
    flat = _synthetic_flat_summary()
    rows = build_fo_ho_random_secondary_rows(flat, seed_count=2)
    classes = {(row["mutant_class"], row["mutation_order"]) for row in rows}
    assert ("FO", 1) in classes
    assert ("HO", 2) in classes
    assert ("HO", 3) in classes


def test_build_fo_ho_deterministic_rows_reads_summary_metrics_with_ci(tmp_path: Path) -> None:
    deterministic = tmp_path / "deterministic"
    deterministic.mkdir()
    (deterministic / "summary_metrics_with_ci.csv").write_text(
        "mutation_order,partition,metric,n_cases,value_mean,value_ci95_low,value_ci95_high,value_n_cases\n"
        "order_1,cohort_wide,detection_rate,250,47.2,41.2,53.6,250\n"
        "order_1,detectable_only,complete_repair_rate,118,77.1186,69.4915,84.7458,118\n"
        "order_2,cohort_wide,mean_bpr_delta,250,0.267039,0.220809,0.315454,250\n"
        "order_3,detectable_only,effective_repair_rate,250,98.0,96.0,99.6,250\n",
        encoding="utf-8",
    )
    rows = build_fo_ho_deterministic_rows(deterministic)
    assert rows
    fo_detection = next(
        row
        for row in rows
        if row["mutant_class"] == "FO"
        and row["metric"] == "detection_rate"
        and row["policy"] == "deterministic"
    )
    assert float(fo_detection["point_estimate"]) == 0.472
    fo_complete = next(
        row
        for row in rows
        if row["mutant_class"] == "FO"
        and row["metric"] == "complete_repair_rate"
        and row["partition"] == "detectable_only"
    )
    assert float(fo_complete["point_estimate"]) == pytest.approx(0.771186, rel=1e-4)


def test_build_fo_ho_comparison_rows_reads_summary_metrics_with_ci(tmp_path: Path) -> None:
    deterministic = tmp_path / "deterministic"
    deterministic.mkdir()
    (deterministic / "summary_metrics_with_ci.csv").write_text(
        "mutation_order,partition,metric,n_cases,value_mean,value_ci95_low,value_ci95_high,value_n_cases\n"
        "order_1,cohort_wide,detection_rate,250,47.2,41.2,53.6,250\n"
        "order_2,cohort_wide,detection_rate,250,99.2,98.0,100.0,250\n"
        "order_2,detectable_only,complete_repair_rate,248,59.6774,53.629,65.7258,248\n",
        encoding="utf-8",
    )
    flat = _synthetic_flat_summary()
    rows = build_fo_ho_comparison_rows(deterministic, flat)
    assert rows
    fo_detection = next(
        row for row in rows if row["mutant_class"] == "FO" and row["metric"] == "detection_rate"
    )
    assert float(fo_detection["deterministic_value"]) == 0.472


def test_integrate_random_secondary_exports_writes_notes_and_csvs(tmp_path: Path) -> None:
    deterministic = tmp_path / "deterministic"
    random_dir = tmp_path / "random"
    paper = tmp_path / "paper"
    deterministic.mkdir()
    random_dir.mkdir()

    (deterministic / "summary.csv").write_text(
        "metric,value\nfirst_order_detection_rate,0.472\nhigher_order_detection_rate,0.996\n"
        "coupling_effect_estimate,1.0\n",
        encoding="utf-8",
    )
    (deterministic / "coupling_metrics.csv").write_text(
        "metric,mutation_order,primary_operator,value\n"
        "detection_rate,1,,0.472\n"
        "detection_rate,2,,0.992\n"
        "detection_rate,3,,1.0\n",
        encoding="utf-8",
    )
    (deterministic / "summary_metrics_with_ci.csv").write_text(
        "mutation_order,partition,metric,n_cases,value_mean,value_ci95_low,value_ci95_high,value_n_cases\n"
        "order_1,cohort_wide,detection_rate,250,47.2,41.2,53.6,250\n"
        "order_2,cohort_wide,detection_rate,250,99.2,98.0,100.0,250\n"
        "order_3,cohort_wide,detection_rate,250,100.0,100.0,100.0,250\n"
        "order_2,detectable_only,complete_repair_rate,248,59.6774,53.629,65.7258,248\n",
        encoding="utf-8",
    )

    flat = _synthetic_flat_summary()
    per_seed = [_minimal_per_seed(0), _minimal_per_seed(1)]
    (random_dir / "random_secondary_summary.json").write_text(
        json.dumps({"summary": flat, "per_seed": per_seed}),
        encoding="utf-8",
    )
    with (random_dir / "per_seed_summary.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PER_SEED_SUMMARY_COLUMNS))
        writer.writeheader()
        for row in per_seed:
            writer.writerow({key: row.get(key, 0) for key in PER_SEED_SUMMARY_COLUMNS})

    result = integrate_random_secondary_exports(
        deterministic_dir=deterministic,
        random_secondary_dir=random_dir,
        paper_rq4_dir=paper,
    )
    assert result["fo_ho_metrics_csv"].is_file()
    assert result["fo_ho_comparison_csv"].is_file()
    comparison_rows = list(csv.DictReader(result["fo_ho_comparison_csv"].open(encoding="utf-8")))
    assert comparison_rows
    assert result["deterministic_chaining_notes"].is_file()
    assert (paper / "random_secondary" / "random_secondary_summary.json").is_file()
