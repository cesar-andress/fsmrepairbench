"""Tests for RQ3 spectral method comparison exports."""

from __future__ import annotations

import csv
from pathlib import Path

from fsmrepairbench.localization_baselines import BASELINE_METHODS
from fsmrepairbench.localization_campaign import localize_case_transitions
from fsmrepairbench.localization_localizability_audit import (
    audit_case_localizability,
    run_localization_localizability_audit,
)
from fsmrepairbench.localization_method_comparison import (
    SPECTRAL_METHODS,
    build_combined_baseline_comparison_rows,
)


FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_tarantula_differs_from_ochiai_on_fixture_when_applicable() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    ochiai = localize_case_transitions(case_dir, method="ochiai")
    tarantula = localize_case_transitions(case_dir, method="tarantula")
    assert ochiai.localized and tarantula.localized
    assert ochiai.transition_count == tarantula.transition_count


def test_export_localization_method_comparison_writes_operator_csv(tmp_path: Path) -> None:
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
    assert result.baseline_comparison_csv_path.is_file()
    assert (out / "localization_method_by_operator.csv").is_file()
    assert (out / "tables" / "table_localization_method_by_operator.tex").is_file()
    assert (out / "figures" / "method_comparison_topk_localizable.png").is_file()

    baseline_rows = list(csv.DictReader(result.baseline_comparison_csv_path.open(encoding="utf-8")))
    assert len(baseline_rows) == len(BASELINE_METHODS) * 2
    partitions = {row["partition"] for row in baseline_rows}
    assert partitions == {"all_detectable", "transition_localizable_gt"}

    operator_rows = list(csv.DictReader((out / "localization_method_by_operator.csv").open(encoding="utf-8")))
    methods = {row["method"] for row in operator_rows}
    assert SPECTRAL_METHODS[0] in methods


def test_build_combined_baseline_comparison_rows_fixture() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    case = localize_case_transitions(case_dir)
    rows = build_combined_baseline_comparison_rows(
        FIXTURE_DATASET,
        detectable_case_rows=[case],
        localizable_case_rows=[case],
    )
    assert len(rows) == len(BASELINE_METHODS) * 2
