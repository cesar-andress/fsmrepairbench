"""Tests for experiment statistical comparisons."""

from __future__ import annotations

from fsmrepairbench.experiment_statistics import (
    cliffs_delta,
    cohens_d,
    compare_independent_groups,
    compare_paired_groups,
    mann_whitney_u,
    wilcoxon_signed_rank,
)


def test_cohens_d_and_cliffs_delta() -> None:
    group_a = [1.0, 2.0, 3.0, 4.0]
    group_b = [0.5, 1.0, 1.5, 2.0]
    assert cohens_d(group_a, group_b) > 0.0
    assert cliffs_delta(group_a, group_b) > 0.0


def test_mann_whitney_u_returns_statistic() -> None:
    statistic, p_value = mann_whitney_u([1.0, 2.0, 3.0], [4.0, 5.0, 6.0])
    assert statistic >= 0.0
    assert p_value is None or 0.0 <= p_value <= 1.0


def test_wilcoxon_signed_rank_returns_statistic() -> None:
    statistic, p_value = wilcoxon_signed_rank([1.0, 2.0, 3.0])
    assert statistic >= 0.0
    assert p_value is None or 0.0 <= p_value <= 1.0


def test_compare_independent_groups_emits_four_tests() -> None:
    mw, wil, cliffs, cohens = compare_independent_groups(
        group_a="reference",
        group_b="missing-transition",
        metric="bpr",
        values_a=[0.9, 0.8, 0.85],
        values_b=[0.4, 0.5, 0.45],
    )
    assert mw.test == "mann_whitney"
    assert wil.test == "wilcoxon"
    assert cliffs.test == "cliffs_delta"
    assert cohens.test == "cohens_d"
    assert mw.n_a == 3
    assert mw.n_b == 3


def test_compare_paired_groups_emits_four_tests() -> None:
    mw, wil, cliffs, cohens = compare_paired_groups(
        group_a="reference",
        group_b="missing-transition",
        metric="bpr",
        values_a=[0.9, 0.8, 0.85],
        values_b=[0.4, 0.5, 0.45],
    )
    assert wil.test == "wilcoxon"
    assert mw.notes.startswith("Paired samples")
    assert wil.n_a == 3
    assert cohens.effect_size > 0.0
