"""Tests for benchmark utility calibration exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fsmrepairbench.benchmark_utility_calibration import (
    MDE_CSV_COLUMNS,
    OPERATOR_MIX_BOOTSTRAP_SEED,
    OPERATOR_MIX_SENSITIVITY_COLUMNS,
    compute_minimum_detectable_effects,
    compute_operator_mix_sensitivity,
    minimum_detectable_effect_pp,
    operator_mix_sensitivity_to_csv_rows,
    write_benchmark_utility_calibration_exports,
)
from fsmrepairbench.statistics import BOOTSTRAP_SEED


def _synthetic_rows() -> list[dict]:
    rows: list[dict] = []
    operators = ("missing_transition", "wrong_target", "guard_flip")
    for case_index in range(30):
        operator = operators[case_index % len(operators)]
        detectable = case_index % 5 != 0
        case_id = f"case_{case_index:03d}"
        rows.extend(
            [
                {
                    "case_id": case_id,
                    "tool_id": "baseline_missing_transition",
                    "mutation_operator": operator,
                    "complete_repair": detectable and case_index % 3 != 0,
                    "effective_repair": detectable and case_index % 2 == 0,
                    "oracle_detected": detectable,
                },
                {
                    "case_id": case_id,
                    "tool_id": "baseline_wrong_target",
                    "mutation_operator": operator,
                    "complete_repair": detectable and case_index % 4 == 0,
                    "effective_repair": detectable and case_index % 3 == 0,
                    "oracle_detected": detectable,
                },
                {
                    "case_id": case_id,
                    "tool_id": "baseline_random",
                    "mutation_operator": operator,
                    "complete_repair": False,
                    "effective_repair": detectable and case_index % 7 == 0,
                    "oracle_detected": detectable,
                },
            ]
        )
    return rows


def test_operator_mix_bootstrap_is_deterministic() -> None:
    rows = _synthetic_rows()
    first = compute_operator_mix_sensitivity(rows, bootstrap_seed=OPERATOR_MIX_BOOTSTRAP_SEED)
    second = compute_operator_mix_sensitivity(rows, bootstrap_seed=OPERATOR_MIX_BOOTSTRAP_SEED)
    assert first["flip_probabilities"] == second["flip_probabilities"]
    assert first["kendall_tau_distribution"]["mean"] == second["kendall_tau_distribution"]["mean"]


def test_operator_mix_sensitivity_csv_schema() -> None:
    summary = compute_operator_mix_sensitivity(_synthetic_rows(), bootstrap_seed=44)
    csv_rows = operator_mix_sensitivity_to_csv_rows(summary)
    assert csv_rows
    assert {row["record_type"] for row in csv_rows} >= {
        "current_ranking",
        "pairwise_flip_probability",
        "kendall_tau_distribution",
    }
    flip_rows = [row for row in csv_rows if row["record_type"] == "pairwise_flip_probability"]
    assert len(flip_rows) == 3
    for row in flip_rows:
        assert 0.0 <= float(row["flip_probability"]) <= 1.0
        assert set(row) == set(OPERATOR_MIX_SENSITIVITY_COLUMNS)


def test_minimum_detectable_effect_sanity_checks() -> None:
    assert minimum_detectable_effect_pp(n_cases=495, pooled_rate=0.5) == pytest.approx(8.904, abs=0.01)
    assert minimum_detectable_effect_pp(n_cases=59, pooled_rate=0.5) == pytest.approx(25.807, abs=0.05)
    assert minimum_detectable_effect_pp(n_cases=495, pooled_rate=0.5) < minimum_detectable_effect_pp(
        n_cases=59,
        pooled_rate=0.5,
    )
    mde_rows = compute_minimum_detectable_effects(_synthetic_rows())
    assert {row["scope"] for row in mde_rows} == {
        "all_detectable",
        "all_detectable_pooled_0.5",
        "per_operator_cell",
    }
    assert all(set(row) == set(MDE_CSV_COLUMNS) for row in mde_rows)


PAPER_C1 = Path(__file__).resolve().parents[2] / "paper1" / "results" / "baseline_repair_C1" / "per_case_results.csv"


@pytest.mark.skipif(not PAPER_C1.is_file(), reason="frozen C1 export missing")
def test_frozen_operator_mix_ranking_is_stable() -> None:
    from fsmrepairbench.benchmark_utility import _load_per_case_rows

    rows = _load_per_case_rows(PAPER_C1)
    summary = compute_operator_mix_sensitivity(rows, bootstrap_seed=BOOTSTRAP_SEED)
    assert summary["baseline_ranks"]["baseline_missing_transition"] == 1
    assert summary["baseline_ranks"]["baseline_wrong_target"] == 2
    assert summary["baseline_ranks"]["baseline_random"] == 3
    assert summary["baseline_kendall_tau"] == pytest.approx(0.111111, abs=0.01)
    assert summary["flip_probabilities"][("baseline_missing_transition", "baseline_random")] == 0.0


def test_write_benchmark_utility_calibration_exports(tmp_path: Path) -> None:
    per_case = tmp_path / "per_case_results.csv"
    per_case.write_text(
        "\n".join(
            [
                "case_id,tool_id,mutation_operator,complete_repair,effective_repair,oracle_detected",
                "case_000001,baseline_missing_transition,missing_transition,True,True,True",
                "case_000001,baseline_wrong_target,missing_transition,False,False,True",
                "case_000001,baseline_random,missing_transition,False,False,True",
                "case_000002,baseline_missing_transition,wrong_target,False,False,True",
                "case_000002,baseline_wrong_target,wrong_target,True,True,True",
                "case_000002,baseline_random,wrong_target,False,False,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    result = write_benchmark_utility_calibration_exports(
        per_case,
        tmp_path / "out",
        paper_export_dir=tmp_path / "paper",
    )
    assert result.operator_mix_csv_path.is_file()
    assert result.operator_mix_tex_path.is_file()
    assert result.mde_tex_path.is_file()
    with result.operator_mix_csv_path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(OPERATOR_MIX_SENSITIVITY_COLUMNS)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["operator_mix_sensitivity"]["bootstrap_seed"] == OPERATOR_MIX_BOOTSTRAP_SEED
