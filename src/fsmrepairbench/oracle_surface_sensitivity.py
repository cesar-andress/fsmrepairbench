"""Oracle-surface sensitivity analysis on a frozen benchmark cohort."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import load_cohort_manifest
from fsmrepairbench.dataset_builder import load_dataset_cases
from fsmrepairbench.oracle_surface import (
    SURFACE_PROFILES,
    OracleSurfaceId,
    case_detected,
    case_saturated,
    score_oracle_suite_with_surface,
)
from fsmrepairbench.statistics import (
    BOOTSTRAP_SEED,
    ConfidenceIntervalRow,
    bootstrap_mean_ci,
    bootstrap_rate_ci,
    confidence_interval_rows_to_dicts,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

OPERATOR_FAMILY: dict[str, str] = {
    "missing_transition": "routing",
    "wrong_source": "routing",
    "wrong_target": "routing",
    "wrong_event": "routing",
    "wrong_initial_state": "routing",
    "guard_flip": "guard",
    "guard_strengthen": "guard",
    "guard_weaken": "guard",
    "guard_inter_class": "guard",
    "action_corruption": "action",
    "action_full_mutation": "action",
    "delay_corruption": "timing",
    "timeout_corruption": "timing",
    "dead_state_intro": "reachability",
    "unreachable_state_intro": "reachability",
    "duplicate_transition": "nondeterminism",
    "nondeterminism_intro": "nondeterminism",
}

CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "mutation_operator",
    "operator_family",
    "reference_bpr_s0",
    "faulty_bpr_s0",
    "bpr_delta_s0",
    "detected_s0",
    "saturated_s0",
    "reference_bpr_s1",
    "faulty_bpr_s1",
    "bpr_delta_s1",
    "detected_s1",
    "saturated_s1",
    "partition_change",
    "saturation_change",
    "detection_gain",
    "detection_loss",
)

SUMMARY_COLUMNS: tuple[str, ...] = (
    "surface_id",
    "surface_label",
    "case_count",
    "overall_detection_rate",
    "saturation_count",
    "saturation_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
)

OPERATOR_COLUMNS: tuple[str, ...] = (
    "surface_id",
    "mutation_operator",
    "operator_family",
    "case_count",
    "detection_rate",
    "saturation_count",
    "saturation_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
)

FAMILY_COLUMNS: tuple[str, ...] = (
    "surface_id",
    "operator_family",
    "case_count",
    "detection_rate",
    "saturation_count",
    "saturation_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
)

PARTITION_COLUMNS: tuple[str, ...] = (
    "case_id",
    "mutation_operator",
    "operator_family",
    "change_type",
    "detected_s0",
    "detected_s1",
    "saturated_s0",
    "saturated_s1",
    "faulty_bpr_s0",
    "faulty_bpr_s1",
)

FAMILY_TRANSITION_COLUMNS: tuple[str, ...] = (
    "operator_family",
    "case_count",
    "partition_transitions",
    "detection_gains",
    "detection_losses",
    "saturation_transitions",
    "detection_rate_s0",
    "detection_rate_s1",
    "saturation_rate_s0",
    "saturation_rate_s1",
)


@dataclass(frozen=True)
class SurfaceCaseScore:
    case_id: str
    mutation_operator: str
    operator_family: str
    reference_bpr: float
    faulty_bpr: float
    bpr_delta: float
    detected: bool
    saturated: bool


@dataclass(frozen=True)
class OracleSurfaceSensitivityResult:
    dataset_dir: Path
    output_dir: Path
    case_count: int
    per_case_path: Path
    summary_path: Path
    operator_path: Path
    family_path: Path
    partition_changes_path: Path
    partition_transitions_path: Path
    family_transitions_path: Path
    confidence_intervals_path: Path


class OracleSurfaceSensitivityError(RuntimeError):
    """Raised when oracle-surface sensitivity analysis cannot complete."""


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _score_case(case_dir: Path, *, operator: str, surface_id: OracleSurfaceId) -> SurfaceCaseScore:
    reference = load_fsm_json(case_dir / "reference_fsm.json")
    faulty = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle = load_oracle_suite(case_dir / "oracle_suite.json")
    profile = SURFACE_PROFILES[surface_id]
    reference_bpr = score_oracle_suite_with_surface(
        reference,
        oracle,
        reference=reference,
        profile=profile,
    ).bpr
    faulty_bpr = score_oracle_suite_with_surface(
        faulty,
        oracle,
        reference=reference,
        profile=profile,
    ).bpr
    bpr_delta = reference_bpr - faulty_bpr
    return SurfaceCaseScore(
        case_id=case_dir.name,
        mutation_operator=operator,
        operator_family=OPERATOR_FAMILY.get(operator, "other"),
        reference_bpr=round(reference_bpr, 6),
        faulty_bpr=round(faulty_bpr, 6),
        bpr_delta=round(bpr_delta, 6),
        detected=case_detected(reference_bpr, faulty_bpr),
        saturated=case_saturated(faulty_bpr),
    )


def _aggregate_surface_rows(cases: list[SurfaceCaseScore], surface_id: OracleSurfaceId) -> dict[str, Any]:
    total = len(cases)
    detected = sum(1 for case in cases if case.detected)
    saturated = sum(1 for case in cases if case.saturated)
    return {
        "surface_id": surface_id.value,
        "surface_label": SURFACE_PROFILES[surface_id].label,
        "case_count": total,
        "overall_detection_rate": round(detected / total, 6) if total else 0.0,
        "saturation_count": saturated,
        "saturation_rate": round(saturated / total, 6) if total else 0.0,
        "mean_faulty_bpr": round(sum(case.faulty_bpr for case in cases) / total, 6) if total else 0.0,
        "mean_bpr_delta": round(sum(case.bpr_delta for case in cases) / total, 6) if total else 0.0,
    }


def _operator_rows(cases: list[SurfaceCaseScore], surface_id: OracleSurfaceId) -> list[dict[str, Any]]:
    by_operator: dict[str, list[SurfaceCaseScore]] = {}
    for case in cases:
        by_operator.setdefault(case.mutation_operator, []).append(case)
    rows: list[dict[str, Any]] = []
    for operator in sorted(by_operator):
        group = by_operator[operator]
        total = len(group)
        detected = sum(1 for case in group if case.detected)
        saturated = sum(1 for case in group if case.saturated)
        rows.append(
            {
                "surface_id": surface_id.value,
                "mutation_operator": operator,
                "operator_family": OPERATOR_FAMILY.get(operator, "other"),
                "case_count": total,
                "detection_rate": round(detected / total, 6) if total else 0.0,
                "saturation_count": saturated,
                "saturation_rate": round(saturated / total, 6) if total else 0.0,
                "mean_faulty_bpr": round(sum(case.faulty_bpr for case in group) / total, 6),
                "mean_bpr_delta": round(sum(case.bpr_delta for case in group) / total, 6),
            }
        )
    return rows


def _family_rows(cases: list[SurfaceCaseScore], surface_id: OracleSurfaceId) -> list[dict[str, Any]]:
    by_family: dict[str, list[SurfaceCaseScore]] = {}
    for case in cases:
        by_family.setdefault(case.operator_family, []).append(case)
    rows: list[dict[str, Any]] = []
    for family in sorted(by_family):
        group = by_family[family]
        total = len(group)
        detected = sum(1 for case in group if case.detected)
        saturated = sum(1 for case in group if case.saturated)
        rows.append(
            {
                "surface_id": surface_id.value,
                "operator_family": family,
                "case_count": total,
                "detection_rate": round(detected / total, 6) if total else 0.0,
                "saturation_count": saturated,
                "saturation_rate": round(saturated / total, 6) if total else 0.0,
                "mean_faulty_bpr": round(sum(case.faulty_bpr for case in group) / total, 6),
                "mean_bpr_delta": round(sum(case.bpr_delta for case in group) / total, 6),
            }
        )
    return rows


def _partition_change_rows(
    s0_cases: dict[str, SurfaceCaseScore],
    s1_cases: dict[str, SurfaceCaseScore],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for case_id in sorted(s0_cases):
        s0 = s0_cases[case_id]
        s1 = s1_cases[case_id]
        if s0.detected == s1.detected and s0.saturated == s1.saturated:
            continue
        if s1.detected and not s0.detected:
            change_type = "detection_gain"
        elif s0.detected and not s1.detected:
            change_type = "detection_loss"
        elif s1.saturated and not s0.saturated:
            change_type = "saturation_gain"
        elif s0.saturated and not s1.saturated:
            change_type = "saturation_loss"
        else:
            change_type = "partition_shift"
        rows.append(
            {
                "case_id": case_id,
                "mutation_operator": s0.mutation_operator,
                "operator_family": s0.operator_family,
                "change_type": change_type,
                "detected_s0": s0.detected,
                "detected_s1": s1.detected,
                "saturated_s0": s0.saturated,
                "saturated_s1": s1.saturated,
                "faulty_bpr_s0": s0.faulty_bpr,
                "faulty_bpr_s1": s1.faulty_bpr,
            }
        )
    return rows


def _family_transition_rows(per_case_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_family: dict[str, list[dict[str, Any]]] = {}
    for row in per_case_rows:
        by_family.setdefault(str(row["operator_family"]), []).append(row)
    output: list[dict[str, Any]] = []
    for family in sorted(by_family):
        group = by_family[family]
        total = len(group)
        transitions = sum(1 for row in group if row["partition_change"])
        gains = sum(1 for row in group if row["detection_gain"])
        losses = sum(1 for row in group if row["detection_loss"])
        saturation_transitions = sum(1 for row in group if row["saturation_change"])
        detected_s0 = sum(1 for row in group if row["detected_s0"])
        detected_s1 = sum(1 for row in group if row["detected_s1"])
        saturated_s0 = sum(1 for row in group if row["saturated_s0"])
        saturated_s1 = sum(1 for row in group if row["saturated_s1"])
        output.append(
            {
                "operator_family": family,
                "case_count": total,
                "partition_transitions": transitions,
                "detection_gains": gains,
                "detection_losses": losses,
                "saturation_transitions": saturation_transitions,
                "detection_rate_s0": round(detected_s0 / total, 6) if total else 0.0,
                "detection_rate_s1": round(detected_s1 / total, 6) if total else 0.0,
                "saturation_rate_s0": round(saturated_s0 / total, 6) if total else 0.0,
                "saturation_rate_s1": round(saturated_s1 / total, 6) if total else 0.0,
            }
        )
    return output


def _confidence_interval_rows(
    s0_cases: list[SurfaceCaseScore],
    s1_cases: list[SurfaceCaseScore],
) -> list[ConfidenceIntervalRow]:
    rows: list[ConfidenceIntervalRow] = []
    for surface_id, cases in (
        (OracleSurfaceId.S0_PUBLISHED, s0_cases),
        (OracleSurfaceId.S1_ACTION_EXTENDED, s1_cases),
    ):
        rows.extend(
            [
                bootstrap_rate_ci(
                    [case.detected for case in cases],
                    "overall_detection_rate",
                    group="oracle-surface",
                    partition="cohort_wide",
                    subgroup=surface_id.value,
                ),
                bootstrap_rate_ci(
                    [case.saturated for case in cases],
                    "saturation_rate",
                    group="oracle-surface",
                    partition="cohort_wide",
                    subgroup=surface_id.value,
                ),
                bootstrap_mean_ci(
                    [case.faulty_bpr for case in cases],
                    "mean_faulty_bpr",
                    group="oracle-surface",
                    partition="cohort_wide",
                    subgroup=surface_id.value,
                ),
                bootstrap_mean_ci(
                    [case.bpr_delta for case in cases],
                    "mean_bpr_delta",
                    group="oracle-surface",
                    partition="cohort_wide",
                    subgroup=surface_id.value,
                ),
            ]
        )
    return rows


def run_oracle_surface_sensitivity(
    dataset_dir: Path,
    output_dir: Path,
    *,
    cohort_path: Path | None = None,
) -> OracleSurfaceSensitivityResult:
    """Rescore the frozen cohort under S0 and S1 without regenerating artefacts."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise OracleSurfaceSensitivityError(msg)

    resolved_cohort = cohort_path or (dataset_dir / "analysis_cohort_1k.txt")
    cohort_ids = load_cohort_manifest(resolved_cohort)
    index_cases = {case.case_id: case for case in load_dataset_cases(dataset_dir)}
    cases_root = dataset_dir / "cases"
    s0_scores: list[SurfaceCaseScore] = []
    s1_scores: list[SurfaceCaseScore] = []
    per_case_rows: list[dict[str, Any]] = []

    for case_id in cohort_ids:
        if case_id not in index_cases:
            msg = f"Cohort case {case_id} missing from dataset index"
            raise OracleSurfaceSensitivityError(msg)
        case_dir = cases_root / case_id
        operator = index_cases[case_id].mutation_operator
        s0 = _score_case(case_dir, operator=operator, surface_id=OracleSurfaceId.S0_PUBLISHED)
        s1 = _score_case(case_dir, operator=operator, surface_id=OracleSurfaceId.S1_ACTION_EXTENDED)
        s0_scores.append(s0)
        s1_scores.append(s1)
        per_case_rows.append(
            {
                "case_id": case_id,
                "mutation_operator": operator,
                "operator_family": s0.operator_family,
                "reference_bpr_s0": s0.reference_bpr,
                "faulty_bpr_s0": s0.faulty_bpr,
                "bpr_delta_s0": s0.bpr_delta,
                "detected_s0": s0.detected,
                "saturated_s0": s0.saturated,
                "reference_bpr_s1": s1.reference_bpr,
                "faulty_bpr_s1": s1.faulty_bpr,
                "bpr_delta_s1": s1.bpr_delta,
                "detected_s1": s1.detected,
                "saturated_s1": s1.saturated,
                "partition_change": s0.detected != s1.detected or s0.saturated != s1.saturated,
                "saturation_change": s0.saturated != s1.saturated,
                "detection_gain": s1.detected and not s0.detected,
                "detection_loss": s0.detected and not s1.detected,
            }
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    per_case_path = output_dir / "per_case_scores.csv"
    summary_path = output_dir / "surface_summary.csv"
    operator_path = output_dir / "operator_breakdown.csv"
    family_path = output_dir / "operator_family_breakdown.csv"
    partition_changes_path = output_dir / "partition_changes.csv"
    partition_transitions_path = output_dir / "partition_transitions.csv"
    family_transitions_path = output_dir / "operator_family_transitions.csv"
    confidence_intervals_path = output_dir / "confidence_intervals.csv"

    _write_csv(per_case_path, CASE_COLUMNS, per_case_rows)
    _write_csv(
        summary_path,
        SUMMARY_COLUMNS,
        [
            _aggregate_surface_rows(s0_scores, OracleSurfaceId.S0_PUBLISHED),
            _aggregate_surface_rows(s1_scores, OracleSurfaceId.S1_ACTION_EXTENDED),
        ],
    )
    _write_csv(
        operator_path,
        OPERATOR_COLUMNS,
        _operator_rows(s0_scores, OracleSurfaceId.S0_PUBLISHED)
        + _operator_rows(s1_scores, OracleSurfaceId.S1_ACTION_EXTENDED),
    )
    _write_csv(
        family_path,
        FAMILY_COLUMNS,
        _family_rows(s0_scores, OracleSurfaceId.S0_PUBLISHED)
        + _family_rows(s1_scores, OracleSurfaceId.S1_ACTION_EXTENDED),
    )

    s0_map = {case.case_id: case for case in s0_scores}
    s1_map = {case.case_id: case for case in s1_scores}
    partition_rows = _partition_change_rows(s0_map, s1_map)
    _write_csv(partition_changes_path, PARTITION_COLUMNS, partition_rows)
    _write_csv(partition_transitions_path, PARTITION_COLUMNS, partition_rows)
    _write_csv(
        family_transitions_path,
        FAMILY_TRANSITION_COLUMNS,
        _family_transition_rows(per_case_rows),
    )

    ci_rows = _confidence_interval_rows(s0_scores, s1_scores)
    ci_dicts = confidence_interval_rows_to_dicts(ci_rows)
    _write_csv(
        confidence_intervals_path,
        (
            "metric",
            "group",
            "partition",
            "subgroup",
            "n_cases",
            "mean",
            "ci95_low",
            "ci95_high",
        ),
        ci_dicts,
    )
    (output_dir / "confidence_intervals.json").write_text(
        json.dumps(ci_dicts, indent=2) + "\n",
        encoding="utf-8",
    )

    gains = sum(1 for row in per_case_rows if row["detection_gain"])
    losses = sum(1 for row in per_case_rows if row["detection_loss"])
    manifest = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "cohort_file": str(resolved_cohort),
        "case_count": len(per_case_rows),
        "bootstrap_seed": BOOTSTRAP_SEED,
        "surfaces": {
            "S0": "state + event + guard (published)",
            "S1": "state + event + guard + action",
        },
        "partition_changes": len(partition_rows),
        "detection_gains_s0_to_s1": gains,
        "detection_losses_s0_to_s1": losses,
        "saturation_changes": sum(1 for row in per_case_rows if row["saturation_change"]),
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return OracleSurfaceSensitivityResult(
        dataset_dir=dataset_dir,
        output_dir=output_dir,
        case_count=len(per_case_rows),
        per_case_path=per_case_path,
        summary_path=summary_path,
        operator_path=operator_path,
        family_path=family_path,
        partition_changes_path=partition_changes_path,
        partition_transitions_path=partition_transitions_path,
        family_transitions_path=family_transitions_path,
        confidence_intervals_path=confidence_intervals_path,
    )
