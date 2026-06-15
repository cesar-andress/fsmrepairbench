"""Operator-level localization metrics, rank-distribution figures, and audit manifest exports."""

from __future__ import annotations

import csv
import json
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from fsmrepairbench.localization_localizability_audit import LocalizabilityAuditRow

from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.localization_alternative_gt import (
    AlternativeGtEvaluation,
    enrich_case_with_alternative_gt,
)
from fsmrepairbench.localization_campaign import (
    CAMPAIGN_LABEL,
    LOCALIZATION_METHOD,
    RANK_BUCKETS,
    RELEASE_LABEL,
    ZENODO_DOI,
    CaseLocalizationResult,
    rank_bucket,
    rank_distribution,
)

OperatorPartition = Literal[
    "all_cohort",
    "all_detectable",
    "transition_localizable_gt",
    "alternative_gt",
]
GtMode = Literal["primary", "alternative"]

OPERATOR_METRICS_COLUMNS: tuple[str, ...] = (
    "mutation_operator",
    "partition",
    "gt_mode",
    "cohort_cases",
    "detectable_cases",
    "skipped_cases",
    "evaluated_cases",
    "not_ranked_count",
    "top1_hits",
    "top3_hits",
    "top5_hits",
    "top1_hit_rate",
    "top3_hit_rate",
    "top5_hit_rate",
    "mrr",
)

RANK_DISTRIBUTION_OPERATOR_COLUMNS: tuple[str, ...] = (
    "mutation_operator",
    "partition",
    "rank_bucket",
    "count",
    "fraction",
)


@dataclass(frozen=True)
class OperatorMetricsExportResult:
    operator_metrics_csv: Path
    rank_distribution_operator_csv: Path
    figures_dir: Path
    manifest_path: Path


def _case_metrics_primary(case: CaseLocalizationResult) -> tuple[int | None, float, bool, bool, bool]:
    return (
        case.rank_of_target,
        case.reciprocal_rank,
        case.top1_hit,
        case.top3_hit,
        case.top5_hit,
    )


def _case_metrics_alternative(
    alt: AlternativeGtEvaluation | None,
    case: CaseLocalizationResult,
) -> tuple[int | None, float, bool, bool, bool]:
    if alt is None:
        return _case_metrics_primary(case)
    return (
        alt.rank_of_target,
        alt.reciprocal_rank,
        alt.top1_hit,
        alt.top3_hit,
        alt.top5_hit,
    )


def _aggregate_operator_metrics(
    rows: list[tuple[CaseLocalizationResult, AlternativeGtEvaluation | None]],
    *,
    gt_mode: GtMode,
) -> dict[str, float | int]:
    if not rows:
        return {
            "evaluated_cases": 0,
            "not_ranked_count": 0,
            "top1_hits": 0,
            "top3_hits": 0,
            "top5_hits": 0,
            "top1_hit_rate": 0.0,
            "top3_hit_rate": 0.0,
            "top5_hit_rate": 0.0,
            "mrr": 0.0,
        }

    metrics_rows: list[tuple[int | None, float, bool, bool, bool]] = []
    for case, alt in rows:
        if gt_mode == "alternative":
            metrics_rows.append(_case_metrics_alternative(alt, case))
        else:
            metrics_rows.append(_case_metrics_primary(case))

    evaluated = len(metrics_rows)
    not_ranked = sum(1 for rank, *_rest in metrics_rows if rank is None)
    top1_hits = sum(1 for _rank, _rec, top1, _top3, _top5 in metrics_rows if top1)
    top3_hits = sum(1 for _rank, _rec, _top1, top3, _top5 in metrics_rows if top3)
    top5_hits = sum(1 for _rank, _rec, _top1, _top3, top5 in metrics_rows if top5)
    mrr = round(sum(rec for _rank, rec, *_hits in metrics_rows) / evaluated, 6)

    return {
        "evaluated_cases": evaluated,
        "not_ranked_count": not_ranked,
        "top1_hits": top1_hits,
        "top3_hits": top3_hits,
        "top5_hits": top5_hits,
        "top1_hit_rate": round(top1_hits / evaluated, 6),
        "top3_hit_rate": round(top3_hits / evaluated, 6),
        "top5_hit_rate": round(top5_hits / evaluated, 6),
        "mrr": mrr,
    }


