"""Tests for C1 saturation inflation analysis."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fsmrepairbench.saturation_inflation import (
    SATURATION_INFLATION_CSV_COLUMNS,
    bootstrap_saturation_inflation_pp,
    build_saturation_inflation_rows,
    write_saturation_inflation_exports,
)
from fsmrepairbench.statistics import BOOTSTRAP_SEED

REPO_ROOT = Path(__file__).resolve().parents[1]
PAPER_C1 = REPO_ROOT.parent / "paper1" / "results" / "baseline_repair_C1"


def _synthetic_outcomes() -> list:
    from fsmrepairbench.saturation_inflation import CaseRepairOutcome

    outcomes: list[CaseRepairOutcome] = []
    for index in range(10):
        detectable = index % 2 == 0
        outcomes.append(
            CaseRepairOutcome(
                case_id=f"case_{index:03d}",
                oracle_detected=detectable,
                complete_repair=detectable and index % 4 == 0,
                effective_repair=detectable and index % 3 == 0,
            )
        )
    return outcomes


def test_bootstrap_saturation_inflation_is_deterministic() -> None:
    outcomes = _synthetic_outcomes()
    first = bootstrap_saturation_inflation_pp(outcomes, bootstrap_seed=BOOTSTRAP_SEED)
    second = bootstrap_saturation_inflation_pp(outcomes, bootstrap_seed=BOOTSTRAP_SEED)
    assert first == second


@pytest.mark.skipif(not PAPER_C1.is_dir(), reason="frozen C1 export missing")
def test_frozen_c1_inflation_values_for_primary_engines() -> None:
    rows = build_saturation_inflation_rows(PAPER_C1, bootstrap_seed=BOOTSTRAP_SEED)
    by_engine = {row.engine: row for row in rows}
    assert by_engine["missing-transition"].saturation_inflation_pp == pytest.approx(15.9152, abs=0.05)
    assert by_engine["wrong-target"].saturation_inflation_pp == pytest.approx(44.3788, abs=0.05)
    assert by_engine["random"].saturation_inflation_pp == pytest.approx(50.398, abs=0.05)
    assert by_engine["random"].detectable_only_complete_repair == pytest.approx(0.00202, abs=1e-5)
    assert by_engine["random"].cohort_wide_complete_repair == pytest.approx(0.506, abs=1e-5)


@pytest.mark.skipif(not PAPER_C1.is_dir(), reason="frozen C1 export missing")
def test_saturation_inflation_csv_schema(tmp_path: Path) -> None:
    result = write_saturation_inflation_exports(
        PAPER_C1,
        out_dir=tmp_path / "out",
        paper_export_dir=None,
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    with result.csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(SATURATION_INFLATION_CSV_COLUMNS)
        rows = list(reader)
    assert len(rows) >= 3
    for row in rows:
        assert set(row) == set(SATURATION_INFLATION_CSV_COLUMNS)
        assert int(row["total_cases"]) == 1000
        assert int(row["saturated_cases"]) == 505
        assert int(row["detectable_cases"]) == 495


@pytest.mark.skipif(not PAPER_C1.is_dir(), reason="frozen C1 export missing")
def test_write_saturation_inflation_exports_writes_table_and_figure(tmp_path: Path) -> None:
    result = write_saturation_inflation_exports(
        PAPER_C1,
        out_dir=tmp_path / "repo",
        paper_export_dir=tmp_path / "paper",
        bootstrap_seed=BOOTSTRAP_SEED,
    )
    assert result.tex_path.is_file()
    assert result.figure_path.is_file()
    assert result.paper_tex_path is not None
    assert result.paper_figure_path is not None
    assert result.paper_tex_path.is_file()
    assert result.paper_figure_path.is_file()
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bootstrap"]["seed"] == BOOTSTRAP_SEED
    random_row = next(row for row in manifest["rows"] if row["engine"] == "random")
    assert random_row["saturation_inflation_ci95_low_pp"] <= random_row["saturation_inflation_pp"]
    assert random_row["saturation_inflation_ci95_high_pp"] >= random_row["saturation_inflation_pp"]
