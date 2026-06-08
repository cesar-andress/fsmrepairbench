"""Automatic benchmark difficulty calibration from structural and taxonomy features."""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fsmrepairbench.coverage_optimizer import CoverageOptimizerError, load_feature_matrix
from fsmrepairbench.difficulty import (
    REFERENCE_MAX_CYCLES,
    REFERENCE_MAX_SCC,
    REFERENCE_MAX_STATES,
    REFERENCE_MAX_TRANSITIONS,
    DifficultyCategory,
    category_for_score,
)
from fsmrepairbench.taxonomy import GuardComplexity, OracleDepth

DIFFICULTY_CALIBRATION_FILENAME = "difficulty_calibration.csv"
DIFFICULTY_CALIBRATION_REPORT_FILENAME = "difficulty_calibration_report.json"

CALIBRATION_NUMERIC_COLUMNS: tuple[str, ...] = (
    "num_states",
    "num_transitions",
    "num_cycles",
    "scc_count",
)

CALIBRATION_TAXONOMY_COLUMNS: tuple[str, ...] = (
    "guard_complexity",
    "oracle_depth",
)

CALIBRATION_COLUMNS: tuple[str, ...] = (
    "case_id",
    *CALIBRATION_NUMERIC_COLUMNS,
    *CALIBRATION_TAXONOMY_COLUMNS,
    "difficulty_score",
    "difficulty_bucket",
)

CalibrationMethod = Literal["fixed", "quantile"]

CALIBRATION_WEIGHTS: dict[str, float] = {
    "num_states": 0.20,
    "num_transitions": 0.20,
    "num_cycles": 0.15,
    "scc_count": 0.15,
    "guard_complexity": 0.15,
    "oracle_depth": 0.15,
}

REFERENCE_MAXIMA: dict[str, float] = {
    "num_states": float(REFERENCE_MAX_STATES),
    "num_transitions": float(REFERENCE_MAX_TRANSITIONS),
    "num_cycles": float(REFERENCE_MAX_CYCLES),
    "scc_count": float(REFERENCE_MAX_SCC),
}

GUARD_COMPLEXITY_SCORES: dict[str, float] = {
    GuardComplexity.NONE.value: 0.0,
    GuardComplexity.SIMPLE.value: 0.33,
    GuardComplexity.COMPOUND.value: 0.66,
    GuardComplexity.NESTED.value: 1.0,
}

ORACLE_DEPTH_SCORES: dict[str, float] = {
    OracleDepth.SHALLOW.value: 0.0,
    OracleDepth.MEDIUM.value: 0.33,
    OracleDepth.DEEP.value: 0.66,
    OracleDepth.EXHAUSTIVE_LIKE.value: 1.0,
}

FIXED_BUCKET_THRESHOLDS: tuple[float, float, float] = (25.0, 50.0, 75.0)


class DifficultyCalibrationError(ValueError):
    """Raised when benchmark difficulty calibration fails."""


@dataclass(frozen=True)
class DifficultyCalibrationRow:
    """Calibrated difficulty for one benchmark case."""

    case_id: str
    num_states: int
    num_transitions: int
    num_cycles: int
    scc_count: int
    guard_complexity: str
    oracle_depth: str
    difficulty_score: float
    difficulty_bucket: DifficultyCategory

    def to_csv_row(self) -> dict[str, str | float]:
        return {
            "case_id": self.case_id,
            "num_states": self.num_states,
            "num_transitions": self.num_transitions,
            "num_cycles": self.num_cycles,
            "scc_count": self.scc_count,
            "guard_complexity": self.guard_complexity,
            "oracle_depth": self.oracle_depth,
            "difficulty_score": round(self.difficulty_score, 2),
            "difficulty_bucket": self.difficulty_bucket,
        }


@dataclass(frozen=True)
class DifficultyCalibrationResult:
    """Artifacts produced by benchmark difficulty calibration."""

    dataset_dir: Path
    feature_matrix_path: Path
    calibration_path: Path
    report_path: Path
    rows: tuple[DifficultyCalibrationRow, ...]
    report: dict[str, Any]


def _normalize_numeric(column: str, value: int) -> float:
    maximum = REFERENCE_MAXIMA[column]
    return min(1.0, float(value) / maximum)


def _normalize_taxonomy(column: str, value: str) -> float:
    if column == "guard_complexity":
        mapping = GUARD_COMPLEXITY_SCORES
    elif column == "oracle_depth":
        mapping = ORACLE_DEPTH_SCORES
    else:
        msg = f"Unsupported taxonomy column: {column}"
        raise DifficultyCalibrationError(msg)

    if value not in mapping:
        msg = f"Unknown {column} value: {value}"
        raise DifficultyCalibrationError(msg)
    return mapping[value]


