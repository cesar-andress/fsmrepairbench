"""Tests for operator-level benchmark difficulty calibration."""

from __future__ import annotations

import json
from pathlib import Path

from fsmrepairbench.operator_difficulty_calibration import (
    assign_difficulty_tiers,
    compute_operator_difficulty_rows,
    write_operator_difficulty_exports,
)


def _write_repair_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "mutation_operator,cases,detectable_cases,oracle_saturated_cases,detection_rate,mean_faulty_bpr,complete_repair_rate,complete_repair_rate_detectable_only,effective_repair_rate,effective_repair_rate_detectable_only,mean_delta_bpr",
                "easy_op,10,10,0,1.0,0.9,1.0,1.0,1.0,1.0,0.1",
                "medium_op,10,10,0,0.5,0.9,0.5,0.5,0.6,0.6,0.1",
                "hard_op,10,0,10,0.0,1.0,1.0,0.0,0.0,0.0,0.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_audit_csv(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "case_id,mutation_operator,changed_transition_id,localized,transition_count,rank_of_target,reciprocal_rank,top1_hit,top3_hit,top5_hit,top_ranked_transition,ground_truth_localizable,non_localizable_reason,localizability_class",
                "case_001,easy_op,t1,True,5,1,1.0,True,True,True,t1,True,,localizable_transition_gt",
                "case_002,easy_op,t2,True,5,2,0.5,False,True,True,t1,True,,localizable_transition_gt",
                "case_003,medium_op,t3,True,5,5,0.2,False,False,True,t1,True,,localizable_transition_gt",
                "case_004,medium_op,t4,True,5,5,0.2,False,False,True,t1,True,,localizable_transition_gt",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_compute_operator_difficulty_rows() -> None:
    repair = Path("repair.csv")
    audit = Path("audit.csv")
    _write_repair_csv(repair)
    _write_audit_csv(audit)
    rows = compute_operator_difficulty_rows(
        repair_by_operator_path=repair,
        localizability_audit_path=audit,
    )
    easy = next(row for row in rows if row["mutation_operator"] == "easy_op")
    assert easy["difficulty_index"] < 0.2
    hard = next(row for row in rows if row["mutation_operator"] == "hard_op")
    assert hard["difficulty_index"] == 1.0


def test_assign_difficulty_tiers_covers_all_operators() -> None:
    rows = [
        {"mutation_operator": "a", "difficulty_index": 0.9},
        {"mutation_operator": "b", "difficulty_index": 0.5},
        {"mutation_operator": "c", "difficulty_index": 0.1},
    ]
    ranked = assign_difficulty_tiers(rows)
    tiers = {row["difficulty_tier"] for row in ranked}
    assert tiers == {"easy", "medium", "hard"}


def test_write_operator_difficulty_exports(tmp_path: Path) -> None:
    repair = tmp_path / "repair.csv"
    audit = tmp_path / "audit.csv"
    _write_repair_csv(repair)
    _write_audit_csv(audit)
    out_dir = tmp_path / "out"
    result = write_operator_difficulty_exports(
        repair_by_operator_path=repair,
        localizability_audit_path=audit,
        out_dir=out_dir,
        paper_export_dir=None,
    )
    assert result.csv_path.is_file()
    assert result.tex_path.is_file()
    assert result.figure_path.is_file()
    assert result.summary_path.is_file()
    payload = json.loads(result.summary_path.read_text(encoding="utf-8"))
    assert payload["operator_count"] == 3
