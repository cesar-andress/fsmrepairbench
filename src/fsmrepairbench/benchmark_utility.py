"""Benchmark utility and discriminative-power analysis for repair campaigns."""

from __future__ import annotations

import csv
import json
import math
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from fsmrepairbench.statistics import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED, bootstrap_ci

C1_TOOL_IDS: tuple[str, ...] = (
    "baseline_missing_transition",
    "baseline_wrong_target",
    "baseline_random",
    "baseline_search_bpr",
    "baseline_oracle_composite",
    "baseline_llm_template",
)

C1_DETERMINISTIC_TOOL_IDS: tuple[str, ...] = (
    "baseline_missing_transition",
    "baseline_wrong_target",
    "baseline_oracle_composite",
    "baseline_llm_template",
)

C1_SEEDED_TOOL_IDS: tuple[str, ...] = (
    "baseline_random",
    "baseline_search_bpr",
)

TOOL_LABELS: dict[str, str] = {
    "baseline_missing_transition": "missing-transition",
    "baseline_wrong_target": "wrong-target",
    "baseline_random": "random",
    "baseline_search_bpr": "search-bpr",
    "baseline_oracle_composite": "oracle-composite",
    "baseline_llm_template": "llm-template",
}

METRIC_FIELDS: tuple[tuple[str, str], ...] = (
    ("complete_repair", "complete_repair"),
    ("effective_repair", "effective_repair"),
)

PARTITIONS: tuple[tuple[str, str | None], ...] = (
    ("detectable_only", "oracle_detected"),
    ("cohort_wide", None),
)

BENCHMARK_UTILITY_CSV_COLUMNS: tuple[str, ...] = (
    "metric",
    "partition",
    "tool_a",
    "tool_b",
    "rate_a",
    "rate_b",
    "cohens_h",
    "abs_cohens_h",
    "mcnemar_statistic",
    "mcnemar_p_value",
    "statistically_distinguishable",
    "case_disagreement_rate",
    "n_cases",
    "n_success_a",
    "n_success_b",
)


@dataclass(frozen=True)
class BenchmarkUtilityExportResult:
    """Paths written by :func:`write_benchmark_utility_exports`."""

    csv_path: Path
    json_path: Path
    tex_path: Path
    figure_path: Path
    paper_csv_path: Path | None = None
    paper_json_path: Path | None = None
    paper_tex_path: Path | None = None
    paper_figure_path: Path | None = None


def cohens_h(proportion_a: float, proportion_b: float) -> float:
    """Cohen's *h* for two independent proportions (arcsine transform)."""
    p_a = min(max(proportion_a, 0.0), 1.0)
    p_b = min(max(proportion_b, 0.0), 1.0)
    return 2.0 * (math.asin(math.sqrt(p_a)) - math.asin(math.sqrt(p_b)))


def mcnemar_exact_p_value(success_a: int, success_b: int, discordant_ab: int, discordant_ba: int) -> float:
    """Two-sided exact McNemar *p*-value for paired binary outcomes."""
    discordant = discordant_ab + discordant_ba
    if discordant == 0:
        return 1.0
    k = min(discordant_ab, discordant_ba)
    probability = 0.0
    for index in range(k + 1):
        probability += math.comb(discordant, index) * (0.5**discordant)
    return min(1.0, 2.0 * probability)


def _kendall_tau(rank_a: dict[str, int], rank_b: dict[str, int]) -> float:
    shared = sorted(set(rank_a) & set(rank_b))
    if len(shared) < 2:
        return 1.0
    concordant = 0
    discordant = 0
    for left, right in combinations(shared, 2):
        delta_a = rank_a[left] - rank_a[right]
        delta_b = rank_b[left] - rank_b[right]
        if delta_a == 0 or delta_b == 0:
            continue
        if delta_a * delta_b > 0:
            concordant += 1
        elif delta_a * delta_b < 0:
            discordant += 1
    denom = concordant + discordant
    if denom == 0:
        return 1.0
    return (concordant - discordant) / denom


