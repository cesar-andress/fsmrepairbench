"""Manifest integrity verification for frozen campaign exports."""

from __future__ import annotations

from pathlib import Path

import pytest

from fsmrepairbench.manifest_integrity import (
    PAPER_CAMPAIGN_DIRS,
    verify_campaign_manifest,
    verify_paper_campaign_manifests,
)
from fsmrepairbench.golden_exports import default_paper_results_dir


@pytest.fixture(scope="module")
def paper_results_dir() -> Path:
    results_dir = default_paper_results_dir()
    if not results_dir.is_dir():
        pytest.skip(f"Frozen paper results not found: {results_dir}")
    return results_dir


@pytest.fixture(scope="module")
def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("campaign_dir", PAPER_CAMPAIGN_DIRS)
def test_paper_campaign_manifest_integrity(
    paper_results_dir: Path,
    repo_root: Path,
    campaign_dir: str,
) -> None:
    manifest_path = paper_results_dir / campaign_dir / "manifest.json"
    if not manifest_path.is_file():
        pytest.skip(f"No manifest for {campaign_dir}")

    result = verify_campaign_manifest(
        manifest_path,
        repo_root=repo_root,
        verify_output_files=False,
    )
    assert result.passed, "\n".join(result.errors)


def test_all_paper_campaign_manifests_pass_integrity(
    paper_results_dir: Path,
    repo_root: Path,
) -> None:
    results = verify_paper_campaign_manifests(paper_results_dir, repo_root=repo_root)
    assert results, "expected at least one campaign manifest under paper1/results"
    failures = [result for result in results if not result.passed]
    assert not failures, "\n\n".join(
        f"{result.manifest_path}:\n" + "\n".join(result.errors) for result in failures
    )


def test_paper_campaign_core_csv_exports_exist(paper_results_dir: Path) -> None:
    required = {
        "baseline_repair_C1": ("summary.csv", "leaderboard.csv"),
        "rq3_localization_1k": ("summary.csv", "per_case_results.csv"),
        "rq4_coupling_250": ("summary.csv", "coupling_metrics.csv", "per_case_results.csv"),
        "oracle_depth_ablation": ("summary.csv", "depth_summary.csv", "per_case_results.csv"),
    }
    missing: list[str] = []
    for campaign_dir, files in required.items():
        root = paper_results_dir / campaign_dir
        if not root.is_dir():
            continue
        for name in files:
            if not (root / name).is_file():
                missing.append(f"{campaign_dir}/{name}")
    assert not missing, "Missing core CSV exports:\n" + "\n".join(missing)
