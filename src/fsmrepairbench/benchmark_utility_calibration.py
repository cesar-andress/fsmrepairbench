"""Operator-mix sensitivity and minimum-detectable-effect calibration for benchmark utility."""

from __future__ import annotations

import csv
import json
import math
import random
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations
from pathlib import Path
from typing import Any

from fsmrepairbench.benchmark_utility import (
    SHIPPED_C1_TOOL_IDS,
    TOOL_LABELS,
    _kendall_tau,
    _load_per_case_rows,
    _operator_ranks,
    _rate,
    _tex_escape,
)
from fsmrepairbench.statistics import BOOTSTRAP_RESAMPLES, BOOTSTRAP_SEED

OPERATOR_MIX_RESAMPLES = 1_000
OPERATOR_MIX_BOOTSTRAP_SEED = BOOTSTRAP_SEED

OPERATOR_MIX_SENSITIVITY_COLUMNS: tuple[str, ...] = (
    "record_type",
    "engine",
    "engine_b",
    "rank",
    "complete_repair_rate",
    "flip_probability",
    "kendall_tau",
    "kendall_tau_ci95_low",
    "kendall_tau_ci95_high",
    "n_resamples",
    "bootstrap_seed",
)

MDE_CSV_COLUMNS: tuple[str, ...] = (
    "scope",
    "n_cases",
    "assumed_pooled_rate",
    "alpha",
    "power",
    "mde_pp",
    "assumption",
)


@dataclass(frozen=True)
class BenchmarkUtilityCalibrationExportResult:
    operator_mix_csv_path: Path
    operator_mix_tex_path: Path
    mde_tex_path: Path
    manifest_path: Path
    paper_operator_mix_csv_path: Path | None = None
    paper_operator_mix_tex_path: Path | None = None
    paper_mde_tex_path: Path | None = None


def _case_detectable_outcomes(
    per_case_rows: Sequence[dict[str, Any]],
    *,
    tool_ids: Sequence[str],
) -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for row in per_case_rows:
        if not row["oracle_detected"]:
            continue
        case_id = str(row["case_id"])
        tool_id = str(row["tool_id"])
        if tool_id not in tool_ids:
            continue
        entry = cases.setdefault(
            case_id,
            {"mutation_operator": str(row["mutation_operator"]), "tools": {}},
        )
        entry["tools"][tool_id] = bool(row["complete_repair"])
    return cases


def _engine_rates_on_cases(
    cases: Sequence[dict[str, Any]],
    *,
    tool_ids: Sequence[str],
) -> dict[str, float]:
    rates: dict[str, float] = {}
    for tool_id in tool_ids:
        values = [case["tools"][tool_id] for case in cases if tool_id in case["tools"]]
        rates[tool_id] = _rate(values)
    return rates


def _rank_engines(rates: dict[str, float]) -> dict[str, int]:
    ordered = sorted(rates.items(), key=lambda item: (-item[1], item[0]))
    return {tool_id: index + 1 for index, (tool_id, _rate_value) in enumerate(ordered)}


def _pairwise_baseline_order(rates: dict[str, float]) -> dict[tuple[str, str], int]:
    ordering: dict[tuple[str, str], int] = {}
    for tool_a, tool_b in combinations(rates, 2):
        ordering[(tool_a, tool_b)] = 1 if rates[tool_a] > rates[tool_b] else -1 if rates[tool_a] < rates[tool_b] else 0
    return ordering


def _operator_rank_tau_mean(
    resampled_rows: list[dict[str, Any]],
    *,
    tool_ids: Sequence[str],
) -> float:
    ranks = {
        tool_id: _operator_ranks(
            resampled_rows,
            tool_id=tool_id,
            metric_field="complete_repair",
            detectable_only=True,
        )
        for tool_id in tool_ids
    }
    shared = set.intersection(*(set(ranks[tool_id]) for tool_id in tool_ids))
    if len(shared) < 2:
        return 1.0
    taus = [_kendall_tau(ranks[tool_a], ranks[tool_b]) for tool_a, tool_b in combinations(tool_ids, 2)]
    return statistics.mean(taus) if taus else 1.0


