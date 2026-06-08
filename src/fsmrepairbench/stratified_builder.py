"""Stratified benchmark dataset builder."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.generators.stratified_generator import generate_reference_fsm_for_cell
from fsmrepairbench.generators.stratified_specs import (
    DatasetPlan,
    GenerationCell,
    load_dataset_plan,
    total_planned_cases,
)
from fsmrepairbench.generator import MAX_MUTATION_RETRIES, write_benchmark_case
from fsmrepairbench.mutators import MutatorError, mutate
from fsmrepairbench.oracle_generator import OracleGeneratorError, generate_oracle_suite
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.taxonomy import (
    CaseFeatures,
    OracleDepth,
    bug_type_to_operator,
    compute_case_features,
)
from fsmrepairbench.versioning import format_case_id

CASE_INDEX_COLUMNS: tuple[str, ...] = (
    "case_id",
    "plan_name",
    "plan_version",
    "cell_index",
    "bug_type",
    "reference_bpr",
    "faulty_bpr",
    "seed",
)


class StratifiedBuilderError(RuntimeError):
    """Raised when stratified dataset construction fails."""


@dataclass(frozen=True)
class StratifiedBuildResult:
    """Result of building a stratified dataset."""

    output_dir: Path
    case_index_path: Path
    feature_matrix_path: Path
    dataset_plan_path: Path
    readme_path: Path
    cases: tuple[CaseFeatures, ...]


def _oracle_depth_to_generator(depth: OracleDepth) -> str:
    return depth.value


def _mutation_seed(plan_seed: int, case_number: int, attempt: int) -> int:
    return plan_seed + case_number * 1000 + attempt


def _try_mutate(reference, operator: str, plan_seed: int, case_number: int):
    last_error: MutatorError | None = None
    for attempt in range(MAX_MUTATION_RETRIES):
        try:
            return mutate(reference, operator, _mutation_seed(plan_seed, case_number, attempt))
        except MutatorError as exc:
            last_error = exc
    msg = f"Could not apply operator '{operator}' for case {case_number}: {last_error}"
    raise StratifiedBuilderError(msg)


def _features_to_row(features: CaseFeatures) -> dict[str, str | int | float]:
    return {
        "case_id": features.case_id,
        "machine_type": features.machine_type.value,
        "determinism": features.determinism.value,
        "completeness": features.completeness.value,
        "arity_class": features.arity_class.value,
        "size_class": features.size_class.value,
        "guard_complexity": features.guard_complexity.value,
        "time_features": "|".join(item.value for item in features.time_features),
        "graph_structure": "|".join(item.value for item in features.graph_structure),
        "oracle_depth": features.oracle_depth.value,
        "bug_type": features.bug_type.value,
        "num_states": features.num_states,
        "num_events": features.num_events,
        "num_transitions": features.num_transitions,
        "avg_out_degree": features.avg_out_degree,
        "max_out_degree": features.max_out_degree,
        "num_guards": features.num_guards,
        "num_timed_guards": features.num_timed_guards,
        "num_timeouts": features.num_timeouts,
        "num_cycles": "" if features.num_cycles is None else features.num_cycles,
        "scc_count": "" if features.scc_count is None else features.scc_count,
        "seed": features.seed,
    }


FEATURE_MATRIX_COLUMNS: tuple[str, ...] = (
    "case_id",
    "machine_type",
    "determinism",
    "completeness",
    "arity_class",
    "size_class",
    "guard_complexity",
    "time_features",
    "graph_structure",
    "oracle_depth",
    "bug_type",
    "num_states",
    "num_events",
    "num_transitions",
    "avg_out_degree",
    "max_out_degree",
    "num_guards",
    "num_timed_guards",
    "num_timeouts",
    "num_cycles",
    "scc_count",
    "seed",
)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _build_readme(plan: DatasetPlan, output_dir: Path, case_count: int) -> str:
    return (
        f"# Stratified Dataset: {plan.name}\n\n"
        f"- Plan version: {plan.version}\n"
        f"- Seed: {plan.seed}\n"
        f"- Generated cases: {case_count}\n"
        f"- Output directory: `{output_dir}`\n\n"
        "Each case directory contains reference/faulty FSMs, oracle suite, bug metadata, "
        "and `case_features.json` with taxonomy tags for reproducible filtering.\n"
    )


def _build_case_for_cell(
    *,
    cell: GenerationCell,
    cell_index: int,
    case_number: int,
    plan: DatasetPlan,
    output_dir: Path,
) -> tuple[CaseFeatures, dict[str, object]]:
    case_id = format_case_id(case_number)
    case_seed = plan.seed + case_number * 17 + cell_index * 101
    reference = generate_reference_fsm_for_cell(cell, case_seed)
    depth = _oracle_depth_to_generator(cell.oracle_depth)
    try:
        oracle_result = generate_oracle_suite(reference, depth=depth)  # type: ignore[arg-type]
    except OracleGeneratorError as exc:
        msg = f"Oracle generation failed for {case_id}: {exc}"
        raise StratifiedBuilderError(msg) from exc

    reference_bpr = score_oracle_suite(reference, oracle_result.suite).bpr
    if reference_bpr != 1.0:
        msg = f"Reference FSM for {case_id} did not achieve BPR=1.0"
        raise StratifiedBuilderError(msg)

    operator = bug_type_to_operator(cell.bug_type)
    faulty_fsm, bug_metadata = _try_mutate(reference, operator, plan.seed, case_number)
    faulty_bpr = score_oracle_suite(faulty_fsm, oracle_result.suite).bpr

    features = compute_case_features(
        reference,
        oracle_result.suite,
        cell.bug_type,
        case_seed,
        case_id=case_id,
        oracle_depth=cell.oracle_depth,
    )

    case_dir = output_dir / "cases" / case_id
    write_benchmark_case(
        case_dir=case_dir,
        reference=reference,
        faulty_fsm=faulty_fsm,
        bug_metadata=bug_metadata,
        oracle=oracle_result.suite,
    )
    (case_dir / "case_features.json").write_text(
        features.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    index_row = {
        "case_id": case_id,
        "plan_name": plan.name,
        "plan_version": plan.version,
        "cell_index": cell_index,
        "bug_type": cell.bug_type.value,
        "reference_bpr": reference_bpr,
        "faulty_bpr": faulty_bpr,
        "seed": case_seed,
    }
    return features, index_row


def build_stratified_dataset(plan_path: Path, output_dir: Path) -> StratifiedBuildResult:
    """Build a stratified dataset from *plan_path* into *output_dir*."""
    plan = load_dataset_plan(plan_path)
    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    features_list: list[CaseFeatures] = []
    index_rows: list[dict[str, object]] = []
    feature_rows: list[dict[str, str | int | float]] = []
    case_number = 0

    for cell_index, cell in enumerate(plan.cells):
        for _ in range(cell.count):
            case_number += 1
            features, index_row = _build_case_for_cell(
                cell=cell,
                cell_index=cell_index,
                case_number=case_number,
                plan=plan,
                output_dir=output_dir,
            )
            features_list.append(features)
            index_rows.append(index_row)
            feature_rows.append(_features_to_row(features))

    case_index_path = output_dir / "case_index.csv"
    feature_matrix_path = output_dir / "feature_matrix.csv"
    _write_csv(case_index_path, CASE_INDEX_COLUMNS, index_rows)
    _write_csv(feature_matrix_path, FEATURE_MATRIX_COLUMNS, feature_rows)

    dataset_plan_path = output_dir / "dataset_plan.json"
    dataset_plan_path.write_text(
        json.dumps(plan.model_dump(mode="json"), indent=2) + "\n",
        encoding="utf-8",
    )

    readme_path = output_dir / "README.md"
    readme_path.write_text(
        _build_readme(plan, output_dir, len(features_list)),
        encoding="utf-8",
    )

    if len(features_list) != total_planned_cases(plan):
        msg = "Stratified build produced an unexpected number of cases"
        raise StratifiedBuilderError(msg)

    return StratifiedBuildResult(
        output_dir=output_dir,
        case_index_path=case_index_path,
        feature_matrix_path=feature_matrix_path,
        dataset_plan_path=dataset_plan_path,
        readme_path=readme_path,
        cases=tuple(features_list),
    )
