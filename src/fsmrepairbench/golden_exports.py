"""Golden regression checks for frozen benchmark campaign exports."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsmrepairbench.freeze import sha256_file

GOLDEN_FIXTURES_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "golden"
DEFAULT_CAMPAIGN_MANIFESTS: tuple[tuple[str, str], ...] = (
    ("c1", "c1_baseline_repair.json"),
    ("rq3", "rq3_localization.json"),
    ("rq4", "rq4_coupling.json"),
    ("c3", "c3_oracle_depth_ablation.json"),
    ("partitions", "campaign_metrics_by_partition.json"),
    ("paired", "campaign_paired_comparison.json"),
)
PAPER_ARTIFACTS_SHA256 = "ARTIFACTS.sha256"


@dataclass(frozen=True)
class GoldenArtifactFailure:
    """One artifact hash mismatch."""

    relative_path: str
    expected_sha256: str
    actual_sha256: str | None
    detail: str


@dataclass(frozen=True)
class GoldenMetricFailure:
    """One headline metric mismatch."""

    description: str
    file: str
    expected: float
    actual: float | None
    detail: str


@dataclass(frozen=True)
class GoldenCampaignVerification:
    """Outcome of verifying one campaign manifest."""

    campaign_id: str
    campaign_label: str
    results_subdir: str
    results_dir: Path
    artifact_failures: tuple[GoldenArtifactFailure, ...]
    metric_failures: tuple[GoldenMetricFailure, ...]
    artifacts_checked: int
    metrics_checked: int

    @property
    def passed(self) -> bool:
        return not self.artifact_failures and not self.metric_failures


@dataclass(frozen=True)
class PaperArtifactsVerification:
    """Outcome of verifying ``paper1/results/ARTIFACTS.sha256`` against disk."""

    checksum_path: Path
    results_dir: Path
    entries_checked: int
    failures: tuple[GoldenArtifactFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class PaperGoldenVerificationReport:
    """Combined outcome for campaign manifests and checksum exports."""

    results_dir: Path
    campaign_results: tuple[GoldenCampaignVerification, ...]
    artifacts_verification: PaperArtifactsVerification | None
    cohort_manifests_ok: bool | None
    cohort_manifests_detail: str

    @property
    def passed(self) -> bool:
        campaigns_ok = all(result.passed for result in self.campaign_results)
        artifacts_ok = self.artifacts_verification is None or self.artifacts_verification.passed
        cohort_ok = self.cohort_manifests_ok is None or self.cohort_manifests_ok
        return campaigns_ok and artifacts_ok and cohort_ok


def repo_root() -> Path:
    """Return the ``fsmrepairbench`` package repository root."""
    return Path(__file__).resolve().parents[2]


def default_paper_results_dir() -> Path:
    """Return the default frozen export directory under ``paper1/results``."""
    override = __import__("os").environ.get("FSMREPAIRBENCH_GOLDEN_RESULTS_DIR")
    if override:
        return Path(override).resolve()
    return repo_root().parent / "paper1" / "results"


def golden_manifest_path(name: str) -> Path:
    """Resolve a golden manifest fixture by filename."""
    return GOLDEN_FIXTURES_DIR / name


def load_golden_manifest(path: Path) -> dict[str, Any]:
    """Load a golden campaign manifest JSON fixture."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = (
        "campaign_id",
        "campaign_label",
        "results_subdir",
        "artifacts",
        "metrics",
    )
    missing = [field for field in required if field not in payload]
    if missing:
        msg = f"Golden manifest {path} missing fields: {', '.join(missing)}"
        raise ValueError(msg)
    return payload


