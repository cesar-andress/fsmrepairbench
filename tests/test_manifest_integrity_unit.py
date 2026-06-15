"""Unit tests for manifest integrity helpers."""

from __future__ import annotations

import json
from pathlib import Path

from fsmrepairbench.freeze import sha256_file
from fsmrepairbench.manifest_integrity import verify_campaign_manifest


def test_verify_campaign_manifest_accepts_directory_output_files(tmp_path: Path) -> None:
    campaign = tmp_path / "campaign"
    figures = campaign / "figures"
    figures.mkdir(parents=True)
    (figures / "plot.png").write_bytes(b"png")
    manifest = {
        "release_label": "test",
        "zenodo_doi": "10.5281/zenodo.0",
        "cohort_sha256": "",
        "regeneration_commands": [],
        "output_files": ["figures/", "figures/plot.png", "manifest.json"],
    }
    manifest_path = campaign / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_campaign_manifest(manifest_path)
    assert result.passed


def test_verify_campaign_manifest_detects_cohort_sha_mismatch(tmp_path: Path) -> None:
    cohort = tmp_path / "cohort.txt"
    cohort.write_text("case_a\n", encoding="utf-8")
    digest = sha256_file(cohort)
    campaign = tmp_path / "campaign"
    campaign.mkdir()
    manifest = {
        "release_label": "test",
        "zenodo_doi": "10.5281/zenodo.0",
        "cohort_sha256": "deadbeef",
        "cohort_path": str(cohort),
        "regeneration_commands": [],
        "output_files": [],
    }
    manifest_path = campaign / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    result = verify_campaign_manifest(manifest_path)
    assert not result.passed
    assert any("cohort_sha256 mismatch" in error for error in result.errors)
