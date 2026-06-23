"""Predictive alignment analysis: operator-oracle field visibility vs saturation/detection."""

from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fsmrepairbench.oracle_surface import OracleSurfaceId, PROGRESSIVE_SURFACE_ORDER
from fsmrepairbench.oracle_surface_sensitivity import OPERATOR_FAMILY

AlignmentClass = Literal["aligned", "partial", "misaligned"]

# Field-visibility alignment rules (instrument §4, oracle_surface pass rules).
# S0 checks state only; S1 adds action; S2 adds guard; S3 adds event.
FAMILY_SURFACE_ALIGNMENT: dict[str, dict[str, AlignmentClass]] = {
    "routing": {
        "S0": "aligned",
        "S1": "aligned",
        "S2": "aligned",
        "S3": "aligned",
    },
    "guard": {
        "S0": "partial",
        "S1": "partial",
        "S2": "aligned",
        "S3": "aligned",
    },
    "action": {
        "S0": "misaligned",
        "S1": "aligned",
        "S2": "aligned",
        "S3": "aligned",
    },
    "timing": {
        "S0": "misaligned",
        "S1": "misaligned",
        "S2": "misaligned",
        "S3": "misaligned",
    },
    "reachability": {
        "S0": "misaligned",
        "S1": "misaligned",
        "S2": "misaligned",
        "S3": "misaligned",
    },
    "nondeterminism": {
        "S0": "misaligned",
        "S1": "misaligned",
        "S2": "misaligned",
        "S3": "misaligned",
    },
}

SURFACE_IDS: tuple[str, ...] = tuple(surface.value for surface in PROGRESSIVE_SURFACE_ORDER)

FAMILY_SUMMARY_COLUMNS: tuple[str, ...] = (
    "dataset",
    "surface_id",
    "operator_family",
    "case_count",
    "alignment_class",
    "predicted_saturation_rate",
    "observed_saturation_rate",
    "predicted_detection_rate",
    "observed_detection_rate",
    "saturation_rate_error",
    "detection_rate_error",
    "saturation_membership_accuracy",
    "detection_membership_accuracy",
)

MODEL_COLUMNS: tuple[str, ...] = (
    "rule",
    "alignment_class",
    "predicted_saturated",
    "predicted_detected",
    "empirical_saturation_rate_1k",
    "empirical_detection_rate_1k",
    "n_cases_1k",
)

METRIC_COLUMNS: tuple[str, ...] = (
    "dataset",
    "surface_id",
    "scope",
    "n_cases",
    "saturation_accuracy",
    "saturation_precision",
    "saturation_recall",
    "saturation_f1",
    "detection_accuracy",
    "detection_precision",
    "detection_recall",
    "detection_f1",
    "saturation_brier",
    "detection_brier",
    "family_rate_mae",
)


@dataclass(frozen=True)
class PredictiveAlignmentResult:
    output_dir: Path
    family_summary_path: Path
    model_path: Path
    metrics_path: Path
    report_path: Path
    table_tex_path: Path


class PredictiveAlignmentError(RuntimeError):
    """Raised when predictive alignment analysis cannot complete."""


def alignment_for(family: str, surface_id: str) -> AlignmentClass:
    return FAMILY_SURFACE_ALIGNMENT.get(family, {}).get(surface_id, "misaligned")


def predict_saturated(alignment: AlignmentClass) -> bool:
    return alignment == "misaligned"


def predict_detected(alignment: AlignmentClass) -> bool | None:
    if alignment == "aligned":
        return True
    if alignment == "misaligned":
        return False
    return None


def predict_saturation_rate(alignment: AlignmentClass, *, empirical_partial: float = 0.143478) -> float:
    if alignment == "misaligned":
        return 1.0
    if alignment == "aligned":
        return 0.0
    return empirical_partial


def predict_detection_rate(alignment: AlignmentClass, *, empirical_partial: float = 0.856522) -> float:
    if alignment == "misaligned":
        return 0.0
    if alignment == "aligned":
        return 1.0
    return empirical_partial


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


