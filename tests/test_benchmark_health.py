"""Tests for benchmark health scorecard."""

from __future__ import annotations

import json
from pathlib import Path

from fsmrepairbench.benchmark_health import compute_benchmark_health, write_benchmark_health_exports


def _write_taxonomy_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "summary.csv").write_text(
        "\n".join(
            [
                "metric,value",
                "case_count,100",
                "mean_dimension_coverage_ratio,0.55",
                "mutation_operators_present,2",
                "mutation_operators_total,3",
                "mutation_operator_coverage_ratio,0.667",
                "complexity_tiers_present,2",
                "complexity_tier_coverage_ratio,1.0",
                "fsm_families_present,1",
                "unique_taxonomy_combinations,10",
                "pairwise_mean_coverage_ratio,0.3",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "coverage_by_mutation_operator.csv").write_text(
        "\n".join(
            [
                "group_key,group_value,case_count,cohort_fraction,distinct_subgroups,subgroup_coverage_ratio,present_in_cohort",
                "mutation_operator,op_a,50,0.5,1,1.0,True",
                "mutation_operator,op_b,50,0.5,1,1.0,True",
                "mutation_operator,op_c,0,0.0,0,0.0,False",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (path / "coverage_by_complexity_tier.csv").write_text(
        "\n".join(
            [
                "group_key,group_value,case_count,cohort_fraction,distinct_subgroups,subgroup_coverage_ratio",
                "complexity_tier,small,50,0.5,2,1.0",
                "complexity_tier,large,50,0.5,2,1.0",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def test_compute_benchmark_health(tmp_path: Path) -> None:
    taxonomy = tmp_path / "taxonomy"
    _write_taxonomy_dir(taxonomy)
    v02 = tmp_path / "v02.csv"
    v02.write_text(
        "metric,value\noverall_detection_rate,0.5\n",
        encoding="utf-8",
    )
    loc = tmp_path / "loc.csv"
    loc.write_text(
        "\n".join(
            [
                "partition,metric,value,denominator,numerator",
                "all_detectable,localized_cases,50,100,50",
                "transition_localizable_gt,localized_cases,40,100,40",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    coupling = tmp_path / "coupling.csv"
    coupling.write_text(
        "metric,value\nexperiment,test\ncohort_size,25\nfirst_order_detection_rate,0.5\n",
        encoding="utf-8",
    )
    report = compute_benchmark_health(
        taxonomy_summary_path=taxonomy / "summary.csv",
        operator_coverage_path=taxonomy / "coverage_by_mutation_operator.csv",
        tier_coverage_path=taxonomy / "coverage_by_complexity_tier.csv",
        v02_summary_path=v02,
        localization_metrics_path=loc,
        coupling_summary_path=coupling,
        cohort_size=100,
    )
    assert 0.0 <= report["composite_health_score"] <= 1.0
    assert len(report["pillars"]) == 6
    assert report["recommendations_v0_3_plus"]


def test_write_benchmark_health_exports(tmp_path: Path) -> None:
    taxonomy = tmp_path / "taxonomy"
    _write_taxonomy_dir(taxonomy)
    v02 = tmp_path / "v02.csv"
    v02.write_text("metric,value\noverall_detection_rate,0.5\n", encoding="utf-8")
    loc = tmp_path / "loc.csv"
    loc.write_text(
        "\n".join(
            [
                "partition,metric,value,denominator,numerator",
                "all_detectable,localized_cases,50,100,50",
                "transition_localizable_gt,localized_cases,40,100,40",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    coupling = tmp_path / "coupling.csv"
    coupling.write_text("metric,value\ncohort_size,25\n", encoding="utf-8")
    out = tmp_path / "out"
    result = write_benchmark_health_exports(
        taxonomy_dir=taxonomy,
        v02_summary_path=v02,
        localization_metrics_path=loc,
        coupling_summary_path=coupling,
        out_dir=out,
        paper_export_dir=None,
    )
    assert result.json_path.is_file()
    assert result.tex_path.is_file()
    assert result.figure_path.is_file()
    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert "composite_health_score" in payload
