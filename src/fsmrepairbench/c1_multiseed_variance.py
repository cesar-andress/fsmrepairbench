"""Multi-seed variance and subgroup bootstrap CIs for C1 baseline repair engines."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import (
    BOOTSTRAP_CI,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    RANDOM_TOOL_ID,
    bootstrap_ci,
)
from fsmrepairbench.benchmark_utility import C1_DETERMINISTIC_TOOL_IDS, C1_TOOL_IDS
from fsmrepairbench.dataset_builder import DatasetBuilderError, DatasetCaseRow, load_dataset_cases
from fsmrepairbench.statistics import bootstrap_rate_ci
from fsmrepairbench.tool_runner import ToolRunSummaryRow

DETERMINISTIC_TOOL_IDS: tuple[str, ...] = C1_DETERMINISTIC_TOOL_IDS

SUBGROUP_METRICS: tuple[str, ...] = (
    "complete_repair_rate",
    "effective_repair_rate",
)
PARTITIONS: tuple[str, ...] = ("cohort_wide", "detectable_only")
TIER_ORDER: tuple[str, ...] = ("small", "medium", "large", "very_large")

BY_OPERATOR_CSV = "multiseed_by_operator.csv"
BY_TIER_CSV = "multiseed_by_tier.csv"
BY_OPERATOR_JSON = "multiseed_by_operator.json"
BY_TIER_JSON = "multiseed_by_tier.json"
ENGINE_SUMMARY_CSV = "multiseed_engine_summary.csv"
SUBGROUP_CI_FIELDNAMES: tuple[str, ...] = (
    "tool_id",
    "subgroup_type",
    "subgroup_value",
    "partition",
    "metric",
    "n_cases",
    "point_estimate",
    "ci95_low",
    "ci95_high",
    "ci_method",
    "seed_count",
)
OPERATOR_TEX = "table_repair_by_operator.tex"
TIER_TEX = "table_repair_by_tier.tex"
OPERATOR_FIGURE = "repair_rate_by_operator_with_ci.png"
TIER_FIGURE = "repair_rate_by_tier_with_ci.png"


@dataclass(frozen=True)
class SubgroupCiRow:
    """One subgroup metric with a 95% confidence interval."""

    tool_id: str
    subgroup_type: str
    subgroup_value: str
    partition: str
    metric: str
    n_cases: int
    point_estimate: float
    ci95_low: float
    ci95_high: float
    ci_method: str
    seed_count: int

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "tool_id": self.tool_id,
            "subgroup_type": self.subgroup_type,
            "subgroup_value": self.subgroup_value,
            "partition": self.partition,
            "metric": self.metric,
            "n_cases": self.n_cases,
            "point_estimate": self.point_estimate,
            "ci95_low": self.ci95_low,
            "ci95_high": self.ci95_high,
            "ci_method": self.ci_method,
            "seed_count": self.seed_count,
        }


@dataclass(frozen=True)
class MultiseedVarianceExportResult:
    """Paths written by :func:`write_c1_multiseed_variance_exports`."""

    by_operator_csv: Path
    by_tier_csv: Path
    by_operator_json: Path
    by_tier_json: Path
    engine_summary_csv: Path
    operator_tex_path: Path
    tier_tex_path: Path
    operator_figure_path: Path
    tier_figure_path: Path


def _rate(flags: Sequence[bool]) -> float:
    if not flags:
        return 0.0
    return sum(1 for flag in flags if flag) / len(flags)


def _load_dataset_rows(dataset_dir: Path, case_ids: set[str]) -> dict[str, DatasetCaseRow]:
    try:
        rows = load_dataset_cases(dataset_dir)
    except DatasetBuilderError:
        return {}
    return {row.case_id: row for row in rows if row.case_id in case_ids}


def enrich_tool_run_rows(
    rows: Sequence[ToolRunSummaryRow],
    dataset_rows: Mapping[str, DatasetCaseRow],
) -> list[dict[str, Any]]:
    """Join tool-run rows with dataset metadata for subgroup analysis."""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        if row.status != "completed":
            continue
        meta = dataset_rows.get(row.case_id)
        if meta is None:
            faulty_bpr = row.initial_bpr
            ref_bpr = 1.0
            complexity = ""
            operator = row.mutation_operator
        else:
            faulty_bpr = meta.faulty_bpr
            ref_bpr = meta.reference_bpr
            complexity = meta.complexity
            operator = meta.mutation_operator
        enriched.append(
            {
                "case_id": row.case_id,
                "tool_id": row.tool_id,
                "mutation_operator": operator,
                "complexity_tier": complexity,
                "complete_repair": row.complete_repair,
                "effective_repair": row.effective_repair,
                "oracle_detected": faulty_bpr < ref_bpr - 1e-9,
            }
        )
    return enriched


def enrich_case_dict_rows(
    rows: Sequence[Mapping[str, Any]],
    dataset_rows: Mapping[str, DatasetCaseRow],
) -> list[dict[str, Any]]:
    """Enrich per-case CSV dict rows for deterministic baseline subgroup CIs."""
    enriched: list[dict[str, Any]] = []
    for row in rows:
        meta = dataset_rows.get(str(row["case_id"]))
        if meta is None:
            faulty_bpr = float(row.get("initial_bpr", 1.0))
            ref_bpr = 1.0
            complexity = ""
            operator = str(row.get("mutation_operator", ""))
        else:
            faulty_bpr = meta.faulty_bpr
            ref_bpr = meta.reference_bpr
            complexity = meta.complexity
            operator = meta.mutation_operator
        enriched.append(
            {
                **dict(row),
                "mutation_operator": operator,
                "complexity_tier": complexity,
                "oracle_detected": faulty_bpr < ref_bpr - 1e-9,
                "complete_repair": bool(row["complete_repair"]),
                "effective_repair": bool(row["effective_repair"]),
            }
        )
    return enriched


def _partition_subset(rows: Sequence[Mapping[str, Any]], partition: str) -> list[Mapping[str, Any]]:
    if partition == "detectable_only":
        return [row for row in rows if row["oracle_detected"]]
    return list(rows)


def _group_rows(
    rows: Sequence[Mapping[str, Any]],
    group_field: str,
) -> dict[str, list[Mapping[str, Any]]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[group_field])].append(row)
    return grouped


def summarize_seed_subgroups(
    rows: Sequence[ToolRunSummaryRow],
    dataset_rows: Mapping[str, DatasetCaseRow],
) -> dict[str, dict[str, dict[str, dict[str, float | int]]]]:
    """Return per-seed operator/tier rates for one random baseline run."""
    enriched = enrich_tool_run_rows(rows, dataset_rows)
    result: dict[str, dict[str, dict[str, dict[str, float | int]]]] = {
        "by_operator": {},
        "by_tier": {},
    }
    for group_key, group_field in (("by_operator", "mutation_operator"), ("by_tier", "complexity_tier")):
        grouped = _group_rows(enriched, group_field)
        for subgroup_value, items in grouped.items():
            if not subgroup_value:
                continue
            entry: dict[str, dict[str, float | int]] = {}
            for partition in PARTITIONS:
                subset = _partition_subset(items, partition)
                entry[partition] = {
                    "n_cases": len(subset),
                    "complete_repair_rate": round(
                        _rate([bool(row["complete_repair"]) for row in subset]),
                        6,
                    ),
                    "effective_repair_rate": round(
                        _rate([bool(row["effective_repair"]) for row in subset]),
                        6,
                    ),
                }
            result[group_key][subgroup_value] = entry
    return result


def aggregate_seed_bootstrap_subgroup_ci(
    per_seed_subgroups: Sequence[Mapping[str, Any]],
    *,
    tool_id: str,
    group_key: str,
    subgroup_type: str,
    seed_count: int,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> list[SubgroupCiRow]:
    """Bootstrap 95% CIs across random baseline seeds for each subgroup cell."""
    import random

    rng = random.Random(bootstrap_seed)
    subgroup_values: set[str] = set()
    for seed_payload in per_seed_subgroups:
        subgroup_values.update(seed_payload.get(group_key, {}).keys())

    rows: list[SubgroupCiRow] = []
    for subgroup_value in sorted(subgroup_values):
        for partition in PARTITIONS:
            for metric in SUBGROUP_METRICS:
                values = [
                    float(seed_payload[group_key][subgroup_value][partition][metric])
                    for seed_payload in per_seed_subgroups
                    if subgroup_value in seed_payload.get(group_key, {})
                    and partition in seed_payload[group_key][subgroup_value]
                ]
                if not values:
                    continue
                n_cases = int(
                    per_seed_subgroups[-1][group_key][subgroup_value][partition]["n_cases"]
                )
                low, high = bootstrap_ci(
                    values,
                    n_resamples=bootstrap_resamples,
                    ci=BOOTSTRAP_CI,
                    rng=rng,
                )
                rows.append(
                    SubgroupCiRow(
                        tool_id=tool_id,
                        subgroup_type=subgroup_type,
                        subgroup_value=subgroup_value,
                        partition=partition,
                        metric=metric,
                        n_cases=n_cases,
                        point_estimate=round(sum(values) / len(values), 6),
                        ci95_low=round(low, 6),
                        ci95_high=round(high, 6),
                        ci_method="seed_bootstrap",
                        seed_count=seed_count,
                    )
                )
    return rows


def compute_case_bootstrap_subgroup_ci(
    enriched_rows: Sequence[Mapping[str, Any]],
    *,
    tool_id: str,
    group_field: str,
    subgroup_type: str,
    bootstrap_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> list[SubgroupCiRow]:
    """Case-level bootstrap CIs for deterministic baselines by subgroup."""
    tool_rows = [row for row in enriched_rows if row["tool_id"] == tool_id]
    grouped = _group_rows(tool_rows, group_field)
    rows: list[SubgroupCiRow] = []
    for subgroup_value in sorted(grouped):
        if not subgroup_value:
            continue
        items = grouped[subgroup_value]
        for partition in PARTITIONS:
            subset = _partition_subset(items, partition)
            if not subset:
                continue
            for metric, field in (
                ("complete_repair_rate", "complete_repair"),
                ("effective_repair_rate", "effective_repair"),
            ):
                ci = bootstrap_rate_ci(
                    [bool(row[field]) for row in subset],
                    metric,
                    n_resamples=bootstrap_resamples,
                    bootstrap_seed=bootstrap_seed,
                )
                rows.append(
                    SubgroupCiRow(
                        tool_id=tool_id,
                        subgroup_type=subgroup_type,
                        subgroup_value=subgroup_value,
                        partition=partition,
                        metric=metric,
                        n_cases=ci.n_cases,
                        point_estimate=ci.mean,
                        ci95_low=ci.ci95_low,
                        ci95_high=ci.ci95_high,
                        ci_method="case_bootstrap",
                        seed_count=1,
                    )
                )
    return rows



def build_multiseed_variance_rows(
    enriched_rows: Sequence[Mapping[str, Any]],
    per_seed_subgroups: Sequence[Mapping[str, Any]] | None,
    *,
    seed_count: int,
) -> list[SubgroupCiRow]:
    """Combine deterministic case-bootstrap and random seed-bootstrap subgroup CIs."""
    rows: list[SubgroupCiRow] = []
    for tool_id in DETERMINISTIC_TOOL_IDS:
        rows.extend(
            compute_case_bootstrap_subgroup_ci(
                enriched_rows,
                tool_id=tool_id,
                group_field="mutation_operator",
                subgroup_type="operator",
            )
        )
        rows.extend(
            compute_case_bootstrap_subgroup_ci(
                enriched_rows,
                tool_id=tool_id,
                group_field="complexity_tier",
                subgroup_type="tier",
            )
        )

    if per_seed_subgroups:
        rows.extend(
            aggregate_seed_bootstrap_subgroup_ci(
                per_seed_subgroups,
                tool_id=RANDOM_TOOL_ID,
                group_key="by_operator",
                subgroup_type="operator",
                seed_count=seed_count,
            )
        )
        rows.extend(
            aggregate_seed_bootstrap_subgroup_ci(
                per_seed_subgroups,
                tool_id=RANDOM_TOOL_ID,
                group_key="by_tier",
                subgroup_type="tier",
                seed_count=seed_count,
            )
        )
    return rows


def _lookup_ci_row(
    rows: Sequence[SubgroupCiRow],
    *,
    tool_id: str,
    subgroup_type: str,
    subgroup_value: str,
    partition: str,
    metric: str,
) -> SubgroupCiRow | None:
    for row in rows:
        if (
            row.tool_id == tool_id
            and row.subgroup_type == subgroup_type
            and row.subgroup_value == subgroup_value
            and row.partition == partition
            and row.metric == metric
        ):
            return row
    return None


def _tex_pct_ci(row: SubgroupCiRow | None) -> str:
    if row is None or row.n_cases == 0:
        return "---"
    return (
        f"{100.0 * row.point_estimate:.1f}\\% "
        f"\\;[{100.0 * row.ci95_low:.1f}, {100.0 * row.ci95_high:.1f}]"
    )


def _tex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
    )


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _write_subgroup_json(path: Path, rows: Sequence[SubgroupCiRow]) -> None:
    payload = {
        "bootstrap": {
            "ci": BOOTSTRAP_CI,
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
        },
        "rows": [row.to_dict() for row in rows],
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


PARTITION_FOOTNOTE_LATEX = (
    r"\par\footnotesize \textbf{Primary repairability and localization metrics use "
    r"detectable-only partitions} ($n=495$; \textbf{505/1{,}000} oracle-saturated at "
    r"faulty BPR $= 1.0$ excluded). Cohort-wide$^\dagger$ columns include "
    r"oracle-saturated faults and are transparency totals only."
)


def _write_tex_table(
    path: Path,
    *,
    caption: str,
    label: str,
    headers: list[str],
    body_rows: list[list[str]],
    note: str | None = PARTITION_FOOTNOTE_LATEX,
) -> None:
    col_spec = "@{}" + "l" + "r" * (len(headers) - 1) + "@{}"
    lines = [
        "% Auto-generated from fsmrepairbench.c1_multiseed_variance",
        "\\begin{table}[t]",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{col_spec}}}",
        "\\toprule",
        " & ".join(headers) + " \\\\",
        "\\midrule",
    ]
    lines.extend(" & ".join(row) + " \\\\" for row in body_rows)
    lines.extend(["\\bottomrule", "\\end{tabular}"])
    if note:
        lines.append(note)
    lines.extend(["\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _operator_order(rows: Sequence[SubgroupCiRow]) -> list[str]:
    operators = sorted(
        {
            row.subgroup_value
            for row in rows
            if row.subgroup_type == "operator" and row.subgroup_value
        }
    )
    return operators


def _write_operator_tex_table(
    path: Path,
    ci_rows: Sequence[SubgroupCiRow],
    *,
    tool_id: str,
    case_count: int,
    detectable_count: int,
    saturated_count: int = 505,
) -> None:
    tool_label = tool_id.replace("baseline_", "")
    operators = _operator_order(ci_rows)
    body: list[list[str]] = []
    for operator in operators:
        complete_det = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="operator",
            subgroup_value=operator,
            partition="detectable_only",
            metric="complete_repair_rate",
        )
        effective_det = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="operator",
            subgroup_value=operator,
            partition="detectable_only",
            metric="effective_repair_rate",
        )
        complete_cohort = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="operator",
            subgroup_value=operator,
            partition="cohort_wide",
            metric="complete_repair_rate",
        )
        effective_cohort = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="operator",
            subgroup_value=operator,
            partition="cohort_wide",
            metric="effective_repair_rate",
        )
        n_detectable = complete_det.n_cases if complete_det else 0
        body.append(
            [
                _tex_escape(operator),
                str(n_detectable),
                _tex_pct_ci(complete_det),
                _tex_pct_ci(complete_cohort),
                _tex_pct_ci(effective_det),
                _tex_pct_ci(effective_cohort),
            ]
        )
    _write_tex_table(
        path,
        caption=(
            f"Repair by mutation operator under the \\texttt{{{tool_label}}} baseline "
            f"($n={case_count:,}$ cohort). \\textbf{{Detectable-only primary}} "
            f"($n={detectable_count}$); cohort-wide$^\\dagger$ includes "
            f"{saturated_count}/1{{,}}000 oracle-saturated cases. "
            f"95\\% CIs: case bootstrap for deterministic engines; seed bootstrap "
            f"for \\texttt{{random}} otherwise."
        ),
        label="tab:baseline-repair-by-operator",
        headers=[
            "Operator",
            "Detectable",
            "Complete (detect.) [95\\% CI]",
            "Complete (cohort$^\\dagger$) [95\\% CI]",
            "Effective (detect.) [95\\% CI]",
            "Effective (cohort$^\\dagger$) [95\\% CI]",
        ],
        body_rows=body,
    )


def _write_tier_tex_table(
    path: Path,
    ci_rows: Sequence[SubgroupCiRow],
    *,
    tool_id: str,
    case_count: int,
    detectable_count: int,
    saturated_count: int = 505,
) -> None:
    tool_label = tool_id.replace("baseline_", "")
    body: list[list[str]] = []
    for tier in TIER_ORDER:
        complete_det = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="tier",
            subgroup_value=tier,
            partition="detectable_only",
            metric="complete_repair_rate",
        )
        effective_det = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="tier",
            subgroup_value=tier,
            partition="detectable_only",
            metric="effective_repair_rate",
        )
        complete_cohort = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="tier",
            subgroup_value=tier,
            partition="cohort_wide",
            metric="complete_repair_rate",
        )
        effective_cohort = _lookup_ci_row(
            ci_rows,
            tool_id=tool_id,
            subgroup_type="tier",
            subgroup_value=tier,
            partition="cohort_wide",
            metric="effective_repair_rate",
        )
        if complete_det is None and effective_det is None:
            continue
        n_detectable = complete_det.n_cases if complete_det else (effective_det.n_cases if effective_det else 0)
        body.append(
            [
                _tex_escape(tier),
                str(n_detectable),
                _tex_pct_ci(complete_det),
                _tex_pct_ci(complete_cohort),
                _tex_pct_ci(effective_det),
                _tex_pct_ci(effective_cohort),
            ]
        )
    _write_tex_table(
        path,
        caption=(
            f"Repair by complexity tier under the \\texttt{{{tool_label}}} baseline "
            f"($n={case_count:,}$ cohort). \\textbf{{Detectable-only primary}}; "
            f"cohort-wide$^\\dagger$ includes {saturated_count}/1{{,}}000 "
            f"oracle-saturated cases. 95\\% CIs as in "
            f"Table~\\ref{{tab:baseline-repair-by-operator}}."
        ),
        label="tab:baseline-repair-by-tier",
        headers=[
            "Tier",
            "Detectable",
            "Complete (detect.) [95\\% CI]",
            "Complete (cohort$^\\dagger$) [95\\% CI]",
            "Effective (detect.) [95\\% CI]",
            "Effective (cohort$^\\dagger$) [95\\% CI]",
        ],
        body_rows=body,
    )


def _write_variance_figures(
    ci_rows: Sequence[SubgroupCiRow],
    *,
    figures_dir: Path,
    primary_tool: str = "baseline_missing_transition",
) -> tuple[Path, Path]:
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)

    operators = _operator_order(
        [row for row in ci_rows if row.tool_id == primary_tool or row.tool_id == RANDOM_TOOL_ID]
    )
    x = range(len(operators))
    width = 0.25
    plt.figure(figsize=(14, 5))
    for idx, tool_id in enumerate(C1_TOOL_IDS):
        means: list[float] = []
        lows: list[float] = []
        highs: list[float] = []
        for operator in operators:
            row = _lookup_ci_row(
                ci_rows,
                tool_id=tool_id,
                subgroup_type="operator",
                subgroup_value=operator,
                partition="detectable_only",
                metric="complete_repair_rate",
            )
            means.append(row.point_estimate if row else 0.0)
            lows.append(row.ci95_low if row else 0.0)
            highs.append(row.ci95_high if row else 0.0)
        offset = (idx - 1) * width
        positions = [i + offset for i in x]
        yerr = [
            [mean - low for mean, low in zip(means, lows, strict=True)],
            [high - mean for mean, high in zip(means, highs, strict=True)],
        ]
        plt.bar(
            positions,
            means,
            width=width,
            label=tool_id.replace("baseline_", ""),
            yerr=yerr,
            capsize=2,
        )
    plt.xticks(list(x), operators, rotation=45, ha="right")
    plt.ylim(0, 1.05)
    plt.ylabel("Complete repair rate (detectable only)")
    plt.title("Complete repair by operator with 95% CI")
    plt.legend()
    plt.tight_layout()
    operator_path = figures_dir / OPERATOR_FIGURE
    plt.savefig(operator_path, dpi=150)
    plt.close()

    plt.figure(figsize=(8, 4))
    width = 0.25
    x = range(len(TIER_ORDER))
    for idx, tool_id in enumerate(C1_TOOL_IDS):
        means = []
        lows = []
        highs = []
        for tier in TIER_ORDER:
            row = _lookup_ci_row(
                ci_rows,
                tool_id=tool_id,
                subgroup_type="tier",
                subgroup_value=tier,
                partition="detectable_only",
                metric="complete_repair_rate",
            )
            means.append(row.point_estimate if row else 0.0)
            lows.append(row.ci95_low if row else 0.0)
            highs.append(row.ci95_high if row else 0.0)
        offset = (idx - 1) * width
        positions = [i + offset for i in x]
        yerr = [
            [mean - low for mean, low in zip(means, lows, strict=True)],
            [high - mean for mean, high in zip(means, highs, strict=True)],
        ]
        plt.bar(
            positions,
            means,
            width=width,
            label=tool_id.replace("baseline_", ""),
            yerr=yerr,
            capsize=2,
        )
    plt.xticks(list(x), TIER_ORDER)
    plt.ylim(0, 1.05)
    plt.ylabel("Complete repair rate (detectable only)")
    plt.xlabel("Complexity tier")
    plt.title("Complete repair by tier with 95% CI")
    plt.legend()
    plt.tight_layout()
    tier_path = figures_dir / TIER_FIGURE
    plt.savefig(tier_path, dpi=150)
    plt.close()
    return operator_path, tier_path


def build_engine_summary_rows(
    ci_rows: Sequence[SubgroupCiRow],
    *,
    seed_count: int,
) -> list[dict[str, str | int | float]]:
    """Cohort-wide engine-level rows derived from subgroup CI exports."""
    rows: list[dict[str, str | int | float]] = []
    for tool_id in C1_TOOL_IDS:
        for metric in SUBGROUP_METRICS:
            for partition in PARTITIONS:
                matching = [
                    row
                    for row in ci_rows
                    if row.tool_id == tool_id
                    and row.partition == partition
                    and row.metric == metric
                    and (
                        (row.subgroup_type == "operator" and row.subgroup_value)
                        or (row.subgroup_type == "tier" and row.subgroup_value in TIER_ORDER)
                    )
                ]
                if not matching:
                    continue
                total_n = max(row.n_cases for row in matching)
                weighted = sum(row.point_estimate * row.n_cases for row in matching)
                weight = sum(row.n_cases for row in matching)
                point = round(weighted / weight, 6) if weight else 0.0
                ci_method = matching[0].ci_method
                tool_seed_count = seed_count if tool_id == RANDOM_TOOL_ID else 1
                rows.append(
                    {
                        "tool_id": tool_id,
                        "partition": partition,
                        "metric": metric,
                        "n_cases": total_n,
                        "point_estimate": point,
                        "ci_method": ci_method,
                        "seed_count": tool_seed_count,
                    }
                )
    return rows


def write_c1_multiseed_variance_exports(
    *,
    raw_runs_dir: Path,
    paper_export_dir: Path,
    enriched_rows: Sequence[Mapping[str, Any]],
    per_seed_subgroups: Sequence[Mapping[str, Any]] | None,
    seed_count: int,
    case_count: int,
    detectable_count: int,
    primary_tool: str = "baseline_missing_transition",
) -> MultiseedVarianceExportResult:
    """Write subgroup CSV/JSON, LaTeX tables, and figures with 95% CIs."""
    ci_rows = build_multiseed_variance_rows(
        enriched_rows,
        per_seed_subgroups,
        seed_count=seed_count,
    )
    operator_rows = [row.to_dict() for row in ci_rows if row.subgroup_type == "operator"]
    tier_rows = [row.to_dict() for row in ci_rows if row.subgroup_type == "tier"]
    fieldnames = list(SUBGROUP_CI_FIELDNAMES)

    by_operator_csv = raw_runs_dir / BY_OPERATOR_CSV
    by_tier_csv = raw_runs_dir / BY_TIER_CSV
    _write_csv(by_operator_csv, fieldnames, operator_rows)
    _write_csv(by_tier_csv, fieldnames, tier_rows)

    by_operator_json = raw_runs_dir / BY_OPERATOR_JSON
    by_tier_json = raw_runs_dir / BY_TIER_JSON
    _write_subgroup_json(by_operator_json, [row for row in ci_rows if row.subgroup_type == "operator"])
    _write_subgroup_json(by_tier_json, [row for row in ci_rows if row.subgroup_type == "tier"])

    engine_summary_csv = raw_runs_dir / ENGINE_SUMMARY_CSV
    _write_csv(
        engine_summary_csv,
        ["tool_id", "partition", "metric", "n_cases", "point_estimate", "ci_method", "seed_count"],
        build_engine_summary_rows(ci_rows, seed_count=seed_count),
    )

    tables_dir = raw_runs_dir / "tables"
    operator_tex = tables_dir / OPERATOR_TEX
    tier_tex = tables_dir / TIER_TEX
    _write_operator_tex_table(
        operator_tex,
        ci_rows,
        tool_id=primary_tool,
        case_count=case_count,
        detectable_count=detectable_count,
    )
    _write_tier_tex_table(
        tier_tex,
        ci_rows,
        tool_id=primary_tool,
        case_count=case_count,
        detectable_count=detectable_count,
    )

    figures_dir = raw_runs_dir / "figures"
    operator_fig, tier_fig = _write_variance_figures(ci_rows, figures_dir=figures_dir)

    shutil = __import__("shutil")
    for name in (
        BY_OPERATOR_CSV,
        BY_TIER_CSV,
        BY_OPERATOR_JSON,
        BY_TIER_JSON,
        ENGINE_SUMMARY_CSV,
    ):
        src = raw_runs_dir / name
        dest = paper_export_dir / name
        if src.is_file() and src.resolve() != dest.resolve():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)

    for rel_path in (
        Path("tables") / OPERATOR_TEX,
        Path("tables") / TIER_TEX,
        Path("figures") / OPERATOR_FIGURE,
        Path("figures") / TIER_FIGURE,
    ):
        src = raw_runs_dir / rel_path
        if not src.is_file():
            continue
        dest = paper_export_dir / rel_path
        if src.resolve() == dest.resolve():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)

    return MultiseedVarianceExportResult(
        by_operator_csv=by_operator_csv,
        by_tier_csv=by_tier_csv,
        by_operator_json=by_operator_json,
        by_tier_json=by_tier_json,
        engine_summary_csv=engine_summary_csv,
        operator_tex_path=operator_tex,
        tier_tex_path=tier_tex,
        operator_figure_path=operator_fig,
        tier_figure_path=tier_fig,
    )