def _partition_case_rows(
    audit_rows: list[LocalizabilityAuditRow],
    alternative_by_case: dict[str, AlternativeGtEvaluation],
    *,
    partition: OperatorPartition,
    operator: str,
) -> list[tuple[CaseLocalizationResult, AlternativeGtEvaluation | None]]:
    operator_rows = [row for row in audit_rows if row.case.mutation_operator == operator]
    selected: list[LocalizabilityAuditRow] = []
    for row in operator_rows:
        if partition == "all_cohort":
            selected.append(row)
        elif partition == "all_detectable" and row.case.localized:
            selected.append(row)
        elif partition == "transition_localizable_gt" and row.case.localized and row.ground_truth_localizable:
            selected.append(row)
        elif partition == "alternative_gt" and row.case.localized:
            selected.append(row)

    result: list[tuple[CaseLocalizationResult, AlternativeGtEvaluation | None]] = []
    for row in selected:
        if partition == "all_cohort":
            continue
        if not row.case.localized:
            continue
        alt = alternative_by_case.get(row.case.case_id)
        result.append((row.case, alt))
    return result


def build_operator_metrics_rows(
    audit_rows: list[LocalizabilityAuditRow],
    alternative_by_case: dict[str, AlternativeGtEvaluation],
) -> list[dict[str, str | int | float]]:
    """Build per-operator metrics for all mutation operators in the cohort."""
    operators = sorted({row.case.mutation_operator for row in audit_rows if row.case.mutation_operator})
    rows: list[dict[str, str | int | float]] = []

    for operator in operators:
        operator_audit = [row for row in audit_rows if row.case.mutation_operator == operator]
        cohort_cases = len(operator_audit)
        detectable_cases = sum(1 for row in operator_audit if row.case.localized)
        skipped_cases = cohort_cases - detectable_cases

        for partition in (
            "all_cohort",
            "all_detectable",
            "transition_localizable_gt",
            "alternative_gt",
        ):
            gt_modes: tuple[GtMode, ...] = ("primary",)
            if partition == "alternative_gt":
                gt_modes = ("alternative",)
            elif partition == "all_detectable":
                gt_modes = ("primary", "alternative")

            for gt_mode in gt_modes:
                case_rows = _partition_case_rows(
                    audit_rows,
                    alternative_by_case,
                    partition=partition,
                    operator=operator,
                )
                metrics = _aggregate_operator_metrics(case_rows, gt_mode=gt_mode)
                rows.append(
                    {
                        "mutation_operator": operator,
                        "partition": partition,
                        "gt_mode": gt_mode,
                        "cohort_cases": cohort_cases,
                        "detectable_cases": detectable_cases,
                        "skipped_cases": skipped_cases,
                        **metrics,
                    }
                )
    return rows


