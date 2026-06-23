"""Cross-seed cohort stability study for FSMRepairBench extension experiments."""

from __future__ import annotations

import csv
import json
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from fsmrepairbench.baseline_repair_campaign import (
    DEFAULT_TOOLS_DIR,
    RANDOM_TOOL_ID,
    run_random_baseline_for_seed,
)
from fsmrepairbench.dataset_builder import load_dataset_cases
from fsmrepairbench.cohort_partition_metrics import compute_partition_metrics_from_index
from fsmrepairbench.generators.stratified_specs import load_dataset_plan
from fsmrepairbench.study_aggregates import (
    aggregate_numeric_across_seeds,
    aggregates_to_dicts,
    try_plot_multiseed_bars,
    write_aggregate_csv,
    write_aggregate_latex_table,
    write_interpretation_markdown,
    write_study_manifest,
)
from fsmrepairbench.stratified_builder import build_stratified_dataset

DEFAULT_COHORT_SEEDS: tuple[int, ...] = tuple(range(44, 144, 10))
DEFAULT_PLAN_PATH = Path("plans/fsmrepairbench_v0_1k_plan.yaml")
DEFAULT_SMOKE_PLAN_PATH = Path("plans/fsmrepairbench_v0_smoke_plan.yaml")
DEFAULT_REPAIR_SEED = 0
REPAIR_WORKERS = 4

PER_SEED_COLUMNS: tuple[str, ...] = (
    "cohort_seed",
    "case_count",
    "detection_rate",
    "saturation_rate",
    "detectable_count",
    "saturated_count",
    "structural_gt_count",
    "spectrally_participating_count",
    "spectrally_absent_count",
    "participation_rate",
    "cohort_wide_crr",
    "detectable_only_crr",
    "saturation_inflation_pp",
    "dataset_dir",
)


@dataclass(frozen=True)
class MultiseedStabilityResult:
    output_dir: Path
    per_seed_path: Path
    aggregate_path: Path
    interpretation_path: Path
    table_tex_path: Path
    figure_path: Path | None
    seed_count: int


class MultiseedStabilityError(RuntimeError):
    """Raised when the multi-seed stability study cannot complete."""


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _plan_path_for_seed(base_plan: Path, seed: int, tmp_dir: Path) -> Path:
    plan = load_dataset_plan(base_plan)
    payload = plan.model_dump(mode="json")
    payload["seed"] = seed
    payload["name"] = f"{plan.name}_seed_{seed}"
    out = tmp_dir / f"plan_seed_{seed}.yaml"
    out.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return out


def _summarize_random_repair(rows) -> tuple[float, float, float]:
    completed = [row for row in rows if row.status == "completed"]
    if not completed:
        return 0.0, 0.0, 0.0
    cohort_wide = sum(1 for row in completed if row.complete_repair) / len(completed)
    detectable = [row for row in completed if row.initial_bpr < 1.0 - 1e-9]
    detectable_only = (
        sum(1 for row in detectable if row.complete_repair) / len(detectable) if detectable else 0.0
    )
    inflation = (cohort_wide - detectable_only) * 100.0
    return round(cohort_wide, 6), round(detectable_only, 6), round(inflation, 6)


