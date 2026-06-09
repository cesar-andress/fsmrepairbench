"""Taxonomy coverage reporting for published benchmark datasets."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.analytics import _save_bar_plot
from fsmrepairbench.coverage_optimizer import (
    COVERAGE_FEATURES,
    FEATURE_UNIVERSES,
    CoverageOptimizerError,
    build_feature_coverage_report,
    load_feature_matrix,
)
from fsmrepairbench.dataset_builder import (
    _primary_mutation_operator,
    is_case_complete,
    resolve_coupling_case_file,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.stratified_builder import FEATURE_MATRIX_COLUMNS
from fsmrepairbench.taxonomy import BugType, CaseFeatures, compute_case_features
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

DEFAULT_OUTPUT_DIR = Path("results/taxonomy_coverage")
DEFAULT_COHORT_MANIFEST = "analysis_cohort_1k.txt"
COMPLEXITY_TIERS: tuple[str, ...] = ("small", "medium", "large", "very_large")
DIMENSION_SUMMARY_COLUMNS: tuple[str, ...] = (
    "dimension",
    "observed_values",
    "universe_values",
    "coverage_ratio",
    "entropy",
)
GROUP_SUMMARY_COLUMNS: tuple[str, ...] = (
    "group_key",
    "group_value",
    "case_count",
    "cohort_fraction",
    "distinct_subgroups",
    "subgroup_coverage_ratio",
)


class TaxonomyCoverageError(RuntimeError):
    """Raised when taxonomy coverage reporting cannot be completed."""


@dataclass(frozen=True)
class TaxonomyCoverageResult:
    """Paths written by a taxonomy coverage report run."""

    dataset_dir: Path
    output_dir: Path
    cohort_path: Path | None
    case_count: int
    report_path: Path
    summary_path: Path
    dimension_summary_path: Path
    dimension_detail_path: Path
    fsm_family_path: Path
    mutation_operator_path: Path
    complexity_tier_path: Path
    feature_space_path: Path
    figures_dir: Path
    tables_dir: Path


def load_cohort_case_ids(
    dataset_dir: Path,
    *,
    cohort_path: Path | None = None,
) -> list[str]:
    """Load case IDs from a cohort manifest or completed rows in progress.csv."""
    manifest = cohort_path or (dataset_dir / DEFAULT_COHORT_MANIFEST)
    if manifest.is_file():
        return [
            line.strip()
            for line in manifest.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    progress_path = dataset_dir / "progress.csv"
    if not progress_path.is_file():
        msg = f"No cohort manifest or progress.csv under {dataset_dir}"
        raise TaxonomyCoverageError(msg)

    return [
        row["case_id"]
        for row in csv.DictReader(progress_path.open(encoding="utf-8"))
        if row.get("status") == "completed" and row.get("case_id")
    ]


def _features_to_row(features: CaseFeatures) -> dict[str, str | int | float]:
    return {
        "case_id": features.case_id,
        "machine_type": features.machine_type.value,
        "determinism": features.determinism.value,
        "completeness": features.completeness.value,
        "arity_class": features.arity_class.value,
        "size_class": features.size_class.value,
        "guard_complexity": features.guard_complexity.value,
        "time_features": "|".join(item.value for item in features.time_features),
        "graph_structure": "|".join(item.value for item in features.graph_structure),
        "oracle_depth": features.oracle_depth.value,
        "bug_type": features.bug_type.value,
        "num_states": features.num_states,
        "num_events": features.num_events,
        "num_transitions": features.num_transitions,
        "avg_out_degree": features.avg_out_degree,
        "max_out_degree": features.max_out_degree,
        "num_guards": features.num_guards,
        "num_timed_guards": features.num_timed_guards,
        "num_timeouts": features.num_timeouts,
        "num_cycles": "" if features.num_cycles is None else features.num_cycles,
        "scc_count": "" if features.scc_count is None else features.scc_count,
        "seed": features.seed,
    }


def _case_features_json_to_row(case_dir: Path) -> dict[str, str | int | float]:
    payload = json.loads((case_dir / "case_features.json").read_text(encoding="utf-8"))
    return {
        "case_id": str(payload["case_id"]),
        "machine_type": str(payload["machine_type"]),
        "determinism": str(payload["determinism"]),
        "completeness": str(payload["completeness"]),
        "arity_class": str(payload["arity_class"]),
        "size_class": str(payload["size_class"]),
        "guard_complexity": str(payload["guard_complexity"]),
        "time_features": "|".join(payload.get("time_features", [])),
        "graph_structure": "|".join(payload.get("graph_structure", [])),
        "oracle_depth": str(payload["oracle_depth"]),
        "bug_type": str(payload["bug_type"]),
        "num_states": int(payload["num_states"]),
        "num_events": int(payload["num_events"]),
        "num_transitions": int(payload["num_transitions"]),
        "avg_out_degree": float(payload["avg_out_degree"]),
        "max_out_degree": int(payload["max_out_degree"]),
        "num_guards": int(payload["num_guards"]),
        "num_timed_guards": int(payload["num_timed_guards"]),
        "num_timeouts": int(payload["num_timeouts"]),
        "num_cycles": "" if payload.get("num_cycles") is None else int(payload["num_cycles"]),
        "scc_count": "" if payload.get("scc_count") is None else int(payload["scc_count"]),
        "seed": int(payload["seed"]),
    }


def _infer_feature_row(case_dir: Path) -> dict[str, str | int | float]:
    if (case_dir / "case_features.json").is_file():
        return _case_features_json_to_row(case_dir)

    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if reference_path is None or oracle_path is None:
        msg = f"Incomplete case directory: {case_dir}"
        raise TaxonomyCoverageError(msg)

    bug_metadata = BugMetadata.model_validate(
        json.loads((case_dir / "bug_metadata.json").read_text(encoding="utf-8"))
    )
    reference = load_fsm_json(reference_path)
    oracle = load_oracle_suite(oracle_path)
    operator = _primary_mutation_operator(bug_metadata.mutation_operator)
    bug_type = (
        BugType(operator)
        if operator in BugType._value2member_map_
        else BugType.MISSING_TRANSITION
    )
    features = compute_case_features(
        reference,
        oracle,
        bug_type,
        bug_metadata.seed,
        case_id=case_dir.name,
    )
    row = _features_to_row(features)
    if operator not in BugType._value2member_map_:
        row["bug_type"] = operator
    return row


def _load_progress_index(dataset_dir: Path) -> dict[str, dict[str, str]]:
    progress_path = dataset_dir / "progress.csv"
    if not progress_path.is_file():
        return {}
    return {
        row["case_id"]: row
        for row in csv.DictReader(progress_path.open(encoding="utf-8"))
        if row.get("case_id")
    }


def load_taxonomy_feature_rows(
    dataset_dir: Path,
    case_ids: list[str],
) -> tuple[list[dict[str, str | int | float]], dict[str, str]]:
    """Load taxonomy feature rows and per-case complexity tiers."""
    matrix_path = dataset_dir / "feature_matrix.csv"
    complexity_by_case: dict[str, str] = {}
    progress_index = _load_progress_index(dataset_dir)

    if matrix_path.is_file():
        rows = load_feature_matrix(matrix_path)
        by_id = {row["case_id"]: row for row in rows}
        selected = [by_id[case_id] for case_id in case_ids if case_id in by_id]
        if len(selected) < len(case_ids):
            missing = len(case_ids) - len(selected)
            msg = f"Feature matrix missing {missing} cohort case IDs"
            raise TaxonomyCoverageError(msg)
        for case_id in case_ids:
            if case_id in progress_index:
                complexity_by_case[case_id] = progress_index[case_id].get("complexity", "")
            elif case_id in by_id:
                size_class = by_id[case_id].get("size_class", "")
                complexity_by_case[case_id] = _size_class_to_complexity_tier(str(size_class))
        return selected, complexity_by_case

    selected: list[dict[str, str | int | float]] = []
    for case_id in case_ids:
        case_dir = dataset_dir / "cases" / case_id
        if not is_case_complete(case_dir):
            msg = f"Incomplete case directory for {case_id}"
            raise TaxonomyCoverageError(msg)
        selected.append(_infer_feature_row(case_dir))
        if case_id in progress_index:
            complexity_by_case[case_id] = progress_index[case_id].get("complexity", "")
        else:
            metadata_path = case_dir / "case_metadata.json"
            if metadata_path.is_file():
                metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
                complexity_by_case[case_id] = str(metadata.get("complexity", ""))

    return selected, complexity_by_case


def _size_class_to_complexity_tier(size_class: str) -> str:
    if size_class in {"tiny", "small"}:
        return "small"
    if size_class == "medium":
        return "medium"
    if size_class == "large":
        return "large"
    if size_class == "very_large":
        return "very_large"
    return size_class


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _observed_dimension_values(
    rows: list[dict[str, str | int | float]],
    dimension: str,
) -> set[str]:
    observed: set[str] = set()
    for row in rows:
        raw = str(row[dimension])
        if dimension in {"graph_structure", "time_features"} and "|" in raw:
            observed.update(part for part in raw.split("|") if part)
        else:
            observed.add(raw)
    return observed


def _universe_for_dimension(dimension: str, observed: set[str]) -> tuple[str, ...]:
    if dimension == "bug_type":
        return tuple(sorted(set(MUTATION_OPERATORS) | observed))
    universe = FEATURE_UNIVERSES.get(dimension, tuple())
    return tuple(sorted(set(universe) | observed))


def _dimension_detail_rows(
    rows: list[dict[str, str | int | float]],
    *,
    case_count: int,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    detail: list[dict[str, object]] = []
    summary: list[dict[str, object]] = []
    feature_report = build_feature_coverage_report(
        [dict(row) for row in rows],
        feature_matrix_path="<cohort>",
    )
    entropies = feature_report["feature_entropy"]

    for dimension in COVERAGE_FEATURES:
        if dimension in {"graph_structure", "time_features"}:
            counts: Counter[str] = Counter()
            for row in rows:
                raw = str(row[dimension])
                parts = raw.split("|") if "|" in raw else [raw]
                for part in parts:
                    if part:
                        counts[part] += 1
        else:
            counts = Counter(str(row[dimension]) for row in rows)

        observed_set = _observed_dimension_values(rows, dimension)
        universe = _universe_for_dimension(dimension, observed_set)
        observed_values = len(observed_set)
        universe_values = len(universe) if universe else observed_values
        coverage_ratio = (
            round(min(1.0, observed_values / universe_values), 6) if universe_values else 0.0
        )
        summary.append(
            {
                "dimension": dimension,
                "observed_values": observed_values,
                "universe_values": universe_values,
                "coverage_ratio": coverage_ratio,
                "entropy": entropies.get(dimension, 0.0),
            }
        )
        for value, count in sorted(counts.items()):
            detail.append(
                {
                    "dimension": dimension,
                    "value": value,
                    "case_count": count,
                    "cohort_fraction": round(count / case_count, 6),
                    "present_in_universe": value in universe if universe else True,
                }
            )
    return summary, detail


def _group_rows(
    rows: list[dict[str, str | int | float]],
    complexity_by_case: dict[str, str],
    *,
    group_key: str,
    group_field: str,
    subgroup_field: str,
    subgroup_universe: tuple[str, ...],
    case_count: int,
) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, str | int | float]]] = defaultdict(list)
    for row in rows:
        if group_field == "complexity_tier":
            value = complexity_by_case.get(str(row["case_id"]), "unknown")
        else:
            value = str(row[group_field])
        grouped[value].append(row)

    output: list[dict[str, object]] = []
    for value in sorted(grouped):
        group_rows = grouped[value]
        count = len(group_rows)
        subgroups = {str(item[subgroup_field]) for item in group_rows}
        universe_size = len(subgroup_universe) if subgroup_universe else len(subgroups)
        output.append(
            {
                "group_key": group_key,
                "group_value": value,
                "case_count": count,
                "cohort_fraction": round(count / case_count, 6),
                "distinct_subgroups": len(subgroups),
                "subgroup_coverage_ratio": round(len(subgroups) / universe_size, 6)
                if universe_size
                else 0.0,
            }
        )
    return output


def _mutation_operator_rows(
    rows: list[dict[str, str | int | float]],
    *,
    case_count: int,
) -> list[dict[str, object]]:
    counts = Counter(str(row["bug_type"]) for row in rows)
    observed_operators = set(counts)
    extended_universe = tuple(sorted(set(MUTATION_OPERATORS) | observed_operators))
    machine_types_by_operator: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        machine_types_by_operator[str(row["bug_type"])].add(str(row["machine_type"]))

    output: list[dict[str, object]] = []
    for operator in extended_universe:
        count = counts.get(operator, 0)
        families = machine_types_by_operator.get(operator, set())
        output.append(
            {
                "group_key": "mutation_operator",
                "group_value": operator,
                "case_count": count,
                "cohort_fraction": round(count / case_count, 6) if case_count else 0.0,
                "distinct_subgroups": len(families),
                "subgroup_coverage_ratio": round(len(families) / len({row["machine_type"] for row in rows}), 6)
                if rows
                else 0.0,
                "present_in_cohort": count > 0,
            }
        )
    return output


def _summary_rows(
    *,
    case_count: int,
    dimension_summary: list[dict[str, object]],
    mutation_rows: list[dict[str, object]],
    complexity_rows: list[dict[str, object]],
    fsm_rows: list[dict[str, object]],
    feature_space: dict[str, object],
) -> list[dict[str, object]]:
    mean_dimension_coverage = round(
        sum(float(row["coverage_ratio"]) for row in dimension_summary) / len(dimension_summary),
        6,
    )
    operators_present = sum(1 for row in mutation_rows if int(row["case_count"]) > 0)
    operators_total = len(mutation_rows)
    tiers_present = sum(
        1 for row in complexity_rows if str(row["group_value"]) in COMPLEXITY_TIERS
    )
    families_present = sum(1 for row in fsm_rows if int(row["case_count"]) > 0)
    triple = feature_space["triple_coverage"]
    return [
        {"metric": "case_count", "value": case_count},
        {"metric": "mean_dimension_coverage_ratio", "value": mean_dimension_coverage},
        {"metric": "mutation_operators_present", "value": operators_present},
        {"metric": "mutation_operators_total", "value": operators_total},
        {"metric": "mutation_operator_coverage_ratio", "value": round(operators_present / operators_total, 6)},
        {"metric": "complexity_tiers_present", "value": tiers_present},
        {"metric": "complexity_tier_coverage_ratio", "value": round(tiers_present / len(COMPLEXITY_TIERS), 6)},
        {"metric": "fsm_families_present", "value": families_present},
        {"metric": "unique_taxonomy_combinations", "value": feature_space["unique_feature_combinations"]["unique_count"]},
        {"metric": "triple_feature_coverage_ratio", "value": triple["coverage"]},
        {"metric": "pairwise_mean_coverage_ratio", "value": round(
            sum(item["coverage"] for item in feature_space["pairwise_coverage"].values())
            / max(len(feature_space["pairwise_coverage"]), 1),
            6,
        )},
    ]


def _write_feature_matrix_snapshot(path: Path, rows: list[dict[str, str | int | float]]) -> None:
    _write_csv(path, FEATURE_MATRIX_COLUMNS, rows)


def _write_figures(
    figures_dir: Path,
    *,
    dimension_summary: list[dict[str, object]],
    fsm_rows: list[dict[str, object]],
    mutation_rows: list[dict[str, object]],
    complexity_rows: list[dict[str, object]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    _save_bar_plot(
        figures_dir / "dimension_coverage_ratio.png",
        title="Taxonomy Dimension Value Coverage",
        xlabel="Dimension",
        ylabel="Observed / Universe",
        labels=[str(row["dimension"]) for row in dimension_summary],
        values=[float(row["coverage_ratio"]) for row in dimension_summary],
    )
    _save_bar_plot(
        figures_dir / "fsm_family_case_counts.png",
        title="Cases by FSM Family",
        xlabel="Machine Type",
        ylabel="Cases",
        labels=[str(row["group_value"]) for row in fsm_rows if int(row["case_count"]) > 0],
        values=[int(row["case_count"]) for row in fsm_rows if int(row["case_count"]) > 0],
    )
    present_mutations = [row for row in mutation_rows if int(row["case_count"]) > 0]
    _save_bar_plot(
        figures_dir / "mutation_operator_case_counts.png",
        title="Cases by Mutation Operator",
        xlabel="Operator",
        ylabel="Cases",
        labels=[str(row["group_value"]) for row in present_mutations],
        values=[int(row["case_count"]) for row in present_mutations],
    )
    tier_rows = [row for row in complexity_rows if str(row["group_value"]) in COMPLEXITY_TIERS]
    _save_bar_plot(
        figures_dir / "complexity_tier_case_counts.png",
        title="Cases by Complexity Tier",
        xlabel="Tier",
        ylabel="Cases",
        labels=[str(row["group_value"]) for row in tier_rows],
        values=[int(row["case_count"]) for row in tier_rows],
    )


def _write_latex_tables(
    tables_dir: Path,
    *,
    dimension_summary: list[dict[str, object]],
    fsm_rows: list[dict[str, object]],
    mutation_rows: list[dict[str, object]],
    complexity_rows: list[dict[str, object]],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by generate-taxonomy-coverage",
        "\\begin{tabular}{lrrr}",
        "\\toprule",
        "Dimension & Observed & Universe & Coverage \\\\",
        "\\midrule",
    ]
    for row in dimension_summary:
        lines.append(
            f"{row['dimension']} & {row['observed_values']} & {row['universe_values']} & "
            f"{float(row['coverage_ratio']):.1%} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (tables_dir / "table_dimension_coverage.tex").write_text("\n".join(lines), encoding="utf-8")

    def _write_group_table(filename: str, title_values: list[dict[str, object]]) -> None:
        table_lines = [
            "% Auto-generated by generate-taxonomy-coverage",
            "\\begin{tabular}{lrr}",
            "\\toprule",
            "Group & Cases & Cohort Share \\\\",
            "\\midrule",
        ]
        for row in title_values:
            if int(row["case_count"]) <= 0:
                continue
            table_lines.append(
                f"{row['group_value']} & {row['case_count']} & "
                f"{float(row['cohort_fraction']):.1%} \\\\"
            )
        table_lines.extend(["\\bottomrule", "\\end{tabular}", ""])
        (tables_dir / filename).write_text("\n".join(table_lines), encoding="utf-8")

    _write_group_table("table_fsm_family_coverage.tex", fsm_rows)
    _write_group_table(
        "table_mutation_operator_coverage.tex",
        [row for row in mutation_rows if int(row["case_count"]) > 0],
    )
    _write_group_table(
        "table_complexity_tier_coverage.tex",
        [row for row in complexity_rows if str(row["group_value"]) in COMPLEXITY_TIERS],
    )


def _support_statement(summary_rows: list[dict[str, object]], feature_space: dict[str, object]) -> str:
    metrics = {str(row["metric"]): row["value"] for row in summary_rows}
    operator_cov = float(metrics["mutation_operator_coverage_ratio"])
    tier_cov = float(metrics["complexity_tier_coverage_ratio"])
    mean_dim = float(metrics["mean_dimension_coverage_ratio"])
    triple_cov = float(metrics["triple_feature_coverage_ratio"])
    unique = int(metrics["unique_taxonomy_combinations"])
    case_count = int(metrics["case_count"])

    if operator_cov >= 0.9 and tier_cov == 1.0 and mean_dim >= 0.5:
        lead = (
            "Published taxonomy claims are **empirically supported** on the analysed cohort: "
            f"mutation operators, complexity tiers, and FSM families are all represented, "
            f"with {unique} distinct taxonomy combinations across {case_count} cases."
        )
    elif operator_cov >= 0.75 and tier_cov >= 0.75:
        lead = (
            "Taxonomy claims are **partially supported**: core dimensions are populated, "
            "but some declared operator or feature-space cells remain absent."
        )
    else:
        lead = (
            "Taxonomy claims are **only weakly supported** on this cohort; several declared "
            "dimensions or operator families are underrepresented."
        )

    return (
        f"{lead} Mean dimension value coverage is {mean_dim:.1%}; "
        f"mutation-operator coverage is {operator_cov:.1%}; "
        f"machine-type/bug-type/size-class triple coverage is {triple_cov:.1%}."
    )


def write_taxonomy_coverage_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    cohort_path: Path | None,
    case_count: int,
    dimension_summary: list[dict[str, object]],
    fsm_rows: list[dict[str, object]],
    mutation_rows: list[dict[str, object]],
    complexity_rows: list[dict[str, object]],
    summary_rows: list[dict[str, object]],
    feature_space: dict[str, object],
) -> None:
    """Write Markdown report demonstrating taxonomy claim support."""
    lines = [
        "# Taxonomy Coverage Report",
        "",
        "Empirical coverage audit of the FSMRepairBench taxonomy on an existing published dataset.",
        "",
        "## Dataset",
        "",
        f"- **Dataset directory:** `{dataset_dir}`",
        f"- **Cases analysed:** {case_count}",
        f"- **Cohort manifest:** `{cohort_path or 'progress.csv (completed cases)'}`",
        "",
        "## Executive summary",
        "",
        _support_statement(summary_rows, feature_space),
        "",
        "## Coverage per taxonomy dimension",
        "",
        "| Dimension | Observed values | Universe | Coverage | Entropy |",
        "|-----------|----------------:|---------:|---------:|--------:|",
    ]
    for row in dimension_summary:
        lines.append(
            f"| `{row['dimension']}` | {row['observed_values']} | {row['universe_values']} | "
            f"{float(row['coverage_ratio']):.1%} | {float(row['entropy']):.3f} |"
        )

    lines.extend(
        [
            "",
            "![Dimension coverage ratios](figures/dimension_coverage_ratio.png)",
            "",
            "## Coverage per FSM family",
            "",
            "| FSM family | Cases | Cohort share | Mutation operators |",
            "|------------|------:|-------------:|-------------------:|",
        ]
    )
    for row in fsm_rows:
        if int(row["case_count"]) <= 0:
            continue
        lines.append(
            f"| `{row['group_value']}` | {row['case_count']} | "
            f"{float(row['cohort_fraction']):.1%} | {row['distinct_subgroups']} |"
        )

    lines.extend(
        [
            "",
            "![FSM family case counts](figures/fsm_family_case_counts.png)",
            "",
            "## Coverage per mutation operator",
            "",
            "| Operator | Cases | Cohort share | FSM families |",
            "|----------|------:|-------------:|-------------:|",
        ]
    )
    for row in mutation_rows:
        if int(row["case_count"]) <= 0:
            continue
        lines.append(
            f"| `{row['group_value']}` | {row['case_count']} | "
            f"{float(row['cohort_fraction']):.1%} | {row['distinct_subgroups']} |"
        )

    lines.extend(
        [
            "",
            "![Mutation operator case counts](figures/mutation_operator_case_counts.png)",
            "",
            "## Coverage per complexity tier",
            "",
            "| Tier | Cases | Cohort share | Mutation operators |",
            "|------|------:|-------------:|-------------------:|",
        ]
    )
    for row in complexity_rows:
        if str(row["group_value"]) not in COMPLEXITY_TIERS:
            continue
        lines.append(
            f"| `{row['group_value']}` | {row['case_count']} | "
            f"{float(row['cohort_fraction']):.1%} | {row['distinct_subgroups']} |"
        )

    missing = feature_space["missing_combinations"]
    lines.extend(
        [
            "",
            "![Complexity tier case counts](figures/complexity_tier_case_counts.png)",
            "",
            "## Feature-space saturation",
            "",
            f"- Unique full-taxonomy combinations: **{feature_space['unique_feature_combinations']['unique_count']}**",
            f"- Missing core 5-feature combinations: **{missing['missing_count']}** "
            f"(of {missing['possible_count']} possible)",
            f"- Triple (`machine_type`, `bug_type`, `size_class`) coverage: "
            f"**{feature_space['triple_coverage']['coverage']:.1%}**",
            "",
            "## Artefacts",
            "",
            f"- Summary metrics: `{output_dir / 'summary.csv'}`",
            f"- Dimension detail: `{output_dir / 'coverage_by_dimension.csv'}`",
            f"- LaTeX tables: `{output_dir / 'tables/'}`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_taxonomy_coverage_report(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_path: Path | None = None,
) -> TaxonomyCoverageResult:
    """Generate taxonomy coverage tables, figures, and report for *dataset_dir*."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise TaxonomyCoverageError(msg)

    out = output_dir or DEFAULT_OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)

    case_ids = load_cohort_case_ids(dataset_dir, cohort_path=cohort_path)
    if not case_ids:
        msg = f"No cases found for taxonomy coverage under {dataset_dir}"
        raise TaxonomyCoverageError(msg)

    rows, complexity_by_case = load_taxonomy_feature_rows(dataset_dir, case_ids)
    case_count = len(rows)
    matrix_snapshot = out / "feature_matrix_snapshot.csv"
    if not (dataset_dir / "feature_matrix.csv").is_file():
        _write_feature_matrix_snapshot(matrix_snapshot, rows)

    string_rows = [dict(row) for row in rows]
    feature_space = build_feature_coverage_report(
        string_rows,
        feature_matrix_path=str(dataset_dir / "feature_matrix.csv")
        if (dataset_dir / "feature_matrix.csv").is_file()
        else str(matrix_snapshot),
    )

    dimension_summary, dimension_detail = _dimension_detail_rows(rows, case_count=case_count)
    fsm_rows = _group_rows(
        rows,
        complexity_by_case,
        group_key="fsm_family",
        group_field="machine_type",
        subgroup_field="bug_type",
        subgroup_universe=tuple(sorted({str(row["bug_type"]) for row in rows})),
        case_count=case_count,
    )
    mutation_rows = _mutation_operator_rows(rows, case_count=case_count)
    complexity_rows = _group_rows(
        rows,
        complexity_by_case,
        group_key="complexity_tier",
        group_field="complexity_tier",
        subgroup_field="bug_type",
        subgroup_universe=tuple(sorted({str(row["bug_type"]) for row in rows})),
        case_count=case_count,
    )
    summary_rows = _summary_rows(
        case_count=case_count,
        dimension_summary=dimension_summary,
        mutation_rows=mutation_rows,
        complexity_rows=complexity_rows,
        fsm_rows=fsm_rows,
        feature_space=feature_space,
    )

    dimension_summary_path = out / "dimension_summary.csv"
    dimension_detail_path = out / "coverage_by_dimension.csv"
    fsm_family_path = out / "coverage_by_fsm_family.csv"
    mutation_operator_path = out / "coverage_by_mutation_operator.csv"
    complexity_tier_path = out / "coverage_by_complexity_tier.csv"
    summary_path = out / "summary.csv"
    feature_space_path = out / "feature_space_report.json"
    report_path = out / "taxonomy_coverage_report.md"
    figures_dir = out / "figures"
    tables_dir = out / "tables"

    _write_csv(dimension_summary_path, DIMENSION_SUMMARY_COLUMNS, dimension_summary)
    _write_csv(
        dimension_detail_path,
        ("dimension", "value", "case_count", "cohort_fraction", "present_in_universe"),
        dimension_detail,
    )
    _write_csv(fsm_family_path, GROUP_SUMMARY_COLUMNS, fsm_rows)
    _write_csv(
        mutation_operator_path,
        GROUP_SUMMARY_COLUMNS + ("present_in_cohort",),
        mutation_rows,
    )
    _write_csv(complexity_tier_path, GROUP_SUMMARY_COLUMNS, complexity_rows)
    _write_csv(summary_path, ("metric", "value"), summary_rows)
    feature_space_path.write_text(json.dumps(feature_space, indent=2) + "\n", encoding="utf-8")

    _write_figures(
        figures_dir,
        dimension_summary=dimension_summary,
        fsm_rows=fsm_rows,
        mutation_rows=mutation_rows,
        complexity_rows=complexity_rows,
    )
    _write_latex_tables(
        tables_dir,
        dimension_summary=dimension_summary,
        fsm_rows=fsm_rows,
        mutation_rows=mutation_rows,
        complexity_rows=complexity_rows,
    )
    write_taxonomy_coverage_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_path or (dataset_dir / DEFAULT_COHORT_MANIFEST),
        case_count=case_count,
        dimension_summary=dimension_summary,
        fsm_rows=fsm_rows,
        mutation_rows=mutation_rows,
        complexity_rows=complexity_rows,
        summary_rows=summary_rows,
        feature_space=feature_space,
    )

    manifest = {
        "experiment": "taxonomy-coverage-report",
        "dataset_dir": str(dataset_dir),
        "output_dir": str(out),
        "case_count": case_count,
        "cohort_path": str(cohort_path or (dataset_dir / DEFAULT_COHORT_MANIFEST)),
        "summary": summary_rows,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    resolved_cohort = cohort_path if cohort_path and cohort_path.is_file() else None
    if resolved_cohort is None:
        default_manifest = dataset_dir / DEFAULT_COHORT_MANIFEST
        resolved_cohort = default_manifest if default_manifest.is_file() else None

    return TaxonomyCoverageResult(
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=resolved_cohort,
        case_count=case_count,
        report_path=report_path,
        summary_path=summary_path,
        dimension_summary_path=dimension_summary_path,
        dimension_detail_path=dimension_detail_path,
        fsm_family_path=fsm_family_path,
        mutation_operator_path=mutation_operator_path,
        complexity_tier_path=complexity_tier_path,
        feature_space_path=feature_space_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
    )
