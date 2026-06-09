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
            {"metric": "experiment", "value": MULTIFAMILY_EXPERIMENT},
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
            f"{row['machine_type']} & {row['built_case_count']} & {row['build_failure_count']} & "
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
            f"{row['machine_type']} & {row['case_count']} & {row['detected_cases']} & "
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
    family_summary_rows: list[dict[str, str | float | int]],
    operator_rows: list[dict[str, str | float | int]],
    records: list[MultifamilyCaseRecord],
) -> None:
    total_built = len(records)
    total_detected = sum(1 for record in records if record.case.bpr_delta > 0.0)
    lines = [
        "# Multi-Family External-Validity Pilot (v0.3.0)",
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
        f"- Plan: `{DEFAULT_PLAN_PATH}` (`{plan.name}`, version {plan.version}, seed {plan.seed})",
        f"- Built dataset: `{dataset_dir}`",
        f"- Built cases: {total_built}",
        f"- Target families: {', '.join(MULTIFAMILY_TARGET_FAMILIES)}",
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


def analyze_multifamily_cohort(
    dataset_dir: Path,
    *,
    plan_path: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
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
    out = output_dir or DEFAULT_OUTPUT_DIR
    paper_dir = paper_export_dir or DEFAULT_PAPER_EXPORT
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
    _write_multifamily_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        plan=plan,
        family_summary_rows=family_summary_rows,
        operator_rows=operator_rows,
        records=records,
    )

    manifest = {
        "experiment": MULTIFAMILY_EXPERIMENT,
        "dataset_dir": str(dataset_dir),
        "plan_path": str(plan_file),
        "plan_sha256": sha256_file(plan_file),
        "output_dir": str(out),
        "paper_export_dir": str(paper_dir),
        "release_label": "v0.3.0-external-validity-pilot",
        "replaces_v0_2_analysis": False,
        "target_families": list(MULTIFAMILY_TARGET_FAMILIES),
        "planned_by_family": planned_by_family,
        "built_case_count": len(records),
        "family_summary": family_summary_rows,
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
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
    )
