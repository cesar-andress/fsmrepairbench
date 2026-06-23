"""Tests for v0.2.0-analysis pipeline verification helpers."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
PAPER1 = REPO.parent / "paper1"
SCRIPTS = PAPER1 / "scripts"
sys_path = REPO / "src"


@pytest.fixture(autouse=True)
def _import_path(monkeypatch: pytest.MonkeyPatch) -> None:
    import sys

    for entry in (str(sys_path), str(PAPER1), str(SCRIPTS)):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def test_verify_campaign_manifest_integrity_passes_for_c1(tmp_path: Path) -> None:
    from replay_v0_2_analysis_pipeline import verify_campaign_manifest_integrity

    export_dir = tmp_path / "baseline_repair_C1"
    export_dir.mkdir()
    manifest = {
        "release_label": "v0.2.0-analysis",
        "zenodo_doi": "10.5281/zenodo.20602577",
        "cohort_file": "data/fsmrepairbench_1k/analysis_cohort_1k.txt",
        "cohort_sha256": "c03c4d5981259510bccfced987c5175f28058d7bdccc164e7ce2ba22410f04f8",
        "regeneration_commands": ["fsmrepairbench export-c1-baseline-repair ..."],
    }
    (export_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    step = verify_campaign_manifest_integrity(
        results_dir=tmp_path,
        campaign_id="c1",
        golden_manifest_name="c1_baseline_repair.json",
    )
    assert step.passed, step.failures


def test_verify_campaign_manifest_integrity_fails_on_doi(tmp_path: Path) -> None:
    from replay_v0_2_analysis_pipeline import verify_campaign_manifest_integrity

    export_dir = tmp_path / "baseline_repair_C1"
    export_dir.mkdir()
    manifest = {
        "release_label": "v0.2.0-analysis",
        "zenodo_doi": "10.5281/zenodo.invalid",
        "cohort_file": "data/fsmrepairbench_1k/analysis_cohort_1k.txt",
        "cohort_sha256": "c03c4d5981259510bccfced987c5175f28058d7bdccc164e7ce2ba22410f04f8",
        "regeneration_commands": [],
    }
    (export_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    step = verify_campaign_manifest_integrity(
        results_dir=tmp_path,
        campaign_id="c1",
        golden_manifest_name="c1_baseline_repair.json",
    )
    assert not step.passed
    assert any("zenodo_doi" in failure for failure in step.failures)