def run_multiseed_stability_study(
    *,
    output_dir: Path,
    plan_path: Path = DEFAULT_PLAN_PATH,
    cohort_seeds: tuple[int, ...] = DEFAULT_COHORT_SEEDS,
    repair_seed: int = DEFAULT_REPAIR_SEED,
    tools_dir: Path = Path(DEFAULT_TOOLS_DIR),
    workers: int = REPAIR_WORKERS,
    skip_build: bool = False,
    skip_repair: bool = False,
) -> MultiseedStabilityResult:
    """Build independent cohorts and aggregate stability metrics across seeds."""
    output_dir.mkdir(parents=True, exist_ok=True)
    cohorts_root = output_dir / "cohorts"
    cohorts_root.mkdir(parents=True, exist_ok=True)
    per_seed_rows: list[dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="multiseed_plans_") as tmp:
        tmp_dir = Path(tmp)
        for cohort_seed in cohort_seeds:
            dataset_dir = cohorts_root / f"seed_{cohort_seed:04d}"
            if not skip_build or not dataset_dir.is_dir():
                seed_plan = _plan_path_for_seed(plan_path, cohort_seed, tmp_dir)
                build_stratified_dataset(seed_plan, dataset_dir)

            partition = compute_partition_metrics_from_index(dataset_dir)
            cohort_wide_crr = 0.0
            detectable_only_crr = 0.0
            inflation_pp = 0.0
            if not skip_repair:
                case_ids = {case.case_id for case in load_dataset_cases(dataset_dir)}
                repair_rows = run_random_baseline_for_seed(
                    dataset_dir,
                    tools_dir,
                    case_ids,
                    repair_seed,
                    workers=workers,
                    output_dir=output_dir / "repair_runs" / f"seed_{cohort_seed:04d}",
                )
                cohort_wide_crr, detectable_only_crr, inflation_pp = _summarize_random_repair(
                    repair_rows
                )

            per_seed_rows.append(
                {
                    "cohort_seed": cohort_seed,
                    "case_count": partition.case_count,
                    "detection_rate": partition.detection_rate,
                    "saturation_rate": partition.saturation_rate,
                    "detectable_count": partition.detectable_count,
                    "saturated_count": partition.saturated_count,
                    "structural_gt_count": partition.structural_gt_count,
                    "spectrally_participating_count": partition.spectrally_participating_count,
                    "spectrally_absent_count": partition.spectrally_absent_count,
                    "participation_rate": partition.participation_rate,
                    "cohort_wide_crr": cohort_wide_crr,
                    "detectable_only_crr": detectable_only_crr,
                    "saturation_inflation_pp": inflation_pp,
                    "dataset_dir": str(dataset_dir),
                }
            )

    per_seed_path = output_dir / "per_seed_metrics.csv"
    _write_csv(per_seed_path, PER_SEED_COLUMNS, per_seed_rows)

    metric_specs: list[tuple[str, bool]] = [
        ("detection_rate", True),
        ("saturation_rate", True),
        ("detectable_only_crr", True),
        ("participation_rate", True),
        ("saturation_inflation_pp", False),
        ("structural_gt_count", False),
        ("spectrally_participating_count", False),
    ]
    aggregates = []
    for metric, is_rate in metric_specs:
        per_seed_values = {
            int(row["cohort_seed"]): float(row[metric]) for row in per_seed_rows
        }
        aggregates.append(
            aggregate_numeric_across_seeds(per_seed_values, metric, is_rate=is_rate)
        )

    aggregate_path = output_dir / "cross_seed_aggregates.csv"
    write_aggregate_csv(aggregate_path, aggregates)

    interpretation_path = output_dir / "INTERPRETATION.md"
    notes = [
        "Cohort generation seed varies; stratified cell counts and taxonomy remain fixed.",
        f"Random repair baseline uses fixed repair seed {repair_seed} ({RANDOM_TOOL_ID}).",
        "Stable metrics have cross-seed range ≤2 pp (rates) or low dispersion on counts.",
        "Seed-sensitive metrics should be reported with dispersion, not single-cohort point estimates.",
        "Detectable-only repair floor near 0% across seeds supports saturation inflation as partition artifact.",
    ]
    write_interpretation_markdown(
        interpretation_path,
        title="Multi-seed stability interpretation",
        aggregates=aggregates,
        notes=notes,
    )

    table_tex_path = output_dir / "table_multiseed_stability.tex"
    write_aggregate_latex_table(
        table_tex_path,
        aggregates,
        caption="Cross-seed stability of cohort partition and random-repair readouts.",
        label="tab:multiseed-stability",
    )

    figure_path = output_dir / "figures" / "multiseed_stability_bars.png"
    plotted = try_plot_multiseed_bars(
        figure_path,
        per_seed_rows,
        ("detection_rate", "saturation_rate", "detectable_only_crr", "saturation_inflation_pp"),
    )

    manifest = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "study": "multiseed_stability",
        "plan_path": str(plan_path),
        "cohort_seeds": list(cohort_seeds),
        "repair_seed": repair_seed,
        "skip_build": skip_build,
        "skip_repair": skip_repair,
        "aggregates": aggregates_to_dicts(aggregates),
    }
    write_study_manifest(output_dir / "manifest.json", manifest)

    return MultiseedStabilityResult(
        output_dir=output_dir,
        per_seed_path=per_seed_path,
        aggregate_path=aggregate_path,
        interpretation_path=interpretation_path,
        table_tex_path=table_tex_path,
        figure_path=figure_path if plotted else None,
        seed_count=len(cohort_seeds),
    )
