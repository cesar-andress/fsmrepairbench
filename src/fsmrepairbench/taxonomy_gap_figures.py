"""Gap visualisations for ten-dimensional stratification plan vs v0.2.0-analysis cohort."""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import _pyplot, _save_bar_plot
from fsmrepairbench.coverage_optimizer import COVERAGE_FEATURES, FEATURE_UNIVERSES
from fsmrepairbench.generators.stratified_specs import GenerationCell, load_dataset_plan
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.taxonomy_coverage import _observed_dimension_values, _universe_for_dimension

DEFAULT_PLAN_PATH = Path("plans/fsmrepairbench_v0_1k_plan.yaml")
PLAN_CELL_GAP_COLUMNS: tuple[str, ...] = (
    "cell_index",
    "machine_type",
    "bug_type",
    "size_class",
    "planned_count",
    "realised_count",
    "realisation_ratio",
    "status",
)
MISSING_VALUE_COLUMNS: tuple[str, ...] = (
    "dimension",
    "value",
    "present_in_cohort",
    "present_in_plan",
)


class TaxonomyGapFigureError(RuntimeError):
    """Raised when gap figure generation fails."""


@dataclass(frozen=True)
class PlanCellRealisation:
    cell_index: int
    machine_type: str
    bug_type: str
    size_class: str
    planned_count: int
    realised_count: int

    @property
    def realisation_ratio(self) -> float:
        if self.planned_count <= 0:
            return 0.0
        return self.realised_count / self.planned_count

    @property
    def status(self) -> str:
        if self.realised_count <= 0:
            return "unrepresented"
        if self.realised_count < self.planned_count:
            return "underfilled"
        return "met_or_exceeded"


def _split_tags(raw: str) -> frozenset[str]:
    if not raw:
        return frozenset()
    return frozenset(part for part in raw.split("|") if part)


def _cell_matches_row(cell: GenerationCell, row: dict[str, str | int | float]) -> bool:
    """Match a realised case to a YAML plan cell on primary stratification keys."""
    if str(row["machine_type"]) != cell.machine_type.value:
        return False
    if str(row["bug_type"]) != cell.bug_type.value:
        return False
    if str(row.get("size_class", "")) and str(row["size_class"]) != cell.size_class.value:
        return False
    return True


def compute_plan_cell_realisations(
    rows: list[dict[str, str | int | float]],
    *,
    plan_path: Path,
) -> list[PlanCellRealisation]:
    plan = load_dataset_plan(plan_path)
    results: list[PlanCellRealisation] = []
    for index, cell in enumerate(plan.cells):
        realised = sum(1 for row in rows if _cell_matches_row(cell, row))
        results.append(
            PlanCellRealisation(
                cell_index=index,
                machine_type=cell.machine_type.value,
                bug_type=cell.bug_type.value,
                size_class=cell.size_class.value,
                planned_count=cell.count,
                realised_count=realised,
            )
        )
    return results


def compute_missing_dimension_values(
    rows: list[dict[str, str | int | float]],
    *,
    plan_path: Path,
) -> list[dict[str, str | bool]]:
    plan = load_dataset_plan(plan_path)
    plan_values: dict[str, set[str]] = defaultdict(set)
    for cell in plan.cells:
        plan_values["machine_type"].add(cell.machine_type.value)
        plan_values["bug_type"].add(cell.bug_type.value)
        plan_values["size_class"].add(cell.size_class.value)
        plan_values["determinism"].add(cell.determinism.value)
        plan_values["completeness"].add(cell.completeness.value)
        plan_values["arity_class"].add(cell.arity_class.value)
        plan_values["guard_complexity"].add(cell.guard_complexity.value)
        plan_values["oracle_depth"].add(cell.oracle_depth.value)
        for item in cell.time_features:
            plan_values["time_features"].add(item.value)
        for item in cell.graph_structure:
            plan_values["graph_structure"].add(item.value)

    missing_rows: list[dict[str, str | bool]] = []
    priority_dimensions = (
        "machine_type",
        "bug_type",
        "size_class",
        "determinism",
        "completeness",
        "oracle_depth",
        "guard_complexity",
        "time_features",
        "graph_structure",
        "arity_class",
    )
    for dimension in priority_dimensions:
        observed = _observed_dimension_values(rows, dimension)
        universe = set(_universe_for_dimension(dimension, observed))
        declared = plan_values.get(dimension, set())
        for value in sorted(universe | declared | set(MUTATION_OPERATORS if dimension == "bug_type" else [])):
            if dimension == "bug_type" and value not in universe and value not in declared:
                continue
            present = value in observed
            in_plan = value in declared
            if present:
                continue
            missing_rows.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "present_in_cohort": False,
                    "present_in_plan": in_plan,
                }
            )
    return missing_rows


