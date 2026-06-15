#!/usr/bin/env python3
"""Tests for the 20-case STVR replication vignette."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fsmrepairbench.replication_vignette import (
    COHORT_SHA256,
    COHORT_SIZE,
    build_headline_metrics,
    pin_replication_vignette_cohort,
    select_replication_vignette_cohort,
    verify_replication_vignette,
)

DATASET = Path(__file__).resolve().parents[1] / "data" / "fsmrepairbench_1k"
ARTIFACT = Path(__file__).resolve().parents[2] / "paper1" / "artifact" / "replication_vignette_20"


@pytest.mark.skipif(not DATASET.is_dir(), reason="Zenodo dataset not present")
def test_select_replication_vignette_cohort_size_and_balance() -> None:
    case_ids = select_replication_vignette_cohort(DATASET)
    assert len(case_ids) == COHORT_SIZE
    assert len(set(case_ids)) == COHORT_SIZE


@pytest.mark.skipif(not DATASET.is_dir(), reason="Zenodo dataset not present")
def test_pin_replication_vignette_cohort_matches_frozen_digest() -> None:
    txt_path, json_path = pin_replication_vignette_cohort(DATASET)
    digest = hashlib.sha256(txt_path.read_bytes()).hexdigest()
    assert digest == COHORT_SHA256
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["sha256"] == COHORT_SHA256
    assert payload["cohort_size"] == COHORT_SIZE


@pytest.mark.skipif(not (ARTIFACT / "VIGNETTE.sha256").is_file(), reason="vignette not built")
def test_frozen_vignette_checksums_and_headline_metrics() -> None:
    errors = verify_replication_vignette(ARTIFACT)
    assert errors == []

    frozen = json.loads(
        (ARTIFACT / "frozen_exports" / "headline_metrics.json").read_text(encoding="utf-8")
    )
    assert frozen["cohort_size"] == COHORT_SIZE
    assert frozen["detection"]["overall_detection_rate"] == 0.5
    assert frozen["repair"]["baseline_missing_transition"]["complete_repair_rate_detectable_only"] == 0.5


@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "results" / "replication_vignette_20").is_dir(),
    reason="vignette results not present",
)
def test_live_results_match_frozen_headline_metrics() -> None:
    results = Path(__file__).resolve().parents[1] / "results" / "replication_vignette_20"
    frozen = json.loads(
        (ARTIFACT / "frozen_exports" / "headline_metrics.json").read_text(encoding="utf-8")
    )
    assert build_headline_metrics(results) == frozen
