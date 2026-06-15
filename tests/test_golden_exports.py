"""Unit tests for golden export verification helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.golden_exports import (
    format_golden_failure_report,
    golden_manifest_path,
    load_artifacts_sha256_entries,
    load_golden_manifest,
    verify_golden_manifest_file,
    verify_paper_artifacts_sha256,
)

FIXTURES = Path(__file__).parent / "fixtures" / "golden"


def test_load_golden_manifest_requires_core_fields(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text('{"campaign_id": "c1"}', encoding="utf-8")
    with pytest.raises(ValueError, match="missing fields"):
        load_golden_manifest(bad)


def test_load_artifacts_sha256_entries(tmp_path: Path) -> None:
    checksum = tmp_path / "ARTIFACTS.sha256"
    checksum.write_text(
        "# demo\n"
        "abc123  campaign/summary.csv\n"
        "def456  campaign/figures/plot.png\n",
        encoding="utf-8",
    )
    entries = load_artifacts_sha256_entries(checksum)
    assert entries == [("abc123", "campaign/summary.csv"), ("def456", "campaign/figures/plot.png")]


def test_verify_paper_artifacts_sha256_detects_mismatch(tmp_path: Path) -> None:
    results = tmp_path / "results"
    campaign = results / "demo"
    campaign.mkdir(parents=True)
    csv_path = campaign / "summary.csv"
    csv_path.write_text("metric,value\ncase_count,1\n", encoding="utf-8")
    checksum = results / "ARTIFACTS.sha256"
    checksum.write_text("deadbeef  demo/summary.csv\n", encoding="utf-8")
    result = verify_paper_artifacts_sha256(results, checksum_path=checksum)
    assert not result.passed
    assert result.failures[0].relative_path == "demo/summary.csv"


def test_format_golden_failure_report_includes_regeneration_hint() -> None:
    manifest_path = golden_manifest_path("c1_baseline_repair.json")
    result = verify_golden_manifest_file(
        manifest_path,
        results_dir=Path(__file__).resolve().parents[2].parent / "paper1" / "results",
    )
    report = format_golden_failure_report(result)
    assert "update_golden_campaign_manifests.py" in report
    if result.passed:
        assert "Golden export regression failed" not in report
    else:
        assert "Golden export regression failed" in report
