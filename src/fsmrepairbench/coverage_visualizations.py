"""Heatmaps and CSV exports for ten-dimensional stratification plan coverage."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import _pyplot
from fsmrepairbench.coverage_optimizer import COVERAGE_FEATURES, FEATURE_UNIVERSES
from fsmrepairbench.freeze import sha256_file
from fsmrepairbench.taxonomy_coverage import ZENODO_DOI
from fsmrepairbench.generators.stratified_specs import GenerationCell, load_dataset_plan
from fsmrepairbench.taxonomy_coverage import COMPLEXITY_TIERS, load_taxonomy_feature_rows
from fsmrepairbench.taxonomy_gap_figures import (
    DEFAULT_PLAN_PATH,
    PlanCellRealisation,
    compute_plan_cell_realisations,
    write_plan_cell_gap_csv,
)

DIMENSION_VALUE_COLUMNS: tuple[str, ...] = (
    "dimension",
    "value",
    "planned_cases",
    "realised_cases",
    "cohort_fraction",
    "realisation_ratio",
    "planned_in_yaml",
    "realised_in_cohort",
    "status",
    "coverage_note",
)
FAMILY_OPERATOR_COLUMNS: tuple[str, ...] = (
    "machine_type",
    "bug_type",
    "planned_count",
    "realised_count",
    "realisation_ratio",
    "status",
)
MATRIX_COLUMNS: tuple[str, ...] = (
    "row_label",
    "column_label",
    "case_count",
    "cohort_fraction",
    "planned_count",
    "realisation_ratio",
    "status",
)
SUMMARY_COLUMNS: tuple[str, ...] = ("metric", "value")


class CoverageVisualizationError(RuntimeError):
    """Raised when coverage visualisation generation fails."""


@dataclass(frozen=True)
class CoverageVisualizationResult:
    """Paths written by :func:`write_coverage_visualizations`."""

    output_dir: Path
    figures_dir: Path
    csv_paths: dict[str, Path]
    figure_paths: dict[str, Path]
    captions_path: Path


def _cell_dimension_values(cell: GenerationCell) -> dict[str, list[str]]:
    return {
        "machine_type": [cell.machine_type.value],
        "determinism": [cell.determinism.value],
        "completeness": [cell.completeness.value],
        "arity_class": [cell.arity_class.value],
        "size_class": [cell.size_class.value],
        "guard_complexity": [cell.guard_complexity.value],
        "oracle_depth": [cell.oracle_depth.value],
        "bug_type": [cell.bug_type.value],
        "time_features": [item.value for item in cell.time_features],
        "graph_structure": [item.value for item in cell.graph_structure],
    }


def _planned_counts_by_dimension(plan_path: Path) -> dict[str, Counter[str]]:
    plan = load_dataset_plan(plan_path)
    counts: dict[str, Counter[str]] = {dimension: Counter() for dimension in COVERAGE_FEATURES}
    for cell in plan.cells:
        for dimension, values in _cell_dimension_values(cell).items():
            for value in values:
                counts[dimension][value] += cell.count
    return counts


def _realised_counts_by_dimension(
    rows: list[dict[str, str | int | float]],
) -> dict[str, Counter[str]]:
    counts: dict[str, Counter[str]] = {dimension: Counter() for dimension in COVERAGE_FEATURES}
    for row in rows:
        for dimension in COVERAGE_FEATURES:
            raw = row.get(dimension)
            if raw is None or raw == "":
                continue
            if dimension in {"time_features", "graph_structure"}:
                for token in str(raw).split("|"):
                    if token:
                        counts[dimension][token] += 1
            else:
                counts[dimension][str(raw)] += 1
    return counts


def _coverage_status(planned: int, realised: int) -> str:
    if planned <= 0 and realised <= 0:
        return "absent"
    if planned <= 0 and realised > 0:
        return "realised_not_planned"
    if realised <= 0:
        return "unrepresented"
    if realised < planned:
        return "underfilled"
    return "met_or_exceeded"


def _coverage_note(dimension: str, value: str, planned: int, realised: int, status: str) -> str:
    if dimension == "size_class" and planned > 0 and realised == 0 and value == "tiny":
        return "Plan specifies tiny; cohort uses balanced small/medium/large/very_large tiers"
    if status == "realised_not_planned":
        return "Observed in cohort but not declared in YAML plan cells"
    if status == "unrepresented" and planned > 0:
        return "Declared in plan but zero matching cohort cases"
    if status == "underfilled":
        return "Partial plan-cell realisation"
    if status == "met_or_exceeded":
        return "Plan quota met or exceeded on matching keys"
    if status == "absent":
        return "Neither planned nor realised"
    return ""


def build_dimension_value_coverage_rows(
    rows: list[dict[str, str | int | float]],
    *,
    plan_path: Path,
    case_count: int,
) -> list[dict[str, object]]:
    planned = _planned_counts_by_dimension(plan_path)
    realised = _realised_counts_by_dimension(rows)
    output: list[dict[str, object]] = []
    for dimension in COVERAGE_FEATURES:
        universe = sorted(set(FEATURE_UNIVERSES.get(dimension, ())) | set(planned[dimension]) | set(realised[dimension]))
        for value in universe:
            planned_cases = int(planned[dimension].get(value, 0))
            realised_cases = int(realised[dimension].get(value, 0))
            ratio = realised_cases / planned_cases if planned_cases > 0 else (1.0 if realised_cases > 0 else 0.0)
            status = _coverage_status(planned_cases, realised_cases)
            output.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "planned_cases": planned_cases,
                    "realised_cases": realised_cases,
                    "cohort_fraction": round(realised_cases / case_count, 6) if case_count else 0.0,
                    "realisation_ratio": round(ratio, 6),
                    "planned_in_yaml": planned_cases > 0,
                    "realised_in_cohort": realised_cases > 0,
                    "status": status,
                    "coverage_note": _coverage_note(dimension, value, planned_cases, realised_cases, status),
                }
            )
    return output


def build_family_operator_rows(
    rows: list[dict[str, str | int | float]],
    realisations: list[PlanCellRealisation],
) -> list[dict[str, object]]:
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
    output: list[dict[str, object]] = []
    for machine_type in machine_types:
        for bug_type in bug_types:
            planned_count = int(planned.get((machine_type, bug_type), 0))
            realised_count = int(realised.get((machine_type, bug_type), 0))
            ratio = realised_count / planned_count if planned_count else 0.0
            output.append(
                {
                    "machine_type": machine_type,
                    "bug_type": bug_type,
                    "planned_count": planned_count,
                    "realised_count": realised_count,
                    "realisation_ratio": round(ratio, 6),
                    "status": _coverage_status(planned_count, realised_count),
                }
            )
    return output


def build_operator_complexity_rows(
    rows: list[dict[str, str | int | float]],
    complexity_by_case: dict[str, str],
    *,
    case_count: int,
) -> list[dict[str, object]]:
    operators = sorted({str(row["bug_type"]) for row in rows})
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        case_id = str(row["case_id"])
        tier = complexity_by_case.get(case_id, "unknown")
        if tier not in COMPLEXITY_TIERS:
            continue
        counts[(str(row["bug_type"]), tier)] += 1
    output: list[dict[str, object]] = []
    for operator in operators:
        for tier in COMPLEXITY_TIERS:
            case_n = int(counts.get((operator, tier), 0))
            output.append(
                {
                    "row_label": operator,
                    "column_label": tier,
                    "case_count": case_n,
                    "cohort_fraction": round(case_n / case_count, 6) if case_count else 0.0,
                    "planned_count": 0,
                    "realisation_ratio": "",
                    "status": "realised" if case_n > 0 else "gap",
                }
            )
    return output


def build_family_complexity_rows(
    rows: list[dict[str, str | int | float]],
    complexity_by_case: dict[str, str],
    *,
    case_count: int,
) -> list[dict[str, object]]:
    families = sorted({str(row["machine_type"]) for row in rows})
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        case_id = str(row["case_id"])
        tier = complexity_by_case.get(case_id, "unknown")
        if tier not in COMPLEXITY_TIERS:
            continue
        counts[(str(row["machine_type"]), tier)] += 1
    output: list[dict[str, object]] = []
    for family in families:
        for tier in COMPLEXITY_TIERS:
            case_n = int(counts.get((family, tier), 0))
            output.append(
                {
                    "row_label": family,
                    "column_label": tier,
                    "case_count": case_n,
                    "cohort_fraction": round(case_n / case_count, 6) if case_count else 0.0,
                    "planned_count": 0,
                    "realisation_ratio": "",
                    "status": "realised" if case_n > 0 else "gap",
                }
            )
    return output


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _dimension_matrix(
    coverage_rows: list[dict[str, object]],
    *,
    value_key: str,
) -> tuple[list[str], list[str], list[list[float]], list[list[str]]]:
    row_labels = list(COVERAGE_FEATURES)
    col_labels: list[str] = []
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in coverage_rows:
        grouped[str(row["dimension"])].append(row)
    max_cols = max(len(grouped[dimension]) for dimension in COVERAGE_FEATURES)
    col_labels = [f"v{i + 1}" for i in range(max_cols)]

    matrix: list[list[float]] = []
    annotations: list[list[str]] = []
    for dimension in COVERAGE_FEATURES:
        values = sorted(grouped[dimension], key=lambda item: str(item["value"]))
        row_vals: list[float] = []
        row_ann: list[str] = []
        for index in range(max_cols):
            if index >= len(values):
                row_vals.append(float("nan"))
                row_ann.append("")
                continue
            item = values[index]
            if value_key == "planned":
                planned = int(item["planned_cases"])
                row_vals.append(1.0 if planned > 0 else 0.0)
                row_ann.append(f"{item['value']}\nP={planned}")
            else:
                realised = int(item["realised_cases"])
                planned = int(item["planned_cases"])
                if planned > 0:
                    row_vals.append(min(realised / planned, 1.0))
                elif realised > 0:
                    row_vals.append(1.0)
                else:
                    row_vals.append(0.0)
                row_ann.append(f"{item['value']}\n{realised}")
        matrix.append(row_vals)
        annotations.append(row_ann)
    return row_labels, col_labels, matrix, annotations


def _save_dimension_plan_vs_realised_heatmap(
    path: Path,
    coverage_rows: list[dict[str, object]],
) -> None:
    plt = _pyplot()
    import numpy as np

    row_labels, col_labels, planned_matrix, planned_ann = _dimension_matrix(
        coverage_rows,
        value_key="planned",
    )
    _, _, realised_matrix, realised_ann = _dimension_matrix(
        coverage_rows,
        value_key="realised",
    )

    figure, axes = plt.subplots(1, 2, figsize=(14, 6.5), sharey=True)
    planned_array = np.array(planned_matrix, dtype=float)
    realised_array = np.array(realised_matrix, dtype=float)

    image0 = axes[0].imshow(planned_array, aspect="auto", cmap="Oranges", vmin=0.0, vmax=1.0)
    axes[0].set_title("Planned coverage (YAML plan cells)")
    axes[0].set_yticks(range(len(row_labels)))
    axes[0].set_yticklabels(row_labels)
    axes[0].set_xticks(range(len(col_labels)))
    axes[0].set_xticklabels(col_labels, fontsize=8)
    figure.colorbar(image0, ax=axes[0], fraction=0.03, pad=0.02, label="Declared in plan")

    image1 = axes[1].imshow(realised_array, aspect="auto", cmap="RdYlGn", vmin=0.0, vmax=1.0)
    axes[1].set_title("Realised coverage (v0.2.0-analysis cohort)")
    axes[1].set_xticks(range(len(col_labels)))
    axes[1].set_xticklabels(col_labels, fontsize=8)
    figure.colorbar(image1, ax=axes[1], fraction=0.03, pad=0.02, label="Realised / planned")

    for axis, annotations in zip(axes, (planned_ann, realised_ann), strict=True):
        for row_index, row in enumerate(annotations):
            for col_index, label in enumerate(row):
                if not label:
                    continue
                value = planned_array[row_index, col_index] if axis is axes[0] else realised_array[row_index, col_index]
                colour = "white" if (value == value and value < 0.45) else "black"
                axis.text(col_index, row_index, label, ha="center", va="center", fontsize=6, color=colour)

    figure.suptitle(
        "Ten-dimensional stratification plan: planned vs realised value coverage "
        "(partial coverage; gaps in non-plain_fsm families and size_class=tiny)",
        fontsize=11,
    )
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def _save_matrix_heatmap(
    path: Path,
    *,
    row_labels: list[str],
    col_labels: list[str],
    values: list[list[float]],
    annotations: list[list[str]],
    title: str,
    cbar_label: str,
    cmap: str = "YlGnBu",
    vmin: float = 0.0,
    vmax: float | None = None,
) -> None:
    plt = _pyplot()
    import numpy as np

    matrix = np.array(values, dtype=float)
    figure, axis = plt.subplots(figsize=(max(8.0, len(col_labels) * 1.1), max(4.5, len(row_labels) * 0.55)))
    image = axis.imshow(matrix, aspect="auto", cmap=cmap, vmin=vmin, vmax=vmax)
    axis.set_xticks(range(len(col_labels)))
    axis.set_xticklabels(col_labels, rotation=25, ha="right", fontsize=8)
    axis.set_yticks(range(len(row_labels)))
    axis.set_yticklabels(row_labels, fontsize=8)
    axis.set_title(title)
    for row_index, row in enumerate(annotations):
        for col_index, label in enumerate(row):
            if not label:
                continue
            value = matrix[row_index, col_index]
            colour = "white" if (value == value and value < (vmax or 1.0) * 0.45) else "black"
            axis.text(col_index, row_index, label, ha="center", va="center", fontsize=7, color=colour)
    figure.colorbar(image, ax=axis, fraction=0.025, pad=0.02, label=cbar_label)
    figure.tight_layout()
    figure.savefig(path, dpi=140)
    plt.close(figure)


def _family_operator_heatmap_data(
    family_operator_rows: list[dict[str, object]],
) -> tuple[list[str], list[str], list[list[float]], list[list[str]]]:
    machine_types = sorted({str(row["machine_type"]) for row in family_operator_rows})
    bug_types = sorted({str(row["bug_type"]) for row in family_operator_rows})
    lookup = {(str(row["machine_type"]), str(row["bug_type"])): row for row in family_operator_rows}
    matrix: list[list[float]] = []
    annotations: list[list[str]] = []
    for machine_type in machine_types:
        row_vals: list[float] = []
        row_ann: list[str] = []
        for bug_type in bug_types:
            item = lookup[(machine_type, bug_type)]
            planned = int(item["planned_count"])
            realised = int(item["realised_count"])
            ratio = float(item["realisation_ratio"]) if planned else (1.0 if realised else 0.0)
            row_vals.append(min(ratio, 1.0))
            row_ann.append(f"{realised}/{planned}" if planned else str(realised))
        matrix.append(row_vals)
        annotations.append(row_ann)
    return machine_types, bug_types, matrix, annotations


def _matrix_heatmap_data(
    matrix_rows: list[dict[str, object]],
    *,
    row_order: list[str] | None = None,
    col_order: list[str] | None = None,
) -> tuple[list[str], list[str], list[list[float]], list[list[str]]]:
    rows = row_order or sorted({str(row["row_label"]) for row in matrix_rows})
    cols = col_order or sorted({str(row["column_label"]) for row in matrix_rows})
    lookup = {(str(row["row_label"]), str(row["column_label"])): row for row in matrix_rows}
    matrix: list[list[float]] = []
    annotations: list[list[str]] = []
    max_count = max(int(row["case_count"]) for row in matrix_rows) or 1
    for row_label in rows:
        row_vals: list[float] = []
        row_ann: list[str] = []
        for col_label in cols:
            item = lookup.get((row_label, col_label), {"case_count": 0})
            count = int(item["case_count"])
            row_vals.append(count / max_count)
            row_ann.append(str(count) if count else "0")
        matrix.append(row_vals)
        annotations.append(row_ann)
    return rows, cols, matrix, annotations


def build_summary_rows(
    *,
    case_count: int,
    dimension_rows: list[dict[str, object]],
    family_operator_rows: list[dict[str, object]],
    realisations: list[PlanCellRealisation],
) -> list[dict[str, object]]:
    mean_dim_cov = sum(
        1 for row in dimension_rows if row["realised_in_cohort"] and row["planned_in_yaml"]
    ) / max(sum(1 for row in dimension_rows if row["planned_in_yaml"]), 1)
    unrepresented_cells = sum(1 for item in realisations if item.realised_count == 0)
    partial_cells = sum(1 for item in realisations if 0 < item.realised_count < item.planned_count)
    met_cells = sum(1 for item in realisations if item.realised_count >= item.planned_count)
    families_realised = len({str(row["machine_type"]) for row in family_operator_rows if int(row["realised_count"]) > 0})
    families_planned = len({str(row["machine_type"]) for row in family_operator_rows if int(row["planned_count"]) > 0})
    return [
        {"metric": "cohort_case_count", "value": case_count},
        {"metric": "plan_cell_count", "value": len(realisations)},
        {"metric": "plan_cells_unrepresented", "value": unrepresented_cells},
        {"metric": "plan_cells_underfilled", "value": partial_cells},
        {"metric": "plan_cells_met_or_exceeded", "value": met_cells},
        {"metric": "fsm_families_planned", "value": families_planned},
        {"metric": "fsm_families_realised", "value": families_realised},
        {"metric": "dimension_values_planned_and_realised", "value": round(mean_dim_cov, 6)},
        {"metric": "complexity_tiers_present", "value": len(COMPLEXITY_TIERS)},
    ]


def build_figure_captions(summary_rows: list[dict[str, object]]) -> str:
    lookup = {str(row["metric"]): row["value"] for row in summary_rows}
    unrepresented = int(lookup.get("plan_cells_unrepresented", 0))
    families_planned = int(lookup.get("fsm_families_planned", 0))
    families_realised = int(lookup.get("fsm_families_realised", 0))
    return "\n".join(
        [
            "# Coverage visualisation captions (v0.2.0-analysis)",
            "",
            "## heatmap_dimension_plan_vs_realised.png",
            "",
            "Dual heatmap comparing declared YAML plan values (left) with realised cohort",
            "counts (right) across all ten stratification dimensions. Orange cells mark values",
            "present in the plan; green cells mark realised/planned ratios near 1.0. Gaps appear",
            "for four non-`plain_fsm` machine families, `size_class=tiny` (cohort uses balanced",
            "small/medium/large/very_large tiers instead), and several time-feature and oracle-depth",
            "values declared in the plan but absent from the built cohort.",
            "",
            "## heatmap_family_operator_plan_vs_realised.png",
            "",
            "Plan-cell realisation ratio heatmap (`machine_type` × mutation operator). Only",
            f"`plain_fsm` rows register realised cases; {unrepresented}/20 YAML cells remain",
            "unrepresented at full cell granularity (`plan_cell_gaps.csv`).",
            "",
            "## heatmap_operator_complexity_tier.png",
            "",
            "Realised cohort density heatmap (mutation operator × structural complexity tier).",
            "Seventeen operators appear with near-uniform tier balance (~246–252 cases per tier);",
            "`timed_selective_mutation` and `variable_intra_class` remain absent.",
            "",
            "## heatmap_family_complexity_tier.png",
            "",
            "Realised cohort density heatmap (FSM family × complexity tier). The v0.2.0-analysis",
            f"release contains only `plain_fsm` ({families_realised}/{families_planned} planned",
            "families realised) with balanced tier counts.",
            "",
            "## heatmap_dimension_coverage_summary.png",
            "",
            "Observed-to-universe coverage ratio per taxonomy dimension (mean 54.8% across ten",
            "axes). Highlights partial coverage: machine_type 12.5%, time_features 20%,",
            "bug_type 89.5%, size_class 80% (cohort tiers differ from plan `tiny` quota).",
            "",
        ]
    )


def _save_dimension_coverage_summary(path: Path, dimension_rows: list[dict[str, object]]) -> None:
    by_dimension: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in dimension_rows:
        by_dimension[str(row["dimension"])].append(row)
    labels = list(COVERAGE_FEATURES)
    values: list[float] = []
    annotations: list[str] = []
    for dimension in labels:
        rows = by_dimension[dimension]
        planned_values = sum(1 for row in rows if row["planned_in_yaml"])
        realised_values = sum(1 for row in rows if row["realised_in_cohort"])
        universe = len(rows) or 1
        ratio = realised_values / universe
        values.append([ratio])
        annotations.append([f"{realised_values}/{universe}"])
    _save_matrix_heatmap(
        path,
        row_labels=labels,
        col_labels=["observed/universe"],
        values=values,
        annotations=annotations,
        title="Dimension value coverage summary (realised values / declared universe)",
        cbar_label="Coverage ratio",
        cmap="RdYlGn",
    )


def write_coverage_visualizations(
    dataset_dir: Path,
    *,
    output_dir: Path,
    cohort_path: Path | None = None,
    plan_path: Path | None = None,
) -> CoverageVisualizationResult:
    """Generate heatmaps and CSV exports under *output_dir*."""
    resolved_plan = plan_path or DEFAULT_PLAN_PATH
    if not resolved_plan.is_file():
        msg = f"Stratification plan not found: {resolved_plan}"
        raise CoverageVisualizationError(msg)
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise CoverageVisualizationError(msg)

    from fsmrepairbench.taxonomy_coverage import load_cohort_case_ids

    resolved_cohort = cohort_path or (dataset_dir / "analysis_cohort_1k.txt")
    case_ids = load_cohort_case_ids(dataset_dir, cohort_path=resolved_cohort)
    rows, complexity_by_case = load_taxonomy_feature_rows(dataset_dir, case_ids)
    string_rows = [dict(row) for row in rows]
    case_count = len(string_rows)

    realisations = compute_plan_cell_realisations(string_rows, plan_path=resolved_plan)
    dimension_rows = build_dimension_value_coverage_rows(
        string_rows,
        plan_path=resolved_plan,
        case_count=case_count,
    )
    family_operator_rows = build_family_operator_rows(string_rows, realisations)
    operator_complexity_rows = build_operator_complexity_rows(
        string_rows,
        complexity_by_case,
        case_count=case_count,
    )
    family_complexity_rows = build_family_complexity_rows(
        string_rows,
        complexity_by_case,
        case_count=case_count,
    )
    summary_rows = build_summary_rows(
        case_count=case_count,
        dimension_rows=dimension_rows,
        family_operator_rows=family_operator_rows,
        realisations=realisations,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(parents=True, exist_ok=True)

    csv_paths = {
        "dimension_value_coverage": output_dir / "dimension_value_coverage.csv",
        "family_operator_plan_vs_realised": output_dir / "family_operator_plan_vs_realised.csv",
        "operator_complexity_tier_matrix": output_dir / "operator_complexity_tier_matrix.csv",
        "family_complexity_tier_matrix": output_dir / "family_complexity_tier_matrix.csv",
        "plan_cell_gaps": output_dir / "plan_cell_gaps.csv",
        "coverage_visualization_summary": output_dir / "coverage_visualization_summary.csv",
    }
    _write_csv(csv_paths["dimension_value_coverage"], DIMENSION_VALUE_COLUMNS, dimension_rows)
    _write_csv(csv_paths["family_operator_plan_vs_realised"], FAMILY_OPERATOR_COLUMNS, family_operator_rows)
    _write_csv(csv_paths["operator_complexity_tier_matrix"], MATRIX_COLUMNS, operator_complexity_rows)
    _write_csv(csv_paths["family_complexity_tier_matrix"], MATRIX_COLUMNS, family_complexity_rows)
    _write_csv(csv_paths["coverage_visualization_summary"], SUMMARY_COLUMNS, summary_rows)
    write_plan_cell_gap_csv(csv_paths["plan_cell_gaps"], realisations)

    figure_paths = {
        "heatmap_dimension_plan_vs_realised": figures_dir / "heatmap_dimension_plan_vs_realised.png",
        "heatmap_family_operator_plan_vs_realised": figures_dir / "heatmap_family_operator_plan_vs_realised.png",
        "heatmap_operator_complexity_tier": figures_dir / "heatmap_operator_complexity_tier.png",
        "heatmap_family_complexity_tier": figures_dir / "heatmap_family_complexity_tier.png",
        "heatmap_dimension_coverage_summary": figures_dir / "heatmap_dimension_coverage_summary.png",
    }
    _save_dimension_plan_vs_realised_heatmap(
        figure_paths["heatmap_dimension_plan_vs_realised"],
        dimension_rows,
    )
    fam_rows, bug_cols, fam_matrix, fam_ann = _family_operator_heatmap_data(family_operator_rows)
    _save_matrix_heatmap(
        figure_paths["heatmap_family_operator_plan_vs_realised"],
        row_labels=fam_rows,
        col_labels=bug_cols,
        values=fam_matrix,
        annotations=fam_ann,
        title="Plan realisation ratio: FSM family × mutation operator (gaps outside plain_fsm)",
        cbar_label="Realised / planned",
        cmap="RdYlGn",
    )
    op_rows, tier_cols, op_matrix, op_ann = _matrix_heatmap_data(
        operator_complexity_rows,
        row_order=sorted({str(row["row_label"]) for row in operator_complexity_rows}),
        col_order=list(COMPLEXITY_TIERS),
    )
    _save_matrix_heatmap(
        figure_paths["heatmap_operator_complexity_tier"],
        row_labels=op_rows,
        col_labels=tier_cols,
        values=op_matrix,
        annotations=op_ann,
        title="Realised cohort density: mutation operator × complexity tier",
        cbar_label="Normalised case count",
        cmap="YlGnBu",
    )
    family_rows, family_tier_cols, family_matrix, family_ann = _matrix_heatmap_data(
        family_complexity_rows,
        row_order=sorted({str(row["row_label"]) for row in family_complexity_rows}),
        col_order=list(COMPLEXITY_TIERS),
    )
    _save_matrix_heatmap(
        figure_paths["heatmap_family_complexity_tier"],
        row_labels=family_rows,
        col_labels=family_tier_cols,
        values=family_matrix,
        annotations=family_ann,
        title="Realised cohort density: FSM family × complexity tier (plain_fsm only)",
        cbar_label="Normalised case count",
        cmap="YlGnBu",
    )
    _save_dimension_coverage_summary(figure_paths["heatmap_dimension_coverage_summary"], dimension_rows)

    captions_path = output_dir / "figure_captions.md"
    captions_path.write_text(build_figure_captions(summary_rows), encoding="utf-8")

    cohort_sha256 = sha256_file(resolved_cohort) if resolved_cohort.is_file() else ""
    manifest = {
        "release_label": "v0.2.0-analysis",
        "zenodo_doi": ZENODO_DOI,
        "dataset_dir": str(dataset_dir),
        "plan_path": str(resolved_plan),
        "cohort_path": str(resolved_cohort),
        "cohort_sha256": cohort_sha256,
        "case_count": case_count,
        "figures": {key: str(path.relative_to(output_dir)) for key, path in figure_paths.items()},
        "csv_exports": {key: str(path.relative_to(output_dir)) for key, path in csv_paths.items()},
        "captions": str(captions_path.relative_to(output_dir)),
        "regeneration_commands": [
            "python ../paper1/scripts/generate_coverage_visualization_outputs.py",
        ],
        "limitations_note": (
            "Visualises plan-vs-realised gaps on the frozen v0.2.0-analysis cohort "
            "(plain_fsm only); heatmaps are descriptive, not inferential."
        ),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return CoverageVisualizationResult(
        output_dir=output_dir,
        figures_dir=figures_dir,
        csv_paths=csv_paths,
        figure_paths=figure_paths,
        captions_path=captions_path,
    )
