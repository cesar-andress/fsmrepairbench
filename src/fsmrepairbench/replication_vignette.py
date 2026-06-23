"""Minimal 20-case standalone replication vignette for STVR supplementary artefact."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import compute_benchmark_analytics, write_analysis_summary_csv
from fsmrepairbench.c1_baseline_repair_exports import run_c1_baseline_repair_experiment
from fsmrepairbench.coupling_campaign import load_cohort_manifest
from fsmrepairbench.dataset_builder import load_dataset_cases
from fsmrepairbench.localization_campaign import run_localization_campaign
from fsmrepairbench.localization_localizability_audit import run_localization_localizability_audit

DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_1k")
DEFAULT_COHORT_TXT = "replication_cohort_20.txt"
DEFAULT_COHORT_JSON = "replication_cohort_20.json"
DEFAULT_OUTPUT_DIR = Path("results/replication_vignette_20")
DEFAULT_PAPER_ARTIFACT_DIR = Path("../paper1/artifact/replication_vignette_20")

COHORT_SIZE = 20
DETECTABLE_QUOTA = 10
SATURATED_QUOTA = 10
SOURCE_MANIFEST = "analysis_cohort_1k.txt"
CAMPAIGN_LABEL = "replication-vignette-20"
RELEASE_LABEL = "v0.2.0-analysis"
ZENODO_DOI = "10.5281/zenodo.20602577"
COHORT_SHA256 = "06a4d9f477a6da71f93d02e08bc784e2d8ce969dc21ea1400e81d4e8c9b7688d"

FROZEN_EXPORT_FILES: tuple[tuple[str, str], ...] = (
    ("detection/summary.csv", "detection/summary.csv"),
    ("detection/mutation_summary.csv", "detection/mutation_summary.csv"),
    ("detection/manifest.json", "detection/manifest.json"),
    ("repair/leaderboard.csv", "repair/leaderboard.csv"),
    ("repair/cohort_summary.csv", "repair/cohort_summary.csv"),
    ("repair/manifest.json", "repair/manifest.json"),
    ("localization/summary.csv", "localization/summary.csv"),
    ("localization/leaderboard.csv", "localization/leaderboard.csv"),
    ("localization/localization_metrics.csv", "localization/localization_metrics.csv"),
    (
        "localization/localization_metrics_localizable_only.csv",
        "localization/localization_metrics_localizable_only.csv",
    ),
    ("localization/manifest.json", "localization/manifest.json"),
    ("metrics_by_partition.csv", "metrics_by_partition.csv"),
    ("headline_metrics.json", "headline_metrics.json"),
)


class ReplicationVignetteError(RuntimeError):
    """Raised when replication vignette steps fail."""


@dataclass(frozen=True)
class ReplicationVignetteResult:
    dataset_dir: Path
    cohort_path: Path
    output_dir: Path
    paper_artifact_dir: Path
    headline_metrics_path: Path
    checksum_path: Path
    manifest_path: Path


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def round_robin_select(groups: dict[str, list[str]], quota: int) -> list[str]:
    selected: list[str] = []
    pointers = dict.fromkeys(sorted(groups), 0)
    while len(selected) < quota:
        added = False
        for operator in sorted(groups):
            index = pointers[operator]
            if index < len(groups[operator]):
                selected.append(groups[operator][index])
                pointers[operator] = index + 1
                added = True
                if len(selected) >= quota:
                    break
        if not added:
            break
    if len(selected) < quota:
        msg = f"Could only select {len(selected)} of {quota} requested cases"
        raise ReplicationVignetteError(msg)
    return selected


def select_replication_vignette_cohort(
    dataset_dir: Path,
    *,
    detectable_quota: int = DETECTABLE_QUOTA,
    saturated_quota: int = SATURATED_QUOTA,
) -> list[str]:
    """Select a balanced 20-case cohort (detectable + oracle-saturated) from analysis pin."""
    source = dataset_dir / SOURCE_MANIFEST
    if not source.is_file():
        msg = f"Missing source manifest: {source}"
        raise ReplicationVignetteError(msg)

    analysis_ids = set(load_cohort_manifest(source))
    cases = [case for case in load_dataset_cases(dataset_dir) if case.case_id in analysis_ids]
    detectable_groups: dict[str, list[str]] = defaultdict(list)
    saturated_groups: dict[str, list[str]] = defaultdict(list)
    for case in cases:
        bucket = detectable_groups if case.bpr_delta > 0 else saturated_groups
        bucket[case.mutation_operator].append(case.case_id)
    for groups in (detectable_groups, saturated_groups):
        for operator in groups:
            groups[operator] = sorted(groups[operator])

    return round_robin_select(detectable_groups, detectable_quota) + round_robin_select(
        saturated_groups,
        saturated_quota,
    )


def pin_replication_vignette_cohort(
    dataset_dir: Path,
    *,
    expected_sha256: str | None = COHORT_SHA256,
) -> tuple[Path, Path]:
    """Write pinned replication cohort manifest under *dataset_dir*."""
    case_ids = select_replication_vignette_cohort(dataset_dir)
    if len(case_ids) != COHORT_SIZE:
        msg = f"Expected {COHORT_SIZE} cases, selected {len(case_ids)}"
        raise ReplicationVignetteError(msg)

    txt_path = dataset_dir / DEFAULT_COHORT_TXT
    json_path = dataset_dir / DEFAULT_COHORT_JSON
    txt_path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    digest = _sha256(txt_path)
    if expected_sha256 is not None and digest != expected_sha256:
        msg = f"Cohort sha256 mismatch: got {digest}, expected {expected_sha256}"
        raise ReplicationVignetteError(msg)

    payload = {
        "dataset": dataset_dir.name,
        "doi": ZENODO_DOI,
        "release_label": RELEASE_LABEL,
        "campaign_label": CAMPAIGN_LABEL,
        "cohort_size": len(case_ids),
        "case_ids": case_ids,
        "source_manifest": SOURCE_MANIFEST,
        "selection_policy": "round_robin_by_mutation_operator",
        "detectable_quota": DETECTABLE_QUOTA,
        "saturated_quota": SATURATED_QUOTA,
        "sha256": digest,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return txt_path, json_path


def _write_detection_exports(
    dataset_dir: Path,
    cohort_path: Path,
    output_dir: Path,
) -> Path:
    cohort_ids = set(load_cohort_manifest(cohort_path))
    cases = [case for case in load_dataset_cases(dataset_dir) if case.case_id in cohort_ids]
    if len(cases) != COHORT_SIZE:
        msg = f"Expected {COHORT_SIZE} cohort cases, loaded {len(cases)}"
        raise ReplicationVignetteError(msg)

    detection_dir = output_dir / "detection"
    detection_dir.mkdir(parents=True, exist_ok=True)
    analytics = compute_benchmark_analytics(cases)
    summary_path = detection_dir / "summary.csv"
    write_analysis_summary_csv(summary_path, cases=cases, analytics=analytics)

    mutation_path = detection_dir / "mutation_summary.csv"
    with mutation_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "case_id",
                "mutation_operator",
                "reference_bpr",
                "faulty_bpr",
                "bpr_delta",
                "fault_detected",
            ],
        )
        writer.writeheader()
        for case in cases:
            writer.writerow(
                {
                    "case_id": case.case_id,
                    "mutation_operator": case.mutation_operator,
                    "reference_bpr": round(case.reference_bpr, 6),
                    "faulty_bpr": round(case.faulty_bpr, 6),
                    "bpr_delta": round(case.bpr_delta, 6),
                    "fault_detected": int(case.bpr_delta > 0),
                }
            )

    manifest = {
        "release_label": CAMPAIGN_LABEL,
        "construct": "detection",
        "zenodo_doi": ZENODO_DOI,
        "cohort_path": str(cohort_path),
        "cohort_sha256": _sha256(cohort_path),
        "case_count": len(cases),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (detection_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return summary_path


def _write_metrics_by_partition(output_dir: Path) -> Path:
    rows: list[dict[str, str | float | int]] = []

    def summary_value(path: Path, metric: str) -> float:
        for row in csv.DictReader(path.open(encoding="utf-8")):
            if row["metric"] == metric:
                return float(row["value"])
        msg = f"Metric {metric} not found in {path}"
        raise ReplicationVignetteError(msg)

    detection_summary = output_dir / "detection" / "summary.csv"
    rows.extend(
        [
            {
                "campaign": CAMPAIGN_LABEL,
                "construct": "detection",
                "metric": "detection_rate",
                "partition": "cohort_wide",
                "subgroup": "all_cases",
                "n_cases": COHORT_SIZE,
                "value": summary_value(detection_summary, "overall_detection_rate"),
            },
            {
                "campaign": CAMPAIGN_LABEL,
                "construct": "detection",
                "metric": "detection_rate",
                "partition": "detectable_only",
                "subgroup": "oracle_detected",
                "n_cases": 10,
                "value": 1.0,
            },
        ]
    )

    for row in csv.DictReader((output_dir / "repair" / "leaderboard.csv").open(encoding="utf-8")):
        tool_id = row["tool_id"]
        n_detectable = int(row["detectable_cases"])
        n_total = int(row["cases"])
        for metric, detect_key, cohort_key in (
            ("complete_repair_rate", "complete_repair_rate_detectable_only", "complete_repair_rate"),
            ("effective_repair_rate", "effective_repair_rate_detectable_only", "effective_repair_rate"),
        ):
            rows.append(
                {
                    "campaign": CAMPAIGN_LABEL,
                    "construct": "repair",
                    "metric": metric,
                    "partition": "detectable_only",
                    "subgroup": tool_id,
                    "n_cases": n_detectable,
                    "value": float(row[detect_key]),
                }
            )
            rows.append(
                {
                    "campaign": CAMPAIGN_LABEL,
                    "construct": "repair",
                    "metric": metric,
                    "partition": "cohort_wide",
                    "subgroup": tool_id,
                    "n_cases": n_total,
                    "value": float(row[cohort_key]),
                }
            )

    localizable = output_dir / "localization" / "localization_metrics_localizable_only.csv"
    for row in csv.DictReader(localizable.open(encoding="utf-8")):
        if row["partition"] != "transition_localizable_gt":
            continue
        if row["metric"] not in {"top1_hit_rate", "top5_hit_rate", "mrr"}:
            continue
        rows.append(
            {
                "campaign": CAMPAIGN_LABEL,
                "construct": "localization",
                "metric": row["metric"],
                "partition": "transition_localizable_gt",
                "subgroup": "ochiai",
                "n_cases": int(float(row["denominator"])),
                "value": float(row["value"]),
            }
        )

    out_path = output_dir / "metrics_by_partition.csv"
    fieldnames = [
        "campaign",
        "construct",
        "metric",
        "partition",
        "subgroup",
        "n_cases",
        "value",
    ]
    with out_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            payload = dict(row)
            payload["value"] = round(float(payload["value"]), 6)
            writer.writerow(payload)
    return out_path


def build_headline_metrics(output_dir: Path) -> dict[str, Any]:
    """Collect headline detection, repair, and localization metrics from export dirs."""

    def metric_rows(path: Path) -> dict[str, str]:
        return {row["metric"]: row["value"] for row in csv.DictReader(path.open(encoding="utf-8"))}

    detection = metric_rows(output_dir / "detection" / "summary.csv")
    repair_tools: dict[str, dict[str, str]] = {}
    for row in csv.DictReader((output_dir / "repair" / "leaderboard.csv").open(encoding="utf-8")):
        repair_tools[row["tool_id"]] = row

    localizable: dict[str, float] = {}
    for row in csv.DictReader(
        (output_dir / "localization" / "localization_metrics_localizable_only.csv").open(encoding="utf-8")
    ):
        if row["partition"] == "transition_localizable_gt":
            localizable[row["metric"]] = float(row["value"])

    localization_summary = metric_rows(output_dir / "localization" / "summary.csv")
    return {
        "release_label": CAMPAIGN_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "cohort_size": COHORT_SIZE,
        "detectable_cases": int(localization_summary.get("detectable_denominator", "10")),
        "oracle_saturated_cases": COHORT_SIZE - int(localization_summary.get("detectable_denominator", "10")),
        "detection": {
            "overall_detection_rate": float(detection["overall_detection_rate"]),
            "mean_bpr_delta": float(detection["mean_bpr_delta"]),
        },
        "repair": {
            tool_id: {
                "complete_repair_rate_detectable_only": float(row["complete_repair_rate_detectable_only"]),
                "effective_repair_rate_detectable_only": float(row["effective_repair_rate_detectable_only"]),
                "complete_repair_rate_cohort_wide": float(row["complete_repair_rate"]),
                "effective_repair_rate_cohort_wide": float(row["effective_repair_rate"]),
            }
            for tool_id, row in repair_tools.items()
        },
        "localization": {
            "partition": "transition_localizable_gt",
            "n_cases": int(localizable.get("localized_cases", 8)),
            "top1_hit_rate": float(localizable["top1_hit_rate"]),
            "top5_hit_rate": float(localizable["top5_hit_rate"]),
            "mrr": float(localizable["mrr"]),
            "detectable_pool_top1_hit_rate": float(localization_summary["top1_hit_rate"]),
        },
    }


def write_headline_metrics(output_dir: Path) -> Path:
    path = output_dir / "headline_metrics.json"
    payload = build_headline_metrics(output_dir)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def write_vignette_checksums(root: Path) -> Path:
    """Write SHA-256 manifest for all frozen vignette exports under *root*."""
    lines = ["# FSMRepairBench replication vignette (20-case subset)", f"# Generated {datetime.now(UTC).isoformat()}", ""]
    for relative, _ in FROZEN_EXPORT_FILES:
        path = root / relative
        if not path.is_file():
            msg = f"Missing export for checksum: {path}"
            raise ReplicationVignetteError(msg)
        digest = _sha256(path)
        lines.append(f"{digest}  {relative}")
    checksum_path = root / "VIGNETTE.sha256"
    checksum_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return checksum_path


def sync_frozen_exports(source_dir: Path, artifact_dir: Path) -> None:
    frozen = artifact_dir / "frozen_exports"
    if frozen.exists():
        shutil.rmtree(frozen)
    frozen.mkdir(parents=True)
    for relative, _ in FROZEN_EXPORT_FILES:
        src = source_dir / relative
        dst = frozen / relative
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)


def sync_cohort_manifest(dataset_dir: Path, artifact_dir: Path) -> None:
    cohort_dir = artifact_dir / "cohort"
    cohort_dir.mkdir(parents=True, exist_ok=True)
    for name in (DEFAULT_COHORT_TXT, DEFAULT_COHORT_JSON):
        shutil.copy2(dataset_dir / name, cohort_dir / name)


def run_replication_vignette(
    dataset_dir: Path | None = None,
    *,
    output_dir: Path | None = None,
    paper_artifact_dir: Path | None = None,
    skip_repair_runs: bool = False,
    workers: int = 4,
) -> ReplicationVignetteResult:
    """Run detection, repair, and localization on the pinned 20-case vignette cohort."""
    dataset = (dataset_dir or DEFAULT_DATASET_DIR).resolve()
    out = (output_dir or DEFAULT_OUTPUT_DIR).resolve()
    artifact = (paper_artifact_dir or DEFAULT_PAPER_ARTIFACT_DIR).resolve()

    cohort_path, _ = pin_replication_vignette_cohort(dataset)
    _write_detection_exports(dataset, cohort_path, out)

    repair_dir = out / "repair"
    if repair_dir.exists() and not skip_repair_runs:
        shutil.rmtree(repair_dir)
    if not skip_repair_runs:
        run_c1_baseline_repair_experiment(
            dataset,
            out_dir=repair_dir,
            cohort_file=cohort_path,
            paper_export_dir=repair_dir,
            workers=workers,
            skip_multi_seed=True,
            resume=False,
        )

    localization_dir = out / "localization"
    if localization_dir.exists():
        shutil.rmtree(localization_dir)
    run_localization_campaign(
        dataset,
        output_dir=localization_dir,
        cohort_path=cohort_path,
    )
    run_localization_localizability_audit(
        dataset,
        output_dir=localization_dir,
    )

    _write_metrics_by_partition(out)
    headline_path = write_headline_metrics(out)

    artifact.mkdir(parents=True, exist_ok=True)
    sync_cohort_manifest(dataset, artifact)
    sync_frozen_exports(out, artifact)
    checksum_path = write_vignette_checksums(artifact / "frozen_exports")

    release = {
        "title": "FSMRepairBench STVR replication vignette (20-case subset)",
        "release_label": CAMPAIGN_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "parent_dataset": RELEASE_LABEL,
        "cohort_size": COHORT_SIZE,
        "cohort_sha256": COHORT_SHA256,
        "generated_at": datetime.now(UTC).isoformat(),
        "regeneration_command": "bash paper1/artifact/replication_vignette_20/run_replication_vignette.sh",
        "verification_command": "python paper1/scripts/verify_replication_vignette.py",
    }
    manifest_path = artifact / "RELEASE.json"
    manifest_path.write_text(json.dumps(release, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    shutil.copy2(checksum_path, artifact / "VIGNETTE.sha256")

    return ReplicationVignetteResult(
        dataset_dir=dataset,
        cohort_path=cohort_path,
        output_dir=out,
        paper_artifact_dir=artifact,
        headline_metrics_path=headline_path,
        checksum_path=checksum_path,
        manifest_path=manifest_path,
    )


def verify_replication_vignette(
    artifact_dir: Path,
    *,
    regenerated_dir: Path | None = None,
) -> list[str]:
    """Verify cohort digest and frozen export SHA-256 manifest."""
    errors: list[str] = []
    artifact = artifact_dir.resolve()
    cohort_txt = artifact / "cohort" / DEFAULT_COHORT_TXT
    if not cohort_txt.is_file():
        errors.append(f"Missing cohort manifest: {cohort_txt}")
    elif _sha256(cohort_txt) != COHORT_SHA256:
        errors.append(f"Cohort sha256 mismatch for {cohort_txt}")

    checksum_path = artifact / "VIGNETTE.sha256"
    if not checksum_path.is_file():
        errors.append(f"Missing checksum manifest: {checksum_path}")
        return errors

    frozen_root = artifact / "frozen_exports"
    for line in checksum_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        digest, relative = line.split(maxsplit=1)
        relative = relative.strip()
        path = frozen_root / relative
        if regenerated_dir is not None:
            regen = regenerated_dir / relative
            if regen.is_file() and _sha256(regen) != digest:
                errors.append(f"Regenerated sha256 mismatch: {relative}")
            continue
        if not path.is_file():
            errors.append(f"Missing frozen export: {relative}")
        elif _sha256(path) != digest:
            errors.append(f"Frozen sha256 mismatch: {relative}")

    expected = json.loads((frozen_root / "headline_metrics.json").read_text(encoding="utf-8"))
    if regenerated_dir is not None:
        actual = build_headline_metrics(regenerated_dir)
        if actual != expected:
            errors.append("Headline metrics differ from frozen headline_metrics.json")

    return errors
