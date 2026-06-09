"""Statistical tests for experiment pipeline comparisons."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

StatisticalTestName = Literal[
    "mann_whitney",
    "wilcoxon",
    "cliffs_delta",
    "cohens_d",
]


@dataclass(frozen=True)
class StatisticalTestResult:
    """Outcome of one statistical comparison."""

    test: StatisticalTestName
    group_a: str
    group_b: str
    metric: str
    statistic: float
    p_value: float | None
    effect_size: float
    effect_label: str
    n_a: int
    n_b: int
    significant: bool
    notes: str = ""

    def to_csv_row(self) -> dict[str, object]:
        return {
            "test": self.test,
            "group_a": self.group_a,
            "group_b": self.group_b,
            "metric": self.metric,
            "statistic": round(self.statistic, 6),
            "p_value": "" if self.p_value is None else round(self.p_value, 6),
            "effect_size": round(self.effect_size, 6),
            "effect_label": self.effect_label,
            "n_a": self.n_a,
            "n_b": self.n_b,
            "significant": int(self.significant),
            "notes": self.notes,
        }


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _std(values: list[float], *, ddof: int = 1) -> float:
    if len(values) <= ddof:
        return 0.0
    avg = _mean(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - ddof)
    return math.sqrt(variance)


def cohens_d(group_a: list[float], group_b: list[float]) -> float:
    """Compute Cohen's d for two independent samples."""
    if len(group_a) < 2 or len(group_b) < 2:
        return 0.0
    mean_a = _mean(group_a)
    mean_b = _mean(group_b)
    var_a = sum((value - mean_a) ** 2 for value in group_a) / (len(group_a) - 1)
    var_b = sum((value - mean_b) ** 2 for value in group_b) / (len(group_b) - 1)
    pooled = math.sqrt(((len(group_a) - 1) * var_a + (len(group_b) - 1) * var_b) / (len(group_a) + len(group_b) - 2))
    if pooled == 0.0:
        return 0.0
    return (mean_a - mean_b) / pooled


def cliffs_delta(group_a: list[float], group_b: list[float]) -> float:
    """Compute Cliff's delta effect size."""
    if not group_a or not group_b:
        return 0.0
    greater = sum(1 for left in group_a for right in group_b if left > right)
    less = sum(1 for left in group_a for right in group_b if left < right)
    return (greater - less) / (len(group_a) * len(group_b))


def _interpret_cohens_d(value: float) -> str:
    magnitude = abs(value)
    if magnitude < 0.2:
        return "negligible"
    if magnitude < 0.5:
        return "small"
    if magnitude < 0.8:
        return "medium"
    return "large"


def _interpret_cliffs_delta(value: float) -> str:
    magnitude = abs(value)
    if magnitude < 0.147:
        return "negligible"
    if magnitude < 0.33:
        return "small"
    if magnitude < 0.474:
        return "medium"
    return "large"


def _assign_ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    index = 0
    while index < len(indexed):
        start = index
        while index + 1 < len(indexed) and indexed[index + 1][1] == indexed[start][1]:
            index += 1
        avg_rank = (start + index + 2) / 2.0
        for position in range(start, index + 1):
            ranks[indexed[position][0]] = avg_rank
        index += 1
    return ranks


def mann_whitney_u(group_a: list[float], group_b: list[float]) -> tuple[float, float | None]:
    """Return Mann-Whitney U statistic and two-sided p-value when SciPy is available."""
    if len(group_a) < 1 or len(group_b) < 1:
        return 0.0, None

    try:
        from scipy.stats import mannwhitneyu

        result = mannwhitneyu(group_a, group_b, alternative="two-sided")
        return float(result.statistic), float(result.pvalue)
    except ImportError:
        combined = [(value, 0) for value in group_a] + [(value, 1) for value in group_b]
        values_only = [value for value, _ in combined]
        ranks = _assign_ranks(values_only)
        rank_a = sum(rank for (_, group), rank in zip(combined, ranks, strict=True) if group == 0)
        u_a = rank_a - (len(group_a) * (len(group_a) + 1) / 2.0)
        u_b = len(group_a) * len(group_b) - u_a
        return min(u_a, u_b), None


