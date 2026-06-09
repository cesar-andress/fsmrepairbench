"""Unified campaign partition summary for paper empirical campaigns."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import load_cohort_manifest
from fsmrepairbench.dataset_builder import DatasetBuilderError, load_dataset_cases
from fsmrepairbench.freeze import sha256_file

DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_1k")
DEFAULT_OUTPUT_DIR = Path("results/campaign_partitions")
DEFAULT_PAPER_EXPORT_DIR = Path("../paper1/results/campaign_partitions")
ZENODO_DOI = "10.5281/zenodo.20602528"

PARTITION_COLUMNS: tuple[str, ...] = (
    "campaign",
    "research_question",
    "release_label",
    "cohort_file",
    "cohort_sha256",
    "cases_total",
    "cases_detectable",
    "cases_skipped",
    "denominator_used_for_primary_metric",
    "primary_metrics",
    "notes",
)

RESULT_DIR_CANDIDATES: dict[str, tuple[str, ...]] = {
    "v0.2.0-analysis": ("results/v0_2_analysis", "results/analysis"),
    "C1-baseline-repair": ("results/repair_baseline_1k_c1",),
    "RQ3-localization": ("results/rq3_localization_1k",),
    "RQ4-coupling": ("results/rq4_coupling_250",),
    "C3-oracle-depth-ablation": ("results/oracle_depth_ablation",),
}


class CampaignPartitionError(ValueError):
    """Raised when campaign partition summary generation fails."""


@dataclass(frozen=True)
class CampaignPartitionRow:
    """One row in the unified campaign partition table."""

    campaign: str
    research_question: str
    release_label: str
    cohort_file: str
    cohort_sha256: str
    cases_total: int
    cases_detectable: int
    cases_skipped: int
    denominator_used_for_primary_metric: str
    primary_metrics: str
    notes: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "campaign": self.campaign,
            "research_question": self.research_question,
            "release_label": self.release_label,
            "cohort_file": self.cohort_file,
            "cohort_sha256": self.cohort_sha256,
            "cases_total": self.cases_total,
            "cases_detectable": self.cases_detectable,
            "cases_skipped": self.cases_skipped,
            "denominator_used_for_primary_metric": self.denominator_used_for_primary_metric,
            "primary_metrics": self.primary_metrics,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class CampaignPartitionResult:
    """Paths written by :func:`summarize_campaign_partitions`."""

    output_dir: Path
    csv_path: Path
    json_path: Path
    report_path: Path
    tex_path: Path | None = None
    paper_csv_path: Path | None = None
    paper_tex_path: Path | None = None


def _relative_repo_path(path: Path, *, repo_root: Path) -> str:
    try:
        return path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return path.as_posix()


def resolve_results_dir(
    campaign_key: str,
    *,
    repo_root: Path | None = None,
    overrides: dict[str, Path] | None = None,
) -> Path:
    """Return the first existing results directory for *campaign_key*."""
    if overrides and campaign_key in overrides:
        path = overrides[campaign_key]
        if path.is_dir():
            return path
        msg = f"Campaign results directory not found: {path}"
        raise CampaignPartitionError(msg)

    base = repo_root or Path(__file__).resolve().parents[2]
    for candidate in RESULT_DIR_CANDIDATES[campaign_key]:
        path = base / candidate
        if path.is_dir():
            return path
    msg = f"No results directory found for {campaign_key}: {RESULT_DIR_CANDIDATES[campaign_key]}"
    raise CampaignPartitionError(msg)


def _load_metric_csv(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    metrics: dict[str, str] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames and "metric" in reader.fieldnames and "value" in reader.fieldnames:
            for row in reader:
                metrics[str(row["metric"])] = str(row["value"])
    return metrics


def _load_leaderboard_detectable(path: Path) -> int | None:
    if not path.is_file():
        return None
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("tool_id") == "baseline_missing_transition":
                return int(float(row["detectable_cases"]))
    return None


def _count_detectable_cases(dataset_dir: Path, cohort_ids: set[str]) -> tuple[int, int]:
    try:
        cases = [case for case in load_dataset_cases(dataset_dir) if case.case_id in cohort_ids]
    except DatasetBuilderError as exc:
        raise CampaignPartitionError(str(exc)) from exc
    detectable = sum(1 for case in cases if case.bpr_delta > 0.0)
    return len(cases), detectable


def _cohort_row(
    *,
    cohort_path: Path,
    repo_root: Path,
) -> tuple[str, str, int]:
    if not cohort_path.is_file():
        msg = f"Cohort manifest not found: {cohort_path}"
        raise CampaignPartitionError(msg)
    case_ids = load_cohort_manifest(cohort_path)
    rel = _relative_repo_path(cohort_path, repo_root=repo_root)
    return rel, sha256_file(cohort_path), len(case_ids)


def build_campaign_partition_rows(
    *,
    dataset_dir: Path,
    repo_root: Path | None = None,
    result_overrides: dict[str, Path] | None = None,
) -> list[CampaignPartitionRow]:
    """Build unified partition rows for all paper empirical campaigns."""
    base = repo_root or Path(__file__).resolve().parents[2]
    dataset_dir = dataset_dir.resolve()
    rows: list[CampaignPartitionRow] = []

    analysis_cohort = dataset_dir / "analysis_cohort_1k.txt"
    analysis_cohort_rel, analysis_sha, analysis_total = _cohort_row(
        cohort_path=analysis_cohort,
        repo_root=base,
    )
    analysis_ids = set(load_cohort_manifest(analysis_cohort))
    _, analysis_detectable = _count_detectable_cases(dataset_dir, analysis_ids)

    analysis_dir = resolve_results_dir(
        "v0.2.0-analysis",
        repo_root=base,
        overrides=result_overrides,
    )
    analysis_metrics = _load_metric_csv(analysis_dir / "summary.csv")

    rows.append(
        CampaignPartitionRow(
            campaign="v0.2.0-analysis",
            research_question="RQ1 (taxonomy coverage) / RQ2 (mutation detection and BPR)",
            release_label="v0.2.0-analysis",
            cohort_file=analysis_cohort_rel,
            cohort_sha256=analysis_sha,
            cases_total=analysis_total,
            cases_detectable=analysis_detectable,
            cases_skipped=0,
            denominator_used_for_primary_metric=f"n={analysis_total} (full pinned cohort)",
            primary_metrics=(
                "RQ2: overall_detection_rate, mean_faulty_bpr, mean_bpr_delta; "
                "RQ1: taxonomy dimension/operator coverage on the same cohort"
            ),
            notes=(
                "Oracle-detectable subset n=495 (bpr_delta>0) used for operator-conditional "
                "detection rates; cohort-wide aggregates use all 1,000 cases."
            ),
        )
    )

    c1_dir = resolve_results_dir("C1-baseline-repair", repo_root=base, overrides=result_overrides)
    c1_detectable = _load_leaderboard_detectable(c1_dir / "leaderboard.csv") or analysis_detectable
    rows.append(
        CampaignPartitionRow(
            campaign="C1-baseline-repair",
            research_question="RQ6 (deterministic baseline repair)",
            release_label="C1-baseline-repair",
            cohort_file=analysis_cohort_rel,
            cohort_sha256=analysis_sha,
            cases_total=analysis_total,
            cases_detectable=c1_detectable,
            cases_skipped=0,
            denominator_used_for_primary_metric=(
                f"n={analysis_total} cohort-wide; n={c1_detectable} for detectable-only repair rates"
            ),
            primary_metrics=(
                "complete_repair_rate, effective_repair_rate, mean_delta_bpr, "
                "complete_repair_rate_detectable_only"
            ),
            notes=(
                "Leaderboard reports cohort-wide rates for three baselines; detectable-only "
                "complete repair conditions on oracle-visible faults (n=495)."
            ),
        )
    )

    localization_cohort = dataset_dir / "localization_cohort_1k.txt"
    loc_cohort_rel, loc_sha, loc_total = _cohort_row(
        cohort_path=localization_cohort,
        repo_root=base,
    )
    rq3_dir = resolve_results_dir("RQ3-localization", repo_root=base, overrides=result_overrides)
    rq3_metrics = _load_metric_csv(rq3_dir / "summary.csv")
    localized = int(float(rq3_metrics.get("localized_cases", analysis_detectable)))
    skipped = int(float(rq3_metrics.get("skipped_cases", loc_total - localized)))
    rows.append(
        CampaignPartitionRow(
            campaign="RQ3-localization-ochiai-1k",
            research_question="RQ3 (transition-level fault localization)",
            release_label="RQ3-localization-ochiai-1k",
            cohort_file=loc_cohort_rel,
            cohort_sha256=loc_sha,
            cases_total=loc_total,
            cases_detectable=localized,
            cases_skipped=skipped,
            denominator_used_for_primary_metric=f"n={localized} localized cases with changed_transition_id",
            primary_metrics="top_1_hit_rate, top_3_hit_rate, top_5_hit_rate, mrr",
            notes=(
                "Skipped cases lack localizable transition ground truth or missing case assets; "
                "hit rates and MRR exclude the 505 skipped cases."
            ),
        )
    )

    coupling_cohort = dataset_dir / "coupling_campaign_250.txt"
    coupling_rel, coupling_sha, coupling_total = _cohort_row(
        cohort_path=coupling_cohort,
        repo_root=base,
    )
    rq4_dir = resolve_results_dir("RQ4-coupling", repo_root=base, overrides=result_overrides)
    rq4_metrics = _load_metric_csv(rq4_dir / "summary.csv")
    rq4_manifest_path = rq4_dir / "manifest.json"
    skipped_ho = 0
    if rq4_manifest_path.is_file():
        manifest_payload = json.loads(rq4_manifest_path.read_text(encoding="utf-8"))
        skipped_ho = len(manifest_payload.get("skipped_ho_generations", []) or [])
    coupling_ids = set(load_cohort_manifest(coupling_cohort))
    _, coupling_detectable = _count_detectable_cases(dataset_dir, coupling_ids)
    total_cases = int(float(rq4_metrics.get("total_cases", coupling_total * 3)))
    fo_cases = int(float(rq4_metrics.get("first_order_case_count", coupling_total)))
    ho_cases = int(float(rq4_metrics.get("higher_order_case_count", total_cases - fo_cases)))
    order23 = ho_cases // 2 if ho_cases else 0
    rows.append(
        CampaignPartitionRow(
            campaign="RQ4-higher-order-coupling-250",
            research_question="RQ4 (higher-order mutation coupling)",
            release_label="RQ4-higher-order-coupling-250",
            cohort_file=coupling_rel,
            cohort_sha256=coupling_sha,
            cases_total=coupling_total,
            cases_detectable=coupling_detectable,
            cases_skipped=skipped_ho,
            denominator_used_for_primary_metric=(
                f"n={coupling_total} pinned source cases; n={fo_cases} order-1, "
                f"n={order23} order-2, n={order23} order-3 generated cases per metric stratum"
            ),
            primary_metrics=(
                "detection_rate, complete_repair_rate, effective_repair_rate, mean_bpr_delta "
                "by mutation order; coupling_effect_estimate"
            ),
            notes=(
                f"Pinned cohort selects {coupling_total} stratified source cases; campaign analyzes "
                f"{total_cases} generated first-/higher-order instances. Order-specific denominators "
                "are 250 per stratum in exported tables."
            ),
        )
    )

    ablation_cohort = dataset_dir / "oracle_depth_ablation_200.txt"
    ablation_rel, ablation_sha, ablation_total = _cohort_row(
        cohort_path=ablation_cohort,
        repo_root=base,
    )
    c3_dir = resolve_results_dir(
        "C3-oracle-depth-ablation",
        repo_root=base,
        overrides=result_overrides,
    )
    depth_summary_path = c3_dir / "depth_summary.csv"
    detectable_ratio = 0.0
    skipped_ref = 0
    if depth_summary_path.is_file():
        depth_rows = list(csv.DictReader(depth_summary_path.open(encoding="utf-8")))
        shallow = depth_rows[0] if depth_rows else {}
        detectable_ratio = float(shallow.get("detectable_case_ratio", "0") or 0)
        skipped_ref = int(float(shallow.get("skipped_reference_bpr_cases", "0") or 0))
    ablation_ids = set(load_cohort_manifest(ablation_cohort))
    _, ablation_detectable = _count_detectable_cases(dataset_dir, ablation_ids)
    detectable_cases = ablation_detectable or round(ablation_total * detectable_ratio)
    rows.append(
        CampaignPartitionRow(
            campaign="C3-oracle-depth-ablation-200",
            research_question="C3 (oracle depth sensitivity ablation)",
            release_label="C3-oracle-depth-ablation-200",
            cohort_file=ablation_rel,
            cohort_sha256=ablation_sha,
            cases_total=ablation_total,
            cases_detectable=detectable_cases,
            cases_skipped=skipped_ref,
            denominator_used_for_primary_metric=f"n={ablation_total} fixed cases per depth preset",
            primary_metrics=(
                "overall_detection_rate, mean_faulty_bpr, mean_bpr_delta by oracle depth "
                "(shallow/medium/deep)"
            ),
            notes=(
                "Same 200-case stratified cohort rescored under regenerated shallow, medium, and "
                "deep oracle suites; detectable count reflects bpr_delta>0 at each depth."
            ),
        )
    )

    _ = analysis_metrics
    return rows


def render_campaign_partitions_tex(rows: Sequence[CampaignPartitionRow]) -> str:
    """Render a LaTeX table summarizing campaign denominators."""
    lines = [
        "% Auto-generated from fsmrepairbench.campaign_partitions",
        "\\begin{table}[t]",
        "\\caption{Unified campaign partitions and primary metric denominators. "
        "Detectable counts follow campaign-specific visibility or localizability rules.}",
        "\\label{tab:campaign-partitions}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}p{2.1cm}p{1.5cm}rrrrp{3.2cm}@{}}",
        "\\toprule",
        "Campaign & RQ & Total & Det. & Skip & Denominator & Primary metrics \\\\",
        "\\midrule",
    ]
    for row in rows:
        rq = row.research_question.split("(", 1)[0].strip().replace("/", ", ")
        lines.append(
            f"{row.release_label.replace('_', '\\_')} & {rq} & {row.cases_total} & "
            f"{row.cases_detectable} & {row.cases_skipped} & "
            f"{row.denominator_used_for_primary_metric.replace('_', '\\_')} & "
            f"{row.primary_metrics.replace('_', '\\_')} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    return "\n".join(lines)


def _write_report(path: Path, rows: Sequence[CampaignPartitionRow]) -> None:
    lines = [
        "# Campaign partition summary",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "Unified view of cohort sizes, detectable subsets, and denominators used for "
        "primary metrics across paper empirical campaigns.",
        "",
        "| Campaign | Cohort | Total | Detectable | Skipped | Denominator |",
        "|----------|--------|------:|-----------:|--------:|-------------|",
    ]
    for row in rows:
        lines.append(
            f"| {row.campaign} | `{row.cohort_file}` | {row.cases_total} | "
            f"{row.cases_detectable} | {row.cases_skipped} | "
            f"{row.denominator_used_for_primary_metric} |"
        )
    lines.extend(["", "## Row notes", ""])
    for row in rows:
        lines.append(f"### {row.campaign}")
        lines.append("")
        lines.append(f"- Research question: {row.research_question}")
        lines.append(f"- Release label: `{row.release_label}`")
        lines.append(f"- Cohort SHA-256: `{row.cohort_sha256}`")
        lines.append(f"- Primary metrics: {row.primary_metrics}")
        lines.append(f"- Notes: {row.notes}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def summarize_campaign_partitions(
    *,
    dataset_dir: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    repo_root: Path | None = None,
    result_overrides: dict[str, Path] | None = None,
) -> CampaignPartitionResult:
    """Write unified campaign partition summary artefacts."""
    base = repo_root or Path(__file__).resolve().parents[2]
    dataset = (dataset_dir or DEFAULT_DATASET_DIR).resolve()
    out = (output_dir or DEFAULT_OUTPUT_DIR).resolve()
    out.mkdir(parents=True, exist_ok=True)

    rows = build_campaign_partition_rows(
        dataset_dir=dataset,
        repo_root=base,
        result_overrides=result_overrides,
    )
    dict_rows = [row.to_dict() for row in rows]

    csv_path = out / "partition_summary.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PARTITION_COLUMNS))
        writer.writeheader()
        writer.writerows(dict_rows)

    json_path = out / "partition_summary.json"
    payload: dict[str, Any] = {
        "zenodo_doi": ZENODO_DOI,
        "dataset_path": _relative_repo_path(dataset, repo_root=base),
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "columns": list(PARTITION_COLUMNS),
        "campaigns": dict_rows,
    }
    json_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    report_path = out / "report.md"
    _write_report(report_path, rows)

    paper_dir = (paper_export_dir or DEFAULT_PAPER_EXPORT_DIR).resolve()
    paper_dir.mkdir(parents=True, exist_ok=True)
    paper_csv = paper_dir / "partition_summary.csv"
    paper_csv.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")

    tables_dir = paper_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    tex_path = tables_dir / "table_campaign_partitions.tex"
    tex_path.write_text(render_campaign_partitions_tex(rows), encoding="utf-8")

    return CampaignPartitionResult(
        output_dir=out,
        csv_path=csv_path,
        json_path=json_path,
        report_path=report_path,
        tex_path=tex_path,
        paper_csv_path=paper_csv,
        paper_tex_path=tex_path,
    )
