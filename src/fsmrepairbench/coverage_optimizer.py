"""Benchmark feature-space coverage analysis and generation suggestions."""

from __future__ import annotations

import csv
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import combinations, product
from pathlib import Path
from typing import Any

from fsmrepairbench.taxonomy import (
    ArityClass,
    BugType,
    Completeness,
    Determinism,
    GraphStructure,
    GuardComplexity,
    MachineType,
    OracleDepth,
    SizeClass,
    TimeFeature,
)

COVERAGE_REPORT_FILENAME = "coverage_report.json"

COVERAGE_FEATURES: tuple[str, ...] = (
    "machine_type",
    "determinism",
    "completeness",
    "arity_class",
    "size_class",
    "guard_complexity",
    "time_features",
    "graph_structure",
    "oracle_depth",
    "bug_type",
)

PAIRWISE_FEATURES: tuple[str, ...] = (
    "machine_type",
    "determinism",
    "bug_type",
    "size_class",
    "arity_class",
    "guard_complexity",
    "oracle_depth",
)

TRIPLE_FEATURES: tuple[str, ...] = (
    "machine_type",
    "bug_type",
    "size_class",
)

SUGGESTION_FEATURES: tuple[str, ...] = (
    "machine_type",
    "determinism",
    "bug_type",
    "size_class",
    "arity_class",
)

FEATURE_UNIVERSES: dict[str, tuple[str, ...]] = {
    "machine_type": tuple(item.value for item in MachineType),
    "determinism": tuple(item.value for item in Determinism),
    "completeness": tuple(item.value for item in Completeness),
    "arity_class": tuple(item.value for item in ArityClass),
    "size_class": tuple(item.value for item in SizeClass),
    "guard_complexity": tuple(item.value for item in GuardComplexity),
    "time_features": tuple(item.value for item in TimeFeature),
    "graph_structure": tuple(item.value for item in GraphStructure),
    "oracle_depth": tuple(item.value for item in OracleDepth),
    "bug_type": tuple(item.value for item in BugType),
}


class CoverageOptimizerError(ValueError):
    """Raised when coverage analysis cannot be completed."""


@dataclass(frozen=True)
class CoverageReportResult:
    """Paths and payload from a coverage analysis run."""

    dataset_dir: Path
    feature_matrix_path: Path
    report_path: Path
    report: dict[str, Any]


def load_feature_matrix(path: Path) -> list[dict[str, str]]:
    """Load rows from *path* as string dictionaries."""
    if not path.is_file():
        msg = f"Feature matrix not found: {path}"
        raise CoverageOptimizerError(msg)

    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"Feature matrix has no header row: {path}"
            raise CoverageOptimizerError(msg)
        rows = [dict(row) for row in reader]

    if not rows:
        msg = f"Feature matrix is empty: {path}"
        raise CoverageOptimizerError(msg)

    missing_columns = [column for column in COVERAGE_FEATURES if column not in reader.fieldnames]
    if missing_columns:
        msg = f"Feature matrix missing columns: {', '.join(missing_columns)}"
        raise CoverageOptimizerError(msg)

    return rows


