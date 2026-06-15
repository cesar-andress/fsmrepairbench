"""Tests for stratification plan gap visualisations."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.generators.stratified_specs import load_dataset_plan
from fsmrepairbench.taxonomy_gap_figures import (
    compute_missing_dimension_values,
    compute_plan_cell_realisations,
    write_taxonomy_gap_figures,
)

PLAN = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_v0_1k_plan.yaml"


def _sample_row(**overrides: str) -> dict[str, str | int | float]:
    base = {
        "case_id": "case_000001",
        "machine_type": "plain_fsm",
        "determinism": "deterministic",
        "completeness": "partial",
        "arity_class": "low",
        "size_class": "tiny",
        "guard_complexity": "none",
        "time_features": "none",
        "graph_structure": "hub_and_spoke",
        "oracle_depth": "shallow",
        "bug_type": "missing_transition",
    }
    base.update(overrides)
    return base


@pytest.mark.skipif(not PLAN.is_file(), reason="plan file missing")
def test_plan_cell_realisation_detects_plain_fsm_only() -> None:
    rows = [_sample_row()]
    realisations = compute_plan_cell_realisations(rows, plan_path=PLAN)
    plain = [item for item in realisations if item.machine_type == "plain_fsm"]
    non_plain = [item for item in realisations if item.machine_type != "plain_fsm"]
    assert any(item.realised_count > 0 for item in plain)
    assert all(item.realised_count == 0 for item in non_plain)


@pytest.mark.skipif(not PLAN.is_file(), reason="plan file missing")
def test_write_taxonomy_gap_figures(tmp_path: Path) -> None:
    rows = [_sample_row()]
    figures_dir = tmp_path / "figures"
    written = write_taxonomy_gap_figures(
        figures_dir,
        rows=rows,
        plan_path=PLAN,
        output_dir=tmp_path,
    )
    for path in written.values():
        assert path.is_file()
    assert (tmp_path / "plan_cell_gaps.csv").is_file()
    missing = compute_missing_dimension_values(rows, plan_path=PLAN)
    assert any(row["dimension"] == "machine_type" for row in missing)