def _read_csv_metric(
    csv_path: Path,
    metric_spec: dict[str, Any],
) -> float:
    metric_name = metric_spec.get("metric")
    lookup = metric_spec.get("lookup")
    column = metric_spec.get("column")
    mutation_order = metric_spec.get("mutation_order")

    with csv_path.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    if lookup is not None and column is not None:
        for row in rows:
            if all(str(row.get(key, "")) == str(value) for key, value in lookup.items()):
                return float(row[column])
        msg = f"No CSV row matching {lookup!r} in {csv_path}"
        raise KeyError(msg)

    if metric_name is not None:
        for row in rows:
            if row.get("metric") != metric_name:
                continue
            if mutation_order is not None and row.get("mutation_order") != str(mutation_order):
                continue
            if mutation_order is None and row.get("mutation_order"):
                if row.get("primary_operator"):
                    continue
                if row.get("mutation_order"):
                    continue
            if row.get("bucket"):
                continue
            return float(row["value"])
        msg = f"Metric {metric_name!r} not found in {csv_path}"
        raise KeyError(msg)

    msg = f"Unsupported metric spec for {csv_path}: {metric_spec!r}"
    raise ValueError(msg)


def verify_golden_campaign(
    manifest: dict[str, Any],
    *,
    results_dir: Path,
) -> GoldenCampaignVerification:
    """Verify frozen exports against a golden campaign manifest."""
    campaign_root = results_dir / str(manifest["results_subdir"])
    artifact_failures: list[GoldenArtifactFailure] = []
    metric_failures: list[GoldenMetricFailure] = []

    for artifact in manifest["artifacts"]:
        relative_path = str(artifact["relative_path"])
        expected_sha256 = str(artifact["sha256"])
        target = campaign_root / relative_path
        if not target.is_file():
            artifact_failures.append(
                GoldenArtifactFailure(
                    relative_path=relative_path,
                    expected_sha256=expected_sha256,
                    actual_sha256=None,
                    detail=f"missing export file: {target}",
                )
            )
            continue
        actual_sha256 = sha256_file(target)
        if actual_sha256 != expected_sha256:
            artifact_failures.append(
                GoldenArtifactFailure(
                    relative_path=relative_path,
                    expected_sha256=expected_sha256,
                    actual_sha256=actual_sha256,
                    detail=(
                        "SHA-256 mismatch; regenerate exports and update "
                        f"tests/fixtures/golden/{manifest['campaign_id']}_*.json"
                    ),
                )
            )

    for metric_spec in manifest["metrics"]:
        description = str(metric_spec["description"])
        relative_file = str(metric_spec["file"])
        expected = float(metric_spec["expected"])
        tolerance = float(metric_spec.get("tolerance", 1e-9))
        csv_path = campaign_root / relative_file
        if not csv_path.is_file():
            metric_failures.append(
                GoldenMetricFailure(
                    description=description,
                    file=relative_file,
                    expected=expected,
                    actual=None,
                    detail=f"missing metric source CSV: {csv_path}",
                )
            )
            continue
        try:
            actual = _read_csv_metric(csv_path, metric_spec)
        except (KeyError, ValueError) as exc:
            metric_failures.append(
                GoldenMetricFailure(
                    description=description,
                    file=relative_file,
                    expected=expected,
                    actual=None,
                    detail=str(exc),
                )
            )
            continue
        if abs(actual - expected) > tolerance:
            metric_failures.append(
                GoldenMetricFailure(
                    description=description,
                    file=relative_file,
                    expected=expected,
                    actual=actual,
                    detail=(
                        f"expected {expected:.12g}, got {actual:.12g} "
                        f"(tolerance {tolerance:.0g})"
                    ),
                )
            )

    return GoldenCampaignVerification(
        campaign_id=str(manifest["campaign_id"]),
        campaign_label=str(manifest["campaign_label"]),
        results_subdir=str(manifest["results_subdir"]),
        results_dir=campaign_root,
        artifact_failures=tuple(artifact_failures),
        metric_failures=tuple(metric_failures),
        artifacts_checked=len(manifest["artifacts"]),
        metrics_checked=len(manifest["metrics"]),
    )


