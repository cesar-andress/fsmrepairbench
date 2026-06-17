"""Tests for C1 baseline delta exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from fsmrepairbench.c1_baseline_delta import (
    compute_c1_baseline_delta_rows,
    write_c1_baseline_delta_exports,
)


def _synthetic_rows() -> list[dict]:
    rows: list[dict] = []
    operators = ("missing_transition", "wrong_target", "guard_flip")
    tiers = ("small", "medium", "large")
    for case_index in range(12):
        operator = operators[case_index % len(operators)]
        tier = tiers[case_index % len(tiers)]
        detectable = case_index % 4 != 0
        case_id = f"case_{case_index:03d}"
        rows.extend(
            [
                {
                    "case_id": case_id,
                    "tool_id": "baseline_missing_transition",
                    "mutation_operator": operator,
                    "complexity_tier": tier,
                    "delta_bpr": 0.10 if detectable else 0.0,
                    "complete_repair": detectable and case_index % 3 != 0,
                    "effective_repair": detectable,
                    "regression": False,
                    "oracle_detected": detectable,
                },
                {
                    "case_id": case_id,
                    "tool_id": "baseline_wrong_target",
                    "mutation_operator": operator,
                    "complexity_tier": tier,
                    "delta_bpr": 0.04 if detectable else 0.0,
                    "complete_repair": detectable and case_index % 5 == 0,
                    "effective_repair": detectable and case_index % 2 == 0,
                    "regression": detectable and case_index % 7 == 0,
                    "oracle_detected": detectable,
                },
                {
                    "case_id": case_id,
                    "tool_id": "baseline_random",
                    "mutation_operator": operator,
                    "complexity_tier": tier,
                    "delta_bpr": -0.02 if detectable else 0.0,
                    "complete_repair": False,
                    "effective_repair": detectable and case_index % 8 == 0,
                    "regression": detectable and case_index % 3 == 0,
                    "oracle_detected": detectable,
                },
            ]
        )
    return rows


def test_compute_c1_baseline_delta_rows_prefers_missing_transition() -> None:
    rows = compute_c1_baseline_delta_rows(_synthetic_rows())
    overall_detectable = next(
        row
        for row in rows
        if row["scope"] == "overall"
        and row["partition"] == "detectable_only"
        and row["comparison_label"] == "missing-transition vs random"
    )
    assert overall_detectable["delta_complete_repair_rate"] > 0.0
    assert overall_detectable["delta_mean_delta_bpr"] > 0.0
    assert overall_detectable["n_cases"] == 9


def test_compute_c1_baseline_delta_rows_by_operator_scope() -> None:
    rows = compute_c1_baseline_delta_rows(_synthetic_rows())
    operator_rows = [
        row
        for row in rows
        if row["scope"] == "by_operator"
        and row["partition"] == "detectable_only"
        and row["group_value"] == "missing_transition"
    ]
    assert len(operator_rows) == 3


def test_write_c1_baseline_delta_exports(tmp_path: Path) -> None:
    per_case = tmp_path / "per_case_results.csv"
    fieldnames = [
        "case_id",
        "tool_id",
        "mutation_operator",
        "complexity_tier",
        "initial_bpr",
        "final_bpr",
        "delta_bpr",
        "complete_repair",
        "effective_repair",
        "regression",
        "faulty_bpr",
        "reference_bpr",
        "difficulty_score",
        "oracle_detected",
        "bpr_delta_pre_repair",
    ]
    with per_case.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in _synthetic_rows():
            writer.writerow(
                {
                    **row,
                    "initial_bpr": 0.8,
                    "final_bpr": 0.9,
                    "faulty_bpr": 0.8 if row["oracle_detected"] else 1.0,
                    "reference_bpr": 1.0,
                    "difficulty_score": 10.0,
                    "bpr_delta_pre_repair": row["delta_bpr"],
                    "complete_repair": str(row["complete_repair"]).lower(),
                    "effective_repair": str(row["effective_repair"]).lower(),
                    "regression": str(row["regression"]).lower(),
                    "oracle_detected": str(row["oracle_detected"]).lower(),
                }
            )

    result = write_c1_baseline_delta_exports(per_case, tmp_path / "out")
    assert result.summary_csv_path.is_file()
    assert result.manifest_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["zenodo_doi"] == "10.5281/zenodo.20724095"
    assert manifest["github_tag"]
    assert manifest["source_per_case_sha256"]
    assert result.operator_figure_path.is_file()
    assert result.summary_tex_path.read_text(encoding="utf-8").startswith("\\begin{table")
