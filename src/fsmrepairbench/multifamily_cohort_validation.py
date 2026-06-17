"""Validate multi-family FSM cohort completeness, stratification, and manifest integrity."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import ZENODO_DOI, load_cohort_manifest
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.generators.stratified_specs import load_dataset_plan, total_planned_cases
from fsmrepairbench.multifamily_analysis import MULTIFAMILY_TARGET_FAMILIES
from fsmrepairbench.multifamily_cohort import (
    ANALYSIS_COHORT_JSON,
    ANALYSIS_COHORT_TXT,
    COUPLING_COHORT_JSON,
    COUPLING_COHORT_TXT,
    LOCALIZATION_COHORT_JSON,
    LOCALIZATION_COHORT_TXT,
    ORACLE_DEPTH_COHORT_JSON,
    ORACLE_DEPTH_COHORT_TXT,
    MultifamilyCohortError,
    resolve_multifamily_dataset,
)
from fsmrepairbench.taxonomy_coverage import load_cohort_case_ids
from fsmrepairbench.taxonomy_gap_figures import compute_plan_cell_realisations

GITHUB_REPO = "https://github.com/cesar-andress/fsmrepairbench"
GITHUB_TAG = "v0.2.1-stvr-polish"
ZENODO_URL = "https://doi.org/10.5281/zenodo.20724095"

COHORT_MANIFEST_SPECS: tuple[tuple[str, str, int], ...] = (
    (ANALYSIS_COHORT_TXT, ANALYSIS_COHORT_JSON, 1000),
    (LOCALIZATION_COHORT_TXT, LOCALIZATION_COHORT_JSON, 1000),
    (COUPLING_COHORT_TXT, COUPLING_COHORT_JSON, 250),
    (ORACLE_DEPTH_COHORT_TXT, ORACLE_DEPTH_COHORT_JSON, 200),
)

V0_1K_MULTIFAMILY_COHORT_SPECS: tuple[tuple[str, str, int], ...] = (
    ("analysis_cohort_1k.txt", "analysis_cohort_1k.json", 1000),
    ("localization_cohort_1k.txt", "localization_cohort_1k.json", 1000),
    ("coupling_campaign_250.txt", "coupling_campaign_250.json", 250),
    ("oracle_depth_ablation_200.txt", "oracle_depth_ablation_200.json", 200),
)


class MultifamilyValidationError(RuntimeError):
    """Raised when multi-family cohort validation fails."""


@dataclass(frozen=True)
class MultifamilyValidationResult:
    dataset_dir: Path
    release_label: str
    case_count: int
    machine_type_counts: dict[str, int]
    plan_cell_coverage: float
    cohort_manifests_verified: int
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass
class MultifamilyValidationReport:
    dataset_dir: Path
    release_label: str
    results: list[MultifamilyValidationResult] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and all(not result.errors for result in self.results)


def _load_feature_rows(dataset_dir: Path) -> list[dict[str, str]]:
    matrix_path = dataset_dir / "feature_matrix.csv"
    if not matrix_path.is_file():
        msg = f"Missing feature matrix: {matrix_path}"
        raise MultifamilyValidationError(msg)
    with matrix_path.open(encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _resolve_plan_path(dataset_dir: Path, plan_path: Path | None) -> Path:
    if plan_path is not None and plan_path.is_file():
        return plan_path
    copied = dataset_dir / "dataset_plan.json"
    if copied.is_file():
        return copied
    repo_plan = Path("plans/fsmrepairbench_v0_1k_plan.yaml")
    if repo_plan.is_file():
        return repo_plan
    msg = f"No stratification plan found for {dataset_dir}"
    raise MultifamilyValidationError(msg)


def _machine_type_counts(rows: list[dict[str, str]]) -> Counter[str]:
    return Counter(str(row.get("machine_type", "unknown")) for row in rows)


def _plan_cell_coverage(rows: list[dict[str, str]], plan_path: Path) -> float:
    string_rows = [dict(row) for row in rows]
    realisations = compute_plan_cell_realisations(string_rows, plan_path=plan_path)
    if not realisations:
        return 0.0
    realised = sum(1 for cell in realisations if cell.realised_count > 0)
    return realised / len(realisations)


def verify_cohort_manifest_pair(
    dataset_dir: Path,
    txt_name: str,
    json_name: str,
    *,
    expected_size: int | None = None,
    release_label: str | None = None,
) -> list[str]:
    """Return validation errors for one pinned cohort manifest pair."""
    errors: list[str] = []
    txt_path = dataset_dir / txt_name
    json_path = dataset_dir / json_name
    if not txt_path.is_file():
        return [f"Missing cohort manifest: {txt_path}"]
    if not json_path.is_file():
        return [f"Missing cohort manifest JSON: {json_path}"]

    case_ids = load_cohort_manifest(txt_path)
    digest = sha256_file(txt_path)
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    if payload.get("sha256") != digest:
        errors.append(f"{json_path}: sha256 field does not match {txt_path}")
    if expected_size is not None and len(case_ids) != expected_size:
        errors.append(f"{txt_path}: expected {expected_size} cases, found {len(case_ids)}")
    if release_label and payload.get("release_label") and payload["release_label"] != release_label:
        errors.append(
            f"{json_path}: release_label {payload.get('release_label')} != {release_label}"
        )
    json_ids = payload.get("case_ids")
    if isinstance(json_ids, list) and json_ids != case_ids:
        errors.append(f"{json_path}: case_ids list does not match {txt_path}")
    if payload.get("cohort_size") not in (None, len(case_ids)):
        errors.append(f"{json_path}: cohort_size != len(case_ids)")
    return errors


def validate_multifamily_dataset(
    dataset_dir: Path,
    *,
    plan_path: Path | None = None,
    release_label: str,
    expected_families: tuple[str, ...] = MULTIFAMILY_TARGET_FAMILIES,
    cases_per_family: int | None = None,
    cohort_specs: tuple[tuple[str, str, int], ...] = COHORT_MANIFEST_SPECS,
    require_cohort_manifests: bool = True,
) -> MultifamilyValidationResult:
    """Validate dataset completeness, 10D stratification, and cohort manifest SHA-256."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise MultifamilyValidationError(msg)

    errors: list[str] = []
    warnings: list[str] = []
    rows = _load_feature_rows(dataset_dir)
    case_count = len(rows)
    resolved_plan = _resolve_plan_path(dataset_dir, plan_path)
    plan = load_dataset_plan(resolved_plan)
    planned_total = total_planned_cases(plan)

    if case_count != planned_total:
        errors.append(f"Expected {planned_total} completed cases, found {case_count}")

    counts = _machine_type_counts(rows)
    missing_families = [family for family in expected_families if counts.get(family, 0) == 0]
    if missing_families:
        errors.append(f"Missing machine families: {', '.join(missing_families)}")

    if cases_per_family is not None:
        for family in expected_families:
            observed = counts.get(family, 0)
            if observed != cases_per_family:
                errors.append(f"{family}: expected {cases_per_family} cases, found {observed}")

    coverage = _plan_cell_coverage(rows, resolved_plan)
    if coverage < 1.0:
        warnings.append(
            f"Plan cell coverage {coverage:.1%} (<100%); some YAML cells have zero realised cases"
        )

    cohort_verified = 0
    if require_cohort_manifests:
        for txt_name, json_name, size in cohort_specs:
            scaled_size = size
            if planned_total < 1000:
                scaled_size = max(1, round(size * planned_total / 1000))
            manifest_errors = verify_cohort_manifest_pair(
                dataset_dir,
                txt_name,
                json_name,
                expected_size=scaled_size if case_count >= scaled_size else None,
                release_label=release_label,
            )
            if manifest_errors:
                errors.extend(manifest_errors)
            else:
                cohort_verified += 1

    return MultifamilyValidationResult(
        dataset_dir=dataset_dir,
        release_label=release_label,
        case_count=case_count,
        machine_type_counts=dict(counts),
        plan_cell_coverage=coverage,
        cohort_manifests_verified=cohort_verified,
        errors=tuple(errors),
        warnings=tuple(warnings),
    )


