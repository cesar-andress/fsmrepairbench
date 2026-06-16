"""Tests for external open-weight LLM repair baseline helpers."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from fsmrepairbench.open_weight_llm_baseline import (
    OPENWEIGHT_TOOL_ID,
    aggregate_c1_subset_metrics,
    aggregate_partition_metrics,
    load_protocol_safe_case,
    outcome_to_row_dict,
    run_open_weight_llm_repair,
)
from fsmrepairbench.repair_engines.baselines import OracleGuidedMissingTransitionRepair
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_protocol_safe_case_reads_only_faulty_and_oracle(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    faulty = reference.model_copy(
        update={
            "transitions": [
                transition for transition in reference.transitions if transition.id != "t2"
            ]
        }
    )
    case_dir = tmp_path / "case_test"
    case_dir.mkdir()
    (case_dir / "faulty_fsm.json").write_text(faulty.model_dump_json(indent=2), encoding="utf-8")
    (case_dir / "oracle_suite.json").write_text(oracle.model_dump_json(indent=2), encoding="utf-8")
    (case_dir / "reference_fsm.json").write_text(reference.model_dump_json(indent=2), encoding="utf-8")
    (case_dir / "bug_metadata.json").write_text(
        '{"mutation_operator": "missing_transition"}',
        encoding="utf-8",
    )

    loaded_faulty, loaded_oracle = load_protocol_safe_case(case_dir)
    assert loaded_faulty.id == faulty.id
    assert loaded_oracle.id == oracle.id


def test_run_open_weight_llm_repair_single_attempt_with_mock() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    faulty = reference.model_copy(
        update={
            "transitions": [
                transition for transition in reference.transitions if transition.id != "t2"
            ]
        }
    )
    case_dir = Path("/tmp/unused")
    patch_obj = OracleGuidedMissingTransitionRepair().propose_patch(faulty, oracle)

    with patch(
        "fsmrepairbench.open_weight_llm_baseline.run_llm_repair_with_client",
    ) as mock_repair:
        from fsmrepairbench.llm.repair import run_llm_repair_with_client

        mock_repair.side_effect = lambda *args, **kwargs: run_llm_repair_with_client(
            *args,
            **kwargs,
            generate_fn=lambda *_a, **_k: patch_obj.model_dump_json(),
        )
        with patch(
            "fsmrepairbench.open_weight_llm_baseline.load_protocol_safe_case",
            return_value=(faulty, oracle),
        ), patch(
            "fsmrepairbench.open_weight_llm_baseline.case_is_oracle_detectable",
            return_value=True,
        ):
            outcome = run_open_weight_llm_repair(case_dir, max_iterations=1, temperature=0.0)

    assert outcome.complete_repair is True
    assert outcome.effective_repair is True
    assert outcome.iterations_completed == 1
    row = outcome_to_row_dict(outcome)
    assert row["tool_id"] == OPENWEIGHT_TOOL_ID


def test_aggregate_partition_metrics_handles_csv_booleans() -> None:
    rows = [
        {"complete_repair": "True", "effective_repair": "False", "delta_bpr": "0.1"},
        {"complete_repair": "false", "effective_repair": "true", "delta_bpr": "0.2"},
    ]
    metrics = aggregate_partition_metrics(rows)
    assert metrics["n_cases"] == 2
    assert metrics["complete_repair_rate"] == pytest.approx(0.5)
    assert metrics["effective_repair_rate"] == pytest.approx(0.5)
    assert metrics["mean_delta_bpr"] == pytest.approx(0.15)


def test_aggregate_c1_subset_metrics_filters_cohort(tmp_path: Path) -> None:
    per_case = tmp_path / "per_case_results.csv"
    per_case.write_text(
        "\n".join(
            [
                "case_id,tool_id,oracle_detected,complete_repair,effective_repair,delta_bpr",
                "case_000001,baseline_missing_transition,True,True,True,0.1",
                "case_000002,baseline_missing_transition,True,False,False,0.0",
                "case_000003,baseline_missing_transition,False,True,True,0.5",
                "case_000001,baseline_random,True,False,False,-0.1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    metrics = aggregate_c1_subset_metrics(
        per_case,
        cohort_case_ids={"case_000001", "case_000002"},
    )
    missing = next(row for row in metrics if row["tool_id"] == "baseline_missing_transition")
    assert missing["n_cases"] == 2
    assert missing["complete_repair_rate"] == pytest.approx(0.5)