def _operator_ranks(
    per_case_rows: Sequence[dict[str, Any]],
    *,
    tool_id: str,
    metric_field: str,
    detectable_only: bool,
) -> dict[str, int]:
    grouped: dict[str, list[bool]] = defaultdict(list)
    for row in per_case_rows:
        if row["tool_id"] != tool_id:
            continue
        if detectable_only and not row["oracle_detected"]:
            continue
        grouped[str(row["mutation_operator"])].append(bool(row[metric_field]))
    eligible: dict[str, float] = {}
    for operator, values in grouped.items():
        if not values:
            continue
        eligible[operator] = sum(values) / len(values)
    ordered = sorted(eligible.items(), key=lambda item: (item[1], item[0]))
    return {operator: index + 1 for index, (operator, _rate) in enumerate(ordered)}


def _load_per_case_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(path.open(encoding="utf-8")):
        rows.append(
            {
                "case_id": row["case_id"],
                "tool_id": row["tool_id"],
                "mutation_operator": row["mutation_operator"],
                "complete_repair": row["complete_repair"].strip().lower() == "true",
                "effective_repair": row["effective_repair"].strip().lower() == "true",
                "oracle_detected": row["oracle_detected"].strip().lower() == "true",
            }
        )
    return rows


def _paired_outcomes(
    per_case_rows: Sequence[dict[str, Any]],
    *,
    tool_a: str,
    tool_b: str,
    metric_field: str,
    detectable_only: bool,
) -> tuple[list[bool], list[bool]]:
    by_case: dict[str, dict[str, bool]] = defaultdict(dict)
    for row in per_case_rows:
        if row["tool_id"] not in {tool_a, tool_b}:
            continue
        if detectable_only and not row["oracle_detected"]:
            continue
        by_case[str(row["case_id"])][str(row["tool_id"])] = bool(row[metric_field])
    outcomes_a: list[bool] = []
    outcomes_b: list[bool] = []
    for tool_map in by_case.values():
        if tool_a in tool_map and tool_b in tool_map:
            outcomes_a.append(tool_map[tool_a])
            outcomes_b.append(tool_map[tool_b])
    return outcomes_a, outcomes_b


