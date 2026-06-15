"""Golden regression tests for all frozen paper1/results SHA-256 exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.golden_exports import (
    DEFAULT_CAMPAIGN_MANIFESTS,
    PAPER_ARTIFACTS_SHA256,
    default_paper_results_dir,
    format_paper_artifacts_failure_report,
    format_paper_golden_verification_report,
    golden_manifest_path,
    load_artifacts_sha256_entries,
    verify_all_paper_golden_exports,
    verify_paper_artifacts_sha256,
)

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def paper_results_dir() -> Path:
    results_dir = default_paper_results_dir()
    if not results_dir.is_dir():
        pytest.skip(f"Frozen paper results not found: {results_dir}")
    return results_dir


def test_paper_artifacts_sha256_matches_frozen_exports(paper_results_dir: Path) -> None:
    checksum_path = paper_results_dir / PAPER_ARTIFACTS_SHA256
    if not checksum_path.is_file():
        pytest.skip(f"Missing checksum file: {checksum_path}")

    entries = load_artifacts_sha256_entries(checksum_path)
    assert entries, "ARTIFACTS.sha256 must list at least one export"

    result = verify_paper_artifacts_sha256(paper_results_dir, checksum_path=checksum_path)
    assert result.passed, format_paper_artifacts_failure_report(result)


@pytest.mark.parametrize(
    ("campaign_id", "manifest_name"),
    DEFAULT_CAMPAIGN_MANIFESTS,
    ids=[campaign_id for campaign_id, _manifest in DEFAULT_CAMPAIGN_MANIFESTS],
)
def test_golden_campaign_manifest_exists(campaign_id: str, manifest_name: str) -> None:
    manifest_path = golden_manifest_path(manifest_name)
    if not manifest_path.is_file():
        pytest.skip(f"Golden manifest not yet pinned: {manifest_path}")
    payload = manifest_path.read_text(encoding="utf-8")
    assert campaign_id in payload


def test_all_paper_golden_exports_pass(paper_results_dir: Path) -> None:
    report = verify_all_paper_golden_exports(
        results_dir=paper_results_dir,
        verify_cohort_manifests=False,
    )
    assert report.passed, format_paper_golden_verification_report(report)