def export_dataset_manifest(
    dataset_dir: Path,
    *,
    release_label: str,
    plan_path: Path | None = None,
    output_path: Path | None = None,
    regeneration_commands: list[str] | None = None,
) -> Path:
    """Write dataset-level manifest with SHA-256 checksums and cohort metadata."""
    resolved_plan = _resolve_plan_path(dataset_dir, plan_path)
    rows = _load_feature_rows(dataset_dir)
    counts = _machine_type_counts(rows)

    checksum_files = [
        "feature_matrix.csv",
        "case_index.csv",
        "dataset_plan.json",
    ]
    checksums: dict[str, str] = {}
    for name in checksum_files:
        path = dataset_dir / name
        if path.is_file():
            checksums[name] = sha256_file(path)

    cohort_entries: dict[str, Any] = {}
    for txt_name, json_name, _ in COHORT_MANIFEST_SPECS:
        txt_path = dataset_dir / txt_name
        if txt_path.is_file():
            cohort_entries[txt_name] = {
                "sha256": sha256_file(txt_path),
                "case_count": len(load_cohort_case_ids(dataset_dir, cohort_path=txt_path)),
            }
    for txt_name, json_name, _ in V0_1K_MULTIFAMILY_COHORT_SPECS:
        if txt_name in cohort_entries:
            continue
        txt_path = dataset_dir / txt_name
        if txt_path.is_file():
            cohort_entries[txt_name] = {
                "sha256": sha256_file(txt_path),
                "case_count": len(load_cohort_case_ids(dataset_dir, cohort_path=txt_path)),
            }

    manifest_path = output_path or dataset_dir / "dataset_manifest.json"
    payload: dict[str, Any] = {
        "release_label": release_label,
        "zenodo_doi": ZENODO_DOI,
        "zenodo_url": ZENODO_URL,
        "github_repo": GITHUB_REPO,
        "github_tag": GITHUB_TAG,
        "dataset_dir": dataset_dir.name,
        "plan_path": resolved_plan.as_posix(),
        "plan_sha256": sha256_file(resolved_plan),
        "case_count": len(rows),
        "machine_families": list(MULTIFAMILY_TARGET_FAMILIES),
        "machine_type_counts": dict(counts),
        "stratification_dimensions": 10,
        "file_checksums": checksums,
        "cohort_manifests": cohort_entries,
        "regeneration_commands": regeneration_commands
        or [
            "fsmrepairbench build-stratified-dataset plans/fsmrepairbench_v0_1k_plan.yaml data/fsmrepairbench_1k_multifamily",
            "python ../paper1/scripts/pin_v0_1k_multifamily_cohorts.py",
            "python ../paper1/scripts/verify_multifamily_cohort_completeness.py",
        ],
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def validate_all_multifamily_cohorts(
    *,
    include_v0_1k: bool = True,
    include_v0_3: bool = True,
) -> MultifamilyValidationReport:
    """Validate all built multi-family datasets present on disk."""
    report = MultifamilyValidationReport(dataset_dir=Path("."), release_label="multi")
    repo = Path(__file__).resolve().parents[2]

    if include_v0_1k:
        dataset = repo / "data" / "fsmrepairbench_1k_multifamily"
        if dataset.is_dir():
            result = validate_multifamily_dataset(
                dataset,
                release_label="v0.3.0-1k-plan-multifamily",
                cases_per_family=200,
                cohort_specs=V0_1K_MULTIFAMILY_COHORT_SPECS,
            )
            report.results.append(result)
            report.errors.extend(result.errors)

    if include_v0_3:
        dataset = repo / "data" / "fsmrepairbench_multifamily_v0_3"
        if dataset.is_dir():
            try:
                resolved = resolve_multifamily_dataset(dataset)
            except MultifamilyCohortError:
                resolved = dataset
            result = validate_multifamily_dataset(
                resolved,
                release_label="v0.3.0-multifamily-cohort",
                cases_per_family=200,
                cohort_specs=COHORT_MANIFEST_SPECS,
            )
            report.results.append(result)
            report.errors.extend(result.errors)

    return report
