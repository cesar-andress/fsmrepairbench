"""Tests for leave-one-out mutation-operator ablation."""

from __future__ import annotations

import csv
from pathlib import Path

from fsmrepairbench.mutation_operator_ablation import (
    AblationCaseRecord,
    compute_operator_ablation_rows,
    load_ablation_case_records,
    write_operator_ablation_exports,
)


def _write_progress(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "mutation_operator",
                "faulty_bpr",
                "bpr_delta",
                "status",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_repair(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "tool_id",
                "complete_repair",
                "effective_repair",
                "delta_bpr",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_compute_operator_ablation_rows_detects_oracle_invisible_impact() -> None:
    records = [
        AblationCaseRecord(
            case_id="a",
            mutation_operator="hard_op",
            faulty_bpr=1.0,
            bpr_delta=0.0,
            complete_repair=True,
            effective_repair=False,
            repair_delta_bpr=0.0,
        ),
        AblationCaseRecord(
            case_id="b",
            mutation_operator="easy_op",
            faulty_bpr=0.8,
            bpr_delta=0.2,
            complete_repair=True,
            effective_repair=True,
            repair_delta_bpr=0.1,
        ),
    ]
    baseline, summary_rows, impact_rows = compute_operator_ablation_rows(records)
    assert baseline["detection_rate"] == 0.5
    hard_impact = next(row for row in impact_rows if row["ablated_operator"] == "hard_op")
    assert float(hard_impact["delta_detection_rate"]) > 0.0
    assert len(summary_rows) == 3


def test_write_operator_ablation_exports(tmp_path: Path) -> None:
    dataset = tmp_path / "data"
    dataset.mkdir()
    cohort = dataset / "cohort.txt"
    cohort.write_text("case_a\ncase_b\ncase_c\n", encoding="utf-8")
    _write_progress(
        dataset / "progress.csv",
        [
            {
                "case_id": "case_a",
                "mutation_operator": "op_a",
                "faulty_bpr": "1.0",
                "bpr_delta": "0.0",
                "status": "completed",
            },
            {
                "case_id": "case_b",
                "mutation_operator": "op_b",
                "faulty_bpr": "0.8",
                "bpr_delta": "0.2",
                "status": "completed",
            },
            {
                "case_id": "case_c",
                "mutation_operator": "op_b",
                "faulty_bpr": "0.7",
                "bpr_delta": "0.3",
                "status": "completed",
            },
        ],
    )
    repair = tmp_path / "repair.csv"
    _write_repair(
        repair,
        [
            {
                "case_id": "case_a",
                "tool_id": "baseline_missing_transition",
                "complete_repair": "True",
                "effective_repair": "False",
                "delta_bpr": "0.0",
            },
            {
                "case_id": "case_b",
                "tool_id": "baseline_missing_transition",
                "complete_repair": "True",
                "effective_repair": "True",
                "delta_bpr": "0.1",
            },
            {
                "case_id": "case_c",
                "tool_id": "baseline_missing_transition",
                "complete_repair": "False",
                "effective_repair": "True",
                "delta_bpr": "0.05",
            },
        ],
    )
    out = tmp_path / "out"
    result = write_operator_ablation_exports(
        dataset_dir=dataset,
        cohort_path=cohort,
        repair_csv=repair,
        out_dir=out,
    )
    assert result.summary_path.is_file()
    assert result.impact_path.is_file()
    assert (result.figures_dir / "ablation_impact_heatmap.png").is_file()
    assert (result.tables_dir / "table_ablation_impact.tex").is_file()

    records = load_ablation_case_records(
        dataset_dir=dataset,
        cohort_ids={"case_a", "case_b", "case_c"},
        repair_csv=repair,
    )
    assert len(records) == 3
