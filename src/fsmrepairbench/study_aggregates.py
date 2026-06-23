"""Cross-seed aggregation helpers for extension studies."""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsmrepairbench.statistics import bootstrap_mean_ci


@dataclass(frozen=True)
class NumericAggregate:
    """Summary statistics for one scalar metric across independent seeds."""

    metric: str
    n_seeds: int
    mean: float
    std: float
    minimum: float
    maximum: float
    ci95_low: float
    ci95_high: float
    stability: str


AGGREGATE_COLUMNS: tuple[str, ...] = (
    "metric",
    "n_seeds",
    "mean",
    "std",
    "min",
    "max",
    "ci95_low",
    "ci95_high",
    "stability",
)


def _classify_stability(values: list[float], *, is_rate: bool) -> str:
    if len(values) < 2:
        return "single_seed"
    value_range = max(values) - min(values)
    mean = statistics.mean(values)
    if mean == 0.0:
        cv = 0.0 if value_range == 0.0 else float("inf")
    else:
        cv = statistics.pstdev(values) / abs(mean)
    if is_rate:
        if value_range <= 0.02:
            return "stable"
        if value_range <= 0.10:
            return "moderate"
        return "seed_sensitive"
    if cv <= 0.05:
        return "stable"
    if cv <= 0.15:
        return "moderate"
    return "seed_sensitive"


def aggregate_numeric_across_seeds(
    per_seed_values: dict[int, float],
    metric: str,
    *,
    is_rate: bool = True,
) -> NumericAggregate:
    """Compute mean, dispersion, bootstrap CI, and stability label."""
    values = [per_seed_values[seed] for seed in sorted(per_seed_values)]
    n_seeds = len(values)
    mean = statistics.mean(values)
    std = statistics.pstdev(values) if n_seeds > 1 else 0.0
    ci_row = bootstrap_mean_ci(
        values,
        metric,
        group="multiseed",
        partition="cross_seed",
    )
    return NumericAggregate(
        metric=metric,
        n_seeds=n_seeds,
        mean=round(mean, 6),
        std=round(std, 6),
        minimum=round(min(values), 6),
        maximum=round(max(values), 6),
        ci95_low=round(ci_row.ci95_low, 6),
        ci95_high=round(ci_row.ci95_high, 6),
        stability=_classify_stability(values, is_rate=is_rate),
    )


def write_aggregate_csv(path: Path, aggregates: list[NumericAggregate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=AGGREGATE_COLUMNS)
        writer.writeheader()
        for row in aggregates:
            writer.writerow(
                {
                    "metric": row.metric,
                    "n_seeds": row.n_seeds,
                    "mean": row.mean,
                    "std": row.std,
                    "min": row.minimum,
                    "max": row.maximum,
                    "ci95_low": row.ci95_low,
                    "ci95_high": row.ci95_high,
                    "stability": row.stability,
                }
            )


def aggregates_to_dicts(aggregates: list[NumericAggregate]) -> list[dict[str, Any]]:
    return [
        {
            "metric": row.metric,
            "n_seeds": row.n_seeds,
            "mean": row.mean,
            "std": row.std,
            "min": row.minimum,
            "max": row.maximum,
            "ci95_low": row.ci95_low,
            "ci95_high": row.ci95_high,
            "stability": row.stability,
        }
        for row in aggregates
    ]


def write_interpretation_markdown(
    path: Path,
    *,
    title: str,
    aggregates: list[NumericAggregate],
    notes: list[str],
) -> None:
    lines = [f"# {title}", ""]
    for row in aggregates:
        is_rate = row.metric.endswith("_rate") or "crr" in row.metric
        if is_rate:
            display = f"{row.mean * 100:.2f}%"
        elif row.metric == "saturation_inflation_pp":
            display = f"{row.mean:.1f} pp"
        else:
            display = f"{row.mean:.1f}"
        lines.append(
            f"- **{row.metric}**: mean {display} "
            f"(std {row.std:.4f}, range [{row.minimum:.4f}, {row.maximum:.4f}], "
            f"95% CI [{row.ci95_low:.4f}, {row.ci95_high:.4f}]) — **{row.stability}**"
        )
    lines.extend(["", "## Notes", ""])
    lines.extend(f"- {note}" for note in notes)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_study_manifest(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def pct_label(value: float) -> str:
    return f"{value * 100:.2f}\\%"


def write_aggregate_latex_table(
    path: Path,
    aggregates: list[NumericAggregate],
    *,
    caption: str,
    label: str,
) -> None:
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        "\\begin{tabular}{@{}lrrrrrrl@{}}",
        "\\toprule",
        "Metric & $n$ & Mean & Std & Min & Max & 95\\% CI & Stability \\\\",
        "\\midrule",
    ]
    for row in aggregates:
        is_rate = row.metric.endswith("_rate") or "repair" in row.metric or "inflation" in row.metric
        if is_rate and row.metric != "saturation_inflation_pp":
            mean_s = pct_label(row.mean)
            std_s = f"{row.std * 100:.2f}"
            min_s = pct_label(row.minimum)
            max_s = pct_label(row.maximum)
            ci_s = f"[{row.ci95_low * 100:.1f}, {row.ci95_high * 100:.1f}]"
        elif row.metric == "saturation_inflation_pp":
            mean_s = f"{row.mean:.1f}"
            std_s = f"{row.std:.1f}"
            min_s = f"{row.minimum:.1f}"
            max_s = f"{row.maximum:.1f}"
            ci_s = f"[{row.ci95_low:.1f}, {row.ci95_high:.1f}]"
        else:
            mean_s = f"{row.mean:.1f}"
            std_s = f"{row.std:.1f}"
            min_s = f"{row.minimum:.1f}"
            max_s = f"{row.maximum:.1f}"
            ci_s = f"[{row.ci95_low:.1f}, {row.ci95_high:.1f}]"
        name = row.metric.replace("_", "\\_")
        lines.append(
            f"{name} & {row.n_seeds} & {mean_s} & {std_s} & {min_s} & {max_s} & {ci_s} & {row.stability} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def try_plot_multiseed_bars(
    path: Path,
    per_seed_rows: list[dict[str, Any]],
    metrics: tuple[str, ...],
) -> bool:
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return False

    seeds = [int(row["cohort_seed"]) for row in per_seed_rows]
    fig, axes = plt.subplots(1, len(metrics), figsize=(4 * len(metrics), 4), squeeze=False)
    for index, metric in enumerate(metrics):
        ax = axes[0, index]
        values = [float(row[metric]) for row in per_seed_rows]
        ax.bar([str(seed) for seed in seeds], [value * 100 for value in values])
        ax.set_title(metric.replace("_", " "))
        ax.set_xlabel("Cohort seed")
        ax.set_ylabel("%")
        ax.tick_params(axis="x", rotation=45)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)
    return True
