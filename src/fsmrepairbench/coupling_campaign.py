"""Higher-order coupling campaign orchestration for RQ4."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import zlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.analytics import _save_bar_plot
from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.higher_order_mutation import (
    HigherOrderMutationError,
    analyze_case_coupling,
    analyze_dataset_coupling,
    dataset_coupling_report_to_dict,
    mutate_higher_order,
    write_dataset_coupling_report,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.patch import PatchError, apply_patch
from fsmrepairbench.repair_engines.baselines import propose_baseline_patch
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.statistics import (
    append_ci_section_to_report,
    compute_rq4_confidence_intervals,
    write_confidence_interval_exports,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

DEFAULT_CAMPAIGN_SEED = 44
DEFAULT_REPAIR_ENGINE = "missing-transition"
HO_ORDERS: tuple[int, ...] = (2, 3)
CHAIN_POOL: tuple[str, ...] = (
    "wrong_target",
    "guard_flip",
    "missing_transition",
    "wrong_event",
    "wrong_source",
    "guard_weaken",
    "guard_strengthen",
    "wrong_initial_state",
)

PER_CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "source_case_id",
    "mutation_order",
    "is_higher_order",
    "primary_operator",
    "mutation_operator",
    "ho_seed",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "fault_detected",
    "first_order_components_detected",
    "first_order_components_total",
    "all_first_order_detected",
    "coupling_eligible",
    "coupling_detected",
    "complete_repair",
    "effective_repair",
    "repair_final_bpr",
    "repair_delta_bpr",
    "generation_status",
)

COUPLING_METRICS_COLUMNS: tuple[str, ...] = (
    "metric",
    "mutation_order",
    "primary_operator",
    "value",
    "count",
    "fraction",
)


class CouplingCampaignError(RuntimeError):
    """Raised when a coupling campaign cannot be completed."""


@dataclass(frozen=True)
class CaseCouplingCampaignResult:
    """Per-case coupling and repair metrics."""

    case_id: str
    source_case_id: str
    mutation_order: int
    is_higher_order: bool
    primary_operator: str
    mutation_operator: str
    ho_seed: int | None
    reference_bpr: float
    faulty_bpr: float
    bpr_delta: float
    fault_detected: bool
    first_order_components_detected: int
    first_order_components_total: int
    all_first_order_detected: bool
    coupling_eligible: bool
    coupling_detected: bool
    complete_repair: bool
    effective_repair: bool
    repair_final_bpr: float
    repair_delta_bpr: float
    generation_status: str

    def to_dict(self) -> dict[str, str | int | float | bool]:
        return {
            "case_id": self.case_id,
            "source_case_id": self.source_case_id,
            "mutation_order": self.mutation_order,
            "is_higher_order": self.is_higher_order,
            "primary_operator": self.primary_operator,
            "mutation_operator": self.mutation_operator,
            "ho_seed": self.ho_seed if self.ho_seed is not None else "",
            "reference_bpr": round(self.reference_bpr, 6),
            "faulty_bpr": round(self.faulty_bpr, 6),
            "bpr_delta": round(self.bpr_delta, 6),
            "fault_detected": self.fault_detected,
            "first_order_components_detected": self.first_order_components_detected,
            "first_order_components_total": self.first_order_components_total,
            "all_first_order_detected": self.all_first_order_detected,
            "coupling_eligible": self.coupling_eligible,
            "coupling_detected": self.coupling_detected,
            "complete_repair": self.complete_repair,
            "effective_repair": self.effective_repair,
            "repair_final_bpr": round(self.repair_final_bpr, 6),
            "repair_delta_bpr": round(self.repair_delta_bpr, 6),
            "generation_status": self.generation_status,
        }


@dataclass(frozen=True)
class CouplingCampaignResult:
    """Paths written by an RQ4 coupling campaign run."""

    dataset_dir: Path
    cohort_path: Path
    subset_dir: Path
    output_dir: Path
    per_case_path: Path
    summary_path: Path
    coupling_metrics_path: Path
    report_path: Path
    figures_dir: Path
    tables_dir: Path
    cohort_size: int
    case_count: int


def load_cohort_manifest(path: Path) -> list[str]:
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise CouplingCampaignError(msg)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def case_ho_seed(source_case_id: str, order: int, campaign_seed: int) -> int:
    digest = zlib.crc32(f"{source_case_id}:ho{order}:{campaign_seed}".encode())
    return campaign_seed + int(digest % 100_000)


def build_operator_chain(primary: str, order: int, source_case_id: str, campaign_seed: int) -> list[str]:
    if order < 1:
        msg = "Mutation order must be at least 1"
        raise CouplingCampaignError(msg)
    if order == 1:
        return [primary]
    pool = [operator for operator in CHAIN_POOL if operator in MUTATION_OPERATORS and operator != primary]
    if not pool:
        msg = f"No secondary operators available for primary '{primary}'"
        raise CouplingCampaignError(msg)
    start = zlib.crc32(f"{source_case_id}:{campaign_seed}:{order}".encode()) % len(pool)
    chain = [primary]
    for index in range(order - 1):
        chain.append(pool[(start + index) % len(pool)])
    return chain


def _copy_optional_case_files(source_dir: Path, target_dir: Path) -> None:
    for filename in ("case_features.json", "case_metadata.json"):
        source = source_dir / filename
        if source.is_file():
            shutil.copy2(source, target_dir / filename)


def _evaluate_repair(
    faulty: object,
    oracle: object,
    *,
    engine: str,
    seed: int,
) -> tuple[float, float, bool, bool]:
    from fsmrepairbench.models import FSM, OracleSuite

    assert isinstance(faulty, FSM)
    assert isinstance(oracle, OracleSuite)
    initial_bpr = score_oracle_suite(faulty, oracle).bpr
    try:
        patch = propose_baseline_patch(faulty, oracle, engine=engine, seed=seed)
        repaired = apply_patch(faulty, patch)
    except (PatchError, ValueError):
        return initial_bpr, 0.0, initial_bpr == 1.0, False
    final_bpr = score_oracle_suite(repaired, oracle).bpr
    return (
        final_bpr,
        final_bpr - initial_bpr,
        final_bpr == 1.0,
        final_bpr > initial_bpr,
    )


def _score_case_metrics(case_dir: Path, record: object | None) -> tuple[float, float, float, bool, int, int, bool, bool, bool]:
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if reference_path is None or faulty_path is None or oracle_path is None:
        return 1.0, 1.0, 0.0, False, 0, 0, False, False, False
    reference = load_fsm_json(reference_path)
    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    reference_bpr = score_oracle_suite(reference, oracle).bpr
    faulty_bpr = score_oracle_suite(faulty, oracle).bpr
    bpr_delta = reference_bpr - faulty_bpr
    fault_detected = bpr_delta > 0.0
    if record is None:
        return (
            reference_bpr,
            faulty_bpr,
            bpr_delta,
            fault_detected,
            1 if fault_detected else 0,
            1,
            fault_detected,
            False,
            fault_detected,
        )
    from fsmrepairbench.higher_order_mutation import CaseCouplingRecord

    assert isinstance(record, CaseCouplingRecord)
    coupling_eligible = bool(record.is_higher_order and record.all_first_order_detected)
    coupling_detected = bool(coupling_eligible and record.higher_order_detected)
    return (
        reference_bpr,
        faulty_bpr,
        bpr_delta,
        fault_detected,
        record.first_order_components_detected,
        record.first_order_components_total,
        record.all_first_order_detected,
        coupling_eligible,
        coupling_detected,
    )


def generate_higher_order_case(
    source_case_dir: Path,
    *,
    target_case_id: str,
    order: int,
    campaign_seed: int,
    repair_engine: str,
) -> CaseCouplingCampaignResult | None:
    metadata_path = source_case_dir / "bug_metadata.json"
    if not metadata_path.is_file():
        return None
    metadata = BugMetadata.model_validate(json.loads(metadata_path.read_text(encoding="utf-8")))
    primary = metadata.mutation_operator
    source_case_id = source_case_dir.name
    reference_path = resolve_coupling_case_file(source_case_dir, "reference_fsm.json")
    oracle_path = resolve_coupling_case_file(source_case_dir, "oracle_suite.json")
    if reference_path is None or oracle_path is None:
        return None

    reference = load_fsm_json(reference_path)
    oracle = load_oracle_suite(oracle_path)
    ho_seed = case_ho_seed(source_case_id, order, campaign_seed)
    operators = build_operator_chain(primary, order, source_case_id, campaign_seed)

    target_dir = source_case_dir.parent / target_case_id
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    try:
        faulty, ho_metadata = mutate_higher_order(reference, operators, ho_seed)
    except HigherOrderMutationError:
        shutil.rmtree(target_dir)
        return None

    (target_dir / "reference_fsm.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (target_dir / "faulty_fsm.json").write_text(
        faulty.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    shutil.copy2(oracle_path, target_dir / "oracle_suite.json")
    (target_dir / "bug_metadata.json").write_text(
        ho_metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    _copy_optional_case_files(source_case_dir, target_dir)

    record = analyze_case_coupling(target_dir)
    (
        reference_bpr,
        faulty_bpr,
        bpr_delta,
        fault_detected,
        components_detected,
        components_total,
        all_fo_detected,
        coupling_eligible,
        coupling_detected,
    ) = _score_case_metrics(target_dir, record)
    repair_final_bpr, repair_delta_bpr, complete_repair, effective_repair = _evaluate_repair(
        faulty,
        oracle,
        engine=repair_engine,
        seed=campaign_seed,
    )

    return CaseCouplingCampaignResult(
        case_id=target_case_id,
        source_case_id=source_case_id,
        mutation_order=order,
        is_higher_order=True,
        primary_operator=primary,
        mutation_operator=ho_metadata.mutation_operator,
        ho_seed=ho_seed,
        reference_bpr=reference_bpr,
        faulty_bpr=faulty_bpr,
        bpr_delta=bpr_delta,
        fault_detected=fault_detected,
        first_order_components_detected=components_detected,
        first_order_components_total=components_total,
        all_first_order_detected=all_fo_detected,
        coupling_eligible=coupling_eligible,
        coupling_detected=coupling_detected,
        complete_repair=complete_repair,
        effective_repair=effective_repair,
        repair_final_bpr=repair_final_bpr,
        repair_delta_bpr=repair_delta_bpr,
        generation_status="generated",
    )


def evaluate_first_order_case(
    case_dir: Path,
    *,
    campaign_seed: int,
    repair_engine: str,
) -> CaseCouplingCampaignResult:
    metadata_path = case_dir / "bug_metadata.json"
    metadata = BugMetadata.model_validate(json.loads(metadata_path.read_text(encoding="utf-8")))
    record = analyze_case_coupling(case_dir)
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    reference = load_fsm_json(reference_path)  # type: ignore[arg-type]
    faulty = load_fsm_json(faulty_path)  # type: ignore[arg-type]
    oracle = load_oracle_suite(oracle_path)  # type: ignore[arg-type]
    (
        reference_bpr,
        faulty_bpr,
        bpr_delta,
        fault_detected,
        components_detected,
        components_total,
        all_fo_detected,
        coupling_eligible,
        coupling_detected,
    ) = _score_case_metrics(case_dir, record)
    repair_final_bpr, repair_delta_bpr, complete_repair, effective_repair = _evaluate_repair(
        faulty,
        oracle,
        engine=repair_engine,
        seed=campaign_seed,
    )
    return CaseCouplingCampaignResult(
        case_id=case_dir.name,
        source_case_id=case_dir.name,
        mutation_order=1,
        is_higher_order=False,
        primary_operator=metadata.mutation_operator,
        mutation_operator=metadata.mutation_operator,
        ho_seed=None,
        reference_bpr=reference_bpr,
        faulty_bpr=faulty_bpr,
        bpr_delta=bpr_delta,
        fault_detected=fault_detected,
        first_order_components_detected=components_detected,
        first_order_components_total=components_total,
        all_first_order_detected=all_fo_detected,
        coupling_eligible=coupling_eligible,
        coupling_detected=coupling_detected,
        complete_repair=complete_repair,
        effective_repair=effective_repair,
        repair_final_bpr=repair_final_bpr,
        repair_delta_bpr=repair_delta_bpr,
        generation_status="source",
    )


def materialize_coupling_subset(
    dataset_dir: Path,
    case_ids: list[str],
    subset_dir: Path,
    *,
    campaign_seed: int,
    repair_engine: str,
    use_symlinks: bool = True,
) -> tuple[list[CaseCouplingCampaignResult], list[str]]:
    cases_root = subset_dir / "cases"
    if subset_dir.exists():
        shutil.rmtree(subset_dir)
    cases_root.mkdir(parents=True)

    rows: list[CaseCouplingCampaignResult] = []
    skipped_ho: list[str] = []

    for case_id in case_ids:
        source_dir = dataset_dir / "cases" / case_id
        if not source_dir.is_dir():
            msg = f"Missing source case directory: {source_dir}"
            raise CouplingCampaignError(msg)
        target_dir = cases_root / case_id
        if use_symlinks:
            target_dir.symlink_to(source_dir.resolve(), target_is_directory=True)
        else:
            shutil.copytree(source_dir, target_dir)
        rows.append(
            evaluate_first_order_case(
                target_dir,
                campaign_seed=campaign_seed,
                repair_engine=repair_engine,
            )
        )

        for order in HO_ORDERS:
            ho_case_id = f"{case_id}__ho{order}"
            generated = generate_higher_order_case(
                cases_root / case_id,
                target_case_id=ho_case_id,
                order=order,
                campaign_seed=campaign_seed,
                repair_engine=repair_engine,
            )
            if generated is None:
                skipped_ho.append(ho_case_id)
                continue
            rows.append(generated)

    manifest = {
        "experiment": "RQ4-higher-order-coupling-250",
        "source_dataset": str(dataset_dir),
        "cohort_size": len(case_ids),
        "campaign_seed": campaign_seed,
        "repair_engine": repair_engine,
        "ho_orders": list(HO_ORDERS),
        "skipped_ho_cases": skipped_ho,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (subset_dir / "subset_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return rows, skipped_ho


def _aggregate_metrics(rows: list[CaseCouplingCampaignResult]) -> list[dict[str, str | int | float]]:
    metrics: list[dict[str, str | int | float]] = []

    def _append(metric: str, value: float | int, *, order: str = "", operator: str = "") -> None:
        metrics.append(
            {
                "metric": metric,
                "mutation_order": order,
                "primary_operator": operator,
                "value": value,
                "count": "",
                "fraction": "",
            }
        )

    _append("cohort_size", len({row.source_case_id for row in rows if row.generation_status == "source"}))
    _append("total_cases", len(rows))
    fo_rows = [row for row in rows if not row.is_higher_order]
    ho_rows = [row for row in rows if row.is_higher_order]
    _append("first_order_case_count", len(fo_rows))
    _append("higher_order_case_count", len(ho_rows))

    for order in (1, 2, 3):
        group = [row for row in rows if row.mutation_order == order]
        if not group:
            continue
        detected = sum(1 for row in group if row.fault_detected)
        complete = sum(1 for row in group if row.complete_repair)
        effective = sum(1 for row in group if row.effective_repair)
        order_label = str(order)
        _append("detection_rate", round(detected / len(group), 6), order=order_label)
        _append("complete_repair_rate", round(complete / len(group), 6), order=order_label)
        _append("effective_repair_rate", round(effective / len(group), 6), order=order_label)
        _append("mean_faulty_bpr", round(sum(row.faulty_bpr for row in group) / len(group), 6), order=order_label)
        _append("mean_bpr_delta", round(sum(row.bpr_delta for row in group) / len(group), 6), order=order_label)

    eligible = [row for row in ho_rows if row.coupling_eligible]
    coupled = sum(1 for row in eligible if row.coupling_detected)
    _append(
        "coupling_effect_estimate",
        round(coupled / len(eligible), 6) if eligible else 0.0,
    )

    operators = sorted({row.primary_operator for row in rows if row.primary_operator})
    for operator in operators:
        for order in (1, 2, 3):
            group = [row for row in rows if row.primary_operator == operator and row.mutation_order == order]
            if not group:
                continue
            detected = sum(1 for row in group if row.fault_detected)
            _append(
                "detection_rate",
                round(detected / len(group), 6),
                order=str(order),
                operator=operator,
            )
            eligible_group = [row for row in group if row.coupling_eligible]
            if eligible_group:
                coupled_group = sum(1 for row in eligible_group if row.coupling_detected)
                _append(
                    "coupling_effect",
                    round(coupled_group / len(eligible_group), 6),
                    order=str(order),
                    operator=operator,
                )

    return metrics


def _write_per_case_csv(path: Path, rows: list[CaseCouplingCampaignResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(PER_CASE_COLUMNS))
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_dict())


def _write_summary_csv(
    path: Path,
    metrics: list[dict[str, str | int | float]],
    *,
    cohort_path: Path,
    campaign_seed: int,
    dataset_report: object,
) -> None:
    from fsmrepairbench.higher_order_mutation import DatasetCouplingReport

    assert isinstance(dataset_report, DatasetCouplingReport)
    path.parent.mkdir(parents=True, exist_ok=True)
    header_rows = [
        ("experiment", "RQ4-higher-order-coupling-250"),
        ("cohort_path", str(cohort_path)),
        ("campaign_seed", campaign_seed),
        ("repair_engine", DEFAULT_REPAIR_ENGINE),
        ("first_order_detection_rate", round(dataset_report.first_order_detection_rate, 6)),
        ("higher_order_detection_rate", round(dataset_report.higher_order_detection_rate, 6)),
        ("coupling_effect_estimate", round(dataset_report.coupling_effect_estimate, 6)),
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        for metric, value in header_rows:
            writer.writerow([metric, value])
        for row in metrics:
            if row["mutation_order"] or row["primary_operator"]:
                continue
            if row["metric"] in {
                "cohort_size",
                "total_cases",
                "first_order_case_count",
                "higher_order_case_count",
                "coupling_effect_estimate",
            }:
                writer.writerow([row["metric"], row["value"]])


def _write_coupling_metrics_csv(path: Path, metrics: list[dict[str, str | int | float]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(COUPLING_METRICS_COLUMNS))
        writer.writeheader()
        writer.writerows(metrics)


def _write_campaign_figures(
    figures_dir: Path,
    rows: list[CaseCouplingCampaignResult],
    metrics: list[dict[str, str | int | float]],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    order_labels = ["Order 1", "Order 2", "Order 3"]
    detection_rates: list[float] = []
    complete_rates: list[float] = []
    for order in (1, 2, 3):
        group = [row for row in rows if row.mutation_order == order]
        if not group:
            detection_rates.append(0.0)
            complete_rates.append(0.0)
            continue
        detection_rates.append(100.0 * sum(1 for row in group if row.fault_detected) / len(group))
        complete_rates.append(100.0 * sum(1 for row in group if row.complete_repair) / len(group))

    _save_bar_plot(
        figures_dir / "detection_rate_by_order.png",
        title="Fault Detection Rate by Mutation Order",
        xlabel="Mutation Order",
        ylabel="Detection Rate (%)",
        labels=order_labels,
        values=[round(value, 1) for value in detection_rates],
    )
    _save_bar_plot(
        figures_dir / "complete_repair_rate_by_order.png",
        title="Complete Repair Rate by Mutation Order",
        xlabel="Mutation Order",
        ylabel="Complete Repair Rate (%)",
        labels=order_labels,
        values=[round(value, 1) for value in complete_rates],
    )

    operators = sorted({row.primary_operator for row in rows if row.mutation_order == 2})
    if operators:
        values = []
        for operator in operators:
            group = [row for row in rows if row.primary_operator == operator and row.mutation_order == 2]
            eligible = [row for row in group if row.coupling_eligible]
            if not eligible:
                values.append(0.0)
                continue
            values.append(
                100.0 * sum(1 for row in eligible if row.coupling_detected) / len(eligible)
            )
        _save_bar_plot(
            figures_dir / "coupling_effect_by_operator_order2.png",
            title="Coupling Effect by Primary Operator (Order 2)",
            xlabel="Primary Operator",
            ylabel="Coupling Effect (%)",
            labels=operators,
            values=[round(value, 1) for value in values],
        )

    coupling_overall = next(
        (float(row["value"]) for row in metrics if row["metric"] == "coupling_effect_estimate" and not row["mutation_order"]),
        0.0,
    )
    _save_bar_plot(
        figures_dir / "coupling_effect_overall.png",
        title="Overall Coupling Effect Estimate",
        xlabel="Metric",
        ylabel="Rate (%)",
        labels=["Coupling effect"],
        values=[round(100.0 * coupling_overall, 1)],
    )


def _write_publication_tables(
    tables_dir: Path,
    rows: list[CaseCouplingCampaignResult],
    metrics: list[dict[str, str | int | float]],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        "% Auto-generated by run-coupling-campaign",
        "\\begin{tabular}{@{}lrrrrr@{}}",
        "\\toprule",
        "Order & Cases & Detection & Complete repair & Effective repair & Mean $\\Delta$BPR \\\\",
        "\\midrule",
    ]
    for order in (1, 2, 3):
        group = [row for row in rows if row.mutation_order == order]
        if not group:
            continue
        detected = sum(1 for row in group if row.fault_detected) / len(group)
        complete = sum(1 for row in group if row.complete_repair) / len(group)
        effective = sum(1 for row in group if row.effective_repair) / len(group)
        mean_delta = sum(row.bpr_delta for row in group) / len(group)
        summary_lines.append(
            f"{order} & {len(group)} & {100 * detected:.1f}\\% & {100 * complete:.1f}\\% & "
            f"{100 * effective:.1f}\\% & {mean_delta:.3f} \\\\"
        )
    coupling = next(
        (float(row["value"]) for row in metrics if row["metric"] == "coupling_effect_estimate" and not row["mutation_order"]),
        0.0,
    )
    summary_lines.extend(
        [
            "\\midrule",
            f"\\multicolumn{{6}}{{l}}{{Coupling effect estimate (HO, all components detected): {100 * coupling:.1f}\\%}} \\\\",
            "\\bottomrule",
            "\\end{tabular}",
            "",
        ]
    )
    (tables_dir / "table_coupling_summary.tex").write_text("\n".join(summary_lines), encoding="utf-8")

    operator_lines = [
        "% Auto-generated by run-coupling-campaign",
        "\\begin{tabular}{@{}lrrr@{}}",
        "\\toprule",
        "Primary operator & Order-1 detection & Order-2 detection & Order-3 detection \\\\",
        "\\midrule",
    ]
    for operator in sorted({row.primary_operator for row in rows}):
        cells = [operator.replace("_", "\\_")]
        for order in (1, 2, 3):
            group = [row for row in rows if row.primary_operator == operator and row.mutation_order == order]
            if not group:
                cells.append("--")
                continue
            rate = sum(1 for row in group if row.fault_detected) / len(group)
            cells.append(f"{100 * rate:.1f}\\%")
        operator_lines.append(" & ".join(cells) + " \\\\")
    operator_lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (tables_dir / "table_detection_by_operator_order.tex").write_text(
        "\n".join(operator_lines), encoding="utf-8"
    )

    repair_lines = [
        "% Auto-generated by run-coupling-campaign",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Order & Cases & Complete repair & Effective repair & Mean faulty BPR \\\\",
        "\\midrule",
    ]
    for order in (1, 2, 3):
        group = [row for row in rows if row.mutation_order == order]
        if not group:
            continue
        complete = sum(1 for row in group if row.complete_repair) / len(group)
        effective = sum(1 for row in group if row.effective_repair) / len(group)
        mean_faulty = sum(row.faulty_bpr for row in group) / len(group)
        repair_lines.append(
            f"{order} & {len(group)} & {100 * complete:.1f}\\% & {100 * effective:.1f}\\% & {mean_faulty:.3f} \\\\"
        )
    repair_lines.extend(["\\bottomrule", "\\end{tabular}", ""])
    (tables_dir / "table_repair_by_order.tex").write_text("\n".join(repair_lines), encoding="utf-8")


def write_coupling_report(
    path: Path,
    *,
    dataset_dir: Path,
    cohort_path: Path,
    subset_dir: Path,
    output_dir: Path,
    rows: list[CaseCouplingCampaignResult],
    metrics: list[dict[str, str | int | float]],
    dataset_report: object,
    campaign_seed: int,
    skipped_ho: list[str],
) -> None:
    from fsmrepairbench.higher_order_mutation import DatasetCouplingReport

    assert isinstance(dataset_report, DatasetCouplingReport)
    lines = [
        "# RQ4 Higher-Order Coupling Campaign",
        "",
        "Higher-order mutants (orders 2 and 3) were generated on the pinned 250-case cohort",
        "by chaining the source first-order operator with deterministic secondary operators",
        f"(campaign seed {campaign_seed}).",
        "",
        "## Experimental design",
        "",
        f"- **Source dataset:** `{dataset_dir}`",
        f"- **Cohort:** `{cohort_path.name}` (250 cases)",
        f"- **Enriched subset:** `{subset_dir}`",
        f"- **Repair baseline:** `{DEFAULT_REPAIR_ENGINE}` (seed {campaign_seed})",
        "",
        "## Aggregate metrics",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Total analyzed cases | {dataset_report.case_count} |",
        f"| First-order cases | {dataset_report.first_order_case_count} |",
        f"| Higher-order cases | {dataset_report.higher_order_case_count} |",
        f"| First-order detection rate | {dataset_report.first_order_detection_rate:.2%} |",
        f"| Higher-order detection rate | {dataset_report.higher_order_detection_rate:.2%} |",
        f"| Coupling effect estimate | {dataset_report.coupling_effect_estimate:.2%} |",
        f"| Skipped HO generations | {len(skipped_ho)} |",
        "",
        "## Detection and repair by mutation order",
        "",
        "| Order | Cases | Detection | Complete repair | Effective repair | Mean faulty BPR | Mean $\\Delta$BPR |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for order in (1, 2, 3):
        group = [row for row in rows if row.mutation_order == order]
        if not group:
            continue
        detected = sum(1 for row in group if row.fault_detected) / len(group)
        complete = sum(1 for row in group if row.complete_repair) / len(group)
        effective = sum(1 for row in group if row.effective_repair) / len(group)
        mean_faulty = sum(row.faulty_bpr for row in group) / len(group)
        mean_delta = sum(row.bpr_delta for row in group) / len(group)
        lines.append(
            f"| {order} | {len(group)} | {detected:.2%} | {complete:.2%} | {effective:.2%} | "
            f"{mean_faulty:.3f} | {mean_delta:.3f} |"
        )

    lines.extend(
        [
            "",
            "## Figures",
            "",
            "![Detection by order](figures/detection_rate_by_order.png)",
            "",
            "![Complete repair by order](figures/complete_repair_rate_by_order.png)",
            "",
            "![Coupling effect by operator (order 2)](figures/coupling_effect_by_operator_order2.png)",
            "",
            "## Artifacts",
            "",
            f"- Summary: `{output_dir / 'summary.csv'}`",
            f"- Coupling metrics: `{output_dir / 'coupling_metrics.csv'}`",
            f"- Per-case results: `{output_dir / 'per_case_results.csv'}`",
            f"- Confidence intervals: `{output_dir / 'confidence_intervals.csv'}`",
            f"- Coupling report JSON: `{output_dir / 'coupling_report.json'}`",
            f"- LaTeX tables: `{output_dir / 'tables'}/`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_coupling_campaign(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_path: Path | None = None,
    subset_dir: Path | None = None,
    campaign_seed: int = DEFAULT_CAMPAIGN_SEED,
    repair_engine: str = DEFAULT_REPAIR_ENGINE,
    use_symlinks: bool = True,
) -> CouplingCampaignResult:
    """Run RQ4 higher-order coupling campaign on a pinned cohort."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise CouplingCampaignError(msg)

    cohort = cohort_path or (dataset_dir / "coupling_campaign_250.txt")
    case_ids = load_cohort_manifest(cohort)
    out = output_dir or Path("results/rq4_coupling_250")
    workspace = subset_dir or Path("results/rq4_coupling_subset")

    rows, skipped_ho = materialize_coupling_subset(
        dataset_dir,
        case_ids,
        workspace,
        campaign_seed=campaign_seed,
        repair_engine=repair_engine,
        use_symlinks=use_symlinks,
    )
    dataset_report = analyze_dataset_coupling(workspace)
    metrics = _aggregate_metrics(rows)

    out.mkdir(parents=True, exist_ok=True)
    per_case_path = out / "per_case_results.csv"
    summary_path = out / "summary.csv"
    coupling_metrics_path = out / "coupling_metrics.csv"
    report_path = out / "report.md"
    figures_dir = out / "figures"
    tables_dir = out / "tables"
    coupling_json = out / "coupling_report.json"

    _write_per_case_csv(per_case_path, rows)
    _write_summary_csv(
        summary_path,
        metrics,
        cohort_path=cohort,
        campaign_seed=campaign_seed,
        dataset_report=dataset_report,
    )
    _write_coupling_metrics_csv(coupling_metrics_path, metrics)
    write_dataset_coupling_report(coupling_json, dataset_report)
    _write_campaign_figures(figures_dir, rows, metrics)
    _write_publication_tables(tables_dir, rows, metrics)
    write_coupling_report(
        report_path,
        dataset_dir=dataset_dir,
        cohort_path=cohort,
        subset_dir=workspace,
        output_dir=out,
        rows=rows,
        metrics=metrics,
        dataset_report=dataset_report,
        campaign_seed=campaign_seed,
        skipped_ho=skipped_ho,
    )

    ci_rows = compute_rq4_confidence_intervals(rows)
    write_confidence_interval_exports(
        out,
        campaign="RQ4-coupling",
        rows=ci_rows,
    )
    append_ci_section_to_report(report_path, ci_rows)

    cohort_digest = hashlib.sha256(cohort.read_bytes()).hexdigest()
    manifest = {
        "experiment": "RQ4-higher-order-coupling-250",
        "dataset_dir": str(dataset_dir),
        "cohort_path": str(cohort),
        "cohort_sha256": cohort_digest,
        "subset_dir": str(workspace),
        "output_dir": str(out),
        "campaign_seed": campaign_seed,
        "repair_engine": repair_engine,
        "dataset_coupling": dataset_coupling_report_to_dict(dataset_report),
        "skipped_ho_generations": skipped_ho,
        "generated_at": datetime.now(UTC).isoformat(),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return CouplingCampaignResult(
        dataset_dir=dataset_dir,
        cohort_path=cohort,
        subset_dir=workspace,
        output_dir=out,
        per_case_path=per_case_path,
        summary_path=summary_path,
        coupling_metrics_path=coupling_metrics_path,
        report_path=report_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        cohort_size=len(case_ids),
        case_count=dataset_report.case_count,
    )