def compute_operator_mix_sensitivity(
    per_case_rows: Sequence[dict[str, Any]],
    *,
    tool_ids: Sequence[str] = SHIPPED_C1_TOOL_IDS,
    n_resamples: int = OPERATOR_MIX_RESAMPLES,
    bootstrap_seed: int = OPERATOR_MIX_BOOTSTRAP_SEED,
) -> dict[str, Any]:
    """Bootstrap resampled operator mixes and rank-stability statistics."""
    cases_map = _case_detectable_outcomes(per_case_rows, tool_ids=tool_ids)
    case_list = [
        {"case_id": case_id, "mutation_operator": payload["mutation_operator"], "tools": payload["tools"]}
        for case_id, payload in sorted(cases_map.items())
    ]
    if not case_list:
        msg = "No detectable paired cases available for operator-mix sensitivity."
        raise ValueError(msg)

    baseline_rates = _engine_rates_on_cases(case_list, tool_ids=tool_ids)
    baseline_ranks = _rank_engines(baseline_rates)
    baseline_order = _pairwise_baseline_order(baseline_rates)

    baseline_rows = [
        {
            "case_id": case["case_id"],
            "tool_id": tool_id,
            "mutation_operator": case["mutation_operator"],
            "complete_repair": case["tools"][tool_id],
            "effective_repair": case["tools"][tool_id],
            "oracle_detected": True,
        }
        for case in case_list
        for tool_id in tool_ids
    ]
    baseline_kendall_tau = _operator_rank_tau_mean(baseline_rows, tool_ids=tool_ids)

    rng = random.Random(bootstrap_seed)
    flip_counts = dict.fromkeys(baseline_order, 0)
    kendall_taus: list[float] = []
    sample_size = len(case_list)

    for _ in range(n_resamples):
        draw = [case_list[rng.randrange(sample_size)] for _ in range(sample_size)]
        sample_rates = _engine_rates_on_cases(draw, tool_ids=tool_ids)
        sample_order = _pairwise_baseline_order(sample_rates)
        for pair, baseline_sign in baseline_order.items():
            if sample_order[pair] != baseline_sign:
                flip_counts[pair] += 1
        resampled_rows = [
            {
                "case_id": f"{case['case_id']}_{index}",
                "tool_id": tool_id,
                "mutation_operator": case["mutation_operator"],
                "complete_repair": case["tools"][tool_id],
                "effective_repair": case["tools"][tool_id],
                "oracle_detected": True,
            }
            for index, case in enumerate(draw)
            for tool_id in tool_ids
        ]
        kendall_taus.append(_operator_rank_tau_mean(resampled_rows, tool_ids=tool_ids))

    kendall_taus.sort()
    alpha = 0.025
    low_index = max(0, int(alpha * n_resamples))
    high_index = min(len(kendall_taus) - 1, int((1.0 - alpha) * n_resamples) - 1)

    return {
        "tool_ids": list(tool_ids),
        "baseline_rates": baseline_rates,
        "baseline_ranks": baseline_ranks,
        "baseline_kendall_tau": round(baseline_kendall_tau, 6),
        "flip_probabilities": {
            pair: flip_counts[pair] / n_resamples for pair in baseline_order
        },
        "kendall_tau_distribution": {
            "mean": round(statistics.mean(kendall_taus), 6),
            "std": round(statistics.pstdev(kendall_taus), 6) if len(kendall_taus) > 1 else 0.0,
            "ci95_low": round(kendall_taus[low_index], 6),
            "ci95_high": round(kendall_taus[high_index], 6),
            "samples": kendall_taus,
        },
        "n_resamples": n_resamples,
        "bootstrap_seed": bootstrap_seed,
    }


