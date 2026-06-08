"""Automatic benchmark dataset quality validation."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fsmrepairbench.coverage_optimizer import (
    COVERAGE_FEATURES,
    _feature_entropy,
    _missing_combinations,
    analyze_feature_coverage,
    load_feature_matrix,
)
from fsmrepairbench.dataset_builder import REQUIRED_CASE_FILES, is_case_complete
from fsmrepairbench.models import FSM
from fsmrepairbench.taxonomy import CaseFeatures
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite, validate_fsm
from fsmrepairbench.versioning import (
    VersioningError,
    detect_benchmark_version,
    discover_case_directories,
    is_stable_case_id,
    version_spec,
)

QUALITY_REPORT_FILENAME = "quality_report.json"

Severity = Literal["info", "warning", "error"]
CheckStatus = Literal["pass", "warn", "fail"]

CLASS_IMBALANCE_THRESHOLD = 0.50
COVERAGE_IMBALANCE_THRESHOLD = 0.10
NEAR_DUPLICATE_JACCARD_THRESHOLD = 0.90
SUSPICIOUS_SEED_REPEAT_THRESHOLD = 3
IMBALANCE_FEATURES: tuple[str, ...] = (
    "bug_type",
    "machine_type",
    "size_class",
    "mutation_operator",
)


class DatasetQualityError(ValueError):
    """Raised when dataset quality validation cannot run."""


@dataclass(frozen=True)
class QualityFinding:
    """One quality issue detected in a dataset."""

    check: str
    severity: Severity
    message: str
    case_ids: tuple[str, ...] = ()
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "severity": self.severity,
            "message": self.message,
            "case_ids": list(self.case_ids),
        }
        if self.details:
            payload["details"] = self.details
        return payload


@dataclass(frozen=True)
class DatasetQualityResult:
    """Quality validation outcome for one dataset."""

    dataset_dir: Path
    report_path: Path
    report: dict[str, Any]
    passed: bool


def _canonical_json_hash(path: Path) -> str:
    payload = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _transition_set(fsm: FSM) -> set[tuple[str, str, str]]:
    return {(transition.source, transition.event, transition.target) for transition in fsm.transitions}


def _jaccard(left: set[tuple[str, str, str]], right: set[tuple[str, str, str]]) -> float:
    if not left and not right:
        return 1.0
    union = left | right
    if not union:
        return 0.0
    return len(left & right) / len(union)


def _check_status(findings: list[QualityFinding]) -> CheckStatus:
    if any(finding.severity == "error" for finding in findings):
        return "fail"
    if findings:
        return "warn"
    return "pass"


def _group_findings(findings: list[QualityFinding]) -> dict[str, Any]:
    status = _check_status(findings)
    return {
        "status": status,
        "finding_count": len(findings),
        "findings": [finding.to_dict() for finding in findings],
    }


def check_duplicate_fsms(case_dirs: list[Path]) -> list[QualityFinding]:
    """Detect exact duplicate reference FSMs across cases."""
    buckets: dict[str, list[str]] = defaultdict(list)
    findings: list[QualityFinding] = []

    for case_dir in case_dirs:
        reference_path = case_dir / "reference_fsm.json"
        if not reference_path.is_file():
            continue
        digest = _canonical_json_hash(reference_path)
        buckets[digest].append(case_dir.name)

    for digest, case_ids in buckets.items():
        if len(case_ids) < 2:
            continue
        findings.append(
            QualityFinding(
                check="duplicate_fsms",
                severity="warning",
                message="Exact duplicate reference FSM content across cases",
                case_ids=tuple(sorted(case_ids)),
                details={"content_hash": digest[:16]},
            )
        )
    return findings


def check_near_duplicate_fsms(case_dirs: list[Path]) -> list[QualityFinding]:
    """Detect structurally similar reference FSMs."""
    entries: list[tuple[str, str, FSM, set[tuple[str, str, str]]]] = []
    findings: list[QualityFinding] = []

    for case_dir in case_dirs:
        reference_path = case_dir / "reference_fsm.json"
        if not reference_path.is_file():
            continue
        digest = _canonical_json_hash(reference_path)
        fsm = load_fsm_json(reference_path)
        entries.append((case_dir.name, digest, fsm, _transition_set(fsm)))

    for index, (case_id_a, digest_a, fsm_a, transitions_a) in enumerate(entries):
        for case_id_b, digest_b, fsm_b, transitions_b in entries[index + 1 :]:
            if digest_a == digest_b:
                continue
            jaccard = _jaccard(transitions_a, transitions_b)
            if (
                len(fsm_a.states) == len(fsm_b.states)
                and jaccard >= NEAR_DUPLICATE_JACCARD_THRESHOLD
            ):
                findings.append(
                    QualityFinding(
                        check="near_duplicate_fsms",
                        severity="warning",
                        message="Near-duplicate reference FSM structure detected",
                        case_ids=(case_id_a, case_id_b),
                        details={
                            "transition_jaccard": round(jaccard, 4),
                            "state_count": len(fsm_a.states),
                            "transition_count": len(fsm_a.transitions),
                        },
                    )
                )
    return findings


def check_duplicate_oracle_suites(case_dirs: list[Path]) -> list[QualityFinding]:
    """Detect exact duplicate oracle suites across cases."""
    buckets: dict[str, list[str]] = defaultdict(list)
    findings: list[QualityFinding] = []

    for case_dir in case_dirs:
        oracle_path = case_dir / "oracle_suite.json"
        if not oracle_path.is_file():
            continue
        digest = _canonical_json_hash(oracle_path)
        buckets[digest].append(case_dir.name)

    for digest, case_ids in buckets.items():
        if len(case_ids) < 2:
            continue
        findings.append(
            QualityFinding(
                check="duplicate_oracle_suites",
                severity="warning",
                message="Exact duplicate oracle suite content across cases",
                case_ids=tuple(sorted(case_ids)),
                details={"content_hash": digest[:16]},
            )
        )
    return findings


def check_invalid_metadata(case_dirs: list[Path]) -> list[QualityFinding]:
    """Validate per-case metadata and FSM/oracle documents."""
    findings: list[QualityFinding] = []

    for case_dir in case_dirs:
        case_id = case_dir.name
        if not is_stable_case_id(case_id):
            findings.append(
                QualityFinding(
                    check="invalid_metadata",
                    severity="error",
                    message="Case directory name is not a stable case ID",
                    case_ids=(case_id,),
                )
            )

        metadata_path = case_dir / "case_metadata.json"
        if metadata_path.is_file():
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                findings.append(
                    QualityFinding(
                        check="invalid_metadata",
                        severity="error",
                        message=f"Invalid case_metadata.json: {exc}",
                        case_ids=(case_id,),
                    )
                )
                metadata = {}
            else:
                recorded_case_id = str(metadata.get("case_id", ""))
                if recorded_case_id and recorded_case_id != case_id:
                    findings.append(
                        QualityFinding(
                            check="invalid_metadata",
                            severity="error",
                            message="case_metadata.case_id does not match directory name",
                            case_ids=(case_id,),
                            details={"recorded_case_id": recorded_case_id},
                        )
                    )
                reference_bpr = metadata.get("reference_bpr")
                if reference_bpr is not None and float(reference_bpr) < 1.0:
                    findings.append(
                        QualityFinding(
                            check="invalid_metadata",
                            severity="warning",
                            message="Reference FSM BPR is below 1.0 in metadata",
                            case_ids=(case_id,),
                            details={"reference_bpr": float(reference_bpr)},
                        )
                    )

        reference_path = case_dir / "reference_fsm.json"
        if reference_path.is_file():
            reference = load_fsm_json(reference_path)
            reference_errors = validate_fsm(reference)
            if reference_errors:
                findings.append(
                    QualityFinding(
                        check="invalid_metadata",
                        severity="error",
                        message=f"Invalid reference FSM: {reference_errors[0]}",
                        case_ids=(case_id,),
                    )
                )

        faulty_path = case_dir / "faulty_fsm.json"
        if faulty_path.is_file():
            faulty = load_fsm_json(faulty_path)
            faulty_errors = validate_fsm(faulty)
            if faulty_errors:
                findings.append(
                    QualityFinding(
                        check="invalid_metadata",
                        severity="error",
                        message=f"Invalid faulty FSM: {faulty_errors[0]}",
                        case_ids=(case_id,),
                    )
                )

        oracle_path = case_dir / "oracle_suite.json"
        if oracle_path.is_file():
            try:
                oracle = load_oracle_suite(oracle_path)
            except (OSError, json.JSONDecodeError, ValueError) as exc:
                findings.append(
                    QualityFinding(
                        check="invalid_metadata",
                        severity="error",
                        message=f"Invalid oracle suite: {exc}",
                        case_ids=(case_id,),
                    )
                )
            else:
                if oracle.fsm_id is not None and reference_path.is_file():
                    reference = load_fsm_json(reference_path)
                    if oracle.fsm_id != reference.id:
                        findings.append(
                            QualityFinding(
                                check="invalid_metadata",
                                severity="warning",
                                message="Oracle fsm_id does not match reference FSM id",
                                case_ids=(case_id,),
                                details={
                                    "oracle_fsm_id": oracle.fsm_id,
                                    "reference_fsm_id": reference.id,
                                },
                            )
                        )

        for filename in REQUIRED_CASE_FILES:
            if not (case_dir / filename).is_file():
                findings.append(
                    QualityFinding(
                        check="invalid_metadata",
                        severity="error",
                        message=f"Missing required case file: {filename}",
                        case_ids=(case_id,),
                    )
                )
    return findings


def check_invalid_feature_vectors(
    dataset_dir: Path,
    case_dirs: list[Path],
) -> list[QualityFinding]:
    """Validate feature_matrix.csv and case_features.json consistency."""
    findings: list[QualityFinding] = []
    case_ids = {case_dir.name for case_dir in case_dirs}

    feature_matrix_path = dataset_dir / "feature_matrix.csv"
    if feature_matrix_path.is_file():
        try:
            rows = load_feature_matrix(feature_matrix_path)
        except ValueError as exc:
            findings.append(
                QualityFinding(
                    check="invalid_feature_vectors",
                    severity="error",
                    message=str(exc),
                    details={"path": str(feature_matrix_path)},
                )
            )
            rows = []
        else:
            matrix_case_ids = {row["case_id"] for row in rows}
            missing_in_matrix = sorted(case_ids - matrix_case_ids)
            extra_in_matrix = sorted(matrix_case_ids - case_ids)
            if missing_in_matrix:
                findings.append(
                    QualityFinding(
                        check="invalid_feature_vectors",
                        severity="warning",
                        message="Cases missing from feature_matrix.csv",
                        case_ids=tuple(missing_in_matrix[:20]),
                        details={"missing_count": len(missing_in_matrix)},
                    )
                )
            if extra_in_matrix:
                findings.append(
                    QualityFinding(
                        check="invalid_feature_vectors",
                        severity="warning",
                        message="feature_matrix.csv references unknown case IDs",
                        case_ids=tuple(extra_in_matrix[:20]),
                        details={"extra_count": len(extra_in_matrix)},
                    )
                )
            for row in rows:
                for feature in COVERAGE_FEATURES:
                    if not str(row.get(feature, "")).strip():
                        findings.append(
                            QualityFinding(
                                check="invalid_feature_vectors",
                                severity="error",
                                message=f"Empty feature value for '{feature}'",
                                case_ids=(row["case_id"],),
                            )
                        )
                        break

    for case_dir in case_dirs:
        features_path = case_dir / "case_features.json"
        if not features_path.is_file():
            continue
        try:
            CaseFeatures.model_validate_json(features_path.read_text(encoding="utf-8"))
        except ValueError as exc:
            findings.append(
                QualityFinding(
                    check="invalid_feature_vectors",
                    severity="error",
                    message=f"Invalid case_features.json: {exc}",
                    case_ids=(case_dir.name,),
                )
            )

    if not feature_matrix_path.is_file() and not any(
        (case_dir / "case_features.json").is_file() for case_dir in case_dirs
    ):
        findings.append(
            QualityFinding(
                check="invalid_feature_vectors",
                severity="info",
                message="No feature_matrix.csv or case_features.json found; feature checks skipped",
            )
        )
    return findings


def _distribution(rows: list[dict[str, str]], feature: str) -> Counter[str]:
    return Counter(str(row.get(feature, "")) for row in rows)


def check_class_imbalance(
    rows: list[dict[str, str]],
    metadata_rows: list[dict[str, Any]],
) -> list[QualityFinding]:
    """Detect heavily skewed taxonomy or mutation distributions."""
    findings: list[QualityFinding] = []

    if rows:
        total = len(rows)
        for feature in IMBALANCE_FEATURES:
            if feature not in rows[0]:
                continue
            counts = _distribution(rows, feature)
            for value, count in counts.most_common(1):
                share = count / total
                if share >= CLASS_IMBALANCE_THRESHOLD:
                    affected = sorted(row["case_id"] for row in rows if row.get(feature) == value)
                    findings.append(
                        QualityFinding(
                            check="class_imbalance",
                            severity="warning",
                            message=f"Feature '{feature}' value '{value}' dominates the dataset",
                            case_ids=tuple(affected[:20]),
                            details={
                                "feature": feature,
                                "value": value,
                                "share": round(share, 4),
                                "count": count,
                                "total": total,
                            },
                        )
                    )
        return findings

    if metadata_rows:
        total = len(metadata_rows)
        operator_counts = Counter(str(row.get("mutation_operator", "unknown")) for row in metadata_rows)
        value, count = operator_counts.most_common(1)[0]
        share = count / total
        if share >= CLASS_IMBALANCE_THRESHOLD:
            findings.append(
                QualityFinding(
                    check="class_imbalance",
                    severity="warning",
                    message=f"Mutation operator '{value}' dominates the dataset",
                    details={"share": round(share, 4), "count": count, "total": total},
                )
            )
    return findings


def check_coverage_imbalance(rows: list[dict[str, str]]) -> list[QualityFinding]:
    """Detect low feature-space coverage and entropy."""
    findings: list[QualityFinding] = []
    if not rows:
        return findings

    entropies = _feature_entropy(rows)
    max_entropy = math.log2(len(rows)) if len(rows) > 1 else 1.0
    for feature, entropy in entropies.items():
        normalized = entropy / max_entropy if max_entropy > 0 else 0.0
        if len(rows) >= 5 and normalized < COVERAGE_IMBALANCE_THRESHOLD:
            findings.append(
                QualityFinding(
                    check="coverage_imbalance",
                    severity="warning",
                    message=f"Low normalized entropy for feature '{feature}'",
                    details={
                        "feature": feature,
                        "entropy": entropy,
                        "normalized_entropy": round(normalized, 4),
                    },
                )
            )

    missing = _missing_combinations(rows)
    if missing["possible_count"] > 0:
        missing_ratio = missing["missing_count"] / missing["possible_count"]
        if missing_ratio >= 0.95 and len(rows) >= 3:
            findings.append(
                QualityFinding(
                    check="coverage_imbalance",
                    severity="warning",
                    message="Taxonomy combination space is severely under-covered",
                    details={
                        "missing_count": missing["missing_count"],
                        "possible_count": missing["possible_count"],
                        "missing_ratio": round(missing_ratio, 4),
                    },
                )
            )
    return findings


def check_suspicious_generation_patterns(
    case_dirs: list[Path],
    rows: list[dict[str, str]],
) -> list[QualityFinding]:
    """Detect suspicious generation artefacts and weak fault injections."""
    findings: list[QualityFinding] = []

    if rows:
        seed_counts = Counter(str(row.get("seed", "")) for row in rows if str(row.get("seed", "")))
        for seed, count in seed_counts.items():
            if count >= SUSPICIOUS_SEED_REPEAT_THRESHOLD:
                affected = sorted(row["case_id"] for row in rows if str(row.get("seed", "")) == seed)
                findings.append(
                    QualityFinding(
                        check="suspicious_generation_patterns",
                        severity="warning",
                        message=f"Seed '{seed}' reused across many cases",
                        case_ids=tuple(affected[:20]),
                        details={"seed": seed, "count": count},
                    )
                )

        combo_counts = Counter(
            (
                str(row.get("seed", "")),
                str(row.get("bug_type", "")),
                str(row.get("machine_type", "")),
            )
            for row in rows
        )
        for combo, count in combo_counts.items():
            if count >= SUSPICIOUS_SEED_REPEAT_THRESHOLD:
                findings.append(
                    QualityFinding(
                        check="suspicious_generation_patterns",
                        severity="info",
                        message="Repeated seed/bug_type/machine_type generation tuple",
                        details={"tuple": combo, "count": count},
                    )
                )

    for case_dir in case_dirs:
        metadata_path = case_dir / "case_metadata.json"
        if not metadata_path.is_file():
            continue
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        reference_bpr = float(metadata.get("reference_bpr", 1.0))
        faulty_bpr = float(metadata.get("faulty_bpr", 0.0))
        if abs(reference_bpr - faulty_bpr) < 1e-9:
            findings.append(
                QualityFinding(
                    check="suspicious_generation_patterns",
                    severity="warning",
                    message="Faulty FSM BPR equals reference BPR; mutation may be ineffective",
                    case_ids=(case_dir.name,),
                    details={"reference_bpr": reference_bpr, "faulty_bpr": faulty_bpr},
                )
            )
        if faulty_bpr >= reference_bpr and reference_bpr < 1.0:
            findings.append(
                QualityFinding(
                    check="suspicious_generation_patterns",
                    severity="warning",
                    message="Faulty BPR is not lower than reference BPR",
                    case_ids=(case_dir.name,),
                    details={"reference_bpr": reference_bpr, "faulty_bpr": faulty_bpr},
                )
            )
    return findings


def validate_dataset(
    dataset_dir: Path,
    *,
    output_path: Path | None = None,
) -> DatasetQualityResult:
    """Run benchmark quality checks and write quality_report.json."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise DatasetQualityError(msg)

    try:
        case_dirs = discover_case_directories(dataset_dir)
    except VersioningError as exc:
        raise DatasetQualityError(str(exc)) from exc

    if not case_dirs:
        cases_root = dataset_dir / "cases"
        if cases_root.is_dir():
            case_dirs = sorted(
                path for path in cases_root.iterdir() if path.is_dir() and is_case_complete(path)
            )
    if not case_dirs:
        msg = f"No benchmark cases found under {dataset_dir}"
        raise DatasetQualityError(msg)

    feature_rows: list[dict[str, str]] = []
    feature_matrix_path = dataset_dir / "feature_matrix.csv"
    if feature_matrix_path.is_file():
        try:
            feature_rows = load_feature_matrix(feature_matrix_path)
        except ValueError:
            feature_rows = []

    metadata_rows: list[dict[str, Any]] = []
    for case_dir in case_dirs:
        metadata_path = case_dir / "case_metadata.json"
        if metadata_path.is_file():
            metadata_rows.append(json.loads(metadata_path.read_text(encoding="utf-8")))

    all_findings: dict[str, list[QualityFinding]] = {
        "duplicate_fsms": check_duplicate_fsms(case_dirs),
        "near_duplicate_fsms": check_near_duplicate_fsms(case_dirs),
        "duplicate_oracle_suites": check_duplicate_oracle_suites(case_dirs),
        "invalid_metadata": check_invalid_metadata(case_dirs),
        "invalid_feature_vectors": check_invalid_feature_vectors(dataset_dir, case_dirs),
        "class_imbalance": check_class_imbalance(feature_rows, metadata_rows),
        "coverage_imbalance": check_coverage_imbalance(feature_rows),
        "suspicious_generation_patterns": check_suspicious_generation_patterns(
            case_dirs,
            feature_rows,
        ),
    }

    flat_findings = [finding for findings in all_findings.values() for finding in findings]
    summary = Counter(finding.severity for finding in flat_findings)
    overall_status: CheckStatus = "pass"
    if summary["error"] > 0:
        overall_status = "fail"
    elif summary["warning"] > 0 or summary["info"] > 0:
        overall_status = "warn"

    try:
        benchmark_version = detect_benchmark_version(dataset_dir).value
        required_files = list(version_spec(detect_benchmark_version(dataset_dir)).required_case_files)
    except VersioningError:
        benchmark_version = "unknown"
        required_files = list(REQUIRED_CASE_FILES)

    coverage_summary: dict[str, Any] | None = None
    if feature_matrix_path.is_file() and feature_rows:
        coverage_summary = {
            "case_count": len(feature_rows),
            "feature_entropy": _feature_entropy(feature_rows),
            "missing_combinations": _missing_combinations(feature_rows),
        }

    report: dict[str, Any] = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "dataset_dir": str(dataset_dir),
        "benchmark_version": benchmark_version,
        "case_count": len(case_dirs),
        "overall_status": overall_status,
        "summary": {
            "errors": summary["error"],
            "warnings": summary["warning"],
            "info": summary["info"],
            "passed": overall_status == "pass",
        },
        "required_case_files": required_files,
        "checks": {name: _group_findings(findings) for name, findings in all_findings.items()},
        "coverage_summary": coverage_summary,
    }

    if feature_matrix_path.is_file() and feature_rows:
        report["feature_matrix_analysis"] = analyze_feature_coverage(
            feature_matrix_path,
            suggestion_count=min(200, max(20, len(feature_rows) * 5)),
        )

    report_path = output_path or (dataset_dir / QUALITY_REPORT_FILENAME)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return DatasetQualityResult(
        dataset_dir=dataset_dir,
        report_path=report_path,
        report=report,
        passed=overall_status != "fail",
    )
