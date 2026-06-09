"""Ground-truth localizability audit for RQ3 transition-level localization."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.localization_campaign import (
    CAMPAIGN_LABEL,
    LOCALIZATION_METHOD,
    CaseLocalizationResult,
    LocalizationCampaignError,
    aggregate_localization_metrics,
    load_cohort_manifest,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.validators import load_fsm_json

LocalizabilityClass = Literal[
    "localizable_transition_gt",
    "missing_or_deleted_transition_gt",
    "non_transition_fault_gt",
    "missing_ground_truth",
]

NON_TRANSITION_FAULT_OPERATORS: frozenset[str] = frozenset(
    {
        "wrong_initial_state",
        "dead_state_intro",
        "unreachable_state_intro",
        "action_full_mutation",
    }
)

LOCALIZABILITY_AUDIT_COLUMNS: tuple[str, ...] = (
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
    "ground_truth_localizable",
    "non_localizable_reason",
    "localizability_class",
)

LOCALIZABLE_METRICS_COLUMNS: tuple[str, ...] = (
    "partition",
    "metric",
    "value",
    "denominator",
    "numerator",
)


@dataclass(frozen=True)
class LocalizabilityAuditRow:
    """Per-case localization outcome with ground-truth localizability metadata."""

    case: CaseLocalizationResult
    ground_truth_localizable: bool
    non_localizable_reason: str
    localizability_class: LocalizabilityClass

    def to_dict(self) -> dict[str, str | int | float | bool]:
        payload = self.case.to_dict()
        payload["ground_truth_localizable"] = self.ground_truth_localizable
        payload["non_localizable_reason"] = self.non_localizable_reason
        payload["localizability_class"] = self.localizability_class
        return payload


@dataclass(frozen=True)
class LocalizabilityAuditResult:
    """Paths written by the RQ3 localizability audit."""

    audit_csv_path: Path
    metrics_csv_path: Path
    report_path: Path
    paper_tables_dir: Path | None
    audit_rows: tuple[LocalizabilityAuditRow, ...]
    all_detectable_metrics: dict[str, float | int]
    localizable_metrics: dict[str, float | int]


def classify_ground_truth_localizability(
    *,
    mutation_operator: str,
    changed_transition_id: str | None,
    faulty_transition_ids: frozenset[str],
) -> tuple[LocalizabilityClass, bool, str]:
    """Classify whether transition-level ``changed_transition_id`` is rankable."""
    target = (changed_transition_id or "").strip()
    operator = mutation_operator

    if operator in NON_TRANSITION_FAULT_OPERATORS:
        return (
            "non_transition_fault_gt",
            False,
            f"{operator} fault is not anchored to a single transition identifier",
        )

    if not target:
        return (
            "missing_ground_truth",
            False,
            "changed_transition_id is empty or null in bug_metadata.json",
        )

    if target not in faulty_transition_ids:
        if operator == "missing_transition":
            return (
                "missing_or_deleted_transition_gt",
                False,
                f"ground-truth transition '{target}' was removed from the faulty FSM",
            )
        return (
            "missing_or_deleted_transition_gt",
            False,
            f"ground-truth transition '{target}' is not present in the faulty FSM",
        )

    return ("localizable_transition_gt", True, "")


def audit_case_localizability(case_dir: Path, case: CaseLocalizationResult) -> LocalizabilityAuditRow:
    """Attach localizability metadata to one localization case result."""
    metadata_path = case_dir / "bug_metadata.json"
    if not metadata_path.is_file():
        return LocalizabilityAuditRow(
            case=case,
            ground_truth_localizable=False,
            non_localizable_reason="missing bug_metadata.json",
            localizability_class="missing_ground_truth",
        )

    metadata = BugMetadata.model_validate(
        json.loads(metadata_path.read_text(encoding="utf-8"))
    )
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    transition_ids: frozenset[str] = frozenset()
    if faulty_path is not None and faulty_path.is_file():
        faulty = load_fsm_json(faulty_path)
        transition_ids = frozenset(transition.id for transition in faulty.transitions)

    localizability_class, localizable, reason = classify_ground_truth_localizability(
        mutation_operator=metadata.mutation_operator,
        changed_transition_id=metadata.changed_transition_id,
        faulty_transition_ids=transition_ids,
    )
    return LocalizabilityAuditRow(
        case=case,
        ground_truth_localizable=localizable,
        non_localizable_reason=reason,
        localizability_class=localizability_class,
    )


def load_per_case_results(path: Path) -> list[CaseLocalizationResult]:
    """Load frozen ``per_case_results.csv`` rows."""
    if not path.is_file():
        msg = f"Per-case localization results not found: {path}"
        raise LocalizationCampaignError(msg)

    rows: list[CaseLocalizationResult] = []
    with path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            rank_raw = raw.get("rank_of_target", "")
            rank = int(rank_raw) if rank_raw not in ("", None) else None
            rows.append(
                CaseLocalizationResult(
                    case_id=str(raw["case_id"]),
                    mutation_operator=str(raw.get("mutation_operator", "")),
                    changed_transition_id=str(raw.get("changed_transition_id", "")),
                    localized=str(raw.get("localized", "")).strip().lower() == "true",
                    transition_count=int(raw.get("transition_count") or 0),
                    rank_of_target=rank,
                    reciprocal_rank=float(raw.get("reciprocal_rank") or 0.0),
                    top1_hit=str(raw.get("top1_hit", "")).strip().lower() == "true",
                    top3_hit=str(raw.get("top3_hit", "")).strip().lower() == "true",
                    top5_hit=str(raw.get("top5_hit", "")).strip().lower() == "true",
                    top_ranked_transition=str(raw.get("top_ranked_transition", "")),
                )
            )
    return rows


def audit_localization_results(
    dataset_dir: Path,
    cases: list[CaseLocalizationResult],
) -> list[LocalizabilityAuditRow]:
    """Audit all localization cases against faulty FSM / bug metadata."""
    audit_rows: list[LocalizabilityAuditRow] = []
    for case in cases:
        case_dir = dataset_dir / "cases" / case.case_id
        if not case_dir.is_dir():
            audit_rows.append(
                LocalizabilityAuditRow(
                    case=case,
                    ground_truth_localizable=False,
                    non_localizable_reason=f"missing case directory: {case.case_id}",
                    localizability_class="missing_ground_truth",
                )
            )
            continue
        audit_rows.append(audit_case_localizability(case_dir, case))
    return audit_rows


def _localized_localizable_rows(
    audit_rows: list[LocalizabilityAuditRow],
) -> list[CaseLocalizationResult]:
    return [
        row.case
        for row in audit_rows
        if row.case.localized and row.ground_truth_localizable
    ]


def aggregate_localized_subset_metrics(
    localized_rows: list[CaseLocalizationResult],
) -> dict[str, float | int]:
    """Compute top-k hit rates and MRR on an already-localized case subset."""
    localized = len(localized_rows)

    def _rate(attr: str) -> float:
        if not localized_rows:
            return 0.0
        hits = sum(1 for row in localized_rows if getattr(row, attr))
        return round(hits / localized, 6)

    mrr = round(
        sum(row.reciprocal_rank for row in localized_rows) / localized if localized else 0.0,
        6,
    )
    return {
        "localized_cases": localized,
        "top1_hit_rate": _rate("top1_hit"),
        "top3_hit_rate": _rate("top3_hit"),
        "top5_hit_rate": _rate("top5_hit"),
        "mrr": mrr,
    }


def _partition_metrics(
    *,
    partition: str,
    metrics: dict[str, float | int],
    cohort_size: int,
    skipped_cases: int,
) -> list[dict[str, str | int | float]]:
    localized = int(metrics["localized_cases"])
    rows: list[dict[str, str | int | float]] = []
    for key in ("top1_hit_rate", "top3_hit_rate", "top5_hit_rate", "mrr"):
        rows.append(
            {
                "partition": partition,
                "metric": key,
                "value": metrics[key],
                "denominator": localized,
                "numerator": "",
            }
        )
    rows.extend(
        [
            {
                "partition": partition,
                "metric": "cohort_size",
                "value": cohort_size,
                "denominator": cohort_size,
                "numerator": cohort_size,
            },
            {
                "partition": partition,
                "metric": "localized_cases",
                "value": localized,
                "denominator": cohort_size,
                "numerator": localized,
            },
            {
                "partition": partition,
                "metric": "skipped_cases",
                "value": skipped_cases,
                "denominator": cohort_size,
                "numerator": skipped_cases,
            },
        ]
    )
    for k in (1, 3, 5):
        attr = {1: "top1_hit", 3: "top3_hit", 5: "top5_hit"}[k]
        hits = int(metrics.get(f"top{k}_hits", 0))
        rows.append(
            {
                "partition": partition,
                "metric": f"top{k}_hits",
                "value": hits,
                "denominator": localized,
                "numerator": hits,
            }
        )
    return rows


def build_localizable_metrics_rows(
    audit_rows: list[LocalizabilityAuditRow],
) -> list[dict[str, str | int | float]]:
    """Build CSV rows comparing all detectable vs transition-localizable GT partitions."""
    all_cases = [row.case for row in audit_rows]
    localized_cases = [row.case for row in audit_rows if row.case.localized]
    localizable_cases = _localized_localizable_rows(audit_rows)
    cohort_size = len(all_cases)

    all_detectable_metrics = aggregate_localization_metrics(all_cases)
    all_detectable_metrics["top1_hits"] = sum(
        1 for row in localized_cases if row.top1_hit
    )
    all_detectable_metrics["top3_hits"] = sum(
        1 for row in localized_cases if row.top3_hit
    )
    all_detectable_metrics["top5_hits"] = sum(
        1 for row in localized_cases if row.top5_hit
    )

    localizable_metrics = aggregate_localized_subset_metrics(localizable_cases)
    localizable_metrics["top1_hits"] = sum(1 for row in localizable_cases if row.top1_hit)
    localizable_metrics["top3_hits"] = sum(1 for row in localizable_cases if row.top3_hit)
    localizable_metrics["top5_hits"] = sum(1 for row in localizable_cases if row.top5_hit)

    rows: list[dict[str, str | int | float]] = []
    rows.extend(
        _partition_metrics(
            partition="all_detectable",
            metrics=all_detectable_metrics,
            cohort_size=cohort_size,
            skipped_cases=int(all_detectable_metrics["skipped_cases"]),
        )
    )
    rows.extend(
        _partition_metrics(
            partition="transition_localizable_gt",
            metrics=localizable_metrics,
            cohort_size=cohort_size,
            skipped_cases=cohort_size - int(localizable_metrics["localized_cases"]),
        )
    )
    return rows


def _operator_localizability_summary(
    audit_rows: list[LocalizabilityAuditRow],
) -> list[dict[str, str | int | float]]:
    grouped: dict[str, list[LocalizabilityAuditRow]] = defaultdict(list)
    for row in audit_rows:
        grouped[row.case.mutation_operator].append(row)

    summary: list[dict[str, str | int | float]] = []
    for operator in sorted(grouped):
        rows = grouped[operator]
        detectable = [row for row in rows if row.case.localized]
        localizable = [row for row in detectable if row.ground_truth_localizable]
        not_localizable = [row for row in detectable if not row.ground_truth_localizable]
        classes = Counter(row.localizability_class for row in detectable)
        top5_all = (
            sum(1 for row in detectable if row.case.top5_hit) / len(detectable)
            if detectable
            else 0.0
        )
        top5_localizable = (
            sum(1 for row in localizable if row.case.top5_hit) / len(localizable)
            if localizable
            else 0.0
        )
        summary.append(
            {
                "mutation_operator": operator,
                "cohort_cases": len(rows),
                "detectable_cases": len(detectable),
                "localizable_gt_cases": len(localizable),
                "not_localizable_gt_cases": len(not_localizable),
                "localizable_transition_gt": classes.get("localizable_transition_gt", 0),
                "missing_or_deleted_transition_gt": classes.get(
                    "missing_or_deleted_transition_gt", 0
                ),
                "non_transition_fault_gt": classes.get("non_transition_fault_gt", 0),
                "missing_ground_truth": classes.get("missing_ground_truth", 0),
                "top5_hit_rate_all_detectable": round(top5_all, 6),
                "top5_hit_rate_localizable_gt": round(top5_localizable, 6),
            }
        )
    return summary


def _write_localizability_audit_csv(path: Path, audit_rows: list[LocalizabilityAuditRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LOCALIZABILITY_AUDIT_COLUMNS))
        writer.writeheader()
        for row in audit_rows:
            writer.writerow(row.to_dict())


def _write_localizable_metrics_csv(
    path: Path,
    metric_rows: list[dict[str, str | int | float]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LOCALIZABLE_METRICS_COLUMNS))
        writer.writeheader()
        writer.writerows(metric_rows)


def _pct(value: float) -> str:
    return f"{100.0 * value:.2f}\\%"


def _write_paper_tables(
    tables_dir: Path,
    *,
    all_detectable_metrics: dict[str, float | int],
    localizable_metrics: dict[str, float | int],
    operator_summary: list[dict[str, str | int | float]],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)

    summary_lines = [
        "% Auto-generated by localization localizability audit",
        "\\begin{table}[t]",
        "\\caption{Transition-level Ochiai localization on oracle-detectable faults: "
        "all detectable cases versus transition-localizable ground-truth subset.}",
        "\\label{tab:localization-localizable-only}",
        "\\begin{tabular}{@{}lrrrrr@{}}",
        "\\toprule",
        "Partition & $n$ & Top-1 & Top-3 & Top-5 & MRR \\\\",
        "\\midrule",
        f"All detectable & {int(all_detectable_metrics['localized_cases'])} & "
        f"{_pct(float(all_detectable_metrics['top1_hit_rate']))} & "
        f"{_pct(float(all_detectable_metrics['top3_hit_rate']))} & "
        f"{_pct(float(all_detectable_metrics['top5_hit_rate']))} & "
        f"{float(all_detectable_metrics['mrr']):.3f} \\\\",
        f"Transition-localizable GT & {int(localizable_metrics['localized_cases'])} & "
        f"{_pct(float(localizable_metrics['top1_hit_rate']))} & "
        f"{_pct(float(localizable_metrics['top3_hit_rate']))} & "
        f"{_pct(float(localizable_metrics['top5_hit_rate']))} & "
        f"{float(localizable_metrics['mrr']):.3f} \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ]
    (tables_dir / "table_localization_localizable_only.tex").write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )

    operator_lines = [
        "% Auto-generated by localization localizability audit",
        "\\begin{table}[t]",
        "\\caption{Ground-truth localizability audit by mutation operator "
        "(detectable cases only).}",
        "\\label{tab:localizability-by-operator}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrr@{}}",
        "\\toprule",
        "Operator & Detectable & Localizable GT & Not localizable & "
        "Deleted GT & Non-trans. GT & Top-5 (loc.) \\\\",
        "\\midrule",
    ]
    for row in operator_summary:
        if int(row["detectable_cases"]) == 0:
            continue
        operator = str(row["mutation_operator"]).replace("_", "\\_")
        operator_lines.append(
            f"{operator} & {row['detectable_cases']} & {row['localizable_gt_cases']} & "
            f"{row['not_localizable_gt_cases']} & "
            f"{row['missing_or_deleted_transition_gt']} & "
            f"{row['non_transition_fault_gt']} & "
            f"{100.0 * float(row['top5_hit_rate_localizable_gt']):.1f}\\% \\\\"
        )
    operator_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_localizability_by_operator.tex").write_text(
        "\n".join(operator_lines),
        encoding="utf-8",
    )


def write_localizability_audit_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    audit_rows: list[LocalizabilityAuditRow],
    all_detectable_metrics: dict[str, float | int],
    localizable_metrics: dict[str, float | int],
    operator_summary: list[dict[str, str | int | float]],
    base_report_path: Path | None = None,
) -> None:
    """Write or extend ``report.md`` with construct-validity audit documentation."""
    class_counts = Counter(row.localizability_class for row in audit_rows if row.case.localized)
    not_localizable = [
        row for row in audit_rows if row.case.localized and not row.ground_truth_localizable
    ]

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
        f"- **Campaign:** {CAMPAIGN_LABEL}",
        f"- **Method:** {LOCALIZATION_METHOD} on transition elements only",
        f"- **Top-k metrics:** top-1, top-3, top-5, MRR",
        "",
        "## Aggregate metrics (legacy all-detectable partition)",
        "",
        "The original RQ3 headline metrics include every oracle-detectable case "
        f"(`n={int(all_detectable_metrics['localized_cases'])}`) even when transition-level "
        "ground truth is not rankable. This partition is **conservative** and mixes "
        "Ochiai weakness with construct-validity failures.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Cohort size | {int(all_detectable_metrics['cohort_size'])} |",
        f"| Detectable (localized) cases | {int(all_detectable_metrics['localized_cases'])} |",
        f"| Skipped cases | {int(all_detectable_metrics['skipped_cases'])} |",
        f"| Top-1 hit rate | {float(all_detectable_metrics['top1_hit_rate']):.2%} |",
        f"| Top-3 hit rate | {float(all_detectable_metrics['top3_hit_rate']):.2%} |",
        f"| Top-5 hit rate | {float(all_detectable_metrics['top5_hit_rate']):.2%} |",
        f"| MRR | {float(all_detectable_metrics['mrr']):.4f} |",
        "",
        "## Construct-valid subset: transition-localizable ground truth",
        "",
        "For construct-valid transition-level evaluation, restrict to detectable cases whose "
        "`changed_transition_id` refers to a transition that still exists in the faulty FSM "
        "and is not a non-transition fault class.",
        "",
        f"- **Transition-localizable GT cases:** {int(localizable_metrics['localized_cases'])}",
        f"- **Top-1 hit rate:** {float(localizable_metrics['top1_hit_rate']):.2%}",
        f"- **Top-3 hit rate:** {float(localizable_metrics['top3_hit_rate']):.2%}",
        f"- **Top-5 hit rate:** {float(localizable_metrics['top5_hit_rate']):.2%}",
        f"- **MRR:** {float(localizable_metrics['mrr']):.4f}",
        "",
        "Use this partition as the primary RQ3 metric set in the paper. The all-detectable "
        "partition remains useful as a lower-bound baseline that includes non-rankable faults.",
        "",
        "## Ground-truth localizability audit",
        "",
        "Per-case audit export: "
        f"`{output_dir / 'localizability_audit.csv'}`.",
        "",
        "### Why some detectable faults are not transition-localizable",
        "",
        "| Class | Detectable cases | Meaning |",
        "|---|---:|---|",
        f"| `localizable_transition_gt` | {class_counts.get('localizable_transition_gt', 0)} | "
        "`changed_transition_id` exists in the faulty FSM and can be ranked. |",
        f"| `missing_or_deleted_transition_gt` | "
        f"{class_counts.get('missing_or_deleted_transition_gt', 0)} | "
        "Ground truth names a transition removed from or absent in the faulty FSM "
        "(notably `missing_transition`). |",
        f"| `non_transition_fault_gt` | {class_counts.get('non_transition_fault_gt', 0)} | "
        "Fault is not anchored to one transition ID (for example `wrong_initial_state`). |",
        f"| `missing_ground_truth` | {class_counts.get('missing_ground_truth', 0)} | "
        "`changed_transition_id` is empty or missing. |",
        "",
        f"Among detectable cases, **{len(not_localizable)}** have non-rankable transition "
        "ground truth. These cases inflate `not_ranked` in the legacy partition.",
        "",
        "### Operators to exclude or report separately",
        "",
        "- **`missing_transition`:** ground truth is the deleted transition; always "
        "`missing_or_deleted_transition_gt`. Report separately or exclude from "
        "transition-localizable aggregates.",
        "- **`wrong_initial_state`:** state-level fault with no transition ID; classify as "
        "`non_transition_fault_gt`. Requires state-level localization metrics outside RQ3.",
        "- **`dead_state_intro`, `unreachable_state_intro`, `action_full_mutation`:** "
        "non-transition fault classes when detectable; exclude from transition-localizable GT.",
        "",
        "## Operator summary",
        "",
        "| Operator | Detectable | Localizable GT | Not localizable | Top-5 all | Top-5 loc. |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in operator_summary:
        if int(row["detectable_cases"]) == 0:
            continue
        lines.append(
            f"| {row['mutation_operator']} | {row['detectable_cases']} | "
            f"{row['localizable_gt_cases']} | {row['not_localizable_gt_cases']} | "
            f"{float(row['top5_hit_rate_all_detectable']):.2%} | "
            f"{float(row['top5_hit_rate_localizable_gt']):.2%} |"
        )

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Localizability audit: `{output_dir / 'localizability_audit.csv'}`",
            f"- Partition metrics: `{output_dir / 'localization_metrics_localizable_only.csv'}`",
            f"- Legacy per-case results: `{output_dir / 'per_case_results.csv'}`",
            f"- Legacy summary: `{output_dir / 'summary.csv'}`",
            f"- LaTeX tables: `{output_dir / 'tables'}/`",
            "",
        ]
    )

    if base_report_path is not None and base_report_path.is_file():
        legacy = base_report_path.read_text(encoding="utf-8")
        marker = "## Bootstrap confidence intervals"
        if marker in legacy:
            lines.extend(["", marker, legacy.split(marker, 1)[1].lstrip()])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_localization_localizability_audit(
    dataset_dir: Path,
    *,
    output_dir: Path,
    paper_export_dir: Path | None = None,
    per_case_path: Path | None = None,
) -> LocalizabilityAuditResult:
    """Audit frozen RQ3 localization outputs and write derived construct-validity exports."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise LocalizationCampaignError(msg)

    out = output_dir.resolve()
    per_case = per_case_path or (out / "per_case_results.csv")
    cases = load_per_case_results(per_case)
    audit_rows = audit_localization_results(dataset_dir, cases)

    all_cases = [row.case for row in audit_rows]
    all_detectable_metrics = aggregate_localization_metrics(all_cases)
    localizable_case_rows = _localized_localizable_rows(audit_rows)
    localizable_metrics = aggregate_localized_subset_metrics(localizable_case_rows)
    metric_rows = build_localizable_metrics_rows(audit_rows)
    operator_summary = _operator_localizability_summary(audit_rows)

    audit_csv_path = out / "localizability_audit.csv"
    metrics_csv_path = out / "localization_metrics_localizable_only.csv"
    report_path = out / "report.md"

    _write_localizability_audit_csv(audit_csv_path, audit_rows)
    _write_localizable_metrics_csv(metrics_csv_path, metric_rows)

    tables_dir = out / "tables"
    _write_paper_tables(
        tables_dir,
        all_detectable_metrics=all_detectable_metrics,
        localizable_metrics=localizable_metrics,
        operator_summary=operator_summary,
    )

    resolved_paper_dir = paper_export_dir
    if resolved_paper_dir is None:
        monorepo_root = out.parent.parent.parent
        candidate = monorepo_root / "paper1" / "results" / out.name
        if candidate.parent.is_dir():
            resolved_paper_dir = candidate

    paper_tables_dir: Path | None = None
    if resolved_paper_dir is not None:
        resolved_paper_dir.mkdir(parents=True, exist_ok=True)
        paper_tables_dir = resolved_paper_dir / "tables"
        _write_paper_tables(
            paper_tables_dir,
            all_detectable_metrics=all_detectable_metrics,
            localizable_metrics=localizable_metrics,
            operator_summary=operator_summary,
        )

    write_localizability_audit_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        audit_rows=audit_rows,
        all_detectable_metrics=all_detectable_metrics,
        localizable_metrics=localizable_metrics,
        operator_summary=operator_summary,
        base_report_path=report_path if report_path.is_file() else None,
    )

    return LocalizabilityAuditResult(
        audit_csv_path=audit_csv_path,
        metrics_csv_path=metrics_csv_path,
        report_path=report_path,
        paper_tables_dir=paper_tables_dir,
        audit_rows=tuple(audit_rows),
        all_detectable_metrics=all_detectable_metrics,
        localizable_metrics=localizable_metrics,
    )
