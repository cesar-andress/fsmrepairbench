"""Null-cohort control analysis for reporting-metric denominator artifacts."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.negative_control_campaign import (
    DEFAULT_DATASET_DIR,
    DEFAULT_OUTPUT_DIR,
    load_cohort_manifest,
)

SUMMARY_COLUMNS: tuple[str, ...] = (
    "metric",
    "partition",
    "tool_id",
    "value",
    "n_cases",
    "interpretation_note",
)

METRIC_ROWS: tuple[str, ...] = (
    "mean_faulty_bpr",
    "mean_reference_bpr",
    "mean_bpr_delta",
    "detection_rate",
    "saturation_rate",
    "cohort_wide_complete_repair_rate",
    "detectable_only_complete_repair_rate",
    "saturation_inflation_pp",
    "false_repair_rate",
    "effective_repair_rate",
    "mean_delta_bpr",
    "localization_applicable_rate",
    "localization_skipped_rate",
)


@dataclass(frozen=True)
class NullControlAnalysisResult:
    output_dir: Path
    summary_path: Path
    report_path: Path
    table_tex_path: Path
    case_count: int


class NullControlAnalysisError(RuntimeError):
    """Raised when null-control analysis cannot complete."""


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _bool(value: str) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _aggregate_null_metrics(
    per_case_rows: list[dict[str, str]],
    *,
    tool_id: str | None = None,
) -> dict[str, Any]:
    rows = [row for row in per_case_rows if not tool_id or row.get("tool_id") == tool_id]
    if not rows:
        return {}

    n = len(rows)
    detectable = [row for row in rows if float(row["initial_bpr"]) < 1.0 - 1e-9]
    saturated = [row for row in rows if float(row["faulty_bpr"]) >= 1.0 - 1e-9]

    cohort_wide_crr = sum(_bool(row["complete_repair"]) for row in rows) / n
    detectable_crr = (
        sum(_bool(row["complete_repair"]) for row in detectable) / len(detectable)
        if detectable
        else None
    )
    inflation = (
        (cohort_wide_crr - detectable_crr) * 100.0 if detectable_crr is not None else None
    )

    return {
        "n_cases": n,
        "mean_faulty_bpr": round(sum(float(row["faulty_bpr"]) for row in rows) / n, 6),
        "mean_reference_bpr": round(sum(float(row["reference_bpr"]) for row in rows) / n, 6),
        "mean_bpr_delta": round(sum(float(row["bpr_delta"]) for row in rows) / n, 6),
        "detection_rate": round(len(detectable) / n, 6),
        "saturation_rate": round(len(saturated) / n, 6),
        "cohort_wide_complete_repair_rate": round(cohort_wide_crr, 6),
        "detectable_only_complete_repair_rate": round(detectable_crr, 6)
        if detectable_crr is not None
        else None,
        "saturation_inflation_pp": round(inflation, 6) if inflation is not None else None,
        "false_repair_rate": round(sum(_bool(row["false_repair"]) for row in rows) / n, 6),
        "effective_repair_rate": round(sum(_bool(row["effective_repair"]) for row in rows) / n, 6),
        "mean_delta_bpr": round(sum(float(row["delta_bpr"]) for row in rows) / n, 6),
        "localization_applicable_rate": round(
            sum(_bool(row["localization_applicable"]) for row in rows) / n, 6
        ),
        "localization_skipped_rate": round(
            sum(_bool(row["localization_skipped"]) for row in rows) / n, 6
        ),
    }


def _summary_rows_from_metrics(
    metrics: dict[str, Any],
    *,
    tool_id: str,
    partition: str,
) -> list[dict[str, Any]]:
    notes = {
        "detection_rate": "No injected fault; BPR delta zero by construction.",
        "saturation_rate": "All cases oracle-saturated (faulty BPR = 1.0).",
        "cohort_wide_complete_repair_rate": (
            "Denominator artifact: complete repair defined as final BPR = 1.0, "
            "already satisfied pre-repair."
        ),
        "detectable_only_complete_repair_rate": (
            "Undefined/empty detectable partition (n=0); not a repair outcome."
        ),
        "saturation_inflation_pp": (
            "Inflation undefined when detectable partition is empty."
        ),
        "false_repair_rate": "No spurious patch applied on correct FSM.",
        "localization_skipped_rate": "No rankable fault; localization not applicable.",
    }
    rows: list[dict[str, Any]] = []
    for metric in METRIC_ROWS:
        value = metrics.get(metric)
        if value is None and metric not in metrics:
            continue
        rows.append(
            {
                "metric": metric,
                "partition": partition,
                "tool_id": tool_id,
                "value": value if value is not None else "NA",
                "n_cases": metrics["n_cases"],
                "interpretation_note": notes.get(metric, ""),
            }
        )
    return rows


def _write_null_table_tex(path: Path, summary_rows: list[dict[str, Any]]) -> None:
    random_rows = {
        row["metric"]: row for row in summary_rows if row["tool_id"] == "baseline_random"
    }
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\caption{Null-cohort control ($n=100$ no-fault cases): reporting metrics without a repairable fault.}",
        "\\label{tab:null-control}",
        "\\begin{tabular}{@{}l r l@{}}",
        "\\toprule",
        "Metric & Value & Note \\\\",
        "\\midrule",
    ]
    display = [
        ("Mean faulty BPR", "mean_faulty_bpr", "1.0"),
        ("Detection rate", "detection_rate", "0\\%"),
        ("Saturation rate", "saturation_rate", "100\\%"),
        ("Cohort-wide CRR", "cohort_wide_complete_repair_rate", "denominator artifact"),
        ("Detectable-only CRR", "detectable_only_complete_repair_rate", "empty partition"),
        ("Saturation inflation", "saturation_inflation_pp", "undefined"),
        ("False repair rate", "false_repair_rate", "0\\%"),
    ]
    for label, key, default_note in display:
        row = random_rows.get(key, {})
        value = row.get("value", "NA")
        if isinstance(value, float) or (isinstance(value, str) and value.replace(".", "", 1).isdigit()):
            num = float(value)
            if key.endswith("_rate") or key == "mean_faulty_bpr":
                val_s = f"{num * 100:.1f}\\%" if num <= 1.0 else f"{num:.2f}"
            else:
                val_s = str(value)
        else:
            val_s = str(value)
        note = str(row.get("interpretation_note", default_note))[:60].replace("_", "\\_")
        lines.append(f"{label} & {val_s} & {default_note} \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_null_control_analysis(
    *,
    output_dir: Path,
    table_dir: Path,
    dataset_dir: Path = DEFAULT_DATASET_DIR,
    campaign_results_dir: Path = DEFAULT_OUTPUT_DIR,
    per_case_path: Path | None = None,
) -> NullControlAnalysisResult:
    """Summarise null-cohort reporting metrics from frozen negative-control exports."""
    resolved_per_case = per_case_path or (campaign_results_dir / "per_case_results.csv")
    if not resolved_per_case.is_file():
        msg = f"Missing negative-control per_case_results: {resolved_per_case}"
        raise NullControlAnalysisError(msg)

    cohort_path = dataset_dir / "negative_control_cohort_100.txt"
    case_ids = load_cohort_manifest(cohort_path) if cohort_path.is_file() else []
    per_case_all = _read_csv(resolved_per_case)

    output_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)

    summary_rows: list[dict[str, Any]] = []
    tool_ids = sorted({row["tool_id"] for row in per_case_all if row.get("tool_id")})

    baseline_rows = [row for row in per_case_all if not row.get("tool_id")]
    if baseline_rows:
        metrics = _aggregate_null_metrics(baseline_rows)
        summary_rows.extend(
            _summary_rows_from_metrics(metrics, tool_id="(oracle_only)", partition="cohort_wide")
        )

    for tool_id in tool_ids:
        metrics = _aggregate_null_metrics(per_case_all, tool_id=tool_id)
        summary_rows.extend(
            _summary_rows_from_metrics(metrics, tool_id=tool_id, partition="cohort_wide")
        )

    summary_path = output_dir / "null_control_summary.csv"
    report_path = output_dir / "null_control_report.md"
    table_tex_path = table_dir / "table_null_control.tex"

    _write_csv(summary_path, SUMMARY_COLUMNS, summary_rows)
    _write_null_table_tex(table_tex_path, summary_rows)

    random_metrics = _aggregate_null_metrics(per_case_all, tool_id="baseline_random")
    report_lines = [
        "# Null-cohort control report (P3)",
        "",
        "## Cohort",
        "",
        f"- **Dataset:** `{dataset_dir}`",
        f"- **Cases:** {len(case_ids) or random_metrics.get('n_cases', 0)} no-fault controls (`no_fault`)",
        "- **Construction:** faulty FSM identical to reference; oracle suite copied from 1k sources.",
        "",
        "## Question",
        "",
        "Does the metric pipeline produce apparent cohort-wide repair when there is no real repairable fault?",
        "",
        "## Results (baseline_random)",
        "",
        f"- Mean faulty BPR: **{float(random_metrics['mean_faulty_bpr']) * 100:.1f}%**",
        f"- Detection rate: **{float(random_metrics['detection_rate']) * 100:.1f}%**",
        f"- Saturation rate: **{float(random_metrics['saturation_rate']) * 100:.1f}%**",
        f"- Cohort-wide complete repair: **{float(random_metrics['cohort_wide_complete_repair_rate']) * 100:.1f}%**",
        "- Detectable-only complete repair: **NA** (detectable partition empty, n=0)",
        "- Saturation inflation: **undefined** (no detectable denominator)",
        f"- False repair rate: **{float(random_metrics['false_repair_rate']) * 100:.1f}%**",
        f"- Localization skipped: **{float(random_metrics['localization_skipped_rate']) * 100:.1f}%**",
        "",
        "## Interpretation (manuscript-ready)",
        "",
        "On the null cohort, every case is oracle-saturated and already passes the full oracle "
        "before any patch. Under cohort-wide reporting, **complete repair is therefore 100%** "
        "for all baselines including random—**not** because any engine restored behaviour, but "
        "because the metric equates pre-repair saturation with repair success. "
        "The detectable-only partition is empty, so detectable-only CRR and saturation inflation "
        "are undefined. This is a **null test of the reporting metric**, not evidence of repair "
        "performance. It demonstrates that cohort-wide CRR can appear high without a genuine "
        "repairable fault whenever faults are oracle-saturated or absent.",
        "",
        f"_Generated {datetime.now(tz=UTC).isoformat()}_",
    ]
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "study": "null_control_p3",
        "dataset_dir": str(dataset_dir),
        "per_case_results": str(resolved_per_case),
        "case_count": len(case_ids) or random_metrics.get("n_cases", 0),
    }
    (output_dir / "null_control_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    return NullControlAnalysisResult(
        output_dir=output_dir,
        summary_path=summary_path,
        report_path=report_path,
        table_tex_path=table_tex_path,
        case_count=len(case_ids) or int(random_metrics.get("n_cases", 0)),
    )