def _combination_key(row: dict[str, str], features: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(row[feature] for feature in features)


def _entropy(counts: Counter[str]) -> float:
    total = sum(counts.values())
    if total == 0:
        return 0.0
    entropy = 0.0
    for count in counts.values():
        if count <= 0:
            continue
        probability = count / total
        entropy -= probability * math.log2(probability)
    return round(entropy, 6)


def _feature_entropy(rows: list[dict[str, str]]) -> dict[str, float]:
    entropies: dict[str, float] = {}
    for feature in COVERAGE_FEATURES:
        counts = Counter(row[feature] for row in rows)
        entropies[feature] = _entropy(counts)
    return entropies


def _pairwise_coverage(rows: list[dict[str, str]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for left, right in combinations(PAIRWISE_FEATURES, 2):
        key = f"{left}__{right}"
        left_values = _values_for_feature(rows, left)
        right_values = _values_for_feature(rows, right)
        observed = {
            (row[left], row[right])
            for row in rows
        }
        possible = len(left_values) * len(right_values)
        results[key] = {
            "feature_a": left,
            "feature_b": right,
            "observed_pairs": len(observed),
            "possible_pairs": possible,
            "coverage": round(len(observed) / possible, 6) if possible else 0.0,
            "missing_pairs": possible - len(observed),
        }
    return results


def _triple_coverage(rows: list[dict[str, str]]) -> dict[str, Any]:
    values = {feature: _values_for_feature(rows, feature) for feature in TRIPLE_FEATURES}
    observed = {
        _combination_key(row, TRIPLE_FEATURES)
        for row in rows
    }
    possible = math.prod(len(values[feature]) for feature in TRIPLE_FEATURES)
    return {
        "features": list(TRIPLE_FEATURES),
        "observed_triples": len(observed),
        "possible_triples": possible,
        "coverage": round(len(observed) / possible, 6) if possible else 0.0,
        "missing_triples": possible - len(observed),
    }


def _values_for_feature(rows: list[dict[str, str]], feature: str) -> tuple[str, ...]:
    observed = {row[feature] for row in rows}
    universe = set(FEATURE_UNIVERSES.get(feature, tuple()))
    return tuple(sorted(observed | universe))


def _unique_feature_combinations(rows: list[dict[str, str]]) -> dict[str, Any]:
    counter: Counter[tuple[str, ...]] = Counter(
        _combination_key(row, COVERAGE_FEATURES) for row in rows
    )
    return {
        "features": list(COVERAGE_FEATURES),
        "unique_count": len(counter),
        "case_count": len(rows),
        "duplicate_combinations": len(rows) - len(counter),
        "top_combinations": [
            {
                "combination": dict(zip(COVERAGE_FEATURES, combo, strict=True)),
                "count": count,
            }
            for combo, count in counter.most_common(10)
        ],
    }


def _rare_combinations(
    rows: list[dict[str, str]],
    *,
    max_count: int = 1,
) -> list[dict[str, Any]]:
    counter: Counter[tuple[str, ...]] = Counter(
        _combination_key(row, SUGGESTION_FEATURES) for row in rows
    )
    rare = [
        {
            "combination": dict(zip(SUGGESTION_FEATURES, combo, strict=True)),
            "count": count,
        }
        for combo, count in sorted(counter.items(), key=lambda item: (item[1], item[0]))
        if count <= max_count
    ]
    return rare


def _missing_combinations(rows: list[dict[str, str]]) -> dict[str, Any]:
    observed = {
        _combination_key(row, SUGGESTION_FEATURES)
        for row in rows
    }
    universes = {feature: _values_for_feature(rows, feature) for feature in SUGGESTION_FEATURES}
    missing: list[dict[str, str]] = []
    for combo in product(*(universes[feature] for feature in SUGGESTION_FEATURES)):
        if combo not in observed:
            missing.append(dict(zip(SUGGESTION_FEATURES, combo, strict=True)))
    return {
        "features": list(SUGGESTION_FEATURES),
        "observed_count": len(observed),
        "possible_count": math.prod(len(universes[feature]) for feature in SUGGESTION_FEATURES),
        "missing_count": len(missing),
        "missing_sample": missing[:50],
    }


def _missing_pairwise_cells(rows: list[dict[str, str]], *, limit: int = 50) -> list[dict[str, str]]:
    missing_cells: list[dict[str, str]] = []
    for left, right in combinations(PAIRWISE_FEATURES, 2):
        observed = {(row[left], row[right]) for row in rows}
        for left_value in _values_for_feature(rows, left):
            for right_value in _values_for_feature(rows, right):
                if (left_value, right_value) in observed:
                    continue
                missing_cells.append(
                    {
                        "feature_a": left,
                        "value_a": left_value,
                        "feature_b": right,
                        "value_b": right_value,
                    }
                )
                if len(missing_cells) >= limit:
                    return missing_cells
    return missing_cells


def _missing_triple_cells(rows: list[dict[str, str]], *, limit: int = 50) -> list[dict[str, str]]:
    observed = {_combination_key(row, TRIPLE_FEATURES) for row in rows}
    universes = {feature: _values_for_feature(rows, feature) for feature in TRIPLE_FEATURES}
    missing: list[dict[str, str]] = []
    for combo in product(*(universes[feature] for feature in TRIPLE_FEATURES)):
        if combo in observed:
            continue
        missing.append(dict(zip(TRIPLE_FEATURES, combo, strict=True)))
        if len(missing) >= limit:
            break
    return missing


def suggest_additional_cases(
    rows: list[dict[str, str]],
    *,
    target_count: int = 200,
) -> dict[str, Any]:
    """Suggest regions where additional benchmark cases would improve coverage."""
    missing = _missing_combinations(rows)
    missing_triples = _missing_triple_cells(rows, limit=target_count)
    missing_pairwise = _missing_pairwise_cells(rows, limit=target_count)

    suggestions: list[dict[str, Any]] = []
    per_region = max(1, target_count // max(1, min(len(missing_triples), 20)))

    for region in missing_triples[:20]:
        suggestions.append(
            {
                "region_type": "triple",
                "features": region,
                "recommended_cases": per_region,
                "reason": "Missing machine_type/bug_type/size_class triple",
            }
        )

    if not suggestions and missing["missing_sample"]:
        per_region = max(1, target_count // min(len(missing["missing_sample"]), 20))
        for region in missing["missing_sample"][:20]:
            suggestions.append(
                {
                    "region_type": "combination",
                    "features": region,
                    "recommended_cases": per_region,
                    "reason": "Missing core taxonomy combination",
                }
            )

    if not suggestions and missing_pairwise:
        per_region = max(1, target_count // min(len(missing_pairwise), 20))
        for region in missing_pairwise[:20]:
            suggestions.append(
                {
                    "region_type": "pairwise",
                    "features": {
                        region["feature_a"]: region["value_a"],
                        region["feature_b"]: region["value_b"],
                    },
                    "recommended_cases": per_region,
                    "reason": "Missing pairwise feature cell",
                }
            )

    total_recommended = sum(item["recommended_cases"] for item in suggestions)
    message = (
        f"generate {target_count} additional cases in these regions"
        if suggestions
        else "coverage is saturated for the analysed feature subspaces"
    )
    return {
        "target_additional_cases": target_count,
        "recommended_total_cases": total_recommended,
        "message": message,
        "regions": suggestions[:20],
    }


def build_feature_coverage_report(
    rows: list[dict[str, str]],
    *,
    feature_matrix_path: str,
    suggestion_count: int = 200,
) -> dict[str, Any]:
    """Compute feature-space coverage metrics for pre-loaded feature-matrix rows."""
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "feature_matrix_path": feature_matrix_path,
        "case_count": len(rows),
        "unique_feature_combinations": _unique_feature_combinations(rows),
        "feature_entropy": _feature_entropy(rows),
        "pairwise_coverage": _pairwise_coverage(rows),
        "triple_coverage": _triple_coverage(rows),
        "rare_combinations": _rare_combinations(rows),
        "missing_combinations": _missing_combinations(rows),
        "missing_pairwise_sample": _missing_pairwise_cells(rows),
        "missing_triple_sample": _missing_triple_cells(rows),
        "suggestions": suggest_additional_cases(rows, target_count=suggestion_count),
    }


def analyze_feature_coverage(
    feature_matrix_path: Path,
    *,
    suggestion_count: int = 200,
) -> dict[str, Any]:
    """Compute feature-space coverage metrics for *feature_matrix_path*."""
    rows = load_feature_matrix(feature_matrix_path)
    return build_feature_coverage_report(
        rows,
        feature_matrix_path=str(feature_matrix_path),
        suggestion_count=suggestion_count,
    )


def generate_coverage_report(
    dataset_dir: Path,
    *,
    output_path: Path | None = None,
    suggestion_count: int = 200,
) -> CoverageReportResult:
    """Analyze dataset coverage and write ``coverage_report.json``."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise CoverageOptimizerError(msg)

    feature_matrix_path = dataset_dir / "feature_matrix.csv"
    report_path = output_path or (dataset_dir / COVERAGE_REPORT_FILENAME)
    report = analyze_feature_coverage(feature_matrix_path, suggestion_count=suggestion_count)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return CoverageReportResult(
        dataset_dir=dataset_dir,
        feature_matrix_path=feature_matrix_path,
        report_path=report_path,
        report=report,
    )