def _surface_case_rows(per_case_path: Path, surface_id: str) -> list[dict[str, Any]]:
    suffix = surface_id.lower()
    rows: list[dict[str, Any]] = []
    for row in _read_csv(per_case_path):
        rows.append(
            {
                "case_id": row["case_id"],
                "mutation_operator": row["mutation_operator"],
                "operator_family": row.get("operator_family")
                or OPERATOR_FAMILY.get(row["mutation_operator"], "other"),
                "detected": _bool(row[f"detected_{suffix}"]),
                "saturated": _bool(row[f"saturated_{suffix}"]),
                "faulty_bpr": float(row[f"faulty_bpr_{suffix}"]),
            }
        )
    return rows


def _family_aggregate_rows(
    dataset: str,
    surface_id: str,
    case_rows: list[dict[str, Any]],
    *,
    partial_saturation_prior: float,
    partial_detection_prior: float,
) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in case_rows:
        by_family[str(row["operator_family"])].append(row)

    output: list[dict[str, Any]] = []
    for family in sorted(by_family):
        group = by_family[family]
        alignment = alignment_for(family, surface_id)
        n = len(group)
        observed_sat = sum(1 for row in group if row["saturated"]) / n if n else 0.0
        observed_det = sum(1 for row in group if row["detected"]) / n if n else 0.0
        pred_sat = predict_saturation_rate(
            alignment,
            empirical_partial=partial_saturation_prior,
        )
        pred_det = predict_detection_rate(
            alignment,
            empirical_partial=partial_detection_prior,
        )
        pred_sat_bool = predict_saturated(alignment)
        pred_det_bool = predict_detected(alignment)
        sat_hits = sum(
            1 for row in group if row["saturated"] == pred_sat_bool
        )
        det_eval = [row for row in group if pred_det_bool is not None]
        det_hits = sum(1 for row in det_eval if row["detected"] == pred_det_bool)
        output.append(
            {
                "dataset": dataset,
                "surface_id": surface_id,
                "operator_family": family,
                "case_count": n,
                "alignment_class": alignment,
                "predicted_saturation_rate": round(pred_sat, 6),
                "observed_saturation_rate": round(observed_sat, 6),
                "predicted_detection_rate": round(pred_det, 6),
                "observed_detection_rate": round(observed_det, 6),
                "saturation_rate_error": round(abs(pred_sat - observed_sat), 6),
                "detection_rate_error": round(abs(pred_det - observed_det), 6),
                "saturation_membership_accuracy": round(sat_hits / n, 6) if n else 0.0,
                "detection_membership_accuracy": round(
                    det_hits / len(det_eval), 6
                )
                if det_eval
                else None,
            }
        )
    return output


