"""Golden regression tests for frozen C1, RQ3, RQ4, and C3 campaign exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.golden_exports import (
    DEFAULT_CAMPAIGN_MANIFESTS,
    default_paper_results_dir,
    format_golden_failure_report,
    golden_manifest_path,
    verify_golden_manifest_file,
)

pytestmark = pytest.mark.golden


@pytest.fixture(scope="module")
def paper_results_dir() -> Path:
    results_dir = default_paper_results_dir()
    if not results_dir.is_dir():
        pytest.skip(f"Frozen paper results not found: {results_dir}")
    return results_dir


@pytest.mark.parametrize(
    ("campaign_id", "manifest_name"),
    DEFAULT_CAMPAIGN_MANIFESTS,
    ids=[campaign_id for campaign_id, _manifest in DEFAULT_CAMPAIGN_MANIFESTS],
)
def test_frozen_campaign_exports_match_golden_manifest(
    campaign_id: str,
    manifest_name: str,
    paper_results_dir: Path,
) -> None:
    manifest_path = golden_manifest_path(manifest_name)
    assert manifest_path.is_file(), f"Missing golden manifest fixture: {manifest_path}"

    result = verify_golden_manifest_file(
        manifest_path,
        results_dir=paper_results_dir,
    )
    assert result.campaign_id == campaign_id
    assert result.passed, format_golden_failure_report(result)


def test_golden_manifests_reference_existing_campaign_dirs(paper_results_dir: Path) -> None:
    missing: list[str] = []
    for _campaign_id, manifest_name in DEFAULT_CAMPAIGN_MANIFESTS:
        manifest_path = golden_manifest_path(manifest_name)
        result = verify_golden_manifest_file(manifest_path, results_dir=paper_results_dir)
        if not result.results_dir.is_dir():
            missing.append(str(result.results_dir))
    assert not missing, "Missing campaign result directories:\n" + "\n".join(missing)
