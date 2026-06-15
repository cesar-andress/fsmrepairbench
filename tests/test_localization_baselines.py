"""Tests for RQ3 localization baselines."""

from __future__ import annotations

import csv
from pathlib import Path

from fsmrepairbench.localization_baselines import (
    BASELINE_METHODS,
    localize_case_baseline,
    run_localization_baseline_comparison,
    write_baseline_comparison_csv,
)
from fsmrepairbench.localization_campaign import localize_case_transitions
from fsmrepairbench.localization_localizability_audit import (
    audit_case_localizability,
    run_localization_localizability_audit,
)

FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_localize_case_baseline_spectral_matches_campaign() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    campaign = localize_case_transitions(case_dir, method="ochiai")
    baseline = localize_case_baseline(case_dir, method="ochiai")
    assert baseline.localized == campaign.localized
    assert baseline.rank_of_target == campaign.rank_of_target
    assert baseline.top5_hit == campaign.top5_hit


def test_localize_case_baseline_random_and_structural_diff_rank_all_transitions() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    random_result = localize_case_baseline(case_dir, method="random")
    structural_result = localize_case_baseline(case_dir, method="structural_diff")
    assert random_result.localized
    assert structural_result.localized
    assert random_result.transition_count > 0
    assert structural_result.transition_count == random_result.transition_count


def test_run_localization_baseline_comparison_on_fixture(tmp_path: Path) -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    case = localize_case_transitions(case_dir)
    audit_row = audit_case_localizability(case_dir, case)
    assert audit_row.ground_truth_localizable

    out = tmp_path / "results"
    out.mkdir()
    per_case_path = out / "per_case_results.csv"
    with per_case_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(case.to_dict().keys()))
        writer.writeheader()
        writer.writerow(case.to_dict())

    result = run_localization_localizability_audit(
        FIXTURE_DATASET,
        output_dir=out,
        per_case_path=per_case_path,
    )
    assert result.baseline_comparison_csv_path is not None
    assert result.baseline_comparison_csv_path.is_file()
    assert (out / "tables" / "table_localization_baselines_localizable.tex").is_file()
    assert (out / "tables" / "table_not_ranked_by_operator.tex").is_file()

    baseline_rows = list(
        csv.DictReader(result.baseline_comparison_csv_path.open(encoding="utf-8"))
    )
    assert {row["method"] for row in baseline_rows} == set(BASELINE_METHODS)


def test_run_localization_baseline_comparison_direct() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    case = localize_case_transitions(case_dir)
    results = run_localization_baseline_comparison(
        FIXTURE_DATASET,
        localizable_case_rows=[case],
    )
    assert len(results) == len(BASELINE_METHODS)
    assert all(int(result.metrics["localized_cases"]) == 1 for result in results)
