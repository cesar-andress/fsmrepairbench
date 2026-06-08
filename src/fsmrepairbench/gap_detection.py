"""Detect underrepresented regions in benchmark feature space."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import product
from pathlib import Path
from typing import Any

import yaml

from fsmrepairbench.coverage_optimizer import (
    SUGGESTION_FEATURES,
    _combination_key,
    _values_for_feature,
    load_feature_matrix,
)
from fsmrepairbench.generators.stratified_specs import DatasetPlan
from fsmrepairbench.taxonomy import (
    Completeness,
    GraphStructure,
    GuardComplexity,
    MachineType,
    OracleDepth,
    SizeClass,
    TimeFeature,
)

MISSING_CELLS_FILENAME = "missing_cells.csv"
GAP_FILL_PLAN_FILENAME = "gap_fill_plan.yaml"
GAP_REPORT_FILENAME = "gap_detection_report.json"

MISSING_CELLS_COLUMNS: tuple[str, ...] = (
    *SUGGESTION_FEATURES,
    "expected_count",
    "current_count",
    "suggested_count",
    "gap_type",
)

DEFAULT_PLAN_NAME = "gap_fill_plan"
DEFAULT_PLAN_VERSION = "0.1.0"
DEFAULT_PLAN_SEED = 42


class GapDetectionError(ValueError):
    """Raised when benchmark gap detection fails."""


@dataclass(frozen=True)
class GapCell:
    """One underrepresented cell in feature space."""

    features: dict[str, str]
    expected_count: int
    current_count: int
    suggested_count: int
    gap_type: str

    def to_csv_row(self) -> dict[str, str | int]:
        row: dict[str, str | int] = dict(self.features)
        row["expected_count"] = self.expected_count
        row["current_count"] = self.current_count
        row["suggested_count"] = self.suggested_count
        row["gap_type"] = self.gap_type
        return row


@dataclass(frozen=True)
class GapDetectionResult:
    """Artifacts produced by benchmark gap detection."""

    dataset_dir: Path
    feature_matrix_path: Path
    missing_cells_path: Path
    gap_fill_plan_path: Path
    report_path: Path
    gaps: tuple[GapCell, ...]
    report: dict[str, Any]


def _expected_count_per_cell(case_count: int, possible_cells: int, *, minimum: int = 1) -> int:
    if possible_cells <= 0:
        return minimum
    return max(minimum, round(case_count / possible_cells))


def _default_time_features(machine_type: str) -> list[str]:
    if machine_type in {MachineType.TIMED_FSM.value, MachineType.TIMED_EFSM.value}:
        return [TimeFeature.TIMEOUT.value]
    return [TimeFeature.NONE.value]


def _default_guard_complexity(machine_type: str) -> str:
    if machine_type in {
        MachineType.EFSM.value,
        MachineType.TIMED_EFSM.value,
        MachineType.TIMED_FSM.value,
    }:
        return GuardComplexity.SIMPLE.value
    return GuardComplexity.NONE.value


def _default_graph_structure(machine_type: str) -> list[str]:
    mapping = {
        MachineType.PLAIN_FSM.value: GraphStructure.ACYCLIC.value,
        MachineType.MEALY.value: GraphStructure.SPARSE.value,
        MachineType.MOORE.value: GraphStructure.LAYERED.value,
        MachineType.EFSM.value: GraphStructure.DENSE.value,
        MachineType.TIMED_FSM.value: GraphStructure.CYCLIC.value,
        MachineType.TIMED_EFSM.value: GraphStructure.STRONGLY_CONNECTED.value,
    }
    return [mapping.get(machine_type, GraphStructure.SPARSE.value)]


def _default_oracle_depth(size_class: str) -> str:
    mapping = {
        SizeClass.TINY.value: OracleDepth.SHALLOW.value,
        SizeClass.SMALL.value: OracleDepth.MEDIUM.value,
        SizeClass.MEDIUM.value: OracleDepth.MEDIUM.value,
        SizeClass.LARGE.value: OracleDepth.DEEP.value,
        SizeClass.VERY_LARGE.value: OracleDepth.EXHAUSTIVE_LIKE.value,
    }
    return mapping.get(size_class, OracleDepth.MEDIUM.value)


def gap_cell_to_generation_cell(gap: GapCell) -> dict[str, Any]:
    """Convert a gap cell into a stratified generation cell payload."""
    machine_type = gap.features["machine_type"]
    size_class = gap.features["size_class"]
    return {
        "machine_type": machine_type,
        "determinism": gap.features["determinism"],
        "completeness": Completeness.COMPLETE.value,
        "arity_class": gap.features["arity_class"],
        "size_class": size_class,
        "guard_complexity": _default_guard_complexity(machine_type),
        "time_features": _default_time_features(machine_type),
        "graph_structure": _default_graph_structure(machine_type),
        "oracle_depth": _default_oracle_depth(size_class),
        "bug_type": gap.features["bug_type"],
        "count": gap.suggested_count,
    }


def _count_rows_by_cell(rows: list[dict[str, str]]) -> dict[tuple[str, ...], int]:
    counts: dict[tuple[str, ...], int] = {}
    for row in rows:
        key = _combination_key(row, SUGGESTION_FEATURES)
        counts[key] = counts.get(key, 0) + 1
    return counts


def detect_gap_cells(
    rows: list[dict[str, str]],
    *,
    expected_count: int | None = None,
    minimum_expected: int = 1,
) -> tuple[GapCell, ...]:
    """Identify missing and low-density cells in feature space."""
    universes = {feature: _values_for_feature(rows, feature) for feature in SUGGESTION_FEATURES}
    possible_cells = math.prod(len(universes[feature]) for feature in SUGGESTION_FEATURES)
    target = expected_count or _expected_count_per_cell(
        len(rows),
        possible_cells,
        minimum=minimum_expected,
    )

    counter = _count_rows_by_cell(rows)
    gaps: list[GapCell] = []
    for combo in product(*(universes[feature] for feature in SUGGESTION_FEATURES)):
        features = dict(zip(SUGGESTION_FEATURES, combo, strict=True))
        current = counter.get(combo, 0)
        if current >= target:
            continue
        suggested = target - current
        gap_type = "missing" if current == 0 else "underrepresented"
        gaps.append(
            GapCell(
                features=features,
                expected_count=target,
                current_count=current,
                suggested_count=suggested,
                gap_type=gap_type,
            )
        )

    gaps.sort(key=lambda item: (-item.suggested_count, item.gap_type, item.features["machine_type"]))
    return tuple(gaps)


def write_missing_cells_csv(path: Path, gaps: tuple[GapCell, ...]) -> None:
    """Write gap cells to ``missing_cells.csv``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MISSING_CELLS_COLUMNS))
        writer.writeheader()
        writer.writerows(gap.to_csv_row() for gap in gaps)


