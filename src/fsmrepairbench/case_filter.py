"""Filtering and subset overlap utilities for taxonomy-tagged datasets."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.taxonomy import CaseFeatures

FILTER_ALIASES: dict[str, str] = {
    "arity": "arity_class",
    "machine-type": "machine_type",
    "bug-type": "bug_type",
    "size": "size_class",
    "guard": "guard_complexity",
    "oracle-depth": "oracle_depth",
}


class CaseFilterError(ValueError):
    """Raised when case filtering or overlap analysis fails."""


@dataclass(frozen=True)
class OverlapResult:
    """Overlap statistics between two feature predicates."""

    count_a: int
    count_b: int
    count_intersection: int
    count_union: int
    jaccard: float

    def to_dict(self) -> dict[str, int | float]:
        return {
            "count_a": self.count_a,
            "count_b": self.count_b,
            "count_intersection": self.count_intersection,
            "count_union": self.count_union,
            "jaccard": round(self.jaccard, 6),
        }


def discover_case_feature_paths(dataset_dir: Path) -> list[Path]:
    """Return sorted ``case_features.json`` paths under *dataset_dir*."""
    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"Cases directory not found: {cases_root}"
        raise CaseFilterError(msg)
    return sorted(cases_root.glob("case_*/case_features.json"))


def load_case_features(dataset_dir: Path) -> list[CaseFeatures]:
    """Load all case feature records from *dataset_dir*."""
    records: list[CaseFeatures] = []
    for path in discover_case_feature_paths(dataset_dir):
        records.append(CaseFeatures.model_validate_json(path.read_text(encoding="utf-8")))
    if not records:
        msg = f"No case_features.json files found under {dataset_dir / 'cases'}"
        raise CaseFilterError(msg)
    return records


def normalize_filter_key(key: str) -> str:
    """Normalize CLI filter keys to CaseFeatures field names."""
    normalized = key.strip().replace("-", "_")
    return FILTER_ALIASES.get(key.strip(), FILTER_ALIASES.get(normalized, normalized))


def parse_predicate_string(raw: str) -> dict[str, str]:
    """Parse ``key=value,key=value`` predicate strings."""
    predicates: dict[str, str] = {}
    for chunk in raw.split(","):
        item = chunk.strip()
        if not item:
            continue
        if "=" not in item:
            msg = f"Invalid predicate chunk '{item}'; expected key=value"
            raise CaseFilterError(msg)
        key, value = item.split("=", 1)
        predicates[normalize_filter_key(key)] = value.strip()
    if not predicates:
        msg = "Predicate string did not contain any filters"
        raise CaseFilterError(msg)
    return predicates


def _feature_value(features: CaseFeatures, field: str) -> str | int | float | list[str]:
    if field == "time_features":
        return [item.value for item in features.time_features]
    if field == "graph_structure":
        return [item.value for item in features.graph_structure]
    value = getattr(features, field)
    if hasattr(value, "value"):
        return value.value  # type: ignore[no-any-return]
    return value


def matches_filters(features: CaseFeatures, filters: dict[str, str]) -> bool:
    """Return whether *features* satisfies all *filters*."""
    for field, expected in filters.items():
        if not hasattr(features, field):
            msg = f"Unknown feature filter field: {field}"
            raise CaseFilterError(msg)
        actual = _feature_value(features, field)
        if isinstance(actual, list):
            if expected not in actual:
                return False
            continue
        if str(actual) != expected:
            return False
    return True


def filter_cases(dataset_dir: Path, filters: dict[str, str]) -> list[CaseFeatures]:
    """Return cases in *dataset_dir* matching all *filters*."""
    return [
        features
        for features in load_case_features(dataset_dir)
        if matches_filters(features, filters)
    ]


def write_filter_csv(path: Path, cases: list[CaseFeatures]) -> None:
    """Write filtered case ids and key taxonomy columns to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "case_id",
        "machine_type",
        "determinism",
        "completeness",
        "arity_class",
        "size_class",
        "guard_complexity",
        "bug_type",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for features in cases:
            writer.writerow(
                {
                    "case_id": features.case_id,
                    "machine_type": features.machine_type.value,
                    "determinism": features.determinism.value,
                    "completeness": features.completeness.value,
                    "arity_class": features.arity_class.value,
                    "size_class": features.size_class.value,
                    "guard_complexity": features.guard_complexity.value,
                    "bug_type": features.bug_type.value,
                }
            )


def compute_subset_overlap(
    dataset_dir: Path,
    predicate_a: dict[str, str],
    predicate_b: dict[str, str],
) -> OverlapResult:
    """Compute overlap statistics between two predicate-defined subsets."""
    cases = load_case_features(dataset_dir)
    set_a = {features.case_id for features in cases if matches_filters(features, predicate_a)}
    set_b = {features.case_id for features in cases if matches_filters(features, predicate_b)}
    intersection = set_a & set_b
    union = set_a | set_b
    jaccard = len(intersection) / len(union) if union else 0.0
    return OverlapResult(
        count_a=len(set_a),
        count_b=len(set_b),
        count_intersection=len(intersection),
        count_union=len(union),
        jaccard=jaccard,
    )


def write_overlap_json(path: Path, overlap: OverlapResult) -> None:
    """Write overlap statistics to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(overlap.to_dict(), indent=2) + "\n", encoding="utf-8")
