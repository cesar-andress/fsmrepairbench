"""Multi-family external-validity pilot cohort analysis (v0.3.0)."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.analytics import (
    _pyplot,
    _save_bar_plot,
    compute_benchmark_analytics,
    write_analysis_summary_csv,
)
from fsmrepairbench.dataset_builder import DatasetCaseRow, load_dataset_cases
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.generators.stratified_specs import DatasetPlan, load_dataset_plan, total_planned_cases

MULTIFAMILY_EXPERIMENT = "multifamily-v0.3.0-external-validity-pilot"
MULTIFAMILY_PILOT_EXPERIMENT = "multifamily-v0.3.0-pilot"
MULTIFAMILY_PILOT_RELEASE = "v0.3.0-multifamily-pilot"
MULTIFAMILY_SMOKE_RELEASE = "v0.3.0-external-validity-pilot"
FROZEN_V020_ZENODO_DOI = "10.5281/zenodo.20724095"
FROZEN_1K_COHORT_PATH = Path("data/fsmrepairbench_1k/analysis_cohort_1k.txt")
DEFAULT_PILOT_PLAN_PATH = Path("plans/fsmrepairbench_multifamily_pilot_plan.yaml")
DEFAULT_PILOT_DATASET_DIR = Path("data/fsmrepairbench_multifamily_pilot")
DEFAULT_PILOT_OUTPUT_DIR = Path("results/multifamily_pilot")
DEFAULT_PILOT_PAPER_EXPORT = Path("../paper1/results/multifamily_pilot")
MULTIFAMILY_TARGET_FAMILIES: tuple[str, ...] = (
    "plain_fsm",
    "mealy",
    "moore",
    "efsm",
    "timed_fsm",
)
DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_multifamily_v0_3_smoke")
DEFAULT_PLAN_PATH = Path("plans/fsmrepairbench_multifamily_v0_3_smoke_plan.yaml")
DEFAULT_OUTPUT_DIR = Path("results/multifamily_v0_3_smoke")
DEFAULT_PAPER_EXPORT = Path("../paper1/results/multifamily_v0_3_smoke")
SUMMARY_COLUMNS: tuple[str, ...] = ("metric", "value")
FAMILY_SUMMARY_COLUMNS: tuple[str, ...] = (
    "machine_type",
    "planned_case_count",
    "built_case_count",
    "build_failure_count",
    "detection_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
    "mean_oracle_state_coverage",
    "mean_oracle_transition_coverage",
    "mean_oracle_event_coverage",
)
OPERATOR_BY_FAMILY_COLUMNS: tuple[str, ...] = (
    "machine_type",
    "mutation_operator",
    "case_count",
    "fraction_within_family",
)
DETECTION_BY_FAMILY_COLUMNS: tuple[str, ...] = (
    "machine_type",
    "case_count",
    "detected_cases",
    "detection_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
    "mean_oracle_state_coverage",
    "mean_oracle_transition_coverage",
    "mean_oracle_event_coverage",
)


class MultifamilyAnalysisError(RuntimeError):
    """Raised when multi-family pilot analysis cannot be completed."""


@dataclass(frozen=True)
class MultifamilyCaseRecord:
    """Case row enriched with machine family from the feature matrix."""

    case: DatasetCaseRow
    machine_type: str


@dataclass(frozen=True)
class MultifamilyAnalysisResult:
    """Paths written by a multi-family pilot analysis run."""

    dataset_dir: Path
    output_dir: Path
    paper_export_dir: Path
    summary_path: Path
    family_summary_path: Path
    operator_by_family_path: Path
    detection_by_family_path: Path
    report_path: Path
    manifest_path: Path
    figures_dir: Path
    tables_dir: Path
    case_count: int
    coverage_dir: Path | None = None


def _resolve_release_metadata(plan: DatasetPlan) -> tuple[str, str]:
    if plan.name == "fsmrepairbench_multifamily_pilot":
        return MULTIFAMILY_PILOT_EXPERIMENT, MULTIFAMILY_PILOT_RELEASE
    return MULTIFAMILY_EXPERIMENT, MULTIFAMILY_SMOKE_RELEASE


def _frozen_1k_reference() -> dict[str, str]:
    cohort_path = FROZEN_1K_COHORT_PATH
    payload: dict[str, str] = {
        "zenodo_doi": FROZEN_V020_ZENODO_DOI,
        "release_label": "v0.2.0-analysis",
        "cohort_path": str(cohort_path),
        "note": "Frozen plain_fsm 1k cohort; not modified by multifamily pilot builds.",
    }
    if cohort_path.is_file():
        payload["cohort_sha256"] = sha256_file(cohort_path)
    return payload


def _list_output_files(output_dir: Path) -> list[str]:
    files: list[str] = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            files.append(path.relative_to(output_dir).as_posix())
    return files


def _build_output_sha256_index(output_dir: Path) -> dict[str, str]:
    index: dict[str, str] = {}
    for relative_path in _list_output_files(output_dir):
        index[relative_path] = sha256_file(output_dir / relative_path)
    return index


def _load_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _append_coverage_report_section(
    lines: list[str],
    *,
    coverage_dir: Path,
) -> None:
    dimension_rows = _load_csv_rows(coverage_dir / "dimension_summary.csv")
    operator_rows = _load_csv_rows(coverage_dir / "coverage_by_mutation_operator.csv")
    tier_rows = _load_csv_rows(coverage_dir / "coverage_by_complexity_tier.csv")
    machine_rows = _load_csv_rows(coverage_dir / "coverage_by_fsm_family.csv")
    summary_rows = _load_csv_rows(coverage_dir / "summary.csv")
    summary_metrics = {row["metric"]: row["value"] for row in summary_rows}

    lines.extend(
        [
            "",
            "## Taxonomy coverage ratios",
            "",
            "Coverage ratios are computed on the pilot cohort using the same taxonomy "
            "dimensions as the frozen `v0.2.0-analysis` release.",
            "",
        ]
    )
    if summary_metrics:
        lines.append(
            f"- Mean dimension coverage: **{float(summary_metrics.get('mean_dimension_coverage_ratio', 0.0)):.1%}**"
        )
        lines.append(
            f"- Mutation-operator coverage: **{float(summary_metrics.get('mutation_operator_coverage_ratio', 0.0)):.1%}**"
        )
        lines.append(
            f"- Complexity-tier coverage: **{float(summary_metrics.get('complexity_tier_coverage_ratio', 0.0)):.1%}**"
        )
        lines.append(
            f"- Machine-type coverage: **{float(summary_metrics.get('fsm_family_coverage_ratio', 0.0)):.1%}**"
        )

    if dimension_rows:
        lines.extend(
            [
                "",
                "### Coverage by taxonomy dimension",
                "",
                "| Dimension | Observed | Universe | Coverage |",
                "|-----------|---------:|---------:|---------:|",
            ]
        )
        for row in dimension_rows:
            lines.append(
                f"| `{row['dimension']}` | {row['observed_values']} | {row['universe_values']} | "
                f"{float(row['coverage_ratio']):.1%} |"
            )

    if operator_rows:
        lines.extend(
            [
                "",
                "### Coverage by mutation operator",
                "",
                "| Operator | Cases | Cohort share | Subgroup coverage |",
                "|----------|------:|-------------:|------------------:|",
            ]
        )
        for row in operator_rows:
            if int(float(row["case_count"])) <= 0:
                continue
            lines.append(
                f"| `{row['group_value']}` | {row['case_count']} | "
                f"{float(row['cohort_fraction']):.1%} | "
                f"{float(row['subgroup_coverage_ratio']):.1%} |"
            )

    if tier_rows:
        lines.extend(
            [
                "",
                "### Coverage by complexity tier",
                "",
                "| Tier | Cases | Cohort share | Subgroup coverage |",
                "|------|------:|-------------:|------------------:|",
            ]
        )
        for row in tier_rows:
            if int(float(row["case_count"])) <= 0:
                continue
            lines.append(
                f"| `{row['group_value']}` | {row['case_count']} | "
                f"{float(row['cohort_fraction']):.1%} | "
                f"{float(row['subgroup_coverage_ratio']):.1%} |"
            )

    if machine_rows:
        lines.extend(
            [
                "",
                "### Coverage by machine type",
                "",
                "| Machine type | Cases | Cohort share | Operator diversity |",
                "|--------------|------:|-------------:|-------------------:|",
            ]
        )
        for row in machine_rows:
            if int(float(row["case_count"])) <= 0:
                continue
            lines.append(
                f"| `{row['group_value']}` | {row['case_count']} | "
                f"{float(row['cohort_fraction']):.1%} | {row['distinct_subgroups']} |"
            )

    lines.extend(
        [
            "",
            f"Full taxonomy coverage artefacts: `{coverage_dir}`",
            "",
        ]
    )


def planned_counts_by_family(plan: DatasetPlan) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for cell in plan.cells:
        counts[cell.machine_type.value] += cell.count
    return dict(sorted(counts.items()))


def load_machine_type_index(dataset_dir: Path) -> dict[str, str]:
    matrix_path = dataset_dir / "feature_matrix.csv"
    if not matrix_path.is_file():
        msg = f"Feature matrix not found: {matrix_path}"
        raise MultifamilyAnalysisError(msg)
    index: dict[str, str] = {}
    with matrix_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None or "machine_type" not in reader.fieldnames:
            msg = f"Feature matrix missing machine_type column: {matrix_path}"
            raise MultifamilyAnalysisError(msg)
        for row in reader:
            index[str(row["case_id"])] = str(row["machine_type"])
    return index


def load_multifamily_records(dataset_dir: Path) -> list[MultifamilyCaseRecord]:
    machine_types = load_machine_type_index(dataset_dir)
    cases = load_dataset_cases(dataset_dir)
    records: list[MultifamilyCaseRecord] = []
    for case in cases:
        machine_type = machine_types.get(case.case_id)
        if machine_type is None:
            msg = f"Missing machine_type for {case.case_id} in feature matrix"
            raise MultifamilyAnalysisError(msg)
        records.append(MultifamilyCaseRecord(case=case, machine_type=machine_type))
    return records


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def compute_family_summary_rows(
    records: list[MultifamilyCaseRecord],
    *,
    planned_by_family: dict[str, int],
) -> list[dict[str, str | float | int]]:
    grouped: dict[str, list[MultifamilyCaseRecord]] = defaultdict(list)
    for record in records:
        grouped[record.machine_type].append(record)

    rows: list[dict[str, str | float | int]] = []
    for family in MULTIFAMILY_TARGET_FAMILIES:
        family_records = grouped.get(family, [])
        built = len(family_records)
        planned = planned_by_family.get(family, 0)
        detected = sum(1 for record in family_records if record.case.bpr_delta > 0.0)
        rows.append(
            {
                "machine_type": family,
                "planned_case_count": planned,
                "built_case_count": built,
                "build_failure_count": max(planned - built, 0),
                "detection_rate": round(detected / built, 6) if built else 0.0,
                "mean_faulty_bpr": round(
                    _mean([record.case.faulty_bpr for record in family_records]), 6
                ),
                "mean_bpr_delta": round(
                    _mean([record.case.bpr_delta for record in family_records]), 6
                ),
                "mean_oracle_state_coverage": round(
                    _mean([record.case.oracle_state_coverage for record in family_records]), 6
                ),
                "mean_oracle_transition_coverage": round(
                    _mean([record.case.oracle_transition_coverage for record in family_records]), 6
                ),
                "mean_oracle_event_coverage": round(
                    _mean([record.case.oracle_event_coverage for record in family_records]), 6
                ),
            }
        )
    return rows


def compute_operator_by_family_rows(
    records: list[MultifamilyCaseRecord],
) -> list[dict[str, str | float | int]]:
    counts: Counter[tuple[str, str]] = Counter()
    family_totals: Counter[str] = Counter()
    for record in records:
        counts[(record.machine_type, record.case.mutation_operator)] += 1
        family_totals[record.machine_type] += 1

    rows: list[dict[str, str | float | int]] = []
    for (family, operator), count in sorted(counts.items()):
        total = family_totals[family]
        rows.append(
            {
                "machine_type": family,
                "mutation_operator": operator,
                "case_count": count,
                "fraction_within_family": round(count / total, 6) if total else 0.0,
            }
        )
    return rows


def compute_detection_by_family_rows(
    records: list[MultifamilyCaseRecord],
) -> list[dict[str, str | float | int]]:
    grouped: dict[str, list[MultifamilyCaseRecord]] = defaultdict(list)
    for record in records:
        grouped[record.machine_type].append(record)

    rows: list[dict[str, str | float | int]] = []
    for family in MULTIFAMILY_TARGET_FAMILIES:
        family_records = grouped.get(family, [])
        built = len(family_records)
        detected = sum(1 for record in family_records if record.case.bpr_delta > 0.0)
        rows.append(
            {
                "machine_type": family,
                "case_count": built,
                "detected_cases": detected,
                "detection_rate": round(detected / built, 6) if built else 0.0,
                "mean_faulty_bpr": round(
                    _mean([record.case.faulty_bpr for record in family_records]), 6
                ),
                "mean_bpr_delta": round(
                    _mean([record.case.bpr_delta for record in family_records]), 6
                ),
                "mean_oracle_state_coverage": round(
                    _mean([record.case.oracle_state_coverage for record in family_records]), 6
                ),
                "mean_oracle_transition_coverage": round(
                    _mean([record.case.oracle_transition_coverage for record in family_records]), 6
                ),
                "mean_oracle_event_coverage": round(
                    _mean([record.case.oracle_event_coverage for record in family_records]), 6
                ),
            }
        )
    return rows


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, str | float | int]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_csv(
    path: Path,
    *,
    records: list[MultifamilyCaseRecord],
    planned_by_family: dict[str, int],
    plan: DatasetPlan,
    experiment: str,
) -> None:
    cases = [record.case for record in records]
    analytics = compute_benchmark_analytics(cases)
    write_analysis_summary_csv(path, cases=cases, analytics=analytics)
    extra_rows: list[dict[str, str | float | int]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        existing = list(csv.DictReader(handle))
    for family in MULTIFAMILY_TARGET_FAMILIES:
        extra_rows.append(
            {
                "metric": f"planned_case_count_{family}",
                "value": planned_by_family.get(family, 0),
            }
        )
        built = sum(1 for record in records if record.machine_type == family)
        extra_rows.append({"metric": f"built_case_count_{family}", "value": built})
        extra_rows.append(
            {
                "metric": f"build_failure_count_{family}",
                "value": max(planned_by_family.get(family, 0) - built, 0),
            }
        )
    extra_rows.extend(
        [
            {"metric": "experiment", "value": experiment},
            {"metric": "plan_name", "value": plan.name},
            {"metric": "plan_version", "value": plan.version},
            {"metric": "plan_seed", "value": plan.seed},
            {"metric": "planned_total_cases", "value": total_planned_cases(plan)},
            {"metric": "built_total_cases", "value": len(records)},
        ]
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(existing + extra_rows)


def _write_multifamily_figures(
    figures_dir: Path,
    *,
    family_summary_rows: list[dict[str, str | float | int]],
    operator_rows: list[dict[str, str | float | int]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    families = [str(row["machine_type"]) for row in family_summary_rows]
    built_counts = [int(row["built_case_count"]) for row in family_summary_rows]
    detection_rates = [float(row["detection_rate"]) * 100.0 for row in family_summary_rows]
    mean_deltas = [float(row["mean_bpr_delta"]) for row in family_summary_rows]

    _save_bar_plot(
        figures_dir / "family_case_counts.png",
        title="Built Cases by Machine Family",
        xlabel="Machine Family",
        ylabel="Cases",
        labels=families,
        values=built_counts,
    )
    _save_bar_plot(
        figures_dir / "detection_rate_by_family.png",
        title="Mutation Detection Rate by Machine Family",
        xlabel="Machine Family",
        ylabel="Detection Rate (%)",
        labels=families,
        values=[round(value, 1) for value in detection_rates],
    )
    _save_bar_plot(
        figures_dir / "mean_bpr_delta_by_family.png",
        title="Mean BPR Delta by Machine Family",
        xlabel="Machine Family",
        ylabel="Mean BPR Delta",
        labels=families,
        values=[round(value, 4) for value in mean_deltas],
    )

    operators = sorted({str(row["mutation_operator"]) for row in operator_rows})
    if operators:
        plt = _pyplot()
        figure, axis = plt.subplots(figsize=(10, 5))
        width = 0.15
        x_positions = list(range(len(families)))
        for index, operator in enumerate(operators):
            values = []
            for family in families:
                match = next(
                    (
                        row
                        for row in operator_rows
                        if row["machine_type"] == family and row["mutation_operator"] == operator
                    ),
                    None,
                )
                values.append(int(match["case_count"]) if match else 0)
            offsets = [pos + (index - len(operators) / 2) * width + width / 2 for pos in x_positions]
            axis.bar(offsets, values, width=width, label=operator)
        axis.set_title("Mutation Operator Distribution by Machine Family")
        axis.set_xlabel("Machine Family")
        axis.set_ylabel("Cases")
        axis.set_xticks(x_positions)
        axis.set_xticklabels(families, rotation=20, ha="right")
        axis.legend(fontsize=8, ncol=2)
        figure.tight_layout()
        figure.savefig(figures_dir / "operator_distribution_by_family.png", dpi=120)
        plt.close(figure)


def _write_multifamily_tables(
    tables_dir: Path,
    *,
    family_summary_rows: list[dict[str, str | float | int]],
    detection_rows: list[dict[str, str | float | int]],
) -> None:
    def _tex_ident(name: str) -> str:
        return str(name).replace("_", "\\_")

    tables_dir.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        "% Auto-generated by analyze-multifamily-cohort",
        "\\begin{table}[t]",
        "\\caption{Multi-family external-validity pilot summary by machine family.}",
        "\\label{tab:multifamily-family-summary}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrr@{}}",
        "\\toprule",
        "Family & Built & Failures & Detection & Mean faulty BPR & Mean $\\Delta$BPR & Trans. cov. \\\\",
        "\\midrule",
    ]
    for row in family_summary_rows:
        summary_lines.append(
            f"\\texttt{{{_tex_ident(row['machine_type'])}}} & {row['built_case_count']} & {row['build_failure_count']} & "
            f"{100 * float(row['detection_rate']):.1f}\\% & "
            f"{float(row['mean_faulty_bpr']):.3f} & "
            f"{float(row['mean_bpr_delta']):.3f} & "
            f"{100 * float(row['mean_oracle_transition_coverage']):.1f}\\% \\\\"
        )
    summary_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_family_summary.tex").write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )

    detection_lines = [
        "% Auto-generated by analyze-multifamily-cohort",
        "\\begin{table}[t]",
        "\\caption{Mutation detection metrics by machine family (v0.3.0 pilot).}",
        "\\label{tab:multifamily-detection-by-family}",
        "\\small",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Family & Cases & Detected & Detection & Mean $\\Delta$BPR \\\\",
        "\\midrule",
    ]
    for row in detection_rows:
        detection_lines.append(
            f"\\texttt{{{_tex_ident(row['machine_type'])}}} & {row['case_count']} & {row['detected_cases']} & "
            f"{100 * float(row['detection_rate']):.1f}\\% & "
            f"{float(row['mean_bpr_delta']):.3f} \\\\"
        )
    detection_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_detection_by_family.tex").write_text(
        "\n".join(detection_lines),
        encoding="utf-8",
    )


def _write_multifamily_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    plan: DatasetPlan,
    plan_path: Path,
    release_label: str,
    family_summary_rows: list[dict[str, str | float | int]],
    operator_rows: list[dict[str, str | float | int]],
    records: list[MultifamilyCaseRecord],
    coverage_dir: Path | None = None,
) -> None:
    total_built = len(records)
    total_detected = sum(1 for record in records if record.case.bpr_delta > 0.0)
    lines = [
        f"# Multi-Family External-Validity Pilot ({release_label})",
        "",
        "**Status:** pilot external-validity mini-cohort for manuscript sensitivity analysis.",
        "",
        "This dataset is **not** part of the frozen Zenodo `v0.2.0-analysis` release and "
        "does **not** replace the published 1,000-case analysis cohort (which contains only "
        "`plain_fsm` cases). It is intended to inform future benchmark releases with balanced "
        "coverage across Mealy, Moore, EFSM, and timed FSM families.",
        "",
        "## Dataset",
        "",
        f"- Plan: `{plan_path}` (`{plan.name}`, version {plan.version}, seed {plan.seed})",
        f"- Built dataset: `{dataset_dir}`",
        f"- Built cases: {total_built}",
        f"- Target families: {', '.join(MULTIFAMILY_TARGET_FAMILIES)}",
        f"- Frozen v0.2.0 reference cohort: `{FROZEN_1K_COHORT_PATH}` (unchanged)",
        "",
        "## Overall metrics",
        "",
        f"- Overall detection rate: **{total_detected / total_built:.2%}**",
        f"- Mean BPR delta: **{_mean([record.case.bpr_delta for record in records]):.4f}**",
        "",
        "## Family summary",
        "",
        "| Family | Planned | Built | Failures | Detection | Mean faulty BPR | Mean BPR delta | Trans. cov. |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in family_summary_rows:
        lines.append(
            f"| `{row['machine_type']}` | {row['planned_case_count']} | {row['built_case_count']} | "
            f"{row['build_failure_count']} | {float(row['detection_rate']):.2%} | "
            f"{float(row['mean_faulty_bpr']):.4f} | {float(row['mean_bpr_delta']):.4f} | "
            f"{float(row['mean_oracle_transition_coverage']):.2%} |"
        )

    lines.extend(
        [
            "",
            "## Operator distribution by family",
            "",
            "| Family | Operator | Cases | Share within family |",
            "|---|---|---:|---:|",
        ]
    )
    for row in operator_rows:
        lines.append(
            f"| `{row['machine_type']}` | `{row['mutation_operator']}` | {row['case_count']} | "
            f"{float(row['fraction_within_family']):.2%} |"
        )

    lines.extend(
        [
            "",
            "## Figures",
            "",
            "![Family case counts](figures/family_case_counts.png)",
            "",
            "![Detection rate by family](figures/detection_rate_by_family.png)",
            "",
            "![Mean BPR delta by family](figures/mean_bpr_delta_by_family.png)",
            "",
            "![Operator distribution by family](figures/operator_distribution_by_family.png)",
            "",
            "## Artifacts",
            "",
            f"- Summary: `{output_dir / 'summary.csv'}`",
            f"- Family summary: `{output_dir / 'family_summary.csv'}`",
            f"- Operator by family: `{output_dir / 'operator_by_family.csv'}`",
            f"- Detection by family: `{output_dir / 'detection_by_family.csv'}`",
            f"- LaTeX tables: `{output_dir / 'tables'}/`",
            "",
        ]
    )
    if coverage_dir is not None:
        _append_coverage_report_section(lines, coverage_dir=coverage_dir)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _copy_paper_exports(*, output_dir: Path, paper_export_dir: Path) -> None:
    paper_export_dir.mkdir(parents=True, exist_ok=True)
    paper_tables = paper_export_dir / "tables"
    paper_figures = paper_export_dir / "figures"
    paper_tables.mkdir(parents=True, exist_ok=True)
    paper_figures.mkdir(parents=True, exist_ok=True)
    for name in (
        "summary.csv",
        "family_summary.csv",
        "operator_by_family.csv",
        "detection_by_family.csv",
        "report.md",
        "manifest.json",
    ):
        source = output_dir / name
        if source.is_file():
            shutil.copy2(source, paper_export_dir / name)
    for folder, target in ((output_dir / "tables", paper_tables), (output_dir / "figures", paper_figures)):
        if not folder.is_dir():
            continue
        for item in folder.iterdir():
            if item.is_file():
                shutil.copy2(item, target / item.name)
    coverage_dir = output_dir / "coverage"
    if coverage_dir.is_dir():
        paper_coverage = paper_export_dir / "coverage"
        paper_coverage.mkdir(parents=True, exist_ok=True)
        for path in sorted(coverage_dir.rglob("*")):
            if path.is_file():
                relative = path.relative_to(coverage_dir)
                destination = paper_coverage / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)


def analyze_multifamily_cohort(
    dataset_dir: Path,
    *,
    plan_path: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    include_taxonomy_coverage: bool = True,
    cohort_path: Path | None = None,
) -> MultifamilyAnalysisResult:
    """Analyze a built multi-family pilot dataset and export paper-ready artifacts."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise MultifamilyAnalysisError(msg)

    plan_file = plan_path or DEFAULT_PLAN_PATH
    if not plan_file.is_file():
        msg = f"Plan file not found: {plan_file}"
        raise MultifamilyAnalysisError(msg)

    plan = load_dataset_plan(plan_file)
    experiment, release_label = _resolve_release_metadata(plan)
    out = output_dir or (
        DEFAULT_PILOT_OUTPUT_DIR if plan.name == "fsmrepairbench_multifamily_pilot" else DEFAULT_OUTPUT_DIR
    )
    paper_dir = paper_export_dir or (
        DEFAULT_PILOT_PAPER_EXPORT if plan.name == "fsmrepairbench_multifamily_pilot" else DEFAULT_PAPER_EXPORT
    )
    out.mkdir(parents=True, exist_ok=True)

    records = load_multifamily_records(dataset_dir)
    planned_by_family = planned_counts_by_family(plan)
    family_summary_rows = compute_family_summary_rows(records, planned_by_family=planned_by_family)
    operator_rows = compute_operator_by_family_rows(records)
    detection_rows = compute_detection_by_family_rows(records)

    summary_path = out / "summary.csv"
    family_summary_path = out / "family_summary.csv"
    operator_by_family_path = out / "operator_by_family.csv"
    detection_by_family_path = out / "detection_by_family.csv"
    report_path = out / "report.md"
    manifest_path = out / "manifest.json"
    figures_dir = out / "figures"
    tables_dir = out / "tables"

    _write_summary_csv(
        summary_path,
        records=records,
        planned_by_family=planned_by_family,
        plan=plan,
        experiment=experiment,
    )
    _write_csv(family_summary_path, FAMILY_SUMMARY_COLUMNS, family_summary_rows)
    _write_csv(operator_by_family_path, OPERATOR_BY_FAMILY_COLUMNS, operator_rows)
    _write_csv(detection_by_family_path, DETECTION_BY_FAMILY_COLUMNS, detection_rows)
    _write_multifamily_figures(
        figures_dir,
        family_summary_rows=family_summary_rows,
        operator_rows=operator_rows,
    )
    _write_multifamily_tables(
        tables_dir,
        family_summary_rows=family_summary_rows,
        detection_rows=detection_rows,
    )

    coverage_dir: Path | None = None
    if include_taxonomy_coverage:
        from fsmrepairbench.multifamily_cohort import ANALYSIS_COHORT_TXT, load_completed_case_ids
        from fsmrepairbench.taxonomy_coverage import generate_taxonomy_coverage_report

        resolved_cohort = cohort_path
        if resolved_cohort is None:
            default_cohort = dataset_dir / ANALYSIS_COHORT_TXT
            if default_cohort.is_file():
                resolved_cohort = default_cohort
            else:
                completed_ids = load_completed_case_ids(dataset_dir)
                if completed_ids:
                    implicit_cohort = out / ".cohort_all_cases.txt"
                    implicit_cohort.write_text("\n".join(completed_ids) + "\n", encoding="utf-8")
                    resolved_cohort = implicit_cohort
        coverage_dir = out / "coverage"
        generate_taxonomy_coverage_report(
            dataset_dir,
            output_dir=coverage_dir,
            cohort_path=resolved_cohort,
        )

    _write_multifamily_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        plan=plan,
        plan_path=plan_file,
        release_label=release_label,
        family_summary_rows=family_summary_rows,
        operator_rows=operator_rows,
        records=records,
        coverage_dir=coverage_dir,
    )

    cohort_manifests: dict[str, object] = {}
    for txt_name, json_name in (
        ("analysis_cohort_multifamily.txt", "analysis_cohort_multifamily.json"),
        ("localization_cohort_multifamily.txt", "localization_cohort_multifamily.json"),
        ("coupling_campaign_multifamily.txt", "coupling_campaign_multifamily.json"),
        ("oracle_depth_ablation_multifamily.txt", "oracle_depth_ablation_multifamily.json"),
    ):
        txt_path = dataset_dir / txt_name
        json_path = dataset_dir / json_name
        if txt_path.is_file():
            entry: dict[str, object] = {
                "txt_path": str(txt_path),
                "txt_sha256": sha256_file(txt_path),
            }
            if json_path.is_file():
                entry["json_path"] = str(json_path)
                entry["json_sha256"] = sha256_file(json_path)
            cohort_manifests[txt_name] = entry

    manifest = {
        "experiment": experiment,
        "dataset_dir": str(dataset_dir),
        "plan_path": str(plan_file),
        "plan_sha256": sha256_file(plan_file),
        "output_dir": str(out),
        "paper_export_dir": str(paper_dir),
        "release_label": release_label,
        "zenodo_doi": FROZEN_V020_ZENODO_DOI,
        "replaces_v0_2_analysis": False,
        "frozen_v0_2_reference": _frozen_1k_reference(),
        "target_families": list(MULTIFAMILY_TARGET_FAMILIES),
        "planned_by_family": planned_by_family,
        "built_case_count": len(records),
        "family_summary": family_summary_rows,
        "cohort_manifests": cohort_manifests,
        "coverage_dir": str(coverage_dir) if coverage_dir is not None else None,
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    manifest["output_files"] = sorted(_list_output_files(out) + ["manifest.json"])
    manifest["output_sha256"] = _build_output_sha256_index(out)
    manifest["regeneration_commands"] = [
        "python ../paper1/scripts/build_multifamily_pilot_dataset.py",
        "python ../paper1/scripts/pin_multifamily_pilot_cohorts.py",
        "python ../paper1/scripts/generate_multifamily_pilot_outputs.py",
    ] if plan.name == "fsmrepairbench_multifamily_pilot" else [
        "python ../paper1/scripts/build_multifamily_v0_3_dataset.py",
        "python ../paper1/scripts/pin_multifamily_cohorts.py",
        "python ../paper1/scripts/generate_multifamily_v0_3_outputs.py",
    ]
    manifest["limitations_note"] = (
        "External-validity pilot on a multi-family cohort; does not replace v0.2.0-analysis "
        "headline metrics (plain_fsm / shallow-oracle slice)."
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _copy_paper_exports(output_dir=out, paper_export_dir=paper_dir)

    return MultifamilyAnalysisResult(
        dataset_dir=dataset_dir,
        output_dir=out,
        paper_export_dir=paper_dir,
        summary_path=summary_path,
        family_summary_path=family_summary_path,
        operator_by_family_path=operator_by_family_path,
        detection_by_family_path=detection_by_family_path,
        report_path=report_path,
        manifest_path=manifest_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        case_count=len(records),
        coverage_dir=coverage_dir,
    )
