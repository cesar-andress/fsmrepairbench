"""Tests for C1 multi-seed subgroup variance exports."""

from __future__ import annotations

from pathlib import Path

from fsmrepairbench.c1_multiseed_variance import (
    aggregate_seed_bootstrap_subgroup_ci,
    build_multiseed_variance_rows,
    compute_case_bootstrap_subgroup_ci,
    enrich_case_dict_rows,
    summarize_seed_subgroups,
    write_c1_multiseed_variance_exports,
)
from fsmrepairbench.tool_runner import ToolRunSummaryRow
from tests.helpers import setup_cases_root


def _summary_row(
    *,
    case_id: str,
    operator: str,
    complete: bool,
    effective: bool,
    initial_bpr: float = 0.8,
) -> ToolRunSummaryRow:
    return ToolRunSummaryRow(
        case_id=case_id,
        tool_id="baseline_random",
        tool_type="baseline",
        model="random",
        mutation_operator=operator,
        status="completed",
        failure_class="none",
        initial_bpr=initial_bpr,
        final_bpr=1.0 if complete else initial_bpr,
        delta_bpr=0.2 if complete else 0.0,
        complete_repair=complete,
        effective_repair=effective,
        regression=False,
        patch_parse_failures=0,
        patch_validation_failures=0,
        patch_application_failures=0,
        iterations_completed=1,
        runtime_seconds=0.1,
    )


def test_summarize_seed_subgroups_groups_by_operator_and_tier() -> None:
    rows = [
        _summary_row(case_id="case_000001", operator="guard_flip", complete=True, effective=True),
        _summary_row(case_id="case_000002", operator="wrong_target", complete=False, effective=False),
    ]
    subgroups = summarize_seed_subgroups(rows, {})
    assert "guard_flip" in subgroups["by_operator"]
    assert subgroups["by_operator"]["guard_flip"]["detectable_only"]["complete_repair_rate"] == 1.0
    assert subgroups["by_operator"]["wrong_target"]["detectable_only"]["complete_repair_rate"] == 0.0


def test_aggregate_seed_bootstrap_subgroup_ci_orders_bounds() -> None:
    per_seed = [
        {
            "by_operator": {
                "guard_flip": {
                    "detectable_only": {
                        "n_cases": 10,
                        "complete_repair_rate": 0.4,
                        "effective_repair_rate": 0.3,
                    },
                    "cohort_wide": {
                        "n_cases": 10,
                        "complete_repair_rate": 0.4,
                        "effective_repair_rate": 0.3,
                    },
                }
            }
        },
        {
            "by_operator": {
                "guard_flip": {
                    "detectable_only": {
                        "n_cases": 10,
                        "complete_repair_rate": 0.6,
                        "effective_repair_rate": 0.5,
                    },
                    "cohort_wide": {
                        "n_cases": 10,
                        "complete_repair_rate": 0.6,
                        "effective_repair_rate": 0.5,
                    },
                }
            }
        },
    ]
    rows = aggregate_seed_bootstrap_subgroup_ci(
        per_seed,
        tool_id="baseline_random",
        group_key="by_operator",
        subgroup_type="operator",
        seed_count=2,
        bootstrap_resamples=500,
        bootstrap_seed=0,
    )
    complete = next(row for row in rows if row.metric == "complete_repair_rate")
    assert complete.point_estimate == 0.5
    assert complete.ci95_low <= complete.point_estimate <= complete.ci95_high


def test_write_c1_multiseed_variance_exports_writes_csv_and_tex(tmp_path: Path) -> None:
    enriched = [
        {
            "case_id": "case_000001",
            "tool_id": "baseline_missing_transition",
            "mutation_operator": "guard_flip",
            "complexity_tier": "small",
            "complete_repair": True,
            "effective_repair": True,
            "oracle_detected": True,
        },
        {
            "case_id": "case_000002",
            "tool_id": "baseline_missing_transition",
            "mutation_operator": "wrong_target",
            "complexity_tier": "medium",
            "complete_repair": False,
            "effective_repair": False,
            "oracle_detected": True,
        },
    ]
    per_seed = [
        {
            "by_operator": {
                "guard_flip": {
                    "detectable_only": {
                        "n_cases": 1,
                        "complete_repair_rate": 0.5,
                        "effective_repair_rate": 0.5,
                    },
                    "cohort_wide": {
                        "n_cases": 1,
                        "complete_repair_rate": 0.5,
                        "effective_repair_rate": 0.5,
                    },
                }
            },
            "by_tier": {
                "small": {
                    "detectable_only": {
                        "n_cases": 1,
                        "complete_repair_rate": 0.5,
                        "effective_repair_rate": 0.5,
                    },
                    "cohort_wide": {
                        "n_cases": 1,
                        "complete_repair_rate": 0.5,
                        "effective_repair_rate": 0.5,
                    },
                }
            },
        }
    ]
    raw_dir = tmp_path / "raw"
    paper_dir = tmp_path / "paper"
    result = write_c1_multiseed_variance_exports(
        raw_runs_dir=raw_dir,
        paper_export_dir=paper_dir,
        enriched_rows=enriched,
        per_seed_subgroups=per_seed,
        seed_count=1,
        case_count=2,
        detectable_count=2,
    )
    assert result.by_operator_csv.is_file()
    assert result.by_tier_csv.is_file()
    assert result.operator_tex_path.is_file()
    assert result.tier_tex_path.is_file()
    assert result.operator_figure_path.is_file()
    assert result.tier_figure_path.is_file()


def test_compute_case_bootstrap_subgroup_ci_for_deterministic_tool() -> None:
    enriched = enrich_case_dict_rows(
        [
            {
                "case_id": "a",
                "tool_id": "baseline_missing_transition",
                "complete_repair": True,
                "effective_repair": True,
                "initial_bpr": 0.5,
            },
            {
                "case_id": "b",
                "tool_id": "baseline_missing_transition",
                "complete_repair": False,
                "effective_repair": False,
                "initial_bpr": 0.5,
            },
        ],
        {},
    )
    for row in enriched:
        row["mutation_operator"] = "guard_flip"
        row["complexity_tier"] = "small"
    rows = compute_case_bootstrap_subgroup_ci(
        enriched,
        tool_id="baseline_missing_transition",
        group_field="mutation_operator",
        subgroup_type="operator",
        bootstrap_resamples=200,
        bootstrap_seed=1,
    )
    complete = next(
        row
        for row in rows
        if row.metric == "complete_repair_rate" and row.partition == "detectable_only"
    )
    assert complete.point_estimate == 0.5
    assert complete.ci_method == "case_bootstrap"


def test_build_multiseed_variance_rows_includes_all_tools() -> None:
    enriched = [
        {
            "case_id": "a",
            "tool_id": tool_id,
            "mutation_operator": "guard_flip",
            "complexity_tier": "small",
            "complete_repair": True,
            "effective_repair": True,
            "oracle_detected": True,
        }
        for tool_id in (
            "baseline_missing_transition",
            "baseline_wrong_target",
            "baseline_random",
        )
    ]
    rows = build_multiseed_variance_rows(enriched, None, seed_count=1)
    tool_ids = {row.tool_id for row in rows if row.subgroup_type == "operator"}
    assert "baseline_missing_transition" in tool_ids
    assert "baseline_wrong_target" in tool_ids
    assert "baseline_random" not in tool_ids
