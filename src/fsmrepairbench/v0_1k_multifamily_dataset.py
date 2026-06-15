"""Build, pin, and export the v0.1 1k-plan multi-family stratified dataset."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.multifamily_cohort import (
    MultifamilyCohortManifests,
    pin_multifamily_cohort_manifests,
)
from fsmrepairbench.multifamily_cohort_validation import (
    MultifamilyValidationResult,
    export_dataset_manifest,
    validate_multifamily_dataset,
)
from fsmrepairbench.stratified_builder import StratifiedBuildResult, build_stratified_dataset
from fsmrepairbench.taxonomy_coverage import TaxonomyCoverageResult, generate_taxonomy_coverage_report

DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_1k_multifamily")
DEFAULT_PLAN_PATH = Path("plans/fsmrepairbench_v0_1k_plan.yaml")
DEFAULT_TAXONOMY_OUTPUT_DIR = Path("results/taxonomy_coverage_1k_multifamily")
DEFAULT_PAPER_TAXONOMY_DIR = Path("../paper1/results/taxonomy_coverage_1k_multifamily")
DEFAULT_ANALYSIS_OUTPUT_DIR = Path("results/analysis_1k_multifamily")
DEFAULT_PAPER_ANALYSIS_DIR = Path("../paper1/results/analysis_1k_multifamily")

V0_1K_MULTIFAMILY_RELEASE = "v0.3.0-1k-plan-multifamily"
ZENODO_DOI = "10.5281/zenodo.20602528"

ANALYSIS_COHORT_TXT = "analysis_cohort_1k.txt"
ANALYSIS_COHORT_JSON = "analysis_cohort_1k.json"
LOCALIZATION_COHORT_TXT = "localization_cohort_1k.txt"
LOCALIZATION_COHORT_JSON = "localization_cohort_1k.json"
COUPLING_COHORT_TXT = "coupling_campaign_250.txt"
COUPLING_COHORT_JSON = "coupling_campaign_250.json"
ORACLE_DEPTH_COHORT_TXT = "oracle_depth_ablation_200.txt"
ORACLE_DEPTH_COHORT_JSON = "oracle_depth_ablation_200.json"


class V0_1kMultifamilyDatasetError(RuntimeError):
    """Raised when v0.1 1k-plan multifamily dataset operations fail."""


@dataclass(frozen=True)
class V0_1kMultifamilyBuildResult:
    output_dir: Path
    plan_path: Path
    case_count: int
    build_result: StratifiedBuildResult


@dataclass(frozen=True)
class V0_1kMultifamilyRq2ExportResult:
    dataset_dir: Path
    cohort_manifest: Path
    analysis_dir: Path
    paper_analysis_dir: Path | None


@dataclass(frozen=True)
class V0_1kMultifamilyValidationResult:
    dataset_dir: Path
    validation: MultifamilyValidationResult
    manifest_path: Path


@dataclass(frozen=True)
class V0_1kMultifamilyRq1ExportResult:
    dataset_dir: Path
    cohort_manifest: Path
    taxonomy_dir: Path
    paper_taxonomy_dir: Path | None
    taxonomy_result: TaxonomyCoverageResult


def build_v0_1k_multifamily_dataset(
    *,
    plan_path: Path | None = None,
    output_dir: Path | None = None,
    repo_root: Path | None = None,
) -> V0_1kMultifamilyBuildResult:
    """Build 1000 stratified cases from the published v0.1 1k YAML plan (seed 44)."""
    base = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    plan = (plan_path or base / DEFAULT_PLAN_PATH).resolve()
    out = (output_dir or base / DEFAULT_DATASET_DIR).resolve()
    if not plan.is_file():
        msg = f"Stratification plan not found: {plan}"
        raise V0_1kMultifamilyDatasetError(msg)

    result = build_stratified_dataset(plan, out)
    metadata_path = out / "dataset_release.json"
    metadata_path.write_text(
        json.dumps(
            {
                "release_label": V0_1K_MULTIFAMILY_RELEASE,
                "zenodo_doi": ZENODO_DOI,
                "plan_path": plan.relative_to(base).as_posix(),
                "plan_seed": 44,
                "case_count": len(result.cases),
                "machine_families": ["plain_fsm", "mealy", "moore", "efsm", "timed_fsm"],
                "stratification_dimensions": 10,
                "generated_at": datetime.now(UTC).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    export_dataset_manifest(
        out,
        release_label=V0_1K_MULTIFAMILY_RELEASE,
        plan_path=plan,
        regeneration_commands=[
            "python ../paper1/scripts/build_v0_1k_multifamily_dataset.py",
            "python ../paper1/scripts/pin_v0_1k_multifamily_cohorts.py",
            "python ../paper1/scripts/verify_multifamily_cohort_completeness.py",
        ],
    )
    return V0_1kMultifamilyBuildResult(
        output_dir=out,
        plan_path=plan,
        case_count=len(result.cases),
        build_result=result,
    )


def pin_v0_1k_multifamily_cohorts(
    dataset_dir: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> MultifamilyCohortManifests:
    """Pin analysis/localization/coupling/oracle-depth cohort manifests with SHA-256."""
    base = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    dataset = (dataset_dir or base / DEFAULT_DATASET_DIR).resolve()
    return pin_multifamily_cohort_manifests(
        dataset,
        release_label=V0_1K_MULTIFAMILY_RELEASE,
        analysis_txt=ANALYSIS_COHORT_TXT,
        analysis_json=ANALYSIS_COHORT_JSON,
        localization_txt=LOCALIZATION_COHORT_TXT,
        localization_json=LOCALIZATION_COHORT_JSON,
        coupling_txt=COUPLING_COHORT_TXT,
        coupling_json=COUPLING_COHORT_JSON,
        oracle_depth_txt=ORACLE_DEPTH_COHORT_TXT,
        oracle_depth_json=ORACLE_DEPTH_COHORT_JSON,
    )


def validate_v0_1k_multifamily_dataset(
    dataset_dir: Path | None = None,
    *,
    repo_root: Path | None = None,
) -> V0_1kMultifamilyValidationResult:
    """Validate 10D stratification, machine-family quotas, and cohort SHA-256 manifests."""
    base = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    dataset = (dataset_dir or base / DEFAULT_DATASET_DIR).resolve()
    plan = base / DEFAULT_PLAN_PATH
    validation = validate_multifamily_dataset(
        dataset,
        plan_path=plan,
        release_label=V0_1K_MULTIFAMILY_RELEASE,
        cases_per_family=200,
        cohort_specs=(
            (ANALYSIS_COHORT_TXT, ANALYSIS_COHORT_JSON, 1000),
            (LOCALIZATION_COHORT_TXT, LOCALIZATION_COHORT_JSON, 1000),
            (COUPLING_COHORT_TXT, COUPLING_COHORT_JSON, 250),
            (ORACLE_DEPTH_COHORT_TXT, ORACLE_DEPTH_COHORT_JSON, 200),
        ),
    )
    if validation.errors:
        msg = "; ".join(validation.errors)
        raise V0_1kMultifamilyDatasetError(msg)
    manifest_path = export_dataset_manifest(
        dataset,
        release_label=V0_1K_MULTIFAMILY_RELEASE,
        plan_path=plan,
    )
    return V0_1kMultifamilyValidationResult(
        dataset_dir=dataset,
        validation=validation,
        manifest_path=manifest_path,
    )


def export_v0_1k_multifamily_rq2(
    *,
    dataset_dir: Path | None = None,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
) -> V0_1kMultifamilyRq2ExportResult:
    """Run analyze-benchmark on the pinned multifamily analysis cohort (RQ2-style export)."""
    from fsmrepairbench.analytics import generate_analysis_report

    base = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    dataset = (dataset_dir or base / DEFAULT_DATASET_DIR).resolve()
    cohort_path = dataset / ANALYSIS_COHORT_TXT
    if not cohort_path.is_file():
        msg = f"Missing pinned analysis cohort: {cohort_path}. Run pin_v0_1k_multifamily_cohorts first."
        raise V0_1kMultifamilyDatasetError(msg)

    out = (output_dir or base / DEFAULT_ANALYSIS_OUTPUT_DIR).resolve()
    analysis = generate_analysis_report(
        dataset,
        output_dir=out,
        cohort_path=cohort_path,
        release_label=V0_1K_MULTIFAMILY_RELEASE,
    )

    manifest_path = out / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "release_label": V0_1K_MULTIFAMILY_RELEASE,
                "zenodo_doi": ZENODO_DOI,
                "dataset_dir": dataset.relative_to(base).as_posix(),
                "cohort_file": cohort_path.name,
                "cohort_sha256": __import__("hashlib").sha256(cohort_path.read_bytes()).hexdigest(),
                "case_count": analysis.case_count,
                "regeneration_commands": [
                    "fsmrepairbench analyze-benchmark data/fsmrepairbench_1k_multifamily "
                    "--cohort-file data/fsmrepairbench_1k_multifamily/analysis_cohort_1k.txt "
                    "--out results/analysis_1k_multifamily",
                    "python ../paper1/scripts/generate_v0_1k_multifamily_rq2_outputs.py",
                ],
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    paper_dir: Path | None = None
    if paper_export_dir is not None:
        paper_dir = paper_export_dir.resolve()
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
        shutil.copytree(out, paper_dir)

    return V0_1kMultifamilyRq2ExportResult(
        dataset_dir=dataset,
        cohort_manifest=cohort_path,
        analysis_dir=out,
        paper_analysis_dir=paper_dir,
    )


def export_v0_1k_multifamily_rq1(
    *,
    dataset_dir: Path | None = None,
    repo_root: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
) -> V0_1kMultifamilyRq1ExportResult:
    """Regenerate RQ1 taxonomy coverage and plan-gap figures for the multifamily 1k cohort."""
    base = (repo_root or Path(__file__).resolve().parents[2]).resolve()
    dataset = (dataset_dir or base / DEFAULT_DATASET_DIR).resolve()
    cohort_path = dataset / ANALYSIS_COHORT_TXT
    if not cohort_path.is_file():
        msg = f"Missing pinned analysis cohort: {cohort_path}. Run pin_v0_1k_multifamily_cohorts first."
        raise V0_1kMultifamilyDatasetError(msg)

    out = (output_dir or base / DEFAULT_TAXONOMY_OUTPUT_DIR).resolve()
    taxonomy_result = generate_taxonomy_coverage_report(
        dataset,
        output_dir=out,
        cohort_path=cohort_path,
    )
    manifest_path = out / "manifest.json"
    if manifest_path.is_file():
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload.update(
            {
                "release_label": V0_1K_MULTIFAMILY_RELEASE,
                "zenodo_doi": ZENODO_DOI,
                "dataset_dir": dataset.relative_to(base).as_posix(),
                "cohort_file": cohort_path.name,
                "cohort_sha256": __import__("hashlib").sha256(cohort_path.read_bytes()).hexdigest(),
                "plan_path": DEFAULT_PLAN_PATH.as_posix(),
                "regeneration_commands": [
                    "python ../paper1/scripts/build_v0_1k_multifamily_dataset.py",
                    "python ../paper1/scripts/pin_v0_1k_multifamily_cohorts.py",
                    "python ../paper1/scripts/generate_v0_1k_multifamily_rq1_outputs.py",
                ],
            }
        )
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paper_dir: Path | None = None
    if paper_export_dir is not None:
        paper_dir = paper_export_dir.resolve()
        if paper_dir.exists():
            shutil.rmtree(paper_dir)
        shutil.copytree(out, paper_dir)

    return V0_1kMultifamilyRq1ExportResult(
        dataset_dir=dataset,
        cohort_manifest=cohort_path,
        taxonomy_dir=out,
        paper_taxonomy_dir=paper_dir,
        taxonomy_result=taxonomy_result,
    )