def _rate(values: Sequence[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0.0


def compute_benchmark_utility(
    per_case_rows: Sequence[dict[str, Any]],
    *,
    tool_ids: Sequence[str] = C1_TOOL_IDS,
    alpha: float = 0.05,
) -> dict[str, Any]:
    """Compute benchmark utility metrics from paired per-case repair outcomes."""
    pairwise_rows: list[dict[str, Any]] = []
    distinguishable_by_metric: dict[str, dict[str, list[bool]]] = defaultdict(lambda: defaultdict(list))
    bdi_by_metric: dict[str, dict[str, float]] = defaultdict(dict)
    rank_stability: dict[str, dict[str, Any]] = {}

    for metric_name, metric_field in METRIC_FIELDS:
        for partition_name, partition_filter in PARTITIONS:
            detectable_only = partition_filter == "oracle_detected"
            for tool_a, tool_b in combinations(tool_ids, 2):
                outcomes_a, outcomes_b = _paired_outcomes(
                    per_case_rows,
                    tool_a=tool_a,
                    tool_b=tool_b,
                    metric_field=metric_field,
                    detectable_only=detectable_only,
                )
                rate_a = _rate(outcomes_a)
                rate_b = _rate(outcomes_b)
                discordant_ab = sum(1 for left, right in zip(outcomes_a, outcomes_b, strict=True) if left and not right)
                discordant_ba = sum(1 for left, right in zip(outcomes_a, outcomes_b, strict=True) if not left and right)
                p_value = mcnemar_exact_p_value(
                    sum(outcomes_a),
                    sum(outcomes_b),
                    discordant_ab,
                    discordant_ba,
                )
                disagreement = discordant_ab + discordant_ba
                n_cases = len(outcomes_a)
                distinguishable = p_value < alpha and n_cases > 0
                effect = cohens_h(rate_a, rate_b)
                pairwise_rows.append(
                    {
                        "metric": metric_name,
                        "partition": partition_name,
                        "tool_a": tool_a,
                        "tool_b": tool_b,
                        "rate_a": round(rate_a, 6),
                        "rate_b": round(rate_b, 6),
                        "cohens_h": round(effect, 6),
                        "abs_cohens_h": round(abs(effect), 6),
                        "mcnemar_statistic": discordant_ab + discordant_ba,
                        "mcnemar_p_value": round(p_value, 8),
                        "statistically_distinguishable": distinguishable,
                        "case_disagreement_rate": round(disagreement / n_cases, 6) if n_cases else 0.0,
                        "n_cases": n_cases,
                        "n_success_a": sum(outcomes_a),
                        "n_success_b": sum(outcomes_b),
                    }
                )
                distinguishable_by_metric[metric_name][partition_name].append(distinguishable)

            # Benchmark discrimination index: mean pairwise per-case disagreement.
            case_ids = sorted({str(row["case_id"]) for row in per_case_rows})
            disagreements: list[float] = []
            for case_id in case_ids:
                tool_outcomes = [
                    bool(row[metric_field])
                    for row in per_case_rows
                    if row["case_id"] == case_id
                    and row["tool_id"] in tool_ids
                    and (not detectable_only or row["oracle_detected"])
                ]
                if len(tool_outcomes) < 2:
                    continue
                unique = len(set(tool_outcomes))
                disagreements.append(1.0 if unique > 1 else 0.0)
            bdi_by_metric[metric_name][partition_name] = (
                statistics.mean(disagreements) if disagreements else 0.0
            )

            ranks = {
                tool_id: _operator_ranks(
                    per_case_rows,
                    tool_id=tool_id,
                    metric_field=metric_field,
                    detectable_only=detectable_only,
                )
                for tool_id in tool_ids
            }
            taus: list[float] = []
            for tool_a, tool_b in combinations(tool_ids, 2):
                taus.append(_kendall_tau(ranks[tool_a], ranks[tool_b]))
            rank_stability[f"{metric_name}_{partition_name}"] = {
                "kendall_tau_mean": statistics.mean(taus) if taus else 1.0,
                "pairwise_kendall_tau": {
                    f"{TOOL_LABELS[a]} vs {TOOL_LABELS[b]}": round(tau, 6)
                    for (a, b), tau in zip(combinations(tool_ids, 2), taus, strict=True)
                },
                "shared_operators": sorted(set.intersection(*(set(ranks[t]) for t in tool_ids))),
            }

    random_pair_probability: dict[str, dict[str, float]] = {}
    for metric_name, partitions in distinguishable_by_metric.items():
        random_pair_probability[metric_name] = {}
        for partition_name, flags in partitions.items():
            random_pair_probability[metric_name][partition_name] = (
                sum(1 for flag in flags if flag) / len(flags) if flags else 0.0
            )

    bootstrap_rate_gaps: dict[str, Any] = {}
    for metric_name, metric_field in METRIC_FIELDS:
        for partition_name, partition_filter in PARTITIONS:
            detectable_only = partition_filter == "oracle_detected"
            gaps: list[float] = []
            for tool_a, tool_b in combinations(tool_ids, 2):
                outcomes_a, outcomes_b = _paired_outcomes(
                    per_case_rows,
                    tool_a=tool_a,
                    tool_b=tool_b,
                    metric_field=metric_field,
                    detectable_only=detectable_only,
                )
                diffs = [
                    float(left) - float(right)
                    for left, right in zip(outcomes_a, outcomes_b, strict=True)
                ]
                if not diffs:
                    continue
                low, high = bootstrap_ci(
                    diffs,
                    n_resamples=BOOTSTRAP_RESAMPLES,
                    rng=__import__("random").Random(BOOTSTRAP_SEED),
                )
                gaps.append(
                    {
                        "tool_a": tool_a,
                        "tool_b": tool_b,
                        "mean_rate_gap": round(statistics.mean(diffs), 6),
                        "bootstrap_ci95_low": round(low, 6),
                        "bootstrap_ci95_high": round(high, 6),
                        "bootstrap_distinguishable": low > 0.0 or high < 0.0,
                    }
                )
            bootstrap_rate_gaps[f"{metric_name}_{partition_name}"] = gaps

    overall_bdi_detectable_complete = bdi_by_metric["complete_repair"]["detectable_only"]
    mean_abs_h_detectable_complete = statistics.mean(
        row["abs_cohens_h"]
        for row in pairwise_rows
        if row["metric"] == "complete_repair" and row["partition"] == "detectable_only"
    )
    utility_index = round(
        overall_bdi_detectable_complete * mean_abs_h_detectable_complete,
        6,
    )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "tools": list(tool_ids),
        "tool_labels": {tool_id: TOOL_LABELS.get(tool_id, tool_id) for tool_id in tool_ids},
        "pairwise_rows": pairwise_rows,
        "rank_stability": rank_stability,
        "random_pair_distinguishability_probability": random_pair_probability,
        "benchmark_discrimination_index": {
            metric: {partition: round(value, 6) for partition, value in partitions.items()}
            for metric, partitions in bdi_by_metric.items()
        },
        "benchmark_utility_index": {
            "detectable_only_complete_repair": utility_index,
            "definition": (
                "mean pairwise case disagreement on detectable-only complete repair "
                "multiplied by mean |Cohen's h| across tool pairs"
            ),
        },
        "bootstrap_rate_gaps": bootstrap_rate_gaps,
        "alpha": alpha,
        "bootstrap_seed": BOOTSTRAP_SEED,
    }


def _tex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
    )


