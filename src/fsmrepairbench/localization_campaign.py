"""Transition-level Ochiai localization campaign orchestration."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fsmrepairbench.analytics import _save_bar_plot, _save_histogram
from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.fault_localization import (
    FaultLocalizationReport,
    SuspiciousnessMethod,
    localize_fault,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.statistics import (
    append_ci_section_to_report,
    compute_rq3_confidence_intervals,
    write_confidence_interval_exports,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

LOCALIZATION_METHOD: SuspiciousnessMethod = "ochiai"
TOP_K_VALUES: tuple[int, ...] = (1, 3, 5)
RANK_BUCKETS: tuple[str, ...] = (
    "1",
    "2",
    "3",
    "4",
    "5",
    "6-10",
    "11-20",
    "21+",
    "not_ranked",
)

PER_CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "mutation_operator",
    "changed_transition_id",
    "localized",
    "transition_count",
    "rank_of_target",
    "reciprocal_rank",
    "top1_hit",
    "top3_hit",
    "top5_hit",
    "top_ranked_transition",
)

LOCALIZATION_METRICS_COLUMNS: tuple[str, ...] = (
    "metric",
    "bucket",
    "value",
    "count",
    "fraction",
)


class LocalizationCampaignError(RuntimeError):
    """Raised when a localization campaign cannot be completed."""


@dataclass(frozen=True)
class CaseLocalizationResult:
    """Transition-level localization outcome for one benchmark case."""

    case_id: str
    mutation_operator: str
    changed_transition_id: str
    localized: bool
    transition_count: int
    rank_of_target: int | None
    reciprocal_rank: float
    top1_hit: bool
    top3_hit: bool
    top5_hit: bool
    top_ranked_transition: str

    def to_dict(self) -> dict[str, str | int | float | bool]:
        return {
            "case_id": self.case_id,
            "mutation_operator": self.mutation_operator,
            "changed_transition_id": self.changed_transition_id,
            "localized": self.localized,
            "transition_count": self.transition_count,
            "rank_of_target": self.rank_of_target if self.rank_of_target is not None else "",
            "reciprocal_rank": round(self.reciprocal_rank, 6),
            "top1_hit": self.top1_hit,
            "top3_hit": self.top3_hit,
            "top5_hit": self.top5_hit,
            "top_ranked_transition": self.top_ranked_transition,
        }


@dataclass(frozen=True)
class LocalizationCampaignResult:
    """Paths written by a localization campaign run."""

    dataset_dir: Path
    output_dir: Path
    cohort_path: Path
    per_case_path: Path
    summary_path: Path
    localization_metrics_path: Path
    report_path: Path
    figures_dir: Path
    tables_dir: Path
    case_count: int
    localized_cases: int


def load_cohort_manifest(path: Path) -> list[str]:
    """Load one case ID per line from *path*."""
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise LocalizationCampaignError(msg)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ranked_transition_ids(report: FaultLocalizationReport) -> list[str]:
    """Return transition element IDs in Ochiai rank order."""
    return [
        element.element_id
        for element in report.ranked_elements
        if element.element_type == "transition"
    ]


def rank_bucket(rank: int | None) -> str:
    """Map a 1-based transition rank to a publication bucket."""
    if rank is None:
        return "not_ranked"
    if rank <= 5:
        return str(rank)
    if rank <= 10:
        return "6-10"
    if rank <= 20:
        return "11-20"
    return "21+"


def transition_localization_metrics(
    target: str,
    ranked_transition_ids: list[str],
) -> tuple[int | None, float, bool, bool, bool]:
    """Compute rank, reciprocal rank, and top-k hits for *target*."""
    if not target or target not in ranked_transition_ids:
        return None, 0.0, False, False, False
    rank = ranked_transition_ids.index(target) + 1
    reciprocal = 1.0 / rank
    return (
        rank,
        reciprocal,
        rank == 1,
        rank <= 3,
        rank <= 5,
    )


def localize_case_transitions(
    case_dir: Path,
    *,
    method: SuspiciousnessMethod = LOCALIZATION_METHOD,
) -> CaseLocalizationResult:
    """Run transition-level localization for one stratified case directory."""
    case_id = case_dir.name
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    metadata_path = case_dir / "bug_metadata.json"
    if faulty_path is None or oracle_path is None or not metadata_path.is_file():
        msg = f"Incomplete case directory: {case_dir}"
        raise LocalizationCampaignError(msg)

    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    metadata = BugMetadata.model_validate(
        json.loads(metadata_path.read_text(encoding="utf-8"))
    )
    target = metadata.changed_transition_id or ""
    operator = metadata.mutation_operator
    if metadata.is_negative_control or metadata.mutation_operator == "no_fault":
        return CaseLocalizationResult(
            case_id=case_id,
            mutation_operator=operator,
            changed_transition_id=target,
            localized=False,
            transition_count=0,
            rank_of_target=None,
            reciprocal_rank=0.0,
            top1_hit=False,
            top3_hit=False,
            top5_hit=False,
            top_ranked_transition="",
        )

    try:
        report = localize_fault(faulty, oracle, method=method)
    except ValueError:
        return CaseLocalizationResult(
            case_id=case_id,
            mutation_operator=operator,
            changed_transition_id=target,
            localized=False,
            transition_count=0,
            rank_of_target=None,
            reciprocal_rank=0.0,
            top1_hit=False,
            top3_hit=False,
            top5_hit=False,
            top_ranked_transition="",
        )

    ranked_ids = ranked_transition_ids(report)
    rank, reciprocal, top1, top3, top5 = transition_localization_metrics(target, ranked_ids)
    return CaseLocalizationResult(
        case_id=case_id,
        mutation_operator=operator,
        changed_transition_id=target,
        localized=True,
        transition_count=len(ranked_ids),
        rank_of_target=rank,
        reciprocal_rank=reciprocal,
        top1_hit=top1,
        top3_hit=top3,
        top5_hit=top5,
        top_ranked_transition=ranked_ids[0] if ranked_ids else "",
    )


def aggregate_localization_metrics(
    rows: list[CaseLocalizationResult],
) -> dict[str, float | int]:
    """Aggregate top-k hit rates, MRR, and cohort counts."""
    localized_rows = [row for row in rows if row.localized]
    localized = len(localized_rows)
    skipped = len(rows) - localized
    cohort_size = len(rows)

    def _rate(attr: Literal["top1_hit", "top3_hit", "top5_hit"]) -> float:
        if not localized_rows:
            return 0.0
        hits = sum(1 for row in localized_rows if getattr(row, attr))
        return round(hits / localized, 6)

    mrr = round(
        sum(row.reciprocal_rank for row in localized_rows) / localized if localized else 0.0,
        6,
    )
    return {
        "cohort_size": cohort_size,
        "localized_cases": localized,
        "skipped_cases": skipped,
        "top1_hit_rate": _rate("top1_hit"),
        "top3_hit_rate": _rate("top3_hit"),
        "top5_hit_rate": _rate("top5_hit"),
        "mrr": mrr,
    }


def rank_distribution(rows: list[CaseLocalizationResult]) -> list[dict[str, str | int | float]]:
    """Count localized cases by transition rank bucket."""
    localized_rows = [row for row in rows if row.localized]
    counts = Counter(rank_bucket(row.rank_of_target) for row in localized_rows)
    total = len(localized_rows) or 1
    distribution: list[dict[str, str | int | float]] = []
    for bucket in RANK_BUCKETS:
        count = counts.get(bucket, 0)
        distribution.append(
            {
                "metric": "rank_distribution",
                "bucket": bucket,
                "value": "",
                "count": count,
                "fraction": round(count / total, 6),
            }
        )
    return distribution


def operator_hit_rates(
    rows: list[CaseLocalizationResult],
    *,
    top_k: int,
) -> dict[str, float]:
    """Per-operator top-k hit rate among localized cases."""
    grouped: dict[str, list[CaseLocalizationResult]] = defaultdict(list)
    for row in rows:
        if row.localized:
            grouped[row.mutation_operator].append(row)

    attr = {1: "top1_hit", 3: "top3_hit", 5: "top5_hit"}[top_k]
    rates: dict[str, float] = {}
    for operator, operator_rows in sorted(grouped.items()):
        hits = sum(1 for row in operator_rows if getattr(row, attr))
        rates[operator] = round(hits / len(operator_rows), 6) if operator_rows else 0.0
    return rates


def _write_per_case_csv(path: Path, rows: list[CaseLocalizationResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PER_CASE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def _write_summary_csv(path: Path, metrics: dict[str, float | int], *, cohort_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("experiment", "RQ3-localization-ochiai-1k"),
        ("method", LOCALIZATION_METHOD),
        ("element_type", "transition"),
        ("ground_truth", "changed_transition_id"),
        ("cohort_path", str(cohort_path)),
        *[(key, value) for key, value in metrics.items()],
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for metric, value in rows:
            writer.writerow([metric, value])


def _write_localization_metrics_csv(
    path: Path,
    metrics: dict[str, float | int],
    distribution: list[dict[str, str | int | float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    aggregate_rows: list[dict[str, str | int | float]] = []
    for key, value in metrics.items():
        aggregate_rows.append(
            {
                "metric": key,
                "bucket": "",
                "value": value,
                "count": "",
                "fraction": "",
            }
        )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LOCALIZATION_METRICS_COLUMNS))
        writer.writeheader()
        writer.writerows(aggregate_rows)
        writer.writerows(distribution)


def _write_campaign_figures(
    figures_dir: Path,
    *,
    metrics: dict[str, float | int],
    distribution: list[dict[str, str | int | float]],
    rows: list[CaseLocalizationResult],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    _save_bar_plot(
        figures_dir / "topk_hit_rates.png",
        title="Transition Localization Hit Rates (Ochiai)",
        xlabel="Top-k",
        ylabel="Hit Rate (%)",
        labels=["Top-1", "Top-3", "Top-5"],
        values=[
            round(float(metrics["top1_hit_rate"]) * 100.0, 1),
            round(float(metrics["top3_hit_rate"]) * 100.0, 1),
            round(float(metrics["top5_hit_rate"]) * 100.0, 1),
        ],
    )

    rank_labels = [row["bucket"] for row in distribution if row["count"]]
    rank_counts = [int(row["count"]) for row in distribution if row["count"]]
    if rank_labels:
        _save_bar_plot(
            figures_dir / "rank_distribution.png",
            title="Transition Rank Distribution (Localized Cases)",
            xlabel="Rank Bucket",
            ylabel="Cases",
            labels=rank_labels,
            values=rank_counts,
        )

    reciprocal_values = [row.reciprocal_rank for row in rows if row.localized and row.reciprocal_rank > 0]
    if reciprocal_values:
        _save_histogram(
            figures_dir / "reciprocal_rank_distribution.png",
            title="Reciprocal Rank Distribution (Hits Only)",
            xlabel="Reciprocal Rank (1/rank)",
            values=reciprocal_values,
            bins=min(10, max(3, len(set(reciprocal_values)))),
        )

    operator_rates = operator_hit_rates(rows, top_k=5)
    if operator_rates:
        labels = list(operator_rates.keys())
        values = [round(rate * 100.0, 1) for rate in operator_rates.values()]
        _save_bar_plot(
            figures_dir / "top5_hit_rate_by_operator.png",
            title="Top-5 Transition Hit Rate by Mutation Operator",
            xlabel="Mutation Operator",
            ylabel="Hit Rate (%)",
            labels=labels,
            values=values,
        )


def _write_publication_tables(
    tables_dir: Path,
    *,
    metrics: dict[str, float | int],
    distribution: list[dict[str, str | int | float]],
    rows: list[CaseLocalizationResult],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        "% Auto-generated by run-localization-campaign",
        "\\begin{tabular}{@{}lrrrrr@{}}",
        "\\toprule",
        "Cases & Localized & Top-1 & Top-3 & Top-5 & MRR \\\\",
        "\\midrule",
        f"{metrics['cohort_size']} & {metrics['localized_cases']} & "
        f"{100 * float(metrics['top1_hit_rate']):.2f}\\% & "
        f"{100 * float(metrics['top3_hit_rate']):.2f}\\% & "
        f"{100 * float(metrics['top5_hit_rate']):.2f}\\% & "
        f"{float(metrics['mrr']):.3f} \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "",
    ]
    (tables_dir / "table_localization_summary.tex").write_text(
        "\n".join(summary_lines), encoding="utf-8"
    )

    distribution_lines = [
        "% Auto-generated by run-localization-campaign",
        "\\begin{tabular}{@{}lrr@{}}",
        "\\toprule",
        "Rank Bucket & Cases & Fraction \\\\",
        "\\midrule",
    ]
    for row in distribution:
        if int(row["count"]) == 0:
            continue
        label = str(row["bucket"]).replace("_", "\\_")
        distribution_lines.append(
            f"{label} & {row['count']} & {100 * float(row['fraction']):.1f}\\% \\\\"
        )
    distribution_lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (tables_dir / "table_rank_distribution.tex").write_text(
        "\n".join(distribution_lines), encoding="utf-8"
    )

    operators = sorted({row.mutation_operator for row in rows if row.localized and row.mutation_operator})
    if operators:
        operator_lines = [
            "% Auto-generated by run-localization-campaign",
            "\\begin{tabular}{@{}lrrr@{}}",
            "\\toprule",
            "Operator & Top-1 & Top-3 & Top-5 \\\\",
            "\\midrule",
        ]
        for operator in operators:
            operator_rows = [row for row in rows if row.localized and row.mutation_operator == operator]
            count = len(operator_rows)
            top1 = sum(1 for row in operator_rows if row.top1_hit) / count
            top3 = sum(1 for row in operator_rows if row.top3_hit) / count
            top5 = sum(1 for row in operator_rows if row.top5_hit) / count
            safe_operator = operator.replace("_", "\\_")
            operator_lines.append(
                f"{safe_operator} & {100 * top1:.1f}\\% & {100 * top3:.1f}\\% & {100 * top5:.1f}\\% \\\\"
            )
        operator_lines.extend(["\\bottomrule", "\\end{tabular}", ""])
        (tables_dir / "table_localization_by_operator.tex").write_text(
            "\n".join(operator_lines), encoding="utf-8"
        )


def write_localization_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    cohort_path: Path,
    metrics: dict[str, float | int],
    distribution: list[dict[str, str | int | float]],
    rows: list[CaseLocalizationResult],
) -> None:
    """Write Markdown report for the localization campaign."""
    lines = [
        "# RQ3 Fault Localization (Ochiai, Transition-Level)",
        "",
        "Spectrum-based fault localization ranks transitions by Ochiai suspiciousness "
        "using oracle pass/fail spectra. Ground truth is `changed_transition_id` from "
        "`bug_metadata.json`.",
        "",
        "## Experimental design",
        "",
        f"- **Dataset:** `{dataset_dir}`",
        f"- **Cohort:** {metrics['cohort_size']} cases (`{cohort_path.name}`)",
        f"- **Method:** {LOCALIZATION_METHOD} on transition elements only",
        f"- **Top-k metrics:** {', '.join(f'top-{k}' for k in TOP_K_VALUES)}",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Localized cases | {metrics['localized_cases']} |",
        f"| Skipped cases | {metrics['skipped_cases']} |",
        f"| Top-1 hit rate | {float(metrics['top1_hit_rate']):.2%} |",
        f"| Top-3 hit rate | {float(metrics['top3_hit_rate']):.2%} |",
        f"| Top-5 hit rate | {float(metrics['top5_hit_rate']):.2%} |",
        f"| MRR | {float(metrics['mrr']):.4f} |",
        "",
        "## Rank distribution",
        "",
        "| Rank bucket | Cases | Fraction |",
        "|---|---:|---:|",
    ]
    for row in distribution:
        lines.append(
            f"| {row['bucket']} | {row['count']} | {float(row['fraction']):.2%} |"
        )

    lines.extend(
        [
            "",
            "## Figures",
            "",
            "![Top-k hit rates](figures/topk_hit_rates.png)",
            "",
            "![Rank distribution](figures/rank_distribution.png)",
            "",
            "![Top-5 hit rate by operator](figures/top5_hit_rate_by_operator.png)",
            "",
            "## Artifacts",
            "",
            f"- Summary: `{output_dir / 'summary.csv'}`",
            f"- Localization metrics: `{output_dir / 'localization_metrics.csv'}`",
            f"- Per-case results: `{output_dir / 'per_case_results.csv'}`",
            f"- Confidence intervals: `{output_dir / 'confidence_intervals.csv'}`",
            f"- LaTeX tables: `{output_dir / 'tables'}/`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_localization_campaign(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_path: Path | None = None,
    method: SuspiciousnessMethod = LOCALIZATION_METHOD,
) -> LocalizationCampaignResult:
    """Run transition-level Ochiai localization on a pinned cohort."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise LocalizationCampaignError(msg)

    cohort = cohort_path or (dataset_dir / "localization_cohort_1k.txt")
    case_ids = load_cohort_manifest(cohort)

    out = output_dir or Path("results/rq3_localization_1k")
    out.mkdir(parents=True, exist_ok=True)

    rows: list[CaseLocalizationResult] = []
    for case_id in case_ids:
        case_dir = dataset_dir / "cases" / case_id
        if not case_dir.is_dir():
            rows.append(
                CaseLocalizationResult(
                    case_id=case_id,
                    mutation_operator="",
                    changed_transition_id="",
                    localized=False,
                    transition_count=0,
                    rank_of_target=None,
                    reciprocal_rank=0.0,
                    top1_hit=False,
                    top3_hit=False,
                    top5_hit=False,
                    top_ranked_transition="",
                )
            )
            continue
        rows.append(localize_case_transitions(case_dir, method=method))

    metrics = aggregate_localization_metrics(rows)
    distribution = rank_distribution(rows)

    per_case_path = out / "per_case_results.csv"
    summary_path = out / "summary.csv"
    localization_metrics_path = out / "localization_metrics.csv"
    report_path = out / "report.md"
    figures_dir = out / "figures"
    tables_dir = out / "tables"

    _write_per_case_csv(per_case_path, rows)
    _write_summary_csv(summary_path, metrics, cohort_path=cohort)
    _write_localization_metrics_csv(localization_metrics_path, metrics, distribution)
    _write_campaign_figures(
        figures_dir,
        metrics=metrics,
        distribution=distribution,
        rows=rows,
    )
    _write_publication_tables(
        tables_dir,
        metrics=metrics,
        distribution=distribution,
        rows=rows,
    )
    write_localization_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort,
        metrics=metrics,
        distribution=distribution,
        rows=rows,
    )

    ci_rows = compute_rq3_confidence_intervals(rows)
    write_confidence_interval_exports(
        out,
        campaign="RQ3-localization",
        rows=ci_rows,
    )
    append_ci_section_to_report(report_path, ci_rows)

    manifest = {
        "experiment": "RQ3-localization-ochiai-1k",
        "dataset_dir": str(dataset_dir),
        "output_dir": str(out),
        "cohort_path": str(cohort),
        "method": method,
        "element_type": "transition",
        "ground_truth": "changed_transition_id",
        "metrics": metrics,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return LocalizationCampaignResult(
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort,
        per_case_path=per_case_path,
        summary_path=summary_path,
        localization_metrics_path=localization_metrics_path,
        report_path=report_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        case_count=len(case_ids),
        localized_cases=int(metrics["localized_cases"]),
    )