def compute_difficulty_score(
    *,
    num_states: int,
    num_transitions: int,
    num_cycles: int,
    scc_count: int,
    guard_complexity: str,
    oracle_depth: str,
) -> float:
    """Compute a composite difficulty score in ``[0, 100]``."""
    normalized = {
        "num_states": _normalize_numeric("num_states", num_states),
        "num_transitions": _normalize_numeric("num_transitions", num_transitions),
        "num_cycles": _normalize_numeric("num_cycles", num_cycles),
        "scc_count": _normalize_numeric("scc_count", scc_count),
        "guard_complexity": _normalize_taxonomy("guard_complexity", guard_complexity),
        "oracle_depth": _normalize_taxonomy("oracle_depth", oracle_depth),
    }
    weighted = sum(CALIBRATION_WEIGHTS[name] * normalized[name] for name in CALIBRATION_WEIGHTS)
    return round(min(100.0, max(0.0, weighted * 100.0)), 2)


def _parse_non_negative_int(row: dict[str, str], column: str, *, case_id: str) -> int:
    raw = row.get(column, "").strip()
    if not raw:
        msg = f"Case {case_id} missing {column}"
        raise DifficultyCalibrationError(msg)
    try:
        value = int(raw)
    except ValueError as exc:
        msg = f"Case {case_id} has invalid {column}: {raw!r}"
        raise DifficultyCalibrationError(msg) from exc
    if value < 0:
        msg = f"Case {case_id} has negative {column}: {value}"
        raise DifficultyCalibrationError(msg)
    return value


def calibrate_case_row(row: dict[str, str]) -> DifficultyCalibrationRow:
    """Build a calibration row from one feature-matrix record."""
    case_id = row.get("case_id", "").strip()
    if not case_id:
        msg = "Feature matrix row missing case_id"
        raise DifficultyCalibrationError(msg)

    num_states = _parse_non_negative_int(row, "num_states", case_id=case_id)
    num_transitions = _parse_non_negative_int(row, "num_transitions", case_id=case_id)
    num_cycles = _parse_non_negative_int(row, "num_cycles", case_id=case_id)
    scc_count = _parse_non_negative_int(row, "scc_count", case_id=case_id)

    guard_complexity = row.get("guard_complexity", "").strip()
    oracle_depth = row.get("oracle_depth", "").strip()
    if not guard_complexity or not oracle_depth:
        msg = f"Case {case_id} missing guard_complexity or oracle_depth"
        raise DifficultyCalibrationError(msg)

    score = compute_difficulty_score(
        num_states=num_states,
        num_transitions=num_transitions,
        num_cycles=num_cycles,
        scc_count=scc_count,
        guard_complexity=guard_complexity,
        oracle_depth=oracle_depth,
    )
    return DifficultyCalibrationRow(
        case_id=case_id,
        num_states=num_states,
        num_transitions=num_transitions,
        num_cycles=num_cycles,
        scc_count=scc_count,
        guard_complexity=guard_complexity,
        oracle_depth=oracle_depth,
        difficulty_score=score,
        difficulty_bucket="easy",
    )


def _quantile_thresholds(scores: list[float]) -> tuple[float, float, float]:
    if len(scores) < 4:
        return FIXED_BUCKET_THRESHOLDS

    ordered = sorted(scores)
    size = len(ordered)

    def percentile(percent: float) -> float:
        if size == 1:
            return ordered[0]
        index = (size - 1) * percent
        lower = int(index)
        upper = min(lower + 1, size - 1)
        weight = index - lower
        return ordered[lower] * (1.0 - weight) + ordered[upper] * weight

    return (
        round(percentile(0.25), 2),
        round(percentile(0.50), 2),
        round(percentile(0.75), 2),
    )


def bucket_for_score_with_thresholds(
    score: float,
    thresholds: tuple[float, float, float],
) -> DifficultyCategory:
    """Map a score to a bucket using explicit thresholds."""
    easy_max, medium_max, hard_max = thresholds
    if score <= easy_max:
        return "easy"
    if score <= medium_max:
        return "medium"
    if score <= hard_max:
        return "hard"
    return "expert"


