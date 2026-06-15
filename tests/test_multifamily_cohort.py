"""Tests for multi-family v0.3 cohort pinning and stratified selection."""

from __future__ import annotations

from pathlib import Path

from fsmrepairbench.multifamily_cohort import (
    pin_multifamily_cohort_manifests,
    select_machine_type_stratified_cohort,
)


FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_select_machine_type_stratified_cohort_balances_families(tmp_path: Path) -> None:
    matrix = tmp_path / "feature_matrix.csv"
    matrix.write_text(
        "case_id,machine_type,bug_type\n"
        "case_a,plain_fsm,missing_transition\n"
        "case_b,mealy,wrong_target\n"
        "case_c,moore,guard_flip\n"
        "case_d,efsm,guard_weaken\n"
        "case_e,timed_fsm,timeout_corruption\n"
        "case_a2,plain_fsm,wrong_source\n"
        "case_b2,mealy,action_corruption\n",
        encoding="utf-8",
    )
    for case_id in ("case_a", "case_b", "case_c", "case_d", "case_e", "case_a2", "case_b2"):
        case_dir = tmp_path / "cases" / case_id
        case_dir.mkdir(parents=True)
        (case_dir / "case_features.json").write_text(
            '{"bug_type":"missing_transition","machine_type":"plain_fsm"}',
            encoding="utf-8",
        )

    selected = select_machine_type_stratified_cohort(
        tmp_path,
        ["case_a", "case_b", "case_c", "case_d", "case_e", "case_a2", "case_b2"],
        size=5,
    )
    assert len(selected) == 5
    assert len(set(selected)) == 5


def test_pin_multifamily_cohort_manifests_on_smoke_dataset() -> None:
    smoke = Path(__file__).resolve().parents[2] / "data" / "fsmrepairbench_multifamily_v0_3_smoke"
    if not smoke.is_dir():
        return
    manifests = pin_multifamily_cohort_manifests(smoke)
    assert manifests.analysis.txt_path.is_file()
    assert manifests.analysis.json_path.is_file()
    assert len(manifests.analysis.case_ids) == 500
    assert manifests.coupling.txt_path.is_file()
    assert len(manifests.coupling.case_ids) == 125
    assert manifests.oracle_depth.txt_path.is_file()
    assert len(manifests.oracle_depth.case_ids) == 100
