"""Leave-one-out mutation-operator ablation on the frozen 1k analysis cohort."""

from __future__ import annotations

import csv
import json
import statistics
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import _pyplot
from fsmrepairbench.baseline_repair_campaign import CAMPAIGN_LABEL, RELEASE_LABEL, ZENODO_DOI
from fsmrepairbench.freeze import get_git_commit, sha256_file

DEFAULT_COHORT_MANIFEST = "analysis_cohort_1k.txt"
DEFAULT_REPAIR_TOOL = "baseline_missing_transition"
DEFAULT_OUTPUT_DIR = Path("results/operator_ablation")

ABLATION_SUMMARY_COLUMNS: tuple[str, ...] = (
    "ablated_operator",
    "removed_cases",
    "remaining_cases",
    "detectable_cases",
    "detection_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
    "complete_repair_rate",
    "effective_repair_rate",
    "complete_repair_rate_detectable",
    "effective_repair_rate_detectable",
    "mean_repair_delta_bpr",
)

ABLATION_IMPACT_COLUMNS: tuple[str, ...] = (
    "ablated_operator",
    "removed_cases",
    "remaining_cases",
    "delta_detection_rate",
    "delta_mean_faulty_bpr",
    "delta_mean_bpr_delta",
    "delta_complete_repair_rate",
    "delta_effective_repair_rate",
    "delta_complete_repair_rate_detectable",
    "delta_effective_repair_rate_detectable",
    "delta_mean_repair_delta_bpr",
    "repair_difficulty_contribution",
)

CONTRIBUTION_COLUMNS: tuple[str, ...] = (
    "mutation_operator",
    "cases",
    "detectable_cases",
    "detection_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
    "complete_repair_rate_detectable",
    "effective_repair_rate_detectable",
    "mean_repair_delta_bpr",
    "share_of_cohort_cases",
    "share_of_detectable_cases",
)


@dataclass(frozen=True)
class AblationCaseRecord:
    """Per-case oracle and repair metrics for operator ablation."""

    case_id: str
    mutation_operator: str
    faulty_bpr: float
    bpr_delta: float
    complete_repair: bool
    effective_repair: bool
    repair_delta_bpr: float

    @property
    def detected(self) -> bool:
        return self.bpr_delta > 0.0


@dataclass(frozen=True)
class OperatorAblationExportResult:
    """Paths written by :func:`write_operator_ablation_exports`."""

    output_dir: Path
    summary_path: Path
    impact_path: Path
    contribution_path: Path
    report_path: Path
    manifest_path: Path
    figures_dir: Path
    tables_dir: Path
    paper_summary_path: Path | None = None
    paper_impact_path: Path | None = None
    paper_contribution_path: Path | None = None
    paper_report_path: Path | None = None
    paper_manifest_path: Path | None = None


class OperatorAblationError(RuntimeError):
    """Raised when operator ablation analysis cannot be completed."""


def load_cohort_case_ids(path: Path) -> list[str]:
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise OperatorAblationError(msg)
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        msg = f"CSV input not found: {path}"
        raise OperatorAblationError(msg)
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _csv_bool(value: str) -> bool:
    return value.strip().lower() == "true"


def load_ablation_case_records(
    *,
    dataset_dir: Path,
    cohort_ids: set[str],
    repair_csv: Path,
    repair_tool: str = DEFAULT_REPAIR_TOOL,
) -> list[AblationCaseRecord]:
    """Join frozen progress oracle metrics with C1 repair outcomes."""
    progress_path = dataset_dir / "progress.csv"
    if not progress_path.is_file():
        msg = f"Progress CSV not found: {progress_path}"
        raise OperatorAblationError(msg)

    repair_by_case: dict[str, dict[str, str]] = {}
    for row in _read_csv(repair_csv):
        if row.get("tool_id") != repair_tool:
            continue
        repair_by_case[str(row["case_id"])] = row

    records: list[AblationCaseRecord] = []
    for row in _read_csv(progress_path):
        if row.get("status", "completed") != "completed":
            continue
        case_id = str(row["case_id"])
        if case_id not in cohort_ids:
            continue
        repair = repair_by_case.get(case_id)
        if repair is None:
            msg = f"Missing repair row for {case_id} ({repair_tool})"
            raise OperatorAblationError(msg)
        records.append(
            AblationCaseRecord(
                case_id=case_id,
                mutation_operator=str(row["mutation_operator"]),
                faulty_bpr=float(row["faulty_bpr"]),
                bpr_delta=float(row["bpr_delta"]),
                complete_repair=_csv_bool(repair["complete_repair"]),
                effective_repair=_csv_bool(repair["effective_repair"]),
                repair_delta_bpr=float(repair["delta_bpr"]),
            )
        )
    if not records:
        msg = f"No ablation records loaded for cohort under {dataset_dir}"
        raise OperatorAblationError(msg)
    return records


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _rate(flags: list[bool]) -> float:
    return sum(1 for flag in flags if flag) / len(flags) if flags else 0.0