def wilcoxon_signed_rank(differences: list[float]) -> tuple[float, float | None]:
    """Return Wilcoxon signed-rank statistic and two-sided p-value when SciPy is available."""
    non_zero = [value for value in differences if abs(value) > 1e-12]
    if len(non_zero) < 1:
        return 0.0, None

    try:
        from scipy.stats import wilcoxon

        result = wilcoxon(non_zero, alternative="two-sided")
        return float(result.statistic), float(result.pvalue)
    except ImportError:
        abs_values = [abs(value) for value in non_zero]
        ranks = _assign_ranks(abs_values)
        statistic = sum(
            rank if value > 0 else -rank
            for value, rank in zip(non_zero, ranks, strict=True)
        )
        return abs(statistic), None


def compare_independent_groups(
    *,
    group_a: str,
    group_b: str,
    metric: str,
    values_a: list[float],
    values_b: list[float],
    alpha: float = 0.05,
) -> tuple[StatisticalTestResult, StatisticalTestResult, StatisticalTestResult, StatisticalTestResult]:
    """Run Mann-Whitney, Cohen's d, and Cliff's delta for independent samples."""
    u_stat, p_mw = mann_whitney_u(values_a, values_b)
    d_value = cohens_d(values_a, values_b)
    delta_value = cliffs_delta(values_a, values_b)

    mann_whitney = StatisticalTestResult(
        test="mann_whitney",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=u_stat,
        p_value=p_mw,
        effect_size=d_value,
        effect_label=_interpret_cohens_d(d_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=p_mw is not None and p_mw < alpha,
        notes="" if p_mw is not None else "SciPy unavailable; p-value not computed",
    )
    cohens = StatisticalTestResult(
        test="cohens_d",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=d_value,
        p_value=None,
        effect_size=d_value,
        effect_label=_interpret_cohens_d(d_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=abs(d_value) >= 0.5,
    )
    cliffs = StatisticalTestResult(
        test="cliffs_delta",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=delta_value,
        p_value=None,
        effect_size=delta_value,
        effect_label=_interpret_cliffs_delta(delta_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=abs(delta_value) >= 0.33,
    )
    wilcoxon_result = StatisticalTestResult(
        test="wilcoxon",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=0.0,
        p_value=None,
        effect_size=0.0,
        effect_label="not_applicable",
        n_a=len(values_a),
        n_b=len(values_b),
        significant=False,
        notes="Independent samples; Wilcoxon not applicable",
    )
    return mann_whitney, wilcoxon_result, cliffs, cohens


def compare_paired_groups(
    *,
    group_a: str,
    group_b: str,
    metric: str,
    values_a: list[float],
    values_b: list[float],
    alpha: float = 0.05,
) -> tuple[StatisticalTestResult, StatisticalTestResult, StatisticalTestResult, StatisticalTestResult]:
    """Run Wilcoxon signed-rank and effect sizes for paired samples."""
    if len(values_a) != len(values_b):
        msg = "Paired comparison requires equal sample sizes"
        raise ValueError(msg)

    differences = [left - right for left, right in zip(values_a, values_b, strict=True)]
    w_stat, p_w = wilcoxon_signed_rank(differences)
    d_value = cohens_d(values_a, values_b)
    delta_value = cliffs_delta(values_a, values_b)

    wilcoxon_result = StatisticalTestResult(
        test="wilcoxon",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=w_stat,
        p_value=p_w,
        effect_size=d_value,
        effect_label=_interpret_cohens_d(d_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=p_w is not None and p_w < alpha,
        notes="" if p_w is not None else "SciPy unavailable; p-value not computed",
    )
    mann_whitney = StatisticalTestResult(
        test="mann_whitney",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=0.0,
        p_value=None,
        effect_size=d_value,
        effect_label=_interpret_cohens_d(d_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=False,
        notes="Paired samples; Mann-Whitney not used",
    )
    cohens = StatisticalTestResult(
        test="cohens_d",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=d_value,
        p_value=None,
        effect_size=d_value,
        effect_label=_interpret_cohens_d(d_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=abs(d_value) >= 0.5,
    )
    cliffs = StatisticalTestResult(
        test="cliffs_delta",
        group_a=group_a,
        group_b=group_b,
        metric=metric,
        statistic=delta_value,
        p_value=None,
        effect_size=delta_value,
        effect_label=_interpret_cliffs_delta(delta_value),
        n_a=len(values_a),
        n_b=len(values_b),
        significant=abs(delta_value) >= 0.33,
    )
    return mann_whitney, wilcoxon_result, cliffs, cohens
