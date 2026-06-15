"""Tests for stratification coverage heatmap exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.coverage_visualizations import (
    build_dimension_value_coverage_rows,
    build_family_operator_rows,
)
from fsmrepairbench.taxonomy_gap_figures import compute_plan_cell_realisations

PLAN = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_v0_1k_plan.yaml"


def _sample_row(**overrides: str) -> dict[str, str | int | float]:
    base = {
        "case_id": "case_000001",
        "machine_type": "plain_fsm",
        "determinism": "deterministic",
        "completeness": "partial",
        "arity_class": "low",
        "size_class": "small",
        "guard_complexity": "none",
        "time_features": "none",
        "graph_structure": "hub_and_spoke",
        "oracle_depth": "shallow",
        "bug_type": "missing_transition",
    }
    base.update(overrides)
    return base


@pytest.mark.skipif(not PLAN.is_file(), reason="plan file missing")
def test_dimension_value_coverage_marks_size_class_gap() -> None:
    rows = [_sample_row()]
    coverage = build_dimension_value_coverage_rows(rows, plan_path=PLAN, case_count=1)
    tiny = next(row for row in coverage if row["dimension"] == "size_class" and row["value"] == "tiny")
    small = next(row for row in coverage if row["dimension"] == "size_class" and row["value"] == "small")
    assert int(tiny["planned_cases"]) > 0
    assert int(tiny["realised_cases"]) == 0
    assert tiny["status"] == "unrepresented"
    assert int(small["realised_cases"]) == 1
    assert small["status"] == "realised_not_planned"


@pytest.mark.skipif(not PLAN.is_file(), reason="plan file missing")
def test_family_operator_rows_mark_plain_fsm_realisation() -> None:
    rows = [_sample_row(case_id=f"case_{index:06d}") for index in range(1, 4)]
    realisations = compute_plan_cell_realisations(rows, plan_path=PLAN)
    family_operator = build_family_operator_rows(rows, realisations)
    plain_missing = next(
        row
        for row in family_operator
        if row["machine_type"] == "plain_fsm" and row["bug_type"] == "missing_transition"
    )
    assert int(plain_missing["realised_count"]) == 3
    assert int(plain_missing["planned_count"]) == 50
    assert plain_missing["status"] == "underfilled"