def build_gap_fill_plan(
    gaps: tuple[GapCell, ...],
    *,
    name: str = DEFAULT_PLAN_NAME,
    version: str = DEFAULT_PLAN_VERSION,
    seed: int = DEFAULT_PLAN_SEED,
    max_cells: int | None = None,
) -> DatasetPlan:
    """Build an automatic stratified generation plan from detected gaps."""
    selected = [gap for gap in gaps if gap.suggested_count > 0]
    if max_cells is not None:
        selected = selected[:max_cells]
    if not selected:
        msg = "No gap cells require additional benchmark cases"
        raise GapDetectionError(msg)

    payload = {
        "name": name,
        "version": version,
        "seed": seed,
        "cells": [gap_cell_to_generation_cell(gap) for gap in selected],
    }
    return DatasetPlan.model_validate(payload)


def write_gap_fill_plan(path: Path, plan: DatasetPlan) -> None:
    """Write a gap-fill generation plan as YAML."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(plan.model_dump(mode="json"), sort_keys=False) + "\n",
        encoding="utf-8",
    )


def build_gap_report(
    *,
    feature_matrix_path: Path,
    gaps: tuple[GapCell, ...],
    expected_count: int,
    plan: DatasetPlan,
) -> dict[str, Any]:
    """Build a JSON summary of gap detection results."""
    missing = sum(1 for gap in gaps if gap.gap_type == "missing")
    underrepresented = sum(1 for gap in gaps if gap.gap_type == "underrepresented")
    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "feature_matrix_path": str(feature_matrix_path),
        "expected_count_per_cell": expected_count,
        "gap_cell_features": list(SUGGESTION_FEATURES),
        "missing_cells": missing,
        "underrepresented_cells": underrepresented,
        "total_gaps": len(gaps),
        "suggested_additional_cases": sum(gap.suggested_count for gap in gaps),
        "generation_plan_cases": sum(cell.count for cell in plan.cells),
        "generation_plan_cells": len(plan.cells),
    }


def detect_benchmark_gaps(
    dataset_dir: Path,
    *,
    expected_count: int | None = None,
    minimum_expected: int = 1,
    max_plan_cells: int | None = 200,
    output_dir: Path | None = None,
) -> GapDetectionResult:
    """Detect benchmark gaps and write missing_cells.csv plus a generation plan."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise GapDetectionError(msg)

    feature_matrix_path = dataset_dir / "feature_matrix.csv"
    rows = load_feature_matrix(feature_matrix_path)
    gaps = detect_gap_cells(
        rows,
        expected_count=expected_count,
        minimum_expected=minimum_expected,
    )

    if not gaps:
        msg = "No low-density zones detected in the analysed feature space"
        raise GapDetectionError(msg)

    target = gaps[0].expected_count
    plan = build_gap_fill_plan(gaps, max_cells=max_plan_cells)

    destination = output_dir or dataset_dir
    missing_cells_path = destination / MISSING_CELLS_FILENAME
    gap_fill_plan_path = destination / GAP_FILL_PLAN_FILENAME
    report_path = destination / GAP_REPORT_FILENAME

    write_missing_cells_csv(missing_cells_path, gaps)
    write_gap_fill_plan(gap_fill_plan_path, plan)
    report = build_gap_report(
        feature_matrix_path=feature_matrix_path,
        gaps=gaps,
        expected_count=target,
        plan=plan,
    )
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return GapDetectionResult(
        dataset_dir=dataset_dir,
        feature_matrix_path=feature_matrix_path,
        missing_cells_path=missing_cells_path,
        gap_fill_plan_path=gap_fill_plan_path,
        report_path=report_path,
        gaps=gaps,
        report=report,
    )