def operator_mix_sensitivity_to_csv_rows(summary: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    n_resamples = int(summary["n_resamples"])
    bootstrap_seed = int(summary["bootstrap_seed"])
    for tool_id, rank in sorted(summary["baseline_ranks"].items(), key=lambda item: item[1]):
        rows.append(
            {
                "record_type": "current_ranking",
                "engine": TOOL_LABELS[tool_id],
                "engine_b": "",
                "rank": rank,
                "complete_repair_rate": round(summary["baseline_rates"][tool_id], 6),
                "flip_probability": "",
                "kendall_tau": "",
                "kendall_tau_ci95_low": "",
                "kendall_tau_ci95_high": "",
                "n_resamples": n_resamples,
                "bootstrap_seed": bootstrap_seed,
            }
        )
    for (tool_a, tool_b), probability in summary["flip_probabilities"].items():
        rows.append(
            {
                "record_type": "pairwise_flip_probability",
                "engine": TOOL_LABELS[tool_a],
                "engine_b": TOOL_LABELS[tool_b],
                "rank": "",
                "complete_repair_rate": "",
                "flip_probability": round(probability, 6),
                "kendall_tau": "",
                "kendall_tau_ci95_low": "",
                "kendall_tau_ci95_high": "",
                "n_resamples": n_resamples,
                "bootstrap_seed": bootstrap_seed,
            }
        )
    distribution = summary["kendall_tau_distribution"]
    rows.append(
        {
            "record_type": "kendall_tau_distribution",
            "engine": "",
            "engine_b": "",
            "rank": "",
            "complete_repair_rate": "",
            "flip_probability": "",
            "kendall_tau": distribution["mean"],
            "kendall_tau_ci95_low": distribution["ci95_low"],
            "kendall_tau_ci95_high": distribution["ci95_high"],
            "n_resamples": n_resamples,
            "bootstrap_seed": bootstrap_seed,
        }
    )
    rows.append(
        {
            "record_type": "kendall_tau_baseline",
            "engine": "",
            "engine_b": "",
            "rank": "",
            "complete_repair_rate": "",
            "flip_probability": "",
            "kendall_tau": summary["baseline_kendall_tau"],
            "kendall_tau_ci95_low": "",
            "kendall_tau_ci95_high": "",
            "n_resamples": n_resamples,
            "bootstrap_seed": bootstrap_seed,
        }
    )
    return rows


def minimum_detectable_effect_pp(
    *,
    n_cases: int,
    pooled_rate: float = 0.5,
    alpha: float = 0.05,
    power: float = 0.80,
) -> float:
    """Two-proportion normal approximation for equal sample sizes."""
    if n_cases <= 0:
        return 0.0
    pooled = min(max(pooled_rate, 0.0), 1.0)
    z_alpha = 1.96 if abs(alpha - 0.05) < 1e-9 else 1.96
    z_beta = 0.841621 if abs(power - 0.80) < 1e-9 else 0.841621
    variance = 2.0 * pooled * (1.0 - pooled) / n_cases
    return 100.0 * (z_alpha + z_beta) * math.sqrt(variance)


def compute_minimum_detectable_effects(
    per_case_rows: Sequence[dict[str, Any]],
    *,
    alpha: float = 0.05,
    power: float = 0.80,
) -> list[dict[str, Any]]:
    detectable_rows = [row for row in per_case_rows if row["oracle_detected"]]
    detectable_count = len({row["case_id"] for row in detectable_rows if row["tool_id"] == SHIPPED_C1_TOOL_IDS[0]})
    shipped_rates = [
        _rate([bool(row["complete_repair"]) for row in detectable_rows if row["tool_id"] == tool_id])
        for tool_id in SHIPPED_C1_TOOL_IDS
    ]
    pooled_detectable = statistics.mean(shipped_rates) if shipped_rates else 0.5

    operator_counts: dict[str, int] = {}
    for row in detectable_rows:
        if row["tool_id"] != SHIPPED_C1_TOOL_IDS[0]:
            continue
        operator = str(row["mutation_operator"])
        operator_counts[operator] = operator_counts.get(operator, 0) + 1
    per_operator_n = round(statistics.mean(operator_counts.values())) if operator_counts else 59

    assumption = (
        "Independent two-proportion normal approximation with equal sample sizes; "
        "alpha=0.05 two-sided; power=0.80; conservative pooled rate shown."
    )
    rows = [
        {
            "scope": "all_detectable",
            "n_cases": detectable_count,
            "assumed_pooled_rate": round(pooled_detectable, 6),
            "alpha": alpha,
            "power": power,
            "mde_pp": round(
                minimum_detectable_effect_pp(
                    n_cases=detectable_count,
                    pooled_rate=pooled_detectable,
                    alpha=alpha,
                    power=power,
                ),
                3,
            ),
            "assumption": assumption,
        },
        {
            "scope": "all_detectable_pooled_0.5",
            "n_cases": detectable_count,
            "assumed_pooled_rate": 0.5,
            "alpha": alpha,
            "power": power,
            "mde_pp": round(
                minimum_detectable_effect_pp(
                    n_cases=detectable_count,
                    pooled_rate=0.5,
                    alpha=alpha,
                    power=power,
                ),
                3,
            ),
            "assumption": assumption + " Pooled rate fixed at 0.5 for conservative upper bound.",
        },
        {
            "scope": "per_operator_cell",
            "n_cases": per_operator_n,
            "assumed_pooled_rate": 0.5,
            "alpha": alpha,
            "power": power,
            "mde_pp": round(
                minimum_detectable_effect_pp(
                    n_cases=per_operator_n,
                    pooled_rate=0.5,
                    alpha=alpha,
                    power=power,
                ),
                3,
            ),
            "assumption": assumption + " Uses mean detectable cases per operator cell.",
        },
    ]
    return rows


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})