def _case_level_metrics(
    dataset: str,
    surface_id: str,
    case_rows: list[dict[str, Any]],
    *,
    scope: str,
    partial_saturation_prior: float,
    partial_detection_prior: float,
) -> dict[str, Any]:
    sat_tp = sat_tn = sat_fp = sat_fn = 0
    det_tp = det_tn = det_fp = det_fn = 0
    sat_brier_sum = 0.0
    det_brier_sum = 0.0
    det_scored = 0

    for row in case_rows:
        family = str(row["operator_family"])
        alignment = alignment_for(family, surface_id)
        pred_sat_prob = predict_saturation_rate(
            alignment,
            empirical_partial=partial_saturation_prior,
        )
        pred_det_prob = predict_detection_rate(
            alignment,
            empirical_partial=partial_detection_prior,
        )
        actual_sat = int(row["saturated"])
        actual_det = int(row["detected"])
        pred_sat = int(predict_saturated(alignment))
        pred_det_opt = predict_detected(alignment)

        sat_brier_sum += (pred_sat_prob - actual_sat) ** 2
        det_brier_sum += (pred_det_prob - actual_det) ** 2

        if pred_sat and actual_sat:
            sat_tp += 1
        elif not pred_sat and not actual_sat:
            sat_tn += 1
        elif pred_sat and not actual_sat:
            sat_fp += 1
        else:
            sat_fn += 1

        if pred_det_opt is not None:
            pred_det = int(pred_det_opt)
            det_scored += 1
            if pred_det and actual_det:
                det_tp += 1
            elif not pred_det and not actual_det:
                det_tn += 1
            elif pred_det and not actual_det:
                det_fp += 1
            else:
                det_fn += 1

    n = len(case_rows)

    def _safe_div(num: int, den: int) -> float:
        return round(num / den, 6) if den else 0.0

    sat_precision = _safe_div(sat_tp, sat_tp + sat_fp)
    sat_recall = _safe_div(sat_tp, sat_tp + sat_fn)
    sat_f1 = (
        round(2 * sat_precision * sat_recall / (sat_precision + sat_recall), 6)
        if sat_precision + sat_recall
        else 0.0
    )
    det_precision = _safe_div(det_tp, det_tp + det_fp)
    det_recall = _safe_div(det_tp, det_tp + det_fn)
    det_f1 = (
        round(2 * det_precision * det_recall / (det_precision + det_recall), 6)
        if det_precision + det_recall
        else 0.0
    )

    return {
        "dataset": dataset,
        "surface_id": surface_id,
        "scope": scope,
        "n_cases": n,
        "saturation_accuracy": _safe_div(sat_tp + sat_tn, n),
        "saturation_precision": sat_precision,
        "saturation_recall": sat_recall,
        "saturation_f1": sat_f1,
        "detection_accuracy": _safe_div(det_tp + det_tn, det_scored),
        "detection_precision": det_precision,
        "detection_recall": det_recall,
        "detection_f1": det_f1,
        "saturation_brier": round(sat_brier_sum / n, 6) if n else 0.0,
        "detection_brier": round(det_brier_sum / n, 6) if n else 0.0,
        "family_rate_mae": None,
    }