def format_golden_failure_report(result: GoldenCampaignVerification) -> str:
    """Render a pytest-friendly failure report for one campaign."""
    lines = [
        f"Golden export regression failed for {result.campaign_label} "
        f"({result.results_subdir}).",
        f"Results directory: {result.results_dir}",
        "",
    ]
    if result.artifact_failures:
        lines.append("Artifact mismatches:")
        for failure in result.artifact_failures:
            lines.append(f"  - {failure.relative_path}: {failure.detail}")
            lines.append(f"      expected SHA-256: {failure.expected_sha256}")
            if failure.actual_sha256 is not None:
                lines.append(f"        actual SHA-256: {failure.actual_sha256}")
        lines.append("")
    if result.metric_failures:
        lines.append("Headline metric mismatches:")
        for failure in result.metric_failures:
            lines.append(f"  - {failure.description} ({failure.file}): {failure.detail}")
        lines.append("")
    manifest_name = next(
        (
            filename
            for _campaign_id, filename in DEFAULT_CAMPAIGN_MANIFESTS
            if _campaign_id == result.campaign_id
        ),
        "<campaign>.json",
    )
    regen = (
        "Regenerate frozen exports, then refresh golden manifests with:\n"
        "  python paper1/scripts/update_golden_campaign_manifests.py"
    )
    lines.extend(
        [
            f"Checked {result.artifacts_checked} artifacts and {result.metrics_checked} metrics.",
            f"Golden manifest fixture: tests/fixtures/golden/{manifest_name}",
            regen,
        ]
    )
    return "\n".join(lines)


def load_artifacts_sha256_entries(checksum_path: Path) -> list[tuple[str, str]]:
    """Parse ``ARTIFACTS.sha256`` into ``(digest, relative_path)`` pairs."""
    if not checksum_path.is_file():
        msg = f"Missing checksum file: {checksum_path}"
        raise FileNotFoundError(msg)
    entries: list[tuple[str, str]] = []
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        digest, relative_path = stripped.split(None, 1)
        entries.append((digest.strip(), relative_path.strip()))
    if not entries:
        msg = f"No checksum entries found in {checksum_path}"
        raise ValueError(msg)
    return entries


def verify_paper_artifacts_sha256(
    results_dir: Path,
    *,
    checksum_path: Path | None = None,
) -> PaperArtifactsVerification:
    """Verify frozen CSV/PNG/LaTeX exports listed in ``ARTIFACTS.sha256``."""
    checksum = (checksum_path or results_dir / PAPER_ARTIFACTS_SHA256).resolve()
    entries = load_artifacts_sha256_entries(checksum)
    failures: list[GoldenArtifactFailure] = []
    for expected_sha256, relative_path in entries:
        target = results_dir / relative_path
        if not target.is_file():
            failures.append(
                GoldenArtifactFailure(
                    relative_path=relative_path,
                    expected_sha256=expected_sha256,
                    actual_sha256=None,
                    detail=f"missing export file: {target}",
                )
            )
            continue
        actual_sha256 = sha256_file(target)
        if actual_sha256 != expected_sha256:
            failures.append(
                GoldenArtifactFailure(
                    relative_path=relative_path,
                    expected_sha256=expected_sha256,
                    actual_sha256=actual_sha256,
                    detail=(
                        "SHA-256 mismatch; refresh checksums with "
                        "python paper1/scripts/generate_artifact_evaluation_package.py"
                    ),
                )
            )
    return PaperArtifactsVerification(
        checksum_path=checksum,
        results_dir=results_dir.resolve(),
        entries_checked=len(entries),
        failures=tuple(failures),
    )


def format_paper_artifacts_failure_report(result: PaperArtifactsVerification) -> str:
    """Render a pytest-friendly failure report for checksum verification."""
    lines = [
        "Paper artifact checksum verification failed "
        f"({result.entries_checked} entries in {result.checksum_path.name}).",
        f"Results directory: {result.results_dir}",
        "",
    ]
    for failure in result.failures:
        lines.append(f"  - {failure.relative_path}: {failure.detail}")
        lines.append(f"      expected SHA-256: {failure.expected_sha256}")
        if failure.actual_sha256 is not None:
            lines.append(f"        actual SHA-256: {failure.actual_sha256}")
    lines.extend(
        [
            "",
            "Refresh checksums with:",
            "  python paper1/scripts/generate_artifact_evaluation_package.py",
            "",
            "Verify independently (no dataset regeneration):",
            "  python paper1/scripts/verify_paper_golden_exports.py",
        ]
    )
    return "\n".join(lines)


