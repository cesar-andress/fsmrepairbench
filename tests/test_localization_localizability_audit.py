"""Tests for RQ3 ground-truth localizability audit."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fsmrepairbench.localization_campaign import localize_case_transitions
from fsmrepairbench.localization_localizability_audit import (
    audit_case_localizability,
    audit_localization_results,
    classify_ground_truth_localizability,
    run_localization_localizability_audit,
)
from fsmrepairbench.mutators import mutate
from fsmrepairbench.validators import load_fsm

FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"
FIXTURES = Path(__file__).parent / "fixtures"


def test_classify_missing_transition_as_deleted_gt() -> None:
    localizability_class, localizable, reason = classify_ground_truth_localizability(
        mutation_operator="missing_transition",
        changed_transition_id="t1",
        faulty_transition_ids=frozenset({"t2"}),
    )
    assert localizable is False
    assert localizability_class == "missing_or_deleted_transition_gt"
    assert "removed" in reason


def test_classify_wrong_initial_state_as_non_transition_fault() -> None:
    localizability_class, localizable, reason = classify_ground_truth_localizability(
        mutation_operator="wrong_initial_state",
        changed_transition_id=None,
        faulty_transition_ids=frozenset({"t1"}),
    )
    assert localizable is False
    assert localizability_class == "non_transition_fault_gt"
    assert "not anchored" in reason


def test_classify_wrong_target_as_localizable() -> None:
    localizability_class, localizable, reason = classify_ground_truth_localizability(
        mutation_operator="wrong_target",
        changed_transition_id="t2",
        faulty_transition_ids=frozenset({"t1", "t2"}),
    )
    assert localizable is True
    assert localizability_class == "localizable_transition_gt"
    assert reason == ""


def test_audit_fixture_wrong_target_case() -> None:
    case_dir = FIXTURE_DATASET / "cases" / "case_000002"
    case = localize_case_transitions(case_dir)
    audit_row = audit_case_localizability(case_dir, case)
    assert audit_row.ground_truth_localizable is True
    assert audit_row.localizability_class == "localizable_transition_gt"


def test_run_localizability_audit_on_fixture_dataset(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    out.mkdir()

    case = localize_case_transitions(FIXTURE_DATASET / "cases" / "case_000002")
    per_case_path = out / "per_case_results.csv"
    with per_case_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(case.to_dict().keys()),
        )
        writer.writeheader()
        writer.writerow(case.to_dict())

    result = run_localization_localizability_audit(
        FIXTURE_DATASET,
        output_dir=out,
        per_case_path=per_case_path,
    )
    assert result.audit_csv_path.is_file()
    assert result.metrics_csv_path.is_file()
    assert result.report_path.is_file()
    assert result.localizable_metrics["localized_cases"] == 1
    assert float(result.localizable_metrics["top1_hit_rate"]) == 1.0

    audit_rows = list(csv.DictReader(result.audit_csv_path.open(encoding="utf-8")))
    assert audit_rows[0]["ground_truth_localizable"] == "True"
    assert audit_rows[0]["localizability_class"] == "localizable_transition_gt"

    metric_rows = list(csv.DictReader(result.metrics_csv_path.open(encoding="utf-8")))
    partitions = {row["partition"] for row in metric_rows}
    assert partitions == {"all_detectable", "transition_localizable_gt"}


def test_audit_synthetic_missing_transition_case(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "missing_transition", 0)
    assert metadata.changed_transition_id is not None

    case_dir = tmp_path / "cases" / "case_missing"
    case_dir.mkdir(parents=True)
    (case_dir / "faulty_fsm.json").write_text(
        json.dumps(faulty.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "bug_metadata.json").write_text(
        json.dumps(
            {
                "bug_id": "test",
                "reference_fsm_id": reference.id,
                "faulty_fsm_id": faulty.id,
                "mutation_operator": metadata.mutation_operator,
                "changed_transition_id": metadata.changed_transition_id,
                "description": metadata.description,
                "seed": metadata.seed,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    from fsmrepairbench.localization_campaign import CaseLocalizationResult

    case = CaseLocalizationResult(
        case_id="case_missing",
        mutation_operator="missing_transition",
        changed_transition_id=metadata.changed_transition_id or "",
        localized=True,
        transition_count=1,
        rank_of_target=None,
        reciprocal_rank=0.0,
        top1_hit=False,
        top3_hit=False,
        top5_hit=False,
        top_ranked_transition="t1",
    )
    audit_row = audit_case_localizability(case_dir, case)
    assert audit_row.ground_truth_localizable is False
    assert audit_row.localizability_class == "missing_or_deleted_transition_gt"

    dataset_dir = tmp_path
    rows = audit_localization_results(dataset_dir, [case])
    assert rows[0].localizability_class == "missing_or_deleted_transition_gt"


def test_operator_export_includes_all_operators_and_not_ranked(tmp_path: Path) -> None:
    from fsmrepairbench.localization_campaign import CaseLocalizationResult
    from fsmrepairbench.localization_localizability_audit import LocalizabilityAuditRow

    audit_rows = [
        LocalizabilityAuditRow(
            case=CaseLocalizationResult(
                case_id="case_a",
                mutation_operator="wrong_target",
                changed_transition_id="t1",
                localized=True,
                transition_count=2,
                rank_of_target=1,
                reciprocal_rank=1.0,
                top1_hit=True,
                top3_hit=True,
                top5_hit=True,
                top_ranked_transition="t1",
            ),
            ground_truth_localizable=True,
            non_localizable_reason="",
            localizability_class="localizable_transition_gt",
        ),
        LocalizabilityAuditRow(
            case=CaseLocalizationResult(
                case_id="case_b",
                mutation_operator="duplicate_transition",
                changed_transition_id="t2",
                localized=False,
                transition_count=0,
                rank_of_target=None,
                reciprocal_rank=0.0,
                top1_hit=False,
                top3_hit=False,
                top5_hit=False,
                top_ranked_transition="",
            ),
            ground_truth_localizable=False,
            non_localizable_reason="oracle-saturated",
            localizability_class="missing_ground_truth",
        ),
    ]
    from fsmrepairbench.localization_operator_exports import (
        build_operator_metrics_rows,
        build_rank_distribution_operator_rows,
    )

    operator_rows = build_operator_metrics_rows(audit_rows, {})
    operators = {str(row["mutation_operator"]) for row in operator_rows}
    assert "wrong_target" in operators
    assert "duplicate_transition" in operators

    wrong_target_primary = next(
        row
        for row in operator_rows
        if row["mutation_operator"] == "wrong_target"
        and row["partition"] == "all_detectable"
        and row["gt_mode"] == "primary"
    )
    assert int(wrong_target_primary["not_ranked_count"]) == 0
    assert float(wrong_target_primary["top1_hit_rate"]) == 1.0

    dup_row = next(
        row
        for row in operator_rows
        if row["mutation_operator"] == "duplicate_transition"
        and row["partition"] == "all_detectable"
    )
    assert int(dup_row["detectable_cases"]) == 0

    rank_rows = build_rank_distribution_operator_rows(audit_rows, {})
    assert any(row["mutation_operator"] == "wrong_target" for row in rank_rows)
