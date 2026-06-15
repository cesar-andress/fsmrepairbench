"""Seed reproducibility tests for coupling and tool campaigns."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from fsmrepairbench.coupling_campaign import (
    build_operator_chain,
    build_random_operator_chain,
    load_per_case_results_csv,
    run_coupling_campaign,
)
from fsmrepairbench.manifest_integrity import csv_rows_stable_digest

FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def _per_case_digest(rows_path: Path) -> str:
    rows = load_per_case_results_csv(rows_path)
    payload = json.dumps([row.to_dict() for row in rows], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_coupling_campaign_seed_44_is_reproducible(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")

    digests: list[str] = []
    for run_idx in range(2):
        out = tmp_path / f"run_{run_idx}"
        subset = tmp_path / f"subset_{run_idx}"
        result = run_coupling_campaign(
            FIXTURE_DATASET,
            output_dir=out,
            cohort_path=cohort_path,
            subset_dir=subset,
            campaign_seed=44,
            use_symlinks=False,
        )
        digests.append(_per_case_digest(result.per_case_path))

    assert digests[0] == digests[1]


def test_coupling_campaign_different_seeds_can_differ(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")

    digests: dict[int, str] = {}
    for seed in (44, 45):
        out = tmp_path / f"seed_{seed}"
        subset = tmp_path / f"subset_{seed}"
        result = run_coupling_campaign(
            FIXTURE_DATASET,
            output_dir=out,
            cohort_path=cohort_path,
            subset_dir=subset,
            campaign_seed=seed,
            use_symlinks=False,
        )
        digests[seed] = _per_case_digest(result.per_case_path)

    assert digests[44] != digests[45]


@pytest.mark.parametrize(
    ("primary", "order", "case_id", "seed"),
    [
        ("wrong_target", 3, "case_000001", 44),
        ("guard_flip", 2, "case_000002", 44),
        ("missing_transition", 3, "case_000003", 7),
    ],
)
def test_operator_chain_is_seed_deterministic(
    primary: str,
    order: int,
    case_id: str,
    seed: int,
) -> None:
    chain_a = build_operator_chain(primary, order, case_id, seed)
    chain_b = build_operator_chain(primary, order, case_id, seed)
    assert chain_a == chain_b
    assert chain_a[0] == primary


@pytest.mark.parametrize("secondary_seed", (0, 3, 9))
def test_random_operator_chain_is_secondary_seed_deterministic(secondary_seed: int) -> None:
    chain_a = build_random_operator_chain("wrong_target", 3, "case_000001", secondary_seed)
    chain_b = build_random_operator_chain("wrong_target", 3, "case_000001", secondary_seed)
    assert chain_a == chain_b


def test_regenerated_coupling_metrics_match_per_case_source(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    subset = tmp_path / "subset"
    result = run_coupling_campaign(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        subset_dir=subset,
        campaign_seed=44,
        use_symlinks=False,
    )

    from fsmrepairbench.coupling_campaign import regenerate_coupling_derived_exports

    before_metrics_digest = csv_rows_stable_digest(result.coupling_metrics_path)
    regenerate_coupling_derived_exports(out)
    after_metrics_digest = csv_rows_stable_digest(out / "coupling_metrics.csv")
    assert before_metrics_digest == after_metrics_digest

    summary_rows = list(csv.DictReader((out / "summary.csv").open(encoding="utf-8")))
    assert any(row["metric"] == "campaign_seed" and row["value"] == "44" for row in summary_rows)