def assign_difficulty_buckets(
    rows: list[DifficultyCalibrationRow],
    *,
    method: CalibrationMethod = "quantile",
) -> tuple[DifficultyCalibrationRow, ...]:
    """Assign difficulty buckets to calibrated rows."""
    if not rows:
        msg = "No calibration rows to bucket"
        raise DifficultyCalibrationError(msg)

    scores = [row.difficulty_score for row in rows]
    thresholds = FIXED_BUCKET_THRESHOLDS if method == "fixed" else _quantile_thresholds(scores)

    bucketed: list[DifficultyCalibrationRow] = []
    for row in rows:
        bucket = (
            category_for_score(row.difficulty_score)
            if method == "fixed"
            else bucket_for_score_with_thresholds(row.difficulty_score, thresholds)
        )
        bucketed.append(
            DifficultyCalibrationRow(
                case_id=row.case_id,
                num_states=row.num_states,
                num_transitions=row.num_transitions,
                num_cycles=row.num_cycles,
                scc_count=row.scc_count,
                guard_complexity=row.guard_complexity,
                oracle_depth=row.oracle_depth,
                difficulty_score=row.difficulty_score,
                difficulty_bucket=bucket,
            )
        )
    return tuple(bucketed)


def calibrate_difficulty_rows(
    matrix_rows: list[dict[str, str]],
    *,
    bucket_method: CalibrationMethod = "quantile",
) -> tuple[DifficultyCalibrationRow, ...]:
    """Calibrate difficulty for all feature-matrix rows."""
    missing_columns = [
        column
        for column in (*CALIBRATION_NUMERIC_COLUMNS, *CALIBRATION_TAXONOMY_COLUMNS)
        if matrix_rows and column not in matrix_rows[0]
    ]
    if missing_columns:
        msg = f"Feature matrix missing calibration columns: {', '.join(missing_columns)}"
        raise DifficultyCalibrationError(msg)

    preliminary = [calibrate_case_row(row) for row in matrix_rows]
    return assign_difficulty_buckets(preliminary, method=bucket_method)


def write_difficulty_calibration_csv(
    path: Path,
    rows: tuple[DifficultyCalibrationRow, ...],
) -> None:
    """Write calibrated difficulty rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(CALIBRATION_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())


def build_calibration_report(
    *,
    feature_matrix_path: Path,
    rows: tuple[DifficultyCalibrationRow, ...],
    bucket_method: CalibrationMethod,
) -> dict[str, Any]:
    """Build a JSON summary of difficulty calibration."""
    scores = [row.difficulty_score for row in rows]
    bucket_counts = Counter(row.difficulty_bucket for row in rows)
    thresholds = (
        FIXED_BUCKET_THRESHOLDS
        if bucket_method == "fixed"
        else _quantile_thresholds(scores)
    )
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "feature_matrix_path": str(feature_matrix_path),
        "calibration_method": bucket_method,
        "calibration_weights": dict(CALIBRATION_WEIGHTS),
        "bucket_thresholds": {
            "easy_max": thresholds[0],
            "medium_max": thresholds[1],
            "hard_max": thresholds[2],
        },
        "case_count": len(rows),
        "score_statistics": {
            "min": min(scores),
            "max": max(scores),
            "mean": round(statistics.mean(scores), 2),
            "median": round(statistics.median(scores), 2),
        },
        "bucket_distribution": dict(sorted(bucket_counts.items())),
    }


def calibrate_benchmark_difficulty(
    dataset_dir: Path,
    *,
    bucket_method: CalibrationMethod = "quantile",
    output_dir: Path | None = None,
) -> DifficultyCalibrationResult:
    """Calibrate benchmark difficulty and write difficulty_calibration.csv."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise DifficultyCalibrationError(msg)

    feature_matrix_path = dataset_dir / "feature_matrix.csv"
    matrix_rows = load_feature_matrix(feature_matrix_path)
    rows = calibrate_difficulty_rows(matrix_rows, bucket_method=bucket_method)

    destination = output_dir or dataset_dir
    calibration_path = destination / DIFFICULTY_CALIBRATION_FILENAME
    report_path = destination / DIFFICULTY_CALIBRATION_REPORT_FILENAME

    write_difficulty_calibration_csv(calibration_path, rows)
    report = build_calibration_report(
        feature_matrix_path=feature_matrix_path,
        rows=rows,
        bucket_method=bucket_method,
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return DifficultyCalibrationResult(
        dataset_dir=dataset_dir,
        feature_matrix_path=feature_matrix_path,
        calibration_path=calibration_path,
        report_path=report_path,
        rows=rows,
        report=report,
    )