def compute_cohort_metrics(records: Sequence[AblationCaseRecord]) -> dict[str, float | int]:
    detectable = [record for record in records if record.detected]
    return {
        "remaining_cases": len(records),
        "detectable_cases": len(detectable),
        "detection_rate": round(_rate([record.detected for record in records]), 6),
        "mean_faulty_bpr": round(_mean([record.faulty_bpr for record in records]), 6),
        "mean_bpr_delta": round(_mean([record.bpr_delta for record in records]), 6),
        "complete_repair_rate": round(_rate([record.complete_repair for record in records]), 6),
        "effective_repair_rate": round(_rate([record.effective_repair for record in records]), 6),
        "complete_repair_rate_detectable": round(
            _rate([record.complete_repair for record in detectable]),
            6,
        ),
        "effective_repair_rate_detectable": round(
            _rate([record.effective_repair for record in detectable]),
            6,
        ),
        "mean_repair_delta_bpr": round(_mean([record.repair_delta_bpr for record in records]), 6),
    }


def compute_operator_contribution_rows(
    records: list[AblationCaseRecord],
) -> list[dict[str, float | int | str]]:
    total_cases = len(records)
    total_detectable = sum(1 for record in records if record.detected)
    grouped: dict[str, list[AblationCaseRecord]] = {}
    for record in records:
        grouped.setdefault(record.mutation_operator, []).append(record)

    rows: list[dict[str, float | int | str]] = []
    for operator in sorted(grouped):
        subset = grouped[operator]
        metrics = compute_cohort_metrics(subset)
        rows.append(
            {
                "mutation_operator": operator,
                "cases": len(subset),
                "detectable_cases": int(metrics["detectable_cases"]),
                "detection_rate": float(metrics["detection_rate"]),
                "mean_faulty_bpr": float(metrics["mean_faulty_bpr"]),
                "mean_bpr_delta": float(metrics["mean_bpr_delta"]),
                "complete_repair_rate_detectable": float(metrics["complete_repair_rate_detectable"]),
                "effective_repair_rate_detectable": float(metrics["effective_repair_rate_detectable"]),
                "mean_repair_delta_bpr": float(metrics["mean_repair_delta_bpr"]),
                "share_of_cohort_cases": round(len(subset) / total_cases, 6),
                "share_of_detectable_cases": round(
                    int(metrics["detectable_cases"]) / total_detectable,
                    6,
                )
                if total_detectable
                else 0.0,
            }
        )
    return rows