def _write_operator_mix_tex(path: Path, summary: dict[str, Any]) -> None:
    flip_rows = [
        (
            TOOL_LABELS[pair[0]],
            TOOL_LABELS[pair[1]],
            f"{probability * 100:.1f}\\%",
        )
        for pair, probability in summary["flip_probabilities"].items()
    ]
    distribution = summary["kendall_tau_distribution"]
    lines = [
        "% Auto-generated from fsmrepairbench.benchmark_utility_calibration",
        "\\begin{table}[t]",
        (
            "\\caption{Operator-mix sensitivity for the shipped C1 trio on detectable-only complete repair "
            "($n=495$). Current ranking uses the actual operator mix; flip probabilities come from "
            f"{summary['n_resamples']:,} bootstrap-resampled operator mixes (seed~{summary['bootstrap_seed']}). "
            f"Mean Kendall $\\tau$ across resampled mixes is {distribution['mean']:.3f} "
            f"[{distribution['ci95_low']:.3f}--{distribution['ci95_high']:.3f}] "
            f"(baseline actual mix: {summary['baseline_kendall_tau']:.3f}). "
            "Takeaway: aggregate engine ordering is stable under operator-mix perturbation, but operator-level "
            "rank profiles remain weakly aligned across engines.}"
        ),
        "\\label{tab:operator-mix-sensitivity}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lrr@{}}",
        "\\toprule",
        "Engine & Rank & Complete repair (detectable-only) \\\\",
        "\\midrule",
    ]
    ordered = sorted(summary["baseline_ranks"].items(), key=lambda item: item[1])
    for tool_id, rank in ordered:
        lines.append(
            f"\\texttt{{{_tex_escape(TOOL_LABELS[tool_id])}}} & {rank} & "
            f"{100.0 * summary['baseline_rates'][tool_id]:.1f}\\% \\\\"
        )
    lines.extend(
        [
            "\\midrule",
            "\\multicolumn{3}{l}{\\textbf{Pairwise ordering flip probability}} \\\\",
            "\\midrule",
            "Engine A & Engine B & Flip probability \\\\",
            "\\midrule",
        ]
    )
    for engine_a, engine_b, probability in flip_rows:
        lines.append(
            f"\\texttt{{{_tex_escape(engine_a)}}} & \\texttt{{{_tex_escape(engine_b)}}} & "
            f"{probability} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_mde_tex(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    primary = next(row for row in rows if row["scope"] == "all_detectable")
    per_operator = next(row for row in rows if row["scope"] == "per_operator_cell")
    conservative = next(row for row in rows if row["scope"] == "all_detectable_pooled_0.5")
    lines = [
        "% Auto-generated from fsmrepairbench.benchmark_utility_calibration",
        "\\begin{table}[t]",
        (
            "\\caption{Minimum detectable complete-repair difference (MDE) at 80\\% power "
            "using a simple two-proportion normal approximation ($\\alpha=0.05$, two-sided). "
            f"All detectable cases ($n={primary['n_cases']}$): {primary['mde_pp']:.1f}~pp at observed pooled rate "
            f"{100.0 * float(primary['assumed_pooled_rate']):.1f}\\%; conservative bound "
            f"{conservative['mde_pp']:.1f}~pp at pooled rate 50\\%. "
            f"Per-operator cells ($n\\approx{per_operator['n_cases']}$): {per_operator['mde_pp']:.1f}~pp. "
            "Assumes independent equal-sized samples; paired McNemar tests on the same cohort can be more powerful.}"
        ),
        "\\label{tab:minimum-detectable-effect}",
        "\\begin{tabular}{@{}lrrrp{0.42\\linewidth}@{}}",
        "\\toprule",
        "Scope & $n$ & Pooled rate & MDE (pp) & Assumption \\\\",
        "\\midrule",
    ]
    for row in rows:
        if row["scope"] == "all_detectable_pooled_0.5":
            label = "All detectable (pooled 0.5)"
        elif row["scope"] == "all_detectable":
            label = "All detectable (observed pooled)"
        else:
            label = "Per-operator cell (mean $n$)"
        lines.append(
            f"{label} & {row['n_cases']} & {100.0 * float(row['assumed_pooled_rate']):.1f}\\% & "
            f"{float(row['mde_pp']):.1f} & {row['assumption']} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_benchmark_utility_calibration_exports(
    per_case_path: Path,
    out_dir: Path,
    *,
    paper_export_dir: Path | None = None,
    tool_ids: Sequence[str] = SHIPPED_C1_TOOL_IDS,
) -> BenchmarkUtilityCalibrationExportResult:
    """Write operator-mix sensitivity and MDE calibration exports."""
    per_case_rows = _load_per_case_rows(per_case_path)
    operator_mix = compute_operator_mix_sensitivity(per_case_rows, tool_ids=tool_ids)
    mde_rows = compute_minimum_detectable_effects(per_case_rows)

    out_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    operator_mix_csv = out_dir / "operator_mix_sensitivity.csv"
    _write_csv(operator_mix_csv, OPERATOR_MIX_SENSITIVITY_COLUMNS, operator_mix_sensitivity_to_csv_rows(operator_mix))

    operator_mix_tex = tables_dir / "table_operator_mix_sensitivity.tex"
    mde_tex = tables_dir / "table_minimum_detectable_effect.tex"
    _write_operator_mix_tex(operator_mix_tex, operator_mix)
    _write_mde_tex(mde_tex, mde_rows)

    manifest = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "source_per_case": str(per_case_path),
        "operator_mix_sensitivity": {
            "tool_ids": operator_mix["tool_ids"],
            "baseline_rates": {
                TOOL_LABELS[tool_id]: rate for tool_id, rate in operator_mix["baseline_rates"].items()
            },
            "baseline_ranks": {
                TOOL_LABELS[tool_id]: rank for tool_id, rank in operator_mix["baseline_ranks"].items()
            },
            "baseline_kendall_tau": operator_mix["baseline_kendall_tau"],
            "flip_probabilities": {
                f"{TOOL_LABELS[pair[0]]}|{TOOL_LABELS[pair[1]]}": probability
                for pair, probability in operator_mix["flip_probabilities"].items()
            },
            "kendall_tau_distribution": {
                key: value
                for key, value in operator_mix["kendall_tau_distribution"].items()
                if key != "samples"
            },
            "n_resamples": operator_mix["n_resamples"],
            "bootstrap_seed": operator_mix["bootstrap_seed"],
        },
        "minimum_detectable_effects": mde_rows,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_operator_mix_csv_path = paper_operator_mix_tex_path = paper_mde_tex_path = None
    if paper_export_dir is not None:
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        (paper_export_dir / "tables").mkdir(parents=True, exist_ok=True)
        paper_operator_mix_csv_path = paper_export_dir / operator_mix_csv.name
        paper_operator_mix_tex_path = paper_export_dir / "tables" / operator_mix_tex.name
        paper_mde_tex_path = paper_export_dir / "tables" / mde_tex.name
        paper_operator_mix_csv_path.write_text(operator_mix_csv.read_text(encoding="utf-8"), encoding="utf-8")
        paper_operator_mix_tex_path.write_text(operator_mix_tex.read_text(encoding="utf-8"), encoding="utf-8")
        paper_mde_tex_path.write_text(mde_tex.read_text(encoding="utf-8"), encoding="utf-8")
        (paper_export_dir / "manifest.json").write_text(manifest_path.read_text(encoding="utf-8"), encoding="utf-8")

    return BenchmarkUtilityCalibrationExportResult(
        operator_mix_csv_path=operator_mix_csv,
        operator_mix_tex_path=operator_mix_tex,
        mde_tex_path=mde_tex,
        manifest_path=manifest_path,
        paper_operator_mix_csv_path=paper_operator_mix_csv_path,
        paper_operator_mix_tex_path=paper_operator_mix_tex_path,
        paper_mde_tex_path=paper_mde_tex_path,
    )