def write_plan_cell_gap_csv(path: Path, realisations: list[PlanCellRealisation]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PLAN_CELL_GAP_COLUMNS))
        writer.writeheader()
        for item in realisations:
            writer.writerow(
                {
                    "cell_index": item.cell_index,
                    "machine_type": item.machine_type,
                    "bug_type": item.bug_type,
                    "size_class": item.size_class,
                    "planned_count": item.planned_count,
                    "realised_count": item.realised_count,
                    "realisation_ratio": round(item.realisation_ratio, 6),
                    "status": item.status,
                }
            )


def write_missing_dimension_values_csv(path: Path, rows: list[dict[str, str | bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MISSING_VALUE_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _machine_type_gap_summary(realisations: list[PlanCellRealisation]) -> tuple[list[str], list[int], list[int]]:
    planned = Counter()
    realised = Counter()
    for item in realisations:
        planned[item.machine_type] += item.planned_count
        realised[item.machine_type] += item.realised_count
    labels = sorted(planned.keys())
    return (
        labels,
        [planned[label] for label in labels],
        [realised[label] for label in labels],
    )


def _save_machine_type_gap_figure(path: Path, realisations: list[PlanCellRealisation]) -> None:
    labels, planned, realised = _machine_type_gap_summary(realisations)
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(9, 4.5))
    width = 0.35
    positions = list(range(len(labels)))
    axis.bar(
        [pos - width / 2 for pos in positions],
        planned,
        width=width,
        label="Planned (YAML)",
        color="#fdae61",
    )
    axis.bar(
        [pos + width / 2 for pos in positions],
        realised,
        width=width,
        label="Realised (v0.2.0-analysis)",
        color="#2c7bb6",
    )
    axis.set_xticks(positions)
    axis.set_xticklabels(labels, rotation=20, ha="right")
    axis.set_ylabel("Cases")
    axis.set_title("Stratification plan vs realised cases by machine type")
    axis.legend(loc="upper right")
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _operator_combination_summary(
    rows: list[dict[str, str | int | float]],
    realisations: list[PlanCellRealisation],
) -> tuple[list[str], list[str], dict[tuple[str, str], tuple[int, int]]]:
    machine_types = sorted({item.machine_type for item in realisations})
    bug_types = sorted({item.bug_type for item in realisations})
    planned: Counter[tuple[str, str]] = Counter()
    for item in realisations:
        planned[(item.machine_type, item.bug_type)] += item.planned_count
    realised: Counter[tuple[str, str]] = Counter()
    for row in rows:
        key = (str(row["machine_type"]), str(row["bug_type"]))
        if key in planned:
            realised[key] += 1
    lookup = {
        key: (realised[key], planned[key])
        for key in planned
    }
    return machine_types, bug_types, lookup


def _save_operator_combination_gap_heatmap(
    path: Path,
    rows: list[dict[str, str | int | float]],
    realisations: list[PlanCellRealisation],
) -> None:
    machine_types, bug_types, lookup = _operator_combination_summary(rows, realisations)
    matrix: list[list[float]] = []
    for machine_type in machine_types:
        row_values: list[float] = []
        for bug_type in bug_types:
            realised, planned = lookup.get((machine_type, bug_type), (0, 0))
            row_values.append(realised / planned if planned else 0.0)
        matrix.append(row_values)

    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(10, 4.8))
    image = axis.imshow(matrix, aspect="auto", cmap="RdYlGn", vmin=0.0, vmax=1.0)
    axis.set_xticks(range(len(bug_types)))
    axis.set_xticklabels(bug_types, rotation=35, ha="right", fontsize=8)
    axis.set_yticks(range(len(machine_types)))
    axis.set_yticklabels(machine_types)
    axis.set_title("Plan cell realisation ratio (machine type × mutation operator)")
    for row_index, machine_type in enumerate(machine_types):
        for col_index, bug_type in enumerate(bug_types):
            realised, planned = lookup.get((machine_type, bug_type), (0, 0))
            if planned <= 0:
                continue
            ratio = realised / planned
            colour = "white" if ratio < 0.45 else "black"
            axis.text(
                col_index,
                row_index,
                f"{realised}/{planned}",
                ha="center",
                va="center",
                fontsize=7,
                color=colour,
            )
    figure.colorbar(image, ax=axis, fraction=0.025, pad=0.02, label="Realised / planned")
    figure.tight_layout()
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _save_missing_values_figure(path: Path, missing_rows: list[dict[str, str | bool]]) -> None:
    focus_dimensions = (
        "machine_type",
        "bug_type",
        "size_class",
        "oracle_depth",
        "time_features",
        "guard_complexity",
    )
    counts = Counter(
        row["dimension"] for row in missing_rows if row["dimension"] in focus_dimensions
    )
    labels = [dimension for dimension in focus_dimensions if counts[dimension] > 0]
    values = [counts[dimension] for dimension in labels]
    if not labels:
        labels = ["none"]
        values = [0]
    _save_bar_plot(
        path,
        title="Unrepresented taxonomy values in v0.2.0-analysis (count by dimension)",
        xlabel="Dimension",
        ylabel="Missing declared values",
        labels=labels,
        values=values,
    )


def _save_complexity_tier_figure(
    path: Path,
    complexity_rows: list[dict[str, object]],
) -> None:
    tier_rows = [
        row for row in complexity_rows if str(row.get("group_value")) in {"small", "medium", "large", "very_large"}
    ]
    _save_bar_plot(
        path,
        title="Complexity tier representation (balanced in v0.2.0-analysis)",
        xlabel="Complexity tier",
        ylabel="Cases",
        labels=[str(row["group_value"]) for row in tier_rows],
        values=[int(row["case_count"]) for row in tier_rows],
    )


def write_taxonomy_gap_figures(
    figures_dir: Path,
    *,
    rows: list[dict[str, str | int | float]],
    plan_path: Path | None = None,
    complexity_rows: list[dict[str, object]] | None = None,
    output_dir: Path | None = None,
) -> dict[str, Path]:
    """Write gap maps comparing the YAML plan to the realised cohort."""
    resolved_plan = plan_path or DEFAULT_PLAN_PATH
    if not resolved_plan.is_file():
        msg = f"Stratification plan not found: {resolved_plan}"
        raise TaxonomyGapFigureError(msg)

    figures_dir.mkdir(parents=True, exist_ok=True)
    realisations = compute_plan_cell_realisations(rows, plan_path=resolved_plan)
    missing_rows = compute_missing_dimension_values(rows, plan_path=resolved_plan)

    export_root = output_dir or figures_dir.parent
    write_plan_cell_gap_csv(export_root / "plan_cell_gaps.csv", realisations)
    write_missing_dimension_values_csv(export_root / "unrepresented_dimension_values.csv", missing_rows)

    written = {
        "plan_machine_type_gaps": figures_dir / "plan_machine_type_gaps.png",
        "plan_operator_combination_gaps": figures_dir / "plan_operator_combination_gaps.png",
        "unrepresented_taxonomy_values": figures_dir / "unrepresented_taxonomy_values.png",
    }
    _save_machine_type_gap_figure(written["plan_machine_type_gaps"], realisations)
    _save_operator_combination_gap_heatmap(written["plan_operator_combination_gaps"], rows, realisations)
    _save_missing_values_figure(written["unrepresented_taxonomy_values"], missing_rows)

    if complexity_rows is not None:
        tier_path = figures_dir / "complexity_tier_coverage_balanced.png"
        _save_complexity_tier_figure(tier_path, complexity_rows)
        written["complexity_tier_coverage_balanced"] = tier_path

    return written


def gap_summary_payload(
    realisations: list[PlanCellRealisation],
    missing_rows: list[dict[str, str | bool]],
) -> dict[str, Any]:
    unrepresented_cells = sum(1 for item in realisations if item.realised_count == 0)
    underfilled_cells = sum(1 for item in realisations if 0 < item.realised_count < item.planned_count)
    missing_machine_types = sorted(
        {
            item.machine_type
            for item in realisations
            if item.realised_count == 0 and item.planned_count > 0
        }
    )
    missing_operators = sorted(
        row["value"]
        for row in missing_rows
        if row["dimension"] == "bug_type" and row["value"] in MUTATION_OPERATORS
    )
    return {
        "plan_cell_count": len(realisations),
        "unrepresented_plan_cells": unrepresented_cells,
        "underfilled_plan_cells": underfilled_cells,
        "missing_machine_types_in_cohort": missing_machine_types,
        "missing_mutation_operators_in_cohort": missing_operators,
    }
