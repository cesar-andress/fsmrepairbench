"""Tests for benchmark utility analysis."""

from __future__ import annotations

import json
from pathlib import Path

from fsmrepairbench.benchmark_utility import (
    cohens_h,
    compute_benchmark_utility,
    mcnemar_exact_p_value,
    write_benchmark_utility_exports,
)


def test_cohens_h_is_signed_and_bounded() -> None:
    assert cohens_h(0.8, 0.2) > 0.0
    assert cohens_h(0.2, 0.8) < 0.0
    assert abs(cohens_h(0.5, 0.5)) < 1e-9


def test_mcnemar_exact_p_value_handles_ties() -> None:
    assert mcnemar_exact_p_value(10, 8, 0, 0) == 1.0
    assert mcnemar_exact_p_value(10, 2, 8, 0) < 0.05


def test_compute_benchmark_utility_detects_distinguishable_tools() -> None:
    rows = []
    for case_index in range(20):
        case_id = f"case_{case_index:03d}"
        rows.extend(
            [
                {
                    "case_id": case_id,
                    "tool_id": "baseline_missing_transition",
                    "mutation_operator": "guard_flip",
                    "complete_repair": case_index < 15,
                    "effective_repair": case_index < 16,
                    "oracle_detected": True,
                },
                {
                    "case_id": case_id,
                    "tool_id": "baseline_wrong_target",
                    "mutation_operator": "guard_flip",
                    "complete_repair": case_index < 5,
                    "effective_repair": case_index < 6,
                    "oracle_detected": True,
                },
                {
                    "case_id": case_id,
                    "tool_id": "baseline_random",
                    "mutation_operator": "guard_flip",
                    "complete_repair": False,
                    "effective_repair": case_index < 1,
                    "oracle_detected": True,
                },
            ]
        )
    summary = compute_benchmark_utility(rows)
    complete_detectable = [
        row
        for row in summary["pairwise_rows"]
        if row["metric"] == "complete_repair" and row["partition"] == "detectable_only"
    ]
    assert len(complete_detectable) == 3
    missing_vs_random = next(
        row
        for row in complete_detectable
        if row["tool_a"] == "baseline_missing_transition" and row["tool_b"] == "baseline_random"
    )
    assert missing_vs_random["statistically_distinguishable"]
    assert summary["random_pair_distinguishability_probability"]["complete_repair"]["detectable_only"] >= 2 / 3
    assert summary["benchmark_discrimination_index"]["complete_repair"]["detectable_only"] > 0.0


def test_write_benchmark_utility_exports(tmp_path: Path) -> None:
    per_case = tmp_path / "per_case_results.csv"
    per_case.write_text(
        "\n".join(
            [
                "case_id,tool_id,mutation_operator,complete_repair,effective_repair,oracle_detected",
                "case_000001,baseline_missing_transition,guard_flip,True,True,True",
                "case_000001,baseline_wrong_target,guard_flip,False,False,True",
                "case_000001,baseline_random,guard_flip,False,False,True",
                "case_000002,baseline_missing_transition,guard_flip,True,True,True",
                "case_000002,baseline_wrong_target,guard_flip,True,True,True",
                "case_000002,baseline_random,guard_flip,False,False,True",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "out"
    result = write_benchmark_utility_exports(per_case, out_dir)
    assert result.csv_path.is_file()
    assert result.json_path.is_file()
    assert result.tex_path.is_file()
    assert result.figure_path.is_file()
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert "benchmark_discrimination_index" in payload
    assert "benchmark_utility_index" in payload
