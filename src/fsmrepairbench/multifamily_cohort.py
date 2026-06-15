"""Multi-family v0.3 cohort manifests, campaign orchestration, and paper exports."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import ZENODO_DOI, load_cohort_manifest
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.multifamily_analysis import (
    MULTIFAMILY_TARGET_FAMILIES,
    load_machine_type_index,
    load_multifamily_records,
)

MULTIFAMILY_V03_EXPERIMENT = "multifamily-v0.3.0-cohort"
MULTIFAMILY_V03_RELEASE = "v0.3.0-multifamily-cohort"
DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_multifamily_v0_3")
DEFAULT_PLAN_PATH = Path("plans/fsmrepairbench_multifamily_v0_3_plan.yaml")
FALLBACK_DATASET_DIR = Path("data/fsmrepairbench_multifamily_v0_3_smoke")
FALLBACK_PLAN_PATH = Path("plans/fsmrepairbench_multifamily_v0_3_smoke_plan.yaml")

ANALYSIS_COHORT_TXT = "analysis_cohort_multifamily.txt"
ANALYSIS_COHORT_JSON = "analysis_cohort_multifamily.json"
LOCALIZATION_COHORT_TXT = "localization_cohort_multifamily.txt"
LOCALIZATION_COHORT_JSON = "localization_cohort_multifamily.json"
COUPLING_COHORT_TXT = "coupling_campaign_multifamily.txt"
COUPLING_COHORT_JSON = "coupling_campaign_multifamily.json"
ORACLE_DEPTH_COHORT_TXT = "oracle_depth_ablation_multifamily.txt"
ORACLE_DEPTH_COHORT_JSON = "oracle_depth_ablation_multifamily.json"

DEFAULT_ANALYSIS_SIZE = 1000
DEFAULT_COUPLING_SIZE = 250
DEFAULT_ORACLE_DEPTH_SIZE = 200
DEFAULT_CAMPAIGN_SEED = 44

CAMPAIGN_OUTPUTS: dict[str, dict[str, str]] = {
    "C1": {
        "release_label": "C1-baseline-repair-multifamily",
        "results_dir": "results/baseline_repair_C1_multifamily",
        "paper_dir": "baseline_repair_C1_multifamily",
    },
    "RQ3": {
        "release_label": "RQ3-localization-multifamily",
        "results_dir": "results/rq3_localization_multifamily",
        "paper_dir": "rq3_localization_multifamily",
    },
    "RQ4": {
        "release_label": "RQ4-coupling-multifamily",
        "results_dir": "results/rq4_coupling_multifamily",
        "paper_dir": "rq4_coupling_multifamily",
    },
    "C3": {
        "release_label": "C3-oracle-depth-multifamily",
        "results_dir": "results/oracle_depth_ablation_multifamily",
        "paper_dir": "oracle_depth_ablation_multifamily",
    },
}


class MultifamilyCohortError(RuntimeError):
    """Raised when multi-family cohort operations fail."""


@dataclass(frozen=True)
class CohortManifest:
    """Pinned cohort manifest paths and metadata."""

    txt_path: Path
    json_path: Path
    experiment: str
    case_ids: tuple[str, ...]
    sha256: str


@dataclass(frozen=True)
class MultifamilyCohortManifests:
    """All pinned manifests for multifamily campaigns."""

    dataset_dir: Path
    analysis: CohortManifest
    localization: CohortManifest
    coupling: CohortManifest
    oracle_depth: CohortManifest


@dataclass(frozen=True)
class MultifamilyCampaignRunResult:
    """Summary of a multifamily campaign execution."""

    campaign: str
    release_label: str
    results_dir: Path
    paper_dir: Path
    command: list[str]
    returncode: int


def resolve_multifamily_dataset(dataset_dir: Path | None = None) -> Path:
    """Return the multifamily dataset directory, falling back to the smoke pilot."""
    if dataset_dir is not None:
        if not dataset_dir.is_dir():
            msg = f"Dataset directory not found: {dataset_dir}"
            raise MultifamilyCohortError(msg)
        return dataset_dir
    if DEFAULT_DATASET_DIR.is_dir():
        return DEFAULT_DATASET_DIR
    if FALLBACK_DATASET_DIR.is_dir():
        return FALLBACK_DATASET_DIR
    msg = f"No multifamily dataset found at {DEFAULT_DATASET_DIR} or {FALLBACK_DATASET_DIR}"
    raise MultifamilyCohortError(msg)


def resolve_multifamily_plan(plan_path: Path | None = None, *, dataset_dir: Path | None = None) -> Path:
    if plan_path is not None:
        return plan_path
    dataset = resolve_multifamily_dataset(dataset_dir)
    copied = dataset / "dataset_plan.json"
    if copied.is_file():
        return copied
    if DEFAULT_PLAN_PATH.is_file():
        return DEFAULT_PLAN_PATH
    return FALLBACK_PLAN_PATH


def load_completed_case_ids(dataset_dir: Path, *, limit: int | None = None) -> list[str]:
    """Load completed case IDs in stable build order."""
    index_path = dataset_dir / "case_index.csv"
    progress_path = dataset_dir / "progress.csv"
    case_ids: list[str] = []
    if index_path.is_file():
        with index_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                case_ids.append(str(row["case_id"]))
    elif progress_path.is_file():
        with progress_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("status", "completed") == "completed":
                    case_ids.append(str(row["case_id"]))
    else:
        cases_dir = dataset_dir / "cases"
        case_ids = sorted(path.name for path in cases_dir.iterdir() if path.is_dir())
    if limit is not None:
        case_ids = case_ids[:limit]
    return case_ids


def _load_case_features(dataset_dir: Path, case_id: str) -> dict[str, Any]:
    features_path = dataset_dir / "cases" / case_id / "case_features.json"
    if features_path.is_file():
        return json.loads(features_path.read_text(encoding="utf-8"))
    matrix_path = dataset_dir / "feature_matrix.csv"
    if matrix_path.is_file():
        with matrix_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                if row["case_id"] == case_id:
                    return dict(row)
    return {}


def select_machine_type_stratified_cohort(
    dataset_dir: Path,
    candidate_ids: Sequence[str],
    *,
    size: int,
) -> list[str]:
    """Round-robin select cases balancing machine_type (and bug_type within family)."""
    if size < 1:
        msg = "Cohort size must be at least 1"
        raise MultifamilyCohortError(msg)
    machine_index = load_machine_type_index(dataset_dir)
    groups: dict[tuple[str, str], list[str]] = defaultdict(list)
    for case_id in candidate_ids:
        features = _load_case_features(dataset_dir, case_id)
        machine_type = machine_index.get(case_id) or str(features.get("machine_type", "unknown"))
        bug_type = str(features.get("bug_type", features.get("mutation_operator", "unknown")))
        groups[(machine_type, bug_type)].append(case_id)
    for key in groups:
        groups[key] = sorted(groups[key])

    available = sum(len(values) for values in groups.values())
    if available < size:
        msg = f"Need {size} stratified cases, found {available}"
        raise MultifamilyCohortError(msg)

    selected: list[str] = []
    pointers = dict.fromkeys(sorted(groups), 0)
    while len(selected) < size:
        added = False
        for key in sorted(groups):
            index = pointers[key]
            if index < len(groups[key]):
                selected.append(groups[key][index])
                pointers[key] = index + 1
                added = True
                if len(selected) >= size:
                    break
        if not added:
            break
    if len(selected) < size:
        msg = f"Could only select {len(selected)} of {size} requested cases"
        raise MultifamilyCohortError(msg)
    return selected


def write_cohort_manifest(
    dataset_dir: Path,
    *,
    txt_name: str,
    json_name: str,
    experiment: str,
    case_ids: Sequence[str],
    source_manifest: str,
    release_label: str = MULTIFAMILY_V03_RELEASE,
    extra: dict[str, Any] | None = None,
) -> CohortManifest:
    txt_path = dataset_dir / txt_name
    json_path = dataset_dir / json_name
    txt_path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    digest = hashlib.sha256(txt_path.read_bytes()).hexdigest()
    payload: dict[str, Any] = {
        "dataset": dataset_dir.name,
        "release_label": release_label,
        "experiment": experiment,
        "cohort_size": len(case_ids),
        "case_ids": list(case_ids),
        "source_manifest": source_manifest,
        "sha256": digest,
        "machine_families": list(MULTIFAMILY_TARGET_FAMILIES),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    if extra:
        payload.update(extra)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return CohortManifest(
        txt_path=txt_path,
        json_path=json_path,
        experiment=experiment,
        case_ids=tuple(case_ids),
        sha256=digest,
    )


def pin_multifamily_cohort_manifests(
    dataset_dir: Path | None = None,
    *,
    analysis_size: int | None = None,
    coupling_size: int | None = None,
    oracle_depth_size: int | None = None,
    release_label: str = MULTIFAMILY_V03_RELEASE,
    analysis_txt: str = ANALYSIS_COHORT_TXT,
    analysis_json: str = ANALYSIS_COHORT_JSON,
    localization_txt: str = LOCALIZATION_COHORT_TXT,
    localization_json: str = LOCALIZATION_COHORT_JSON,
    coupling_txt: str = COUPLING_COHORT_TXT,
    coupling_json: str = COUPLING_COHORT_JSON,
    oracle_depth_txt: str = ORACLE_DEPTH_COHORT_TXT,
    oracle_depth_json: str = ORACLE_DEPTH_COHORT_JSON,
) -> MultifamilyCohortManifests:
    """Pin analysis, localization, coupling, and oracle-depth cohort manifests."""
    dataset = resolve_multifamily_dataset(dataset_dir)
    completed = load_completed_case_ids(dataset)
    target_analysis = min(analysis_size or DEFAULT_ANALYSIS_SIZE, len(completed))
    resolved_coupling = min(
        coupling_size or max(1, round(target_analysis * DEFAULT_COUPLING_SIZE / DEFAULT_ANALYSIS_SIZE)),
        target_analysis,
    )
    resolved_oracle_depth = min(
        oracle_depth_size or max(1, round(target_analysis * DEFAULT_ORACLE_DEPTH_SIZE / DEFAULT_ANALYSIS_SIZE)),
        target_analysis,
    )
    if len(completed) < target_analysis:
        msg = f"Need {target_analysis} completed cases, found {len(completed)} in {dataset}"
        raise MultifamilyCohortError(msg)
    analysis_ids = completed[:target_analysis]

    analysis = write_cohort_manifest(
        dataset,
        txt_name=analysis_txt,
        json_name=analysis_json,
        experiment="multifamily-analysis-cohort",
        case_ids=analysis_ids,
        source_manifest="case_index.csv",
        release_label=release_label,
        extra={"stratification": "first-N completed cases in build order"},
    )
    localization = write_cohort_manifest(
        dataset,
        txt_name=localization_txt,
        json_name=localization_json,
        experiment="RQ3-localization-multifamily",
        case_ids=analysis_ids,
        source_manifest=analysis_txt,
        release_label=release_label,
    )
    coupling_ids = select_machine_type_stratified_cohort(
        dataset,
        analysis_ids,
        size=resolved_coupling,
    )
    coupling = write_cohort_manifest(
        dataset,
        txt_name=coupling_txt,
        json_name=coupling_json,
        experiment="RQ4-coupling-multifamily",
        case_ids=coupling_ids,
        source_manifest=analysis_txt,
        release_label=release_label,
        extra={"stratification": "machine_type × bug_type round-robin"},
    )
    oracle_ids = select_machine_type_stratified_cohort(
        dataset,
        analysis_ids,
        size=resolved_oracle_depth,
    )
    oracle_depth = write_cohort_manifest(
        dataset,
        txt_name=oracle_depth_txt,
        json_name=oracle_depth_json,
        experiment="C3-oracle-depth-multifamily",
        case_ids=oracle_ids,
        source_manifest=analysis_txt,
        release_label=release_label,
        extra={"stratification": "machine_type × bug_type round-robin"},
    )
    return MultifamilyCohortManifests(
        dataset_dir=dataset,
        analysis=analysis,
        localization=localization,
        coupling=coupling,
        oracle_depth=oracle_depth,
    )


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def run_multifamily_campaigns(
    dataset_dir: Path | None = None,
    *,
    repo_root: Path | None = None,
    campaign_seed: int = DEFAULT_CAMPAIGN_SEED,
    skip: set[str] | None = None,
    skip_c1_multi_seed: bool = True,
) -> list[MultifamilyCampaignRunResult]:
    """Run C1, RQ3, RQ4, and C3 on the multifamily dataset."""
    from fsmrepairbench.baseline_repair_campaign import BaselineRepairCampaignError
    from fsmrepairbench.c1_baseline_repair_exports import (
        C1BaselineRepairExportError,
        run_c1_baseline_repair_experiment,
    )
    from fsmrepairbench.coupling_campaign import CouplingCampaignError, run_coupling_campaign
    from fsmrepairbench.localization_campaign import (
        LocalizationCampaignError,
        run_localization_campaign,
    )
    from fsmrepairbench.oracle_depth_ablation import (
        OracleDepthAblationError,
        run_oracle_depth_ablation,
    )
    from fsmrepairbench.tool_runner import ToolRunnerError

    base = repo_root or _repo_root()
    dataset = resolve_multifamily_dataset(dataset_dir)
    manifests = pin_multifamily_cohort_manifests(dataset)
    paper_root = base.parent / "paper1" / "results"
    skip_campaigns = skip or set()
    results: list[MultifamilyCampaignRunResult] = []

    def _copy_campaign_outputs(raw_dir: Path, paper_dir: Path) -> None:
        paper_dir.mkdir(parents=True, exist_ok=True)
        if not raw_dir.is_dir():
            return
        for name in ("summary.csv", "per_case_results.csv", "manifest.json", "report.md", "leaderboard.csv"):
            source = raw_dir / name
            if source.is_file():
                shutil.copy2(source, paper_dir / name)
        for sub in ("figures", "tables"):
            src_sub = raw_dir / sub
            if src_sub.is_dir():
                dst_sub = paper_dir / sub
                if dst_sub.exists():
                    shutil.rmtree(dst_sub)
                shutil.copytree(src_sub, dst_sub)

    if "C1" not in skip_campaigns:
        raw_dir = base / CAMPAIGN_OUTPUTS["C1"]["results_dir"]
        paper_dir = paper_root / CAMPAIGN_OUTPUTS["C1"]["paper_dir"]
        try:
            run_c1_baseline_repair_experiment(
                dataset,
                out_dir=raw_dir,
                cohort_file=manifests.analysis.txt_path,
                paper_export_dir=paper_dir,
                skip_multi_seed=skip_c1_multi_seed,
            )
            returncode = 0
        except (BaselineRepairCampaignError, C1BaselineRepairExportError, ToolRunnerError) as exc:
            raise MultifamilyCohortError(str(exc)) from exc
        _copy_campaign_outputs(raw_dir, paper_dir)
        results.append(
            MultifamilyCampaignRunResult(
                campaign="C1",
                release_label=CAMPAIGN_OUTPUTS["C1"]["release_label"],
                results_dir=raw_dir,
                paper_dir=paper_dir,
                command=["run_c1_baseline_repair_experiment"],
                returncode=returncode,
            )
        )

    if "RQ3" not in skip_campaigns:
        raw_dir = base / CAMPAIGN_OUTPUTS["RQ3"]["results_dir"]
        paper_dir = paper_root / CAMPAIGN_OUTPUTS["RQ3"]["paper_dir"]
        try:
            run_localization_campaign(
                dataset,
                output_dir=raw_dir,
                cohort_path=manifests.localization.txt_path,
            )
            returncode = 0
        except LocalizationCampaignError as exc:
            raise MultifamilyCohortError(str(exc)) from exc
        _copy_campaign_outputs(raw_dir, paper_dir)
        results.append(
            MultifamilyCampaignRunResult(
                campaign="RQ3",
                release_label=CAMPAIGN_OUTPUTS["RQ3"]["release_label"],
                results_dir=raw_dir,
                paper_dir=paper_dir,
                command=["run_localization_campaign"],
                returncode=returncode,
            )
        )

    if "RQ4" not in skip_campaigns:
        raw_dir = base / CAMPAIGN_OUTPUTS["RQ4"]["results_dir"]
        paper_dir = paper_root / CAMPAIGN_OUTPUTS["RQ4"]["paper_dir"]
        subset_dir = base / "results/rq4_coupling_subset_multifamily"
        try:
            run_coupling_campaign(
                dataset,
                output_dir=raw_dir,
                cohort_path=manifests.coupling.txt_path,
                subset_dir=subset_dir,
                campaign_seed=campaign_seed,
            )
            returncode = 0
        except CouplingCampaignError as exc:
            raise MultifamilyCohortError(str(exc)) from exc
        _copy_campaign_outputs(raw_dir, paper_dir)
        results.append(
            MultifamilyCampaignRunResult(
                campaign="RQ4",
                release_label=CAMPAIGN_OUTPUTS["RQ4"]["release_label"],
                results_dir=raw_dir,
                paper_dir=paper_dir,
                command=["run_coupling_campaign"],
                returncode=returncode,
            )
        )

    if "C3" not in skip_campaigns:
        raw_dir = base / CAMPAIGN_OUTPUTS["C3"]["results_dir"]
        paper_dir = paper_root / CAMPAIGN_OUTPUTS["C3"]["paper_dir"]
        try:
            run_oracle_depth_ablation(
                dataset,
                output_dir=raw_dir,
                cohort_path=manifests.oracle_depth.txt_path,
                write_cohort=False,
                paper_export_dir=paper_dir,
            )
            returncode = 0
        except OracleDepthAblationError as exc:
            raise MultifamilyCohortError(str(exc)) from exc
        _copy_campaign_outputs(raw_dir, paper_dir)
        results.append(
            MultifamilyCampaignRunResult(
                campaign="C3",
                release_label=CAMPAIGN_OUTPUTS["C3"]["release_label"],
                results_dir=raw_dir,
                paper_dir=paper_dir,
                command=["run_oracle_depth_ablation"],
                returncode=returncode,
            )
        )

    return results


def _dedupe_case_rows(
    rows: list[dict[str, str]],
    *,
    tool_id: str | None = None,
) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    seen: set[str] = set()
    for row in rows:
        if tool_id is not None and row.get("tool_id") != tool_id:
            continue
        case_id = str(row.get("case_id", ""))
        if not case_id or case_id in seen:
            continue
        seen.add(case_id)
        deduped.append(row)
    return deduped


def _aggregate_campaign_by_family(
    per_case_csv: Path,
    machine_index: dict[str, str],
    *,
    metric_columns: dict[str, str],
    tool_id: str | None = None,
) -> list[dict[str, str | float | int]]:
    if not per_case_csv.is_file():
        return []
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with per_case_csv.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = row.get("case_id") or row.get("source_case_id", "")
            family = machine_index.get(case_id, "unknown")
            grouped[family].append(row)

    rows: list[dict[str, str | float | int]] = []
    for family in MULTIFAMILY_TARGET_FAMILIES:
        family_rows = _dedupe_case_rows(grouped.get(family, []), tool_id=tool_id)
        if not family_rows:
            continue
        payload: dict[str, str | float | int] = {
            "machine_type": family,
            "case_count": len(family_rows),
        }
        for out_name, source_col in metric_columns.items():
            if source_col.endswith("_rate") or source_col in {"complete_repair", "effective_repair", "fault_detected", "top1_hit"}:
                truthy = sum(1 for row in family_rows if str(row.get(source_col, "")).lower() == "true")
                payload[out_name] = round(truthy / len(family_rows), 6)
            else:
                values = [float(row[source_col]) for row in family_rows if row.get(source_col)]
                payload[out_name] = round(sum(values) / len(values), 6) if values else 0.0
        rows.append(payload)
    return rows


def export_multifamily_campaign_summary(
    dataset_dir: Path | None = None,
    *,
    repo_root: Path | None = None,
    paper_export_dir: Path | None = None,
) -> Path:
    """Write cross-campaign family breakdown CSV/LaTeX for the paper."""
    base = repo_root or _repo_root()
    dataset = resolve_multifamily_dataset(dataset_dir)
    machine_index = load_machine_type_index(dataset)
    paper_dir = paper_export_dir or (base.parent / "paper1/results/multifamily_v0_3_campaigns")
    paper_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = paper_dir / "tables"
    figures_dir = paper_dir / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    campaign_specs = {
        "C1": (
            base / CAMPAIGN_OUTPUTS["C1"]["results_dir"] / "per_case_results.csv",
            {
                "complete_repair_rate": "complete_repair",
                "effective_repair_rate": "effective_repair",
                "mean_delta_bpr": "delta_bpr",
            },
            "baseline_missing_transition",
        ),
        "RQ3": (
            base / CAMPAIGN_OUTPUTS["RQ3"]["results_dir"] / "per_case_results.csv",
            {"top1_hit_rate": "top1_hit", "mrr": "reciprocal_rank"},
            None,
        ),
        "RQ4": (
            base / CAMPAIGN_OUTPUTS["RQ4"]["results_dir"] / "per_case_results.csv",
            {
                "detection_rate": "fault_detected",
                "complete_repair_rate": "complete_repair",
                "effective_repair_rate": "effective_repair",
            },
            None,
        ),
        "C3": (
            base / CAMPAIGN_OUTPUTS["C3"]["results_dir"] / "per_case_results.csv",
            {"detection_rate": "fault_detected", "mean_bpr_delta": "bpr_delta"},
            None,
        ),
    }

    summary_rows: list[dict[str, str | float | int]] = []
    for campaign, (csv_path, metrics, tool_id) in campaign_specs.items():
        family_rows = _aggregate_campaign_by_family(
            csv_path,
            machine_index,
            metric_columns=metrics,
            tool_id=tool_id,
        )
        for row in family_rows:
            summary_rows.append({"campaign": campaign, **row})

    summary_csv = paper_dir / "campaign_by_family_summary.csv"
    fieldnames = [
        "campaign",
        "machine_type",
        "case_count",
        *sorted({k for _, metrics, _ in campaign_specs.values() for k in metrics}),
    ]
    with summary_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(summary_rows)

    tex_lines = [
        "% Auto-generated by fsmrepairbench.multifamily_cohort",
        "\\begin{table}[t]",
        "\\caption{Multifamily v0.3 campaign outcomes by machine family "
        "(detectable-only repair and localization metrics vary by campaign partition).}",
        "\\label{tab:multifamily-campaign-by-family}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}llrrrr@{}}",
        "\\toprule",
        "Campaign & Family & $n$ & Primary metric & Value \\\\",
        "\\midrule",
    ]
    primary_metric = {
        "C1": "complete_repair_rate",
        "RQ3": "top1_hit_rate",
        "RQ4": "detection_rate",
        "C3": "detection_rate",
    }
    for row in summary_rows:
        metric = primary_metric[str(row["campaign"])]
        value = float(row.get(metric, 0.0))
        display = f"{100 * value:.1f}\\%" if "rate" in metric or metric.endswith("_hit_rate") else f"{value:.3f}"
        metric_tex = metric.replace("_", r"\_")
        tex_lines.append(
            f"{row['campaign']} & \\texttt{{{row['machine_type'].replace('_', r'\\_')}}} & {row['case_count']} & "
            f"{metric_tex} & {display} \\\\"
        )
    tex_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_campaign_by_family.tex").write_text("\n".join(tex_lines), encoding="utf-8")

    analysis_cohort = dataset / "analysis_cohort_multifamily.txt"
    manifest = {
        "experiment": MULTIFAMILY_V03_EXPERIMENT,
        "release_label": MULTIFAMILY_V03_RELEASE,
        "zenodo_doi": ZENODO_DOI,
        "dataset_dir": str(dataset),
        "dataset_sha256": sha256_file(dataset / "feature_matrix.csv"),
        "cohort_path": str(analysis_cohort) if analysis_cohort.is_file() else None,
        "cohort_sha256": sha256_file(analysis_cohort) if analysis_cohort.is_file() else None,
        "git_commit_hash": get_git_commit(),
        "campaign_outputs": CAMPAIGN_OUTPUTS,
        "summary_csv": str(summary_csv),
        "regeneration_commands": [
            "python ../paper1/scripts/run_multifamily_campaigns.py --seed 44",
            "python ../paper1/scripts/generate_multifamily_v0_3_outputs.py",
        ],
        "limitations_note": (
            "Cross-campaign family breakdown on the v0.3 multi-family cohort; "
            "partitions differ by campaign (detectable-only repair, localizable-only RQ3)."
        ),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (paper_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return paper_dir