def build_rank_distribution_operator_rows(
    audit_rows: list[LocalizabilityAuditRow],
    alternative_by_case: dict[str, AlternativeGtEvaluation],
) -> list[dict[str, str | int | float]]:
    """Rank bucket counts by operator for detectable and alternative-GT partitions."""
    rows: list[dict[str, str | int | float]] = []
    operators = sorted({row.case.mutation_operator for row in audit_rows if row.case.mutation_operator})

    for operator in operators:
        for partition in ("all_detectable", "alternative_gt"):
            case_rows = _partition_case_rows(
                audit_rows,
                alternative_by_case,
                partition=partition,
                operator=operator,
            )
            if not case_rows:
                continue

            bucket_counts: Counter[str] = Counter()
            for case, alt in case_rows:
                if partition == "alternative_gt" and alt is not None:
                    rank = alt.rank_of_target
                else:
                    rank = case.rank_of_target
                bucket_counts[rank_bucket(rank)] += 1

            total = sum(bucket_counts.values()) or 1
            for bucket in RANK_BUCKETS:
                count = bucket_counts.get(bucket, 0)
                if count == 0 and bucket != "not_ranked":
                    continue
                rows.append(
                    {
                        "mutation_operator": operator,
                        "partition": partition,
                        "rank_bucket": bucket,
                        "count": count,
                        "fraction": round(count / total, 6),
                    }
                )
    return rows


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str | int | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def write_operator_metrics_tex(
    path: Path,
    operator_rows: list[dict[str, str | int | float]],
) -> None:
    """Write LaTeX table with top-k, MRR, and not_ranked per operator (all detectable)."""
    primary_rows = [
        row
        for row in operator_rows
        if row["partition"] == "all_detectable" and row["gt_mode"] == "primary"
    ]
    alt_rows = {
        str(row["mutation_operator"]): row
        for row in operator_rows
        if row["partition"] == "all_detectable" and row["gt_mode"] == "alternative"
    }

    lines = [
        "% Auto-generated from fsmrepairbench.localization_operator_exports",
        "\\begin{table}[t]",
        "\\caption{Transition-level Ochiai localization by mutation operator "
        "(\\textbf{all detectable} partition; $n=495$; "
        "\\textbf{505/1{,}000} oracle-saturated excluded). "
        "Primary GT uses \\texttt{changed\\_transition\\_id}; "
        "Alt.~GT uses deleted-transition proxies and initial-state outgoing transitions. "
        "Includes operators with non-rankable primary ground truth.}",
        "\\label{tab:localization-by-operator-metrics}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrrrr@{}}",
        "\\toprule",
        "Operator & Cohort & Detect. & Not ranked & Top-1 & Top-3 & Top-5 & MRR & Alt Top-5 \\\\",
        "\\midrule",
    ]
    for row in primary_rows:
        operator = str(row["mutation_operator"]).replace("_", "\\_")
        alt = alt_rows.get(str(row["mutation_operator"]))
        alt_top5 = _pct(float(alt["top5_hit_rate"])) if alt and int(alt["evaluated_cases"]) > 0 else "---"
        if int(row["detectable_cases"]) == 0:
            lines.append(
                f"{operator} & {row['cohort_cases']} & 0 & --- & --- & --- & --- & --- & --- \\\\"
            )
            continue
        lines.append(
            f"{operator} & {row['cohort_cases']} & {row['detectable_cases']} & "
            f"{row['not_ranked_count']} & {_pct(float(row['top1_hit_rate']))} & "
            f"{_pct(float(row['top3_hit_rate']))} & {_pct(float(row['top5_hit_rate']))} & "
            f"{float(row['mrr']):.3f} & {alt_top5} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_rank_distribution_figures(
    figures_dir: Path,
    *,
    audit_rows: list[LocalizabilityAuditRow],
    alternative_by_case: dict[str, AlternativeGtEvaluation],
    cohort_distribution: list[dict[str, str | int | float]],
) -> None:
    """Write cohort-wide and per-operator rank distribution figures."""
    import matplotlib.pyplot as plt
    import numpy as np

    from fsmrepairbench.analytics import _save_bar_plot

    figures_dir.mkdir(parents=True, exist_ok=True)

    cohort_labels = [str(row["bucket"]) for row in cohort_distribution if int(row["count"]) > 0]
    cohort_counts = [int(row["count"]) for row in cohort_distribution if int(row["count"]) > 0]
    if cohort_labels:
        _save_bar_plot(
            figures_dir / "rank_distribution_cohort.png",
            title="Transition Rank Distribution (All Detectable Cases)",
            xlabel="Rank Bucket",
            ylabel="Cases",
            labels=cohort_labels,
            values=cohort_counts,
        )
        _save_bar_plot(
            figures_dir / "rank_distribution.png",
            title="Transition Rank Distribution (Primary GT, Detectable)",
            xlabel="Rank Bucket",
            ylabel="Cases",
            labels=cohort_labels,
            values=cohort_counts,
        )

    operator_rows = build_rank_distribution_operator_rows(audit_rows, alternative_by_case)
    operators = sorted({str(row["mutation_operator"]) for row in operator_rows})
    buckets = list(RANK_BUCKETS)
    bucket_index = {bucket: idx for idx, bucket in enumerate(buckets)}

    fig, axes = plt.subplots(1, 2, figsize=(14, 5), sharey=True)
    titles = ["Primary GT (detectable)", "Alternative GT (detectable)"]
    partitions = ["all_detectable", "alternative_gt"]
    for axis, title, partition in zip(axes, titles, partitions, strict=True):
        matrix = np.zeros((len(operators), len(buckets)))
        for row in operator_rows:
            if row["partition"] != partition:
                continue
            op_idx = operators.index(str(row["mutation_operator"]))
            bucket = str(row["rank_bucket"])
            if bucket in bucket_index:
                matrix[op_idx, bucket_index[bucket]] = int(row["count"])
        im = axis.imshow(matrix, aspect="auto", cmap="Blues")
        axis.set_title(title)
        axis.set_xticks(range(len(buckets)))
        axis.set_xticklabels(buckets, rotation=45, ha="right")
        axis.set_yticks(range(len(operators)))
        axis.set_yticklabels(operators)
        fig.colorbar(im, ax=axis, shrink=0.85, label="Cases")
    fig.suptitle("Rank Bucket Counts by Mutation Operator")
    fig.tight_layout()
    fig.savefig(figures_dir / "rank_distribution_by_operator.png", dpi=150)
    plt.close(fig)

    fig, axis = plt.subplots(figsize=(12, 5))
    x = np.arange(len(operators))
    bottom = np.zeros(len(operators))
    colors = plt.cm.tab20(np.linspace(0, 1, len(buckets)))
    for bucket_idx, bucket in enumerate(buckets):
        values = []
        for operator in operators:
            match = next(
                (
                    int(row["count"])
                    for row in operator_rows
                    if row["partition"] == "all_detectable"
                    and str(row["mutation_operator"]) == operator
                    and str(row["rank_bucket"]) == bucket
                ),
                0,
            )
            values.append(match)
        axis.bar(x, values, width=0.8, bottom=bottom, label=bucket, color=colors[bucket_idx])
        bottom += np.array(values, dtype=float)
    axis.set_xticks(x)
    axis.set_xticklabels(operators, rotation=45, ha="right")
    axis.set_ylabel("Cases")
    axis.set_title("Primary GT Rank Buckets by Operator (Stacked)")
    axis.legend(title="Bucket", bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
    fig.tight_layout()
    fig.savefig(figures_dir / "rank_distribution_by_operator_stacked.png", dpi=150)
    plt.close(fig)


def _relative_repo_path(path: Path, *, repo_root: Path | None = None) -> str:
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def build_audit_manifest(
    *,
    dataset_dir: Path,
    output_dir: Path,
    cohort_path: Path,
    all_detectable_metrics: dict[str, float | int],
    localizable_metrics: dict[str, float | int],
    repo_root: Path | None = None,
) -> dict[str, object]:
    """Build RQ3 manifest after localization campaign + localizability audit."""
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    output_files: list[str] = []
    for path in sorted(output_dir.rglob("*")):
        if path.is_file():
            output_files.append(path.relative_to(output_dir).as_posix())
    if "manifest.json" not in output_files:
        output_files.append("manifest.json")

    return {
        "release_label": RELEASE_LABEL,
        "campaign_label": CAMPAIGN_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "experiment": CAMPAIGN_LABEL,
        "dataset_dir": _relative_repo_path(dataset_dir, repo_root=repo_root),
        "output_dir": _relative_repo_path(output_dir, repo_root=repo_root),
        "cohort_path": _relative_repo_path(cohort_path, repo_root=repo_root),
        "cohort_sha256": sha256_file(cohort_path) if cohort_path.is_file() else "",
        "method": LOCALIZATION_METHOD,
        "element_type": "transition",
        "ground_truth": "changed_transition_id",
        "ground_truth_modes": [
            "primary",
            "deleted_transition_proxy",
            "initial_state_outgoing",
        ],
        "partitions": {
            "all_cohort": int(all_detectable_metrics["cohort_size"]),
            "all_detectable": int(all_detectable_metrics["localized_cases"]),
            "transition_localizable_gt": int(localizable_metrics["localized_cases"]),
        },
        "case_count": int(all_detectable_metrics["cohort_size"]),
        "localized_cases": int(all_detectable_metrics["localized_cases"]),
        "skipped_cases": int(all_detectable_metrics["skipped_cases"]),
        "detectable_denominator": int(all_detectable_metrics["localized_cases"]),
        "metrics": {
            "all_detectable": all_detectable_metrics,
            "transition_localizable_gt": localizable_metrics,
        },
        "output_files": sorted(set(output_files)),
        "regeneration_commands": [
            (
                "fsmrepairbench run-localization-campaign data/fsmrepairbench_1k "
                f"--out {output_dir} "
                f"--cohort-file {cohort_path}"
            ),
            (
                "fsmrepairbench audit-rq3-localization-localizability data/fsmrepairbench_1k "
                f"--out {output_dir}"
            ),
            "python ../paper1/scripts/generate_rq3_localization_outputs.py",
        ],
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
    }


def write_audit_manifest(path: Path, manifest: dict[str, object]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return path


def compute_alternative_gt_by_case(
    dataset_dir: Path,
    audit_rows: list[LocalizabilityAuditRow],
) -> dict[str, AlternativeGtEvaluation]:
    """Evaluate alternative GT for every localized detectable case."""
    alternative_by_case: dict[str, AlternativeGtEvaluation] = {}
    for row in audit_rows:
        if not row.case.localized:
            continue
        case_dir = dataset_dir / "cases" / row.case.case_id
        alt = enrich_case_with_alternative_gt(case_dir, row.case)
        if alt is not None:
            alternative_by_case[row.case.case_id] = alt
    return alternative_by_case


def export_operator_localization_metrics(
    *,
    dataset_dir: Path,
    output_dir: Path,
    audit_rows: list[LocalizabilityAuditRow],
    all_detectable_metrics: dict[str, float | int],
    localizable_metrics: dict[str, float | int],
    cohort_path: Path,
    paper_export_dir: Path | None = None,
) -> OperatorMetricsExportResult:
    """Write operator metrics CSV, rank distribution exports, figures, and manifest."""
    alternative_by_case = compute_alternative_gt_by_case(dataset_dir, audit_rows)
    operator_rows = build_operator_metrics_rows(audit_rows, alternative_by_case)
    rank_operator_rows = build_rank_distribution_operator_rows(audit_rows, alternative_by_case)

    operator_metrics_csv = output_dir / "localization_metrics_by_operator.csv"
    rank_distribution_operator_csv = output_dir / "rank_distribution_by_operator.csv"
    _write_csv(operator_metrics_csv, list(OPERATOR_METRICS_COLUMNS), operator_rows)
    _write_csv(
        rank_distribution_operator_csv,
        list(RANK_DISTRIBUTION_OPERATOR_COLUMNS),
        rank_operator_rows,
    )

    tables_dir = output_dir / "tables"
    write_operator_metrics_tex(
        tables_dir / "table_localization_metrics_by_operator.tex",
        operator_rows,
    )

    not_ranked_rows = [
        {
            "mutation_operator": row["mutation_operator"],
            "partition": row["partition"],
            "gt_mode": row["gt_mode"],
            "detectable_cases": row["detectable_cases"],
            "not_ranked_count": row["not_ranked_count"],
            "evaluated_cases": row["evaluated_cases"],
        }
        for row in operator_rows
        if row["partition"] == "all_detectable" and row["gt_mode"] == "primary"
    ]
    _write_csv(
        output_dir / "not_ranked_by_operator.csv",
        [
            "mutation_operator",
            "partition",
            "gt_mode",
            "detectable_cases",
            "not_ranked_count",
            "evaluated_cases",
        ],
        not_ranked_rows,
    )

    detectable_cases = [row.case for row in audit_rows if row.case.localized]
    cohort_distribution = rank_distribution(detectable_cases)
    figures_dir = output_dir / "figures"
    write_rank_distribution_figures(
        figures_dir,
        audit_rows=audit_rows,
        alternative_by_case=alternative_by_case,
        cohort_distribution=cohort_distribution,
    )

    manifest = build_audit_manifest(
        dataset_dir=dataset_dir,
        output_dir=output_dir,
        cohort_path=cohort_path,
        all_detectable_metrics=all_detectable_metrics,
        localizable_metrics=localizable_metrics,
    )
    manifest_path = write_audit_manifest(output_dir / "manifest.json", manifest)

    if paper_export_dir is not None and paper_export_dir.resolve() != output_dir.resolve():
        import shutil

        paper_export_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "localization_metrics_by_operator.csv",
            "rank_distribution_by_operator.csv",
            "not_ranked_by_operator.csv",
            "manifest.json",
        ):
            src = output_dir / name
            if src.is_file():
                shutil.copy2(src, paper_export_dir / name)
        for subdir in ("tables", "figures"):
            src_dir = output_dir / subdir
            if src_dir.is_dir():
                dest = paper_export_dir / subdir
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src_dir, dest)

    return OperatorMetricsExportResult(
        operator_metrics_csv=operator_metrics_csv,
        rank_distribution_operator_csv=rank_distribution_operator_csv,
        figures_dir=figures_dir,
        manifest_path=manifest_path,
    )
