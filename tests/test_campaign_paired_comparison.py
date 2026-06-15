"""Tests for cross-campaign paired comparison on the RQ4 coupling pin."""

from __future__ import annotations

import csv
from pathlib import Path

from fsmrepairbench.campaign_paired_comparison import (
    build_paired_case_rows,
    compute_paired_summary_rows,
    export_campaign_paired_comparison,
    write_paired_comparison_figure,
)


def _write_c1(path: Path, case_id: str, *, detected: bool, complete: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.is_file()
    with path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "tool_id",
                "mutation_operator",
                "complexity_tier",
                "initial_bpr",
                "final_bpr",
                "delta_bpr",
                "complete_repair",
                "effective_repair",
                "faulty_bpr",
                "reference_bpr",
                "oracle_detected",
                "bpr_delta_pre_repair",
            ],
        )
        if write_header:
            writer.writeheader()
        writer.writerow(
            {
                "case_id": case_id,
                "tool_id": "baseline_missing_transition",
                "mutation_operator": "wrong_target",
                "complexity_tier": "small",
                "initial_bpr": "0.9",
                "final_bpr": "1.0" if complete else "0.9",
                "delta_bpr": "0.1" if complete else "0.0",
                "complete_repair": str(complete),
                "effective_repair": str(complete),
                "faulty_bpr": "0.9" if detected else "1.0",
                "reference_bpr": "1.0",
                "oracle_detected": str(detected),
                "bpr_delta_pre_repair": "0.1" if detected else "0.0",
            }
        )


def _write_rq3(per_case: Path, audit: Path, case_id: str, *, localizable: bool) -> None:
    per_case.parent.mkdir(parents=True, exist_ok=True)
    per_case.write_text(
        "case_id,top1_hit\n"
        f"{case_id},False\n",
        encoding="utf-8",
    )
    audit.write_text(
        "case_id,ground_truth_localizable\n"
        f"{case_id},{localizable}\n",
        encoding="utf-8",
    )


def _write_rq4(path: Path, case_id: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "case_id,source_case_id,mutation_order,is_higher_order,primary_operator,mutation_operator,"
        "reference_bpr,faulty_bpr,bpr_delta,fault_detected,complete_repair,effective_repair,"
        "repair_delta_bpr\n"
        f"{case_id},{case_id},1,False,wrong_target,wrong_target,1.0,0.9,0.1,True,True,True,0.1\n"
        f"{case_id}__ho2,{case_id},2,True,wrong_target,wrong_target|missing_transition,1.0,0.5,0.5,True,False,True,0.2\n",
        encoding="utf-8",
    )


def test_build_and_summarize_paired_rows(tmp_path: Path) -> None:
    case_id = "case_000001"
    c1_path = tmp_path / "c1" / "per_case_results.csv"
    rq3_per_case = tmp_path / "rq3" / "per_case_results.csv"
    rq3_audit = tmp_path / "rq3" / "localizability_audit.csv"
    rq4_path = tmp_path / "rq4" / "per_case_results.csv"

    _write_c1(c1_path, case_id, detected=True, complete=True)
    _write_rq3(rq3_per_case, rq3_audit, case_id, localizable=True)
    _write_rq4(rq4_path, case_id)

    c1_rows = {case_id: next(csv.DictReader(c1_path.open(encoding="utf-8")))}
    rq3_rows = {case_id: next(csv.DictReader(rq3_per_case.open(encoding="utf-8")))}
    rq3_audit_rows = {case_id: next(csv.DictReader(rq3_audit.open(encoding="utf-8")))}
    fo_row = next(csv.DictReader(rq4_path.open(encoding="utf-8")))
    ho_row = list(csv.DictReader(rq4_path.open(encoding="utf-8")))[1]

    paired = build_paired_case_rows(
        case_ids=[case_id],
        c1_rows=c1_rows,
        rq3_rows=rq3_rows,
        rq3_audit=rq3_audit_rows,
        rq4_first_order={case_id: fo_row},
        rq4_higher_order={case_id: ho_row},
    )
    assert paired[0]["detection_gained_fo_to_ho"] is False
    assert paired[0]["rq4_ho_bpr_delta"] == 0.5

    summary = compute_paired_summary_rows(paired)
    lookup = {(row["campaign_lane"], row["metric"], row["partition"]): row for row in summary}
    assert lookup[("rq4_higher_order", "mean_bpr_delta_pre_repair", "cohort_wide")]["value"] == 0.5
    assert lookup[("rq3_ochiai", "top_1_hit_rate", "transition_localizable_gt")]["n_cases"] == 1

    figure_path = tmp_path / "figure.png"
    write_paired_comparison_figure(
        figure_path,
        summary_rows=summary,
        case_rows=paired,
    )
    assert figure_path.is_file()


def test_export_campaign_paired_comparison(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    dataset = repo / "data" / "fsmrepairbench_1k"
    dataset.mkdir(parents=True)
    cohort = dataset / "coupling_campaign_250.txt"
    cohort.write_text("case_000001\n", encoding="utf-8")

    c1_dir = repo / "results" / "baseline_repair_C1"
    rq3_dir = repo / "results" / "rq3_localization_1k"
    rq4_dir = repo / "results" / "rq4_coupling_250"
    _write_c1(c1_dir / "per_case_results.csv", "case_000001", detected=True, complete=True)
    _write_rq3(
        rq3_dir / "per_case_results.csv",
        rq3_dir / "localizability_audit.csv",
        "case_000001",
        localizable=True,
    )
    _write_rq4(rq4_dir / "per_case_results.csv", "case_000001")

    paper_out = tmp_path / "paper1" / "results" / "campaign_paired_comparison"
    result = export_campaign_paired_comparison(
        repo_root=repo,
        cohort_manifest=cohort,
        output_dir=repo / "results" / "campaign_paired_comparison",
        paper_export_dir=paper_out,
        result_overrides={
            "C1-baseline-repair": c1_dir,
            "RQ3-localization": rq3_dir,
            "RQ4-coupling": rq4_dir,
        },
    )
    assert result.case_csv_path.is_file()
    assert result.figure_path.is_file()
    assert (paper_out / "paired_cohort_summary.csv").is_file()