def _build_model_table(
    family_summary_1k: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for alignment in ("misaligned", "partial", "aligned"):
        subset = [
            row
            for row in family_summary_1k
            if row["alignment_class"] == alignment and row["surface_id"] == "S0"
        ]
        if not subset:
            continue
        n = sum(int(row["case_count"]) for row in subset)
        obs_sat = sum(
            float(row["observed_saturation_rate"]) * int(row["case_count"]) for row in subset
        ) / n
        obs_det = sum(
            float(row["observed_detection_rate"]) * int(row["case_count"]) for row in subset
        ) / n
        rows.append(
            {
                "rule": "field_visibility_alignment",
                "alignment_class": alignment,
                "predicted_saturated": predict_saturated(alignment),  # type: ignore[arg-type]
                "predicted_detected": predict_detected(alignment),  # type: ignore[arg-type]
                "empirical_saturation_rate_1k": round(obs_sat, 6),
                "empirical_detection_rate_1k": round(obs_det, 6),
                "n_cases_1k": n,
            }
        )
    return rows


def _cross_family_validation(
    train_family_summary: list[dict[str, Any]],
    holdout_family_summary: list[dict[str, Any]],
    *,
    surface_id: str,
) -> dict[str, Any]:
    train = {
        row["operator_family"]: row
        for row in train_family_summary
        if row["surface_id"] == surface_id
    }
    errors: list[float] = []
    for row in holdout_family_summary:
        if row["surface_id"] != surface_id:
            continue
        family = row["operator_family"]
        if family not in train:
            continue
        pred_sat = float(train[family]["predicted_saturation_rate"])
        obs_sat = float(row["observed_saturation_rate"])
        errors.append(abs(pred_sat - obs_sat))
    return {
        "surface_id": surface_id,
        "holdout_dataset": "multifamily_v0_3",
        "family_saturation_mae": round(sum(errors) / len(errors), 6) if errors else None,
        "families_scored": len(errors),
    }


def _write_report(path: Path, *, sections: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")


def _write_alignment_table_tex(path: Path, family_summary: list[dict[str, Any]]) -> None:
    s0_rows = [row for row in family_summary if row["surface_id"] == "S0" and row["dataset"] == "fsmrepairbench_1k"]
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\caption{Predictive alignment: operator-family saturation under S0 vs field-visibility rule.}",
        "\\label{tab:predictive-alignment}",
        "\\begin{tabular}{@{}l l r r r r@{}}",
        "\\toprule",
        "Family & Alignment & $n$ & Pred.\\ sat. & Obs.\\ sat. & Sat.\\ acc. \\\\",
        "\\midrule",
    ]
    for row in sorted(s0_rows, key=lambda item: item["operator_family"]):
        fam = str(row["operator_family"]).replace("_", "\\_")
        align = str(row["alignment_class"])
        lines.append(
            f"{fam} & {align} & {row['case_count']} & "
            f"{float(row['predicted_saturation_rate']) * 100:.1f}\\% & "
            f"{float(row['observed_saturation_rate']) * 100:.1f}\\% & "
            f"{float(row['saturation_membership_accuracy']) * 100:.1f}\\% \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_predictive_alignment_analysis(
    *,
    output_dir: Path,
    table_dir: Path,
    per_case_1k: Path = Path("fsmrepairbench/results/oracle_surface_sensitivity/per_case_scores.csv"),
    per_case_multifamily: Path = Path(
        "fsmrepairbench/results/oracle_surface_sensitivity_multifamily_v0_3/per_case_scores.csv"
    ),
    family_breakdown_1k: Path = Path(
        "fsmrepairbench/results/oracle_surface_sensitivity/operator_family_breakdown.csv"
    ),
) -> PredictiveAlignmentResult:
    """Run predictive alignment analysis using frozen oracle-surface exports."""
    if not per_case_1k.is_file():
        msg = f"Missing frozen per-case scores: {per_case_1k}"
        raise PredictiveAlignmentError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)

    guard_partial_sat = 0.143478
    guard_partial_det = 0.856522
    if family_breakdown_1k.is_file():
        for row in _read_csv(family_breakdown_1k):
            if row["surface_id"] == "S0" and row["operator_family"] == "guard":
                guard_partial_sat = float(row["saturation_rate"])
                guard_partial_det = float(row["detection_rate"])

    family_summary: list[dict[str, Any]] = []
    metrics_rows: list[dict[str, Any]] = []

    for surface_id in ("S0", "S1"):
        case_rows_1k = _surface_case_rows(per_case_1k, surface_id)
        family_summary.extend(
            _family_aggregate_rows(
                "fsmrepairbench_1k",
                surface_id,
                case_rows_1k,
                partial_saturation_prior=guard_partial_sat,
                partial_detection_prior=guard_partial_det,
            )
        )
        metrics_rows.append(
            _case_level_metrics(
                "fsmrepairbench_1k",
                surface_id,
                case_rows_1k,
                scope="case_level",
                partial_saturation_prior=guard_partial_sat,
                partial_detection_prior=guard_partial_det,
            )
        )

    if per_case_multifamily.is_file():
        for surface_id in ("S0", "S1"):
            case_rows_mf = _surface_case_rows(per_case_multifamily, surface_id)
            mf_family = _family_aggregate_rows(
                "multifamily_v0_3",
                surface_id,
                case_rows_mf,
                partial_saturation_prior=guard_partial_sat,
                partial_detection_prior=guard_partial_det,
            )
            family_summary.extend(mf_family)
            metrics_rows.append(
                _case_level_metrics(
                    "multifamily_v0_3",
                    surface_id,
                    case_rows_mf,
                    scope="case_level_holdout",
                    partial_saturation_prior=guard_partial_sat,
                    partial_detection_prior=guard_partial_det,
                )
            )
            train_s0 = [row for row in family_summary if row["dataset"] == "fsmrepairbench_1k"]
            cv = _cross_family_validation(train_s0, mf_family, surface_id=surface_id)
            mae = cv["family_saturation_mae"]
            if mae is not None:
                for metric_row in metrics_rows:
                    if (
                        metric_row["dataset"] == "multifamily_v0_3"
                        and metric_row["surface_id"] == surface_id
                    ):
                        metric_row["family_rate_mae"] = mae

    model_rows = _build_model_table(
        [row for row in family_summary if row["dataset"] == "fsmrepairbench_1k"]
    )

    family_summary_path = output_dir / "predictive_alignment_summary.csv"
    model_path = output_dir / "predictive_alignment_model.csv"
    metrics_path = output_dir / "predictive_alignment_metrics.csv"
    report_path = output_dir / "predictive_alignment_report.md"
    table_tex_path = table_dir / "table_predictive_alignment.tex"

    _write_csv(family_summary_path, FAMILY_SUMMARY_COLUMNS, family_summary)
    _write_csv(model_path, MODEL_COLUMNS, model_rows)
    _write_csv(metrics_path, METRIC_COLUMNS, metrics_rows)
    _write_alignment_table_tex(table_tex_path, family_summary)

    s0_metrics = next(
        row for row in metrics_rows if row["dataset"] == "fsmrepairbench_1k" and row["surface_id"] == "S0"
    )
    s1_metrics = next(
        row for row in metrics_rows if row["dataset"] == "fsmrepairbench_1k" and row["surface_id"] == "S1"
    )
    mf_row = next(
        (row for row in metrics_rows if row["dataset"] == "multifamily_v0_3" and row["surface_id"] == "S0"),
        None,
    )

    report_sections = [
        "# Predictive alignment report (P3)",
        "",
        "## Question",
        "",
        "Can oracle saturation be predicted from whether the mutated field is visible under the oracle surface?",
        "",
        "## Rule-based model",
        "",
        "- **Misaligned** (action/timing/reachability/nondeterminism under S0): predict saturated, not detectable.",
        "- **Aligned** (routing under all surfaces; action under S1+): predict detectable, not saturated.",
        "- **Partial** (guard under S0/S1): calibrate to empirical guard-family rates from the 1k cohort.",
        "",
        "## Case-level metrics (1k cohort)",
        "",
        f"- **S0 saturation accuracy:** {float(s0_metrics['saturation_accuracy']) * 100:.1f}% "
        f"(F1 {float(s0_metrics['saturation_f1']):.3f}, Brier {float(s0_metrics['saturation_brier']):.3f})",
        f"- **S0 detection accuracy** (aligned/misaligned families only): "
        f"{float(s0_metrics['detection_accuracy']) * 100:.1f}% "
        f"(F1 {float(s0_metrics['detection_f1']):.3f})",
        f"- **S1 saturation accuracy:** {float(s1_metrics['saturation_accuracy']) * 100:.1f}%",
        "",
        "## Cross-family hold-out (multifamily v0.3, S0)",
        "",
    ]
    if mf_row and mf_row.get("family_rate_mae") is not None:
        report_sections.append(
            f"- Family-level saturation rate MAE: **{float(mf_row['family_rate_mae']) * 100:.2f} pp** "
            f"({mf_row['n_cases']} cases)."
        )
    else:
        report_sections.append("- Multifamily hold-out not available.")

    report_sections.extend(
        [
            "",
            "## Interpretation (manuscript-ready)",
            "",
            "Saturation **magnitude** varies with operator-family saturation mass on the cohort, "
            "but **membership** (saturated vs detectable under a fixed surface) is largely predictable "
            "from operator-oracle field alignment: misaligned families saturate at ~100% under S0, "
            "aligned routing remains detectable, and guard sits between the two. "
            "Extending the oracle surface to S1 converts action-family misalignment into alignment, "
            "collapsing action saturation without changing the underlying mutation. "
            "This supports treating saturation as a measurement consequence of alignment rules, "
            "not as an engine capability or tautological definition—while **not** claiming industrial "
            "validity beyond the synthetic stratified laboratory scope.",
            "",
            f"_Generated {datetime.now(tz=UTC).isoformat()}_",
        ]
    )
    _write_report(report_path, sections=report_sections)

    manifest = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "study": "predictive_alignment_p3",
        "inputs": {
            "per_case_1k": str(per_case_1k),
            "per_case_multifamily": str(per_case_multifamily),
            "family_breakdown_1k": str(family_breakdown_1k),
        },
        "guard_partial_priors": {
            "saturation_rate": guard_partial_sat,
            "detection_rate": guard_partial_det,
        },
    }
    (output_dir / "predictive_alignment_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )

    return PredictiveAlignmentResult(
        output_dir=output_dir,
        family_summary_path=family_summary_path,
        model_path=model_path,
        metrics_path=metrics_path,
        report_path=report_path,
        table_tex_path=table_tex_path,
    )