def verify_all_paper_golden_exports(
    *,
    results_dir: Path | None = None,
    campaign_manifests: Sequence[tuple[str, str]] = DEFAULT_CAMPAIGN_MANIFESTS,
    verify_artifacts_checksum: bool = True,
    verify_cohort_manifests: bool = False,
) -> PaperGoldenVerificationReport:
    """Verify campaign golden manifests and optional ``ARTIFACTS.sha256`` exports."""
    root = (results_dir or default_paper_results_dir()).resolve()
    campaign_results: list[GoldenCampaignVerification] = []
    for _campaign_id, manifest_name in campaign_manifests:
        manifest_path = golden_manifest_path(manifest_name)
        if not manifest_path.is_file():
            continue
        campaign_results.append(
            verify_golden_manifest_file(manifest_path, results_dir=root)
        )

    artifacts_verification: PaperArtifactsVerification | None = None
    if verify_artifacts_checksum:
        checksum_path = root / PAPER_ARTIFACTS_SHA256
        if checksum_path.is_file():
            artifacts_verification = verify_paper_artifacts_sha256(root, checksum_path=checksum_path)

    cohort_ok: bool | None = None
    cohort_detail = "skipped"
    if verify_cohort_manifests:
        import subprocess
        import sys

        repo = repo_root()
        script = repo.parent / "paper1" / "scripts" / "verify_cohort_manifests.py"
        if script.is_file():
            completed = subprocess.run(
                [sys.executable, str(script)],
                cwd=repo,
                check=False,
                capture_output=True,
                text=True,
            )
            output = ((completed.stdout or "") + (completed.stderr or "")).strip()
            cohort_ok = completed.returncode == 0
            cohort_detail = output.splitlines()[-1] if output else f"exit code {completed.returncode}"
        else:
            cohort_ok = False
            cohort_detail = f"missing verifier script: {script}"

    return PaperGoldenVerificationReport(
        results_dir=root,
        campaign_results=tuple(campaign_results),
        artifacts_verification=artifacts_verification,
        cohort_manifests_ok=cohort_ok,
        cohort_manifests_detail=cohort_detail,
    )


def format_paper_golden_verification_report(report: PaperGoldenVerificationReport) -> str:
    """Render a combined verification report for CLI and pytest."""
    lines = [
        f"Paper golden export verification ({report.results_dir})",
        f"Overall: {'PASS' if report.passed else 'FAIL'}",
        "",
    ]
    for result in report.campaign_results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(
            f"[{status}] {result.campaign_label} "
            f"({result.artifacts_checked} artifacts, {result.metrics_checked} metrics)"
        )
        if not result.passed:
            lines.append(format_golden_failure_report(result))
            lines.append("")
    if report.artifacts_verification is not None:
        artifacts = report.artifacts_verification
        status = "PASS" if artifacts.passed else "FAIL"
        lines.append(
            f"[{status}] ARTIFACTS.sha256 "
            f"({artifacts.entries_checked} CSV/PNG/LaTeX exports)"
        )
        if not artifacts.passed:
            lines.append(format_paper_artifacts_failure_report(artifacts))
            lines.append("")
    if report.cohort_manifests_ok is not None:
        status = "PASS" if report.cohort_manifests_ok else "FAIL"
        lines.append(f"[{status}] Pinned cohort manifests: {report.cohort_manifests_detail}")
    return "\n".join(lines)


def verify_golden_manifest_file(
    manifest_path: Path,
    *,
    results_dir: Path | None = None,
) -> GoldenCampaignVerification:
    """Load and verify one golden manifest fixture."""
    manifest = load_golden_manifest(manifest_path)
    return verify_golden_campaign(
        manifest,
        results_dir=results_dir or default_paper_results_dir(),
    )