def compute_operator_ablation_rows(
    records: list[AblationCaseRecord],
) -> tuple[dict[str, float | int], list[dict[str, float | int | str]], list[dict[str, float | int | str]]]:
    """Compute full-cohort baseline and leave-one-out ablation metrics."""
    baseline = compute_cohort_metrics(records)
    operator_counts = Counter(record.mutation_operator for record in records)
    summary_rows: list[dict[str, float | int | str]] = [
        {
            "ablated_operator": "full_cohort",
            "removed_cases": 0,
            **baseline,
        }
    ]
    impact_rows: list[dict[str, float | int | str]] = []

    for operator in sorted(operator_counts):
        removed = operator_counts[operator]
        subset = [record for record in records if record.mutation_operator != operator]
        metrics = compute_cohort_metrics(subset)
        summary = {
            "ablated_operator": operator,
            "removed_cases": removed,
            **metrics,
        }
        summary_rows.append(summary)

        impact = {
            "ablated_operator": operator,
            "removed_cases": removed,
            "remaining_cases": int(metrics["remaining_cases"]),
            "delta_detection_rate": round(float(metrics["detection_rate"]) - float(baseline["detection_rate"]), 6),
            "delta_mean_faulty_bpr": round(
                float(metrics["mean_faulty_bpr"]) - float(baseline["mean_faulty_bpr"]),
                6,
            ),
            "delta_mean_bpr_delta": round(
                float(metrics["mean_bpr_delta"]) - float(baseline["mean_bpr_delta"]),
                6,
            ),
            "delta_complete_repair_rate": round(
                float(metrics["complete_repair_rate"]) - float(baseline["complete_repair_rate"]),
                6,
            ),
            "delta_effective_repair_rate": round(
                float(metrics["effective_repair_rate"]) - float(baseline["effective_repair_rate"]),
                6,
            ),
            "delta_complete_repair_rate_detectable": round(
                float(metrics["complete_repair_rate_detectable"])
                - float(baseline["complete_repair_rate_detectable"]),
                6,
            ),
            "delta_effective_repair_rate_detectable": round(
                float(metrics["effective_repair_rate_detectable"])
                - float(baseline["effective_repair_rate_detectable"]),
                6,
            ),
            "delta_mean_repair_delta_bpr": round(
                float(metrics["mean_repair_delta_bpr"]) - float(baseline["mean_repair_delta_bpr"]),
                6,
            ),
        }
        removed_subset = [record for record in records if record.mutation_operator == operator]
        removed_metrics = compute_cohort_metrics(removed_subset)
        repair_gap = 1.0 - float(removed_metrics["complete_repair_rate_detectable"])
        detect_gap = 1.0 - float(removed_metrics["detection_rate"])
        impact["repair_difficulty_contribution"] = round(
            0.5 * detect_gap + 0.5 * repair_gap,
            6,
        )
        impact_rows.append(impact)

    return baseline, summary_rows, impact_rows


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _write_ablation_impact_tex(path: Path, impact_rows: list[dict[str, Any]], baseline: dict[str, float | int]) -> None:
    ordered = sorted(
        impact_rows,
        key=lambda row: (-float(row["repair_difficulty_contribution"]), str(row["ablated_operator"])),
    )
    lines = [
        "% Auto-generated by fsmrepairbench.mutation_operator_ablation",
        "\\begin{table}[t]",
        "\\caption{Leave-one-out mutation-operator ablation on the frozen 1{,}000-case cohort. "
        "Each row removes one operator family and recomputes cohort-wide detection, BPR, and "
        "\\texttt{missing-transition} repair metrics on the remaining cases. "
        f"Full-cohort baseline: detection {_pct(float(baseline['detection_rate']))}, "
        f"mean faulty BPR {float(baseline['mean_faulty_bpr']):.3f}, "
        f"detectable-only complete repair {_pct(float(baseline['complete_repair_rate_detectable']))}. "
        "Positive $\\Delta$detection indicates that removing oracle-invisible families raises the "
        "observable detection rate; repair-difficulty contribution ranks operator removal impact.}",
        "\\label{tab:operator-ablation-impact}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lrrrrrrr@{}}",
        "\\toprule",
        "Removed operator & Rem. & $\\Delta$Detect & $\\Delta$BPR & $\\Delta$Complete & $\\Delta$Effective & $\\Delta$Rep.$\\Delta$BPR & Contrib. \\\\",
        "\\midrule",
    ]
    for row in ordered[:12]:
        lines.append(
            f"\\texttt{{{_tex_escape(str(row['ablated_operator']))}}} & "
            f"{row['remaining_cases']} & "
            f"{100.0 * float(row['delta_detection_rate']):+.1f}pp & "
            f"{float(row['delta_mean_bpr_delta']):+.3f} & "
            f"{100.0 * float(row['delta_complete_repair_rate_detectable']):+.1f}pp & "
            f"{100.0 * float(row['delta_effective_repair_rate_detectable']):+.1f}pp & "
            f"{float(row['delta_mean_repair_delta_bpr']):+.3f} & "
            f"{float(row['repair_difficulty_contribution']):.2f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_operator_contribution_tex(
    path: Path,
    contribution_rows: list[dict[str, Any]],
) -> None:
    ordered = sorted(
        contribution_rows,
        key=lambda row: (-float(row["detection_rate"]), str(row["mutation_operator"])),
    )
    lines = [
        "% Auto-generated by fsmrepairbench.mutation_operator_ablation",
        "\\begin{table}[t]",
        "\\caption{Per-operator contribution to cohort repair difficulty "
        "(standalone operator slices before ablation). Detectable-only repair uses the "
        "\\texttt{missing-transition} baseline on oracle-detectable faults.}",
        "\\label{tab:operator-ablation-contribution}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrr@{}}",
        "\\toprule",
        "Operator & Cases & Detectable & Detection & Mean $\\Delta$BPR & Complete & Effective \\\\",
        "\\midrule",
    ]
    for row in ordered:
        lines.append(
            f"\\texttt{{{_tex_escape(str(row['mutation_operator']))}}} & "
            f"{row['cases']} & {row['detectable_cases']} & "
            f"{_pct(float(row['detection_rate']))} & "
            f"{float(row['mean_bpr_delta']):.3f} & "
            f"{_pct(float(row['complete_repair_rate_detectable']))} & "
            f"{_pct(float(row['effective_repair_rate_detectable']))} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _save_horizontal_bar_plot(
    path: Path,
    *,
    title: str,
    xlabel: str,
    ylabel: str,
    labels: list[str],
    values: list[float],
) -> None:
    plt = _pyplot()
    figure, axis = plt.subplots(figsize=(9, max(4.0, 0.28 * len(labels) + 1.5)))
    y_positions = list(range(len(labels)))
    axis.barh(y_positions, values, color="#4472C4")
    axis.set_yticks(y_positions)
    axis.set_yticklabels(labels, fontsize=8)
    axis.set_title(title)
    axis.set_xlabel(xlabel)
    axis.set_ylabel(ylabel)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120)
    plt.close(figure)


