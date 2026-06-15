"""Campaign manifest integrity checks for frozen benchmark exports."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsmrepairbench.freeze import sha256_file

REQUIRED_MANIFEST_FIELDS: tuple[str, ...] = (
    "release_label",
    "zenodo_doi",
    "cohort_sha256",
    "regeneration_commands",
    "output_files",
)

PAPER_CAMPAIGN_DIRS: tuple[str, ...] = (
    "baseline_repair_C1",
    "rq3_localization_1k",
    "rq4_coupling_250",
    "oracle_depth_ablation",
)


@dataclass(frozen=True)
class ManifestIntegrityResult:
    """Outcome of verifying one campaign ``manifest.json``."""

    manifest_path: Path
    campaign_dir: Path
    errors: tuple[str, ...]
    csv_artifacts_checked: int

    @property
    def passed(self) -> bool:
        return not self.errors


def _resolve_cohort_path(cohort_path: str, *, repo_root: Path | None) -> Path:
    path = Path(cohort_path)
    if path.is_file():
        return path.resolve()
    if repo_root is not None:
        candidate = (repo_root / path).resolve()
        if candidate.is_file():
            return candidate
    return path


def verify_campaign_manifest(
    manifest_path: Path,
    *,
    repo_root: Path | None = None,
    required_fields: tuple[str, ...] = REQUIRED_MANIFEST_FIELDS,
    verify_output_files: bool = True,
    verify_csv_sha256: bool = True,
) -> ManifestIntegrityResult:
    """Validate structure, cohort pin, listed outputs, and CSV digests in *manifest_path*."""
    errors: list[str] = []
    campaign_dir = manifest_path.parent

    if not manifest_path.is_file():
        return ManifestIntegrityResult(
            manifest_path=manifest_path,
            campaign_dir=campaign_dir,
            errors=(f"missing manifest: {manifest_path}",),
            csv_artifacts_checked=0,
        )

    try:
        payload: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return ManifestIntegrityResult(
            manifest_path=manifest_path,
            campaign_dir=campaign_dir,
            errors=(f"invalid JSON: {exc}",),
            csv_artifacts_checked=0,
        )

    for field in required_fields:
        if field not in payload:
            errors.append(f"missing required field: {field}")

    cohort_sha = str(payload.get("cohort_sha256", ""))
    cohort_path_raw = payload.get("cohort_path") or payload.get("cohort_file")
    if cohort_sha and cohort_path_raw:
        cohort_resolved = _resolve_cohort_path(str(cohort_path_raw), repo_root=repo_root)
        if not cohort_resolved.is_file():
            errors.append(f"cohort file not found: {cohort_path_raw}")
        elif sha256_file(cohort_resolved) != cohort_sha:
            errors.append(
                f"cohort_sha256 mismatch for {cohort_resolved.name} "
                f"(manifest={cohort_sha[:16]}…)"
            )

    output_files = payload.get("output_files")
    if verify_output_files:
        if not isinstance(output_files, list):
            errors.append("output_files must be a list")
        else:
            for relative in output_files:
                rel = str(relative)
                if rel == "manifest.json":
                    continue
                if any(char in rel for char in ("*", "?", "[")):
                    continue
                target = campaign_dir / rel
                if rel.endswith("/"):
                    if not target.is_dir():
                        errors.append(f"missing listed output directory: {rel}")
                    continue
                if not target.is_file():
                    errors.append(f"missing listed output file: {rel}")

    csv_checked = 0
    if verify_csv_sha256:
        artifact_hashes = payload.get("artifact_sha256")
        if isinstance(artifact_hashes, dict):
            for rel, expected in artifact_hashes.items():
                if not str(rel).endswith(".csv"):
                    continue
                target = campaign_dir / str(rel)
                if not target.is_file():
                    errors.append(f"missing CSV listed in artifact_sha256: {rel}")
                    continue
                csv_checked += 1
                actual = sha256_file(target)
                if actual != expected:
                    errors.append(f"CSV SHA-256 mismatch: {rel}")

    return ManifestIntegrityResult(
        manifest_path=manifest_path,
        campaign_dir=campaign_dir,
        errors=tuple(errors),
        csv_artifacts_checked=csv_checked,
    )


def verify_paper_campaign_manifests(
    results_dir: Path,
    *,
    repo_root: Path | None = None,
    campaign_dirs: tuple[str, ...] = PAPER_CAMPAIGN_DIRS,
    verify_output_files: bool = False,
) -> list[ManifestIntegrityResult]:
    """Verify manifests for all known frozen paper campaign export directories."""
    results: list[ManifestIntegrityResult] = []
    for dirname in campaign_dirs:
        manifest_path = results_dir / dirname / "manifest.json"
        if not manifest_path.is_file():
            continue
        results.append(
            verify_campaign_manifest(
                manifest_path,
                repo_root=repo_root,
                verify_output_files=verify_output_files,
            )
        )
    return results


def csv_rows_stable_digest(csv_path: Path) -> str:
    """Return a deterministic digest of CSV row content (order-sensitive)."""
    import hashlib

    rows = list(csv.DictReader(csv_path.open(encoding="utf-8")))
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
