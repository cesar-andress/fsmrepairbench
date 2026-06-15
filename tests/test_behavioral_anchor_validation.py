"""Tests for behavioral-anchor ground-truth validation."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fsmrepairbench.behavioral_anchor_validation import (
    BEHAVIORAL_ANCHOR_COLUMNS,
    OPERATOR_SUMMARY_COLUMNS,
    build_behavioral_anchor_rows,
    restoring_transition_ids,
    select_behavioral_anchor,
    summarize_behavioral_anchor_rows,
    validate_case_behavioral_anchor,
    write_behavioral_anchor_exports,
)
from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"
DATASET_1K = Path(__file__).resolve().parents[1] / "data" / "fsmrepairbench_1k"
PAPER_RQ3 = Path(__file__).resolve().parents[2] / "paper1" / "results" / "rq3_localization_1k"


def test_select_behavioral_anchor_exact_match() -> None:
    anchor, exact, notes = select_behavioral_anchor("t1", ("t1",))
    assert anchor == "t1"
    assert exact is True
    assert notes == ""


def test_select_behavioral_anchor_multiple_prefers_metadata() -> None:
    anchor, exact, notes = select_behavioral_anchor("t2", ("t1", "t2"))
    assert anchor == "t2"
    assert exact is True
    assert "multiple behavioral anchors" in notes


def test_select_behavioral_anchor_no_restoring_transition() -> None:
    anchor, exact, notes = select_behavioral_anchor("t1", ())
    assert anchor == ""
    assert exact is False
    assert "no single-transition revert" in notes


@pytest.mark.skipif(not (FIXTURE_DATASET / "cases" / "case_000002").is_dir(), reason="fixture missing")
def test_restoring_transition_ids_on_fixture_case() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    reference = load_fsm_json(resolve_coupling_case_file(case_dir, "reference_fsm.json"))
    faulty = load_fsm_json(resolve_coupling_case_file(case_dir, "faulty_fsm.json"))
    oracle = load_oracle_suite(resolve_coupling_case_file(case_dir, "oracle_suite.json"))
    restoring = restoring_transition_ids(faulty, reference, oracle)
    assert restoring == ("t2",)


@pytest.mark.skipif(not DATASET_1K.is_dir() or not PAPER_RQ3.is_dir(), reason="1k dataset or RQ3 export missing")
def test_frozen_cohort_has_perfect_agreement() -> None:
    rows = build_behavioral_anchor_rows(DATASET_1K, PAPER_RQ3 / "localizability_audit.csv")
    summary = summarize_behavioral_anchor_rows(rows)
    assert summary.n_cases == 376
    assert summary.agreement_rate == pytest.approx(1.0)
    assert summary.n_no_anchor == 0
    assert summary.n_multiple_anchors == 0


@pytest.mark.skipif(not DATASET_1K.is_dir() or not PAPER_RQ3.is_dir(), reason="1k dataset or RQ3 export missing")
def test_write_behavioral_anchor_exports_schema(tmp_path: Path) -> None:
    rq3_dir = tmp_path / "rq3"
    rq3_dir.mkdir()
    (rq3_dir / "localizability_audit.csv").write_text(
        (PAPER_RQ3 / "localizability_audit.csv").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    result = write_behavioral_anchor_exports(DATASET_1K, rq3_dir, out_dir=rq3_dir)
    with result.csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(BEHAVIORAL_ANCHOR_COLUMNS)
        rows = list(reader)
    assert len(rows) == 376
    assert all(row["exact_match"] == "True" for row in rows)

    with result.operator_csv_path.open(encoding="utf-8") as handle:
        operator_reader = csv.DictReader(handle)
        assert operator_reader.fieldnames == list(OPERATOR_SUMMARY_COLUMNS)

    assert result.tex_path.is_file()
    assert result.manifest_path.is_file()


@pytest.mark.skipif(not (FIXTURE_DATASET / "cases" / "case_000002").is_dir(), reason="fixture missing")
def test_validate_case_behavioral_anchor_fixture() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    row = validate_case_behavioral_anchor(
        case_dir,
        {
            "case_id": "case_000002",
            "mutation_operator": "wrong_target",
            "changed_transition_id": "t2",
        },
    )
    assert row is not None
    assert row.exact_match is True
    assert row.behavioral_anchor_transition == "t2"