def _write_ablation_figures(
    figures_dir: Path,
    *,
    impact_rows: list[dict[str, Any]],
    contribution_rows: list[dict[str, Any]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    ordered_impact = sorted(
        impact_rows,
        key=lambda row: float(row["repair_difficulty_contribution"]),
        reverse=True,
    )
    labels = [str(row["ablated_operator"]) for row in ordered_impact]
    _save_horizontal_bar_plot(
        figures_dir / "delta_detection_by_ablated_operator.png",
        title="Detection Rate Change When Removing One Operator",
        xlabel="Delta Detection Rate (pp)",
        ylabel="Removed Operator",
        labels=labels,
        values=[round(100.0 * float(row["delta_detection_rate"]), 2) for row in ordered_impact],
    )
    _save_horizontal_bar_plot(
        figures_dir / "delta_repair_detectable_by_ablated_operator.png",
        title="Detectable-Only Complete Repair Change",
        xlabel="Delta Complete Repair (pp)",
        ylabel="Removed Operator",
        labels=labels,
        values=[
            round(100.0 * float(row["delta_complete_repair_rate_detectable"]), 2)
            for row in ordered_impact
        ],
    )
    contribution_ordered = sorted(
        contribution_rows,
        key=lambda row: (-float(row["share_of_detectable_cases"]), str(row["mutation_operator"])),
    )
    _save_horizontal_bar_plot(
        figures_dir / "repair_difficulty_contribution.png",
        title="Operator Contribution to Repair Difficulty",
        xlabel="Contribution Score",
        ylabel="Mutation Operator",
        labels=[str(row["mutation_operator"]) for row in contribution_ordered],
        values=[
            round(
                0.5 * (1.0 - float(row["detection_rate"]))
                + 0.5 * (1.0 - float(row["complete_repair_rate_detectable"])),
                3,
            )
            for row in contribution_ordered
        ],
    )

    import matplotlib.pyplot as plt
    import numpy as np

    metric_keys = (
        ("delta_detection_rate", "Delta detection"),
        ("delta_mean_bpr_delta", "Delta mean BPR"),
        ("delta_complete_repair_rate_detectable", "Delta complete repair"),
        ("delta_effective_repair_rate_detectable", "Delta effective repair"),
    )
    matrix = np.array(
        [
            [float(row[key]) * (100.0 if "rate" in key else 1.0) for key, _label in metric_keys]
            for row in ordered_impact
        ]
    )
    fig_height = max(6.0, 0.28 * len(labels) + 1.5)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    im = ax.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-15.0, vmax=15.0)
    ax.set_xticks(range(len(metric_keys)))
    ax.set_xticklabels([label for _key, label in metric_keys], rotation=20, ha="right")
    ax.set_yticks(range(len(labels)))
    ax.set_yticklabels(labels, fontsize=8)
    for row_index in range(matrix.shape[0]):
        for col_index in range(matrix.shape[1]):
            ax.text(
                col_index,
                row_index,
                f"{matrix[row_index, col_index]:+.1f}",
                ha="center",
                va="center",
                fontsize=7,
            )
    fig.colorbar(im, ax=ax, shrink=0.85, label="Impact when operator removed")
    ax.set_title("Leave-one-out operator ablation impact heatmap")
    fig.subplots_adjust(left=0.24, bottom=0.12, right=0.92, top=0.94)
    fig.savefig(figures_dir / "ablation_impact_heatmap.png", dpi=150)
    plt.close(fig)


def _write_ablation_report(
    path: Path,
    *,
    dataset_dir: Path,
    cohort_path: Path,
    baseline: dict[str, float | int],
    impact_rows: list[dict[str, Any]],
    contribution_rows: list[dict[str, Any]],
    repair_tool: str,
) -> None:
    top_impact = sorted(
        impact_rows,
        key=lambda row: float(row["repair_difficulty_contribution"]),
        reverse=True,
    )[:5]
    invisible = [
        row
        for row in contribution_rows
        if float(row["detection_rate"]) == 0.0
    ]
    lines = [
        "# Mutation Operator Ablation (Leave-One-Out)",
        "",
        "Selective removal of individual mutation operators from the frozen 1k analysis cohort.",
        "",
        "## Experimental design",
        "",
        f"- **Dataset:** `{dataset_dir}`",
        f"- **Cohort:** `{cohort_path.name}` ({baseline['remaining_cases']} cases)",
        f"- **Repair engine:** `{repair_tool}`",
        f"- **Release:** `{RELEASE_LABEL}` (DOI [{ZENODO_DOI}](https://doi.org/{ZENODO_DOI}))",
        "",
        "## Full-cohort baseline",
        "",
        f"- Detection rate: **{100.0 * float(baseline['detection_rate']):.1f}%**",
        f"- Mean faulty BPR: **{float(baseline['mean_faulty_bpr']):.4f}**",
        f"- Mean BPR delta: **{float(baseline['mean_bpr_delta']):.4f}**",
        f"- Complete repair (detectable-only): **{100.0 * float(baseline['complete_repair_rate_detectable']):.1f}%**",
        f"- Effective repair (detectable-only): **{100.0 * float(baseline['effective_repair_rate_detectable']):.1f}%**",
        "",
        "## Top removal impacts",
        "",
        "| Removed operator | Delta detection (pp) | Delta complete repair (pp) | Contribution |",
        "|---|---:|---:|---:|",
    ]
    for row in top_impact:
        lines.append(
            f"| `{row['ablated_operator']}` | "
            f"{100.0 * float(row['delta_detection_rate']):+.1f} | "
            f"{100.0 * float(row['delta_complete_repair_rate_detectable']):+.1f} | "
            f"{float(row['repair_difficulty_contribution']):.2f} |"
        )
    lines.extend(
        [
            "",
            f"Oracle-invisible operator families ({len(invisible)}): "
            + ", ".join(f"`{row['mutation_operator']}`" for row in invisible[:8])
            + (" ..." if len(invisible) > 8 else ""),
            "",
            "## Figures",
            "",
            "![Delta detection by ablated operator](figures/delta_detection_by_ablated_operator.png)",
            "",
            "![Delta detectable complete repair](figures/delta_repair_detectable_by_ablated_operator.png)",
            "",
            "![Ablation impact heatmap](figures/ablation_impact_heatmap.png)",
            "",
            "![Repair difficulty contribution](figures/repair_difficulty_contribution.png)",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_operator_ablation_exports(
    *,
    dataset_dir: Path,
    cohort_path: Path,
    repair_csv: Path,
    out_dir: Path,
    paper_export_dir: Path | None = None,
    repair_tool: str = DEFAULT_REPAIR_TOOL,
) -> OperatorAblationExportResult:
    """Write leave-one-out operator ablation CSVs, figures, tables, and manifest."""
    cohort_ids = set(load_cohort_case_ids(cohort_path))
    records = load_ablation_case_records(
        dataset_dir=dataset_dir,
        cohort_ids=cohort_ids,
        repair_csv=repair_csv,
        repair_tool=repair_tool,
    )
    baseline, summary_rows, impact_rows = compute_operator_ablation_rows(records)
    contribution_rows = compute_operator_contribution_rows(records)

    out_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = out_dir / "figures"
    tables_dir = out_dir / "tables"
    summary_path = out_dir / "operator_ablation_summary.csv"
    impact_path = out_dir / "operator_ablation_impact.csv"
    contribution_path = out_dir / "operator_contribution.csv"
    report_path = out_dir / "report.md"
    manifest_path = out_dir / "manifest.json"

    _write_csv(summary_path, ABLATION_SUMMARY_COLUMNS, summary_rows)
    _write_csv(impact_path, ABLATION_IMPACT_COLUMNS, impact_rows)
    _write_csv(contribution_path, CONTRIBUTION_COLUMNS, contribution_rows)
    _write_ablation_impact_tex(tables_dir / "table_ablation_impact.tex", impact_rows, baseline)
    _write_operator_contribution_tex(tables_dir / "table_operator_contribution.tex", contribution_rows)
    _write_ablation_figures(
        figures_dir,
        impact_rows=impact_rows,
        contribution_rows=contribution_rows,
    )
    _write_ablation_report(
        report_path,
        dataset_dir=dataset_dir,
        cohort_path=cohort_path,
        baseline=baseline,
        impact_rows=impact_rows,
        contribution_rows=contribution_rows,
        repair_tool=repair_tool,
    )

    manifest = {
        "experiment": "mutation-operator-ablation-1k",
        "release_label": RELEASE_LABEL,
        "campaign_label": CAMPAIGN_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "dataset_dir": str(dataset_dir),
        "cohort_path": str(cohort_path),
        "cohort_sha256": sha256_file(cohort_path),
        "repair_csv": str(repair_csv),
        "repair_tool": repair_tool,
        "baseline": baseline,
        "operator_count": len(contribution_rows),
        "output_files": sorted(
            path.relative_to(out_dir).as_posix()
            for path in out_dir.rglob("*")
            if path.is_file()
        ),
        "regeneration_commands": [
            "python ../paper1/scripts/generate_operator_ablation_outputs.py",
        ],
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_summary_path = paper_impact_path = paper_contribution_path = None
    paper_report_path = paper_manifest_path = None
    if paper_export_dir is not None and paper_export_dir.resolve() != out_dir.resolve():
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            summary_path.name,
            impact_path.name,
            contribution_path.name,
            report_path.name,
            manifest_path.name,
        ):
            target = paper_export_dir / name
            target.write_text((out_dir / name).read_text(encoding="utf-8"), encoding="utf-8")
        paper_summary_path = paper_export_dir / summary_path.name
        paper_impact_path = paper_export_dir / impact_path.name
        paper_contribution_path = paper_export_dir / contribution_path.name
        paper_report_path = paper_export_dir / report_path.name
        paper_manifest_path = paper_export_dir / manifest_path.name
        for folder in ("figures", "tables"):
            source = out_dir / folder
            target = paper_export_dir / folder
            target.mkdir(parents=True, exist_ok=True)
            for item in source.iterdir():
                if item.is_file():
                    target_item = target / item.name
                    if item.suffix == ".png":
                        target_item.write_bytes(item.read_bytes())
                    else:
                        target_item.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")

    return OperatorAblationExportResult(
        output_dir=out_dir,
        summary_path=summary_path,
        impact_path=impact_path,
        contribution_path=contribution_path,
        report_path=report_path,
        manifest_path=manifest_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        paper_summary_path=paper_summary_path,
        paper_impact_path=paper_impact_path,
        paper_contribution_path=paper_contribution_path,
        paper_report_path=paper_report_path,
        paper_manifest_path=paper_manifest_path,
    )
