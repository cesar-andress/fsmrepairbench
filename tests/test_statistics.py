"""Tests for bootstrap confidence interval utilities."""

from __future__ import annotations

import json
from pathlib import Path

from fsmrepairbench.statistics import (
    BOOTSTRAP_SEED,
    bootstrap_ci,
    bootstrap_mean_ci,
    bootstrap_rate_ci,
    compute_rq2_confidence_intervals,
    confidence_interval_rows_to_dicts,
    write_confidence_interval_exports,
)


class _Case:
    def __init__(self, *, bpr_delta: float, faulty_bpr: float) -> None:
        self.bpr_delta = bpr_delta
        self.faulty_bpr = faulty_bpr


def test_bootstrap_ci_is_deterministic_with_fixed_seed() -> None:
    values = [0.45, 0.50, 0.55, 0.48, 0.52, 0.49, 0.51, 0.47, 0.53, 0.46]
    rng_a = __import__("random").Random(BOOTSTRAP_SEED)
    rng_b = __import__("random").Random(BOOTSTRAP_SEED)
    assert bootstrap_ci(values, n_resamples=5000, rng=rng_a) == bootstrap_ci(
        values,
        n_resamples=5000,
        rng=rng_b,
    )


def test_bootstrap_mean_ci_handles_empty_values() -> None:
    row = bootstrap_mean_ci([], "mean_faulty_bpr")
    assert row.mean == 0.0
    assert row.ci95_low == 0.0
    assert row.ci95_high == 0.0
    assert row.n_cases == 0


def test_bootstrap_mean_ci_handles_identical_values() -> None:
    row = bootstrap_mean_ci([0.5, 0.5, 0.5, 0.5], "overall_detection_rate")
    assert row.mean == 0.5
    assert row.ci95_low == 0.5
    assert row.ci95_high == 0.5
    assert row.n_cases == 4


def test_bootstrap_rate_ci_matches_binary_mean() -> None:
    row = bootstrap_rate_ci([True, False, True, True], "overall_detection_rate", bootstrap_seed=1)
    assert row.mean == 0.75
    assert row.ci95_low <= row.mean <= row.ci95_high


def test_write_confidence_interval_exports_shape(tmp_path: Path) -> None:
    cases = [
        _Case(bpr_delta=0.1, faulty_bpr=0.9),
        _Case(bpr_delta=0.0, faulty_bpr=1.0),
        _Case(bpr_delta=0.2, faulty_bpr=0.8),
    ]
    rows = compute_rq2_confidence_intervals(cases)
    result = write_confidence_interval_exports(
        tmp_path,
        campaign="v0.2.0-analysis",
        rows=rows,
        paper_export_dir=None,
    )

    assert result.csv_path.is_file()
    assert result.json_path.is_file()
    csv_text = result.csv_path.read_text(encoding="utf-8")
    assert "metric,group,subgroup,n_cases,mean,ci95_low,ci95_high" in csv_text
    assert "overall_detection_rate" in csv_text

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert payload["seed"] == BOOTSTRAP_SEED
    assert payload["method"] == "percentile_case_resample"
    assert len(payload["metrics"]) == 3
    assert payload["metrics"][0]["metric"] == "overall_detection_rate"


def test_confidence_interval_rows_to_dicts_preserves_columns() -> None:
    rows = compute_rq2_confidence_intervals(
        [_Case(bpr_delta=0.1, faulty_bpr=0.9), _Case(bpr_delta=0.0, faulty_bpr=1.0)]
    )
    dict_rows = confidence_interval_rows_to_dicts(rows)
    assert set(dict_rows[0]) == {
        "metric",
        "group",
        "subgroup",
        "n_cases",
        "mean",
        "ci95_low",
        "ci95_high",
    }


def test_compute_rq2_confidence_intervals_returns_three_metrics() -> None:
    cases = [
        _Case(bpr_delta=0.1, faulty_bpr=0.9),
        _Case(bpr_delta=0.0, faulty_bpr=1.0),
        _Case(bpr_delta=0.2, faulty_bpr=0.8),
    ]
    rows = compute_rq2_confidence_intervals(cases)
    assert [row.metric for row in rows] == [
        "overall_detection_rate",
        "mean_faulty_bpr",
        "mean_bpr_delta",
    ]
    assert all(row.n_cases == 3 for row in rows)


def test_compute_c1_confidence_intervals_includes_detectable_only() -> None:
    from fsmrepairbench.statistics import compute_c1_confidence_intervals

    rows = [
        {
            "case_id": "case_000001",
            "tool_id": "baseline_missing_transition",
            "complete_repair": "True",
            "effective_repair": "True",
            "delta_bpr": "0.1",
        },
        {
            "case_id": "case_000002",
            "tool_id": "baseline_missing_transition",
            "complete_repair": "False",
            "effective_repair": "False",
            "delta_bpr": "0.0",
        },
    ]
    ci_rows = compute_c1_confidence_intervals(
        rows,
        detectable_case_ids={"case_000001"},
        tool_id="baseline_missing_transition",
    )
    metrics = [row.metric for row in ci_rows]
    assert "complete_repair_rate_detectable_only" in metrics