def _write_benchmark_utility_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BENCHMARK_UTILITY_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in BENCHMARK_UTILITY_CSV_COLUMNS})


def _write_benchmark_utility_figure(path: Path, summary: dict[str, Any]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    metrics = ["complete_repair", "effective_repair"]
    partitions = ["detectable_only", "cohort_wide"]
    tool_pairs = [
        ("missing-transition", "wrong-target"),
        ("missing-transition", "random"),
        ("wrong-target", "random"),
    ]
    pair_keys = {
        ("baseline_missing_transition", "baseline_wrong_target"): (0, 0),
        ("baseline_missing_transition", "baseline_random"): (0, 1),
        ("baseline_wrong_target", "baseline_random"): (0, 2),
    }
    data = np.zeros((len(metrics), len(partitions), len(tool_pairs)))
    for row in summary["pairwise_rows"]:
        pair_key = (row["tool_a"], row["tool_b"])
        if pair_key not in pair_keys:
            continue
        metric_index = metrics.index(row["metric"])
        partition_index = partitions.index(row["partition"])
        pair_index = pair_keys[pair_key]
        data[metric_index, partition_index, pair_index[1]] = row["abs_cohens_h"]

    fig, axes = plt.subplots(1, 2, figsize=(10, 4.5), sharey=True)
    titles = ["Detectable-only ($n=495$)", "Cohort-wide ($n=1{,}000$)"]
    ylabels = ["Complete repair", "Effective repair"]
    for axis_index, (axis, title) in enumerate(zip(axes, titles, strict=True)):
        matrix = data[:, axis_index, :]
        im = axis.imshow(matrix, cmap="YlOrRd", vmin=0.0, vmax=max(1.5, float(matrix.max()) or 1.0))
        axis.set_title(title)
        axis.set_xticks(range(len(tool_pairs)))
        axis.set_xticklabels([f"{a}\nvs\n{b}" for a, b in tool_pairs], fontsize=8)
        axis.set_yticks(range(len(metrics)))
        axis.set_yticklabels(ylabels)
        for row_index in range(matrix.shape[0]):
            for col_index in range(matrix.shape[1]):
                axis.text(
                    col_index,
                    row_index,
                    f"{matrix[row_index, col_index]:.2f}",
                    ha="center",
                    va="center",
                    color="black",
                    fontsize=9,
                )
    fig.colorbar(im, ax=axes.ravel().tolist(), shrink=0.85, label="|Cohen's h|")
    bdi = summary["benchmark_discrimination_index"]["complete_repair"]["detectable_only"]
    utility = summary["benchmark_utility_index"]["detectable_only_complete_repair"]
    fig.suptitle(
        "C1 benchmark utility: |Cohen's h| by metric and partition "
        f"(BDI={bdi:.3f}, utility index={utility:.3f})",
        fontsize=11,
    )
    fig.subplots_adjust(top=0.82, wspace=0.25)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _write_benchmark_utility_tex(path: Path, summary: dict[str, Any]) -> None:
    rows: list[list[str]] = []
    for row in summary["pairwise_rows"]:
        rows.append(
            [
                _tex_escape(row["metric"].replace("_", "-")),
                _tex_escape(row["partition"].replace("_", "-")),
                _tex_escape(TOOL_LABELS[row["tool_a"]]),
                _tex_escape(TOOL_LABELS[row["tool_b"]]),
                f"{row['rate_a'] * 100:.1f}\\%",
                f"{row['rate_b'] * 100:.1f}\\%",
                f"{row['cohens_h']:.3f}",
                f"{row['case_disagreement_rate'] * 100:.1f}\\%",
                "yes" if row["statistically_distinguishable"] else "no",
            ]
        )
    body_lines = [
        "\\begin{tabular}{@{}llllrrrrl@{}}",
        "\\toprule",
        "Metric & Partition & Tool A & Tool B & Rate A & Rate B & Cohen's $h$ & Disagree & Distinct? \\\\",
        "\\midrule",
    ]
    for row in rows:
        body_lines.append(" & ".join(row) + " \\\\")
    body_lines.extend(["\\bottomrule", "\\end{tabular}"])
    bdi = summary["benchmark_discrimination_index"]["complete_repair"]["detectable_only"]
    utility = summary["benchmark_utility_index"]["detectable_only_complete_repair"]
    rank_tau = summary["rank_stability"]["complete_repair_detectable_only"]["kendall_tau_mean"]
    p_dist = summary["random_pair_distinguishability_probability"]["complete_repair"]["detectable_only"]
    tex = (
        "\\begin{table}[t]\n"
        "\\caption{Benchmark utility analysis for C1 engine-specific baselines on the "
        "1{,}000-case \\texttt{plain\\_fsm}/shallow-oracle cohort. "
        "Pairwise Cohen's $h$ and McNemar tests use paired per-case outcomes; "
        f"detectable-only complete-repair BDI~$={bdi:.3f}$, utility index~$={utility:.3f}$, "
        f"operator rank stability (mean Kendall $\\tau$)~=~{rank_tau:.3f}, "
        f"random-pair distinguishability~=~{p_dist * 100:.0f}\\%. "
        "Takeaway: the benchmark separates the three shipped engines on detectable-only "
        "complete and effective repair; cohort-wide partitions inherit oracle-saturation confounds.}\n"
        "\\label{tab:benchmark-utility}\n"
        + "\n".join(body_lines)
        + "\n\\end{table}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")


def write_benchmark_utility_exports(
    per_case_path: Path,
    out_dir: Path,
    *,
    paper_export_dir: Path | None = None,
    tool_ids: Sequence[str] = C1_TOOL_IDS,
) -> BenchmarkUtilityExportResult:
    """Write benchmark utility CSV/JSON/LaTeX/PNG exports from C1 per-case results."""
    per_case_rows = _load_per_case_rows(per_case_path)
    summary = compute_benchmark_utility(per_case_rows, tool_ids=tool_ids)

    csv_path = out_dir / "benchmark_utility.csv"
    json_path = out_dir / "utility_summary.json"
    tex_path = out_dir / "tables" / "benchmark_utility.tex"
    figure_path = out_dir / "figures" / "benchmark_utility.png"

    _write_benchmark_utility_csv(csv_path, summary["pairwise_rows"])
    json_payload = {key: value for key, value in summary.items() if key != "pairwise_rows"}
    json_payload["pairwise_effect_sizes"] = summary["pairwise_rows"]
    json_path.write_text(json.dumps(json_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_benchmark_utility_tex(tex_path, summary)
    _write_benchmark_utility_figure(figure_path, summary)

    paper_csv_path = paper_json_path = paper_tex_path = paper_figure_path = None
    if paper_export_dir is not None and paper_export_dir.resolve() != out_dir.resolve():
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        paper_csv_path = paper_export_dir / csv_path.name
        paper_json_path = paper_export_dir / json_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_figure_path = paper_export_dir / "figures" / figure_path.name
        paper_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_json_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_tex_path.parent.mkdir(parents=True, exist_ok=True)
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_figure_path.parent.mkdir(parents=True, exist_ok=True)
        paper_figure_path.write_bytes(figure_path.read_bytes())

    return BenchmarkUtilityExportResult(
        csv_path=csv_path,
        json_path=json_path,
        tex_path=tex_path,
        figure_path=figure_path,
        paper_csv_path=paper_csv_path,
        paper_json_path=paper_json_path,
        paper_tex_path=paper_tex_path,
        paper_figure_path=paper_figure_path,
    )
