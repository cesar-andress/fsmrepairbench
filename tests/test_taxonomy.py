"""Tests for taxonomy, stratified generation, filtering, and overlap."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.case_filter import (
    compute_subset_overlap,
    filter_cases,
    matches_filters,
    parse_predicate_string,
    write_filter_csv,
)
from fsmrepairbench.cli import app
from fsmrepairbench.generators.stratified_specs import DatasetPlan, load_dataset_plan
from fsmrepairbench.generators.synthetic_factory import (
    SyntheticGenerationParams,
    generate_synthetic_fsm,
)
from fsmrepairbench.models import FSM, Transition
from fsmrepairbench.mutators import mutate
from fsmrepairbench.oracle_generator import generate_oracle_suite
from fsmrepairbench.stratified_builder import build_stratified_dataset
from fsmrepairbench.taxonomy import (
    ArityClass,
    BugType,
    CaseFeatures,
    Completeness,
    Determinism,
    GraphStructure,
    GuardComplexity,
    MachineType,
    OracleDepth,
    SizeClass,
    TimeFeature,
    compute_case_features,
    infer_arity_class,
    infer_completeness,
    infer_determinism,
    infer_size_class,
)
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _tiny_plan_yaml() -> str:
    return textwrap.dedent(
        """
        name: tiny-stratified
        version: "1.0"
        seed: 42
        cells:
          - machine_type: plain_fsm
            determinism: deterministic
            completeness: complete
            arity_class: low
            size_class: tiny
            guard_complexity: none
            time_features: [none]
            graph_structure: [acyclic]
            oracle_depth: shallow
            bug_type: missing_transition
            count: 1
          - machine_type: mealy
            determinism: deterministic
            completeness: complete
            arity_class: medium
            size_class: small
            guard_complexity: simple
            time_features: [none]
            graph_structure: [cyclic]
            oracle_depth: medium
            bug_type: wrong_target
            count: 1
        """
    ).strip()


def test_official_10k_plan_loads_and_sums_to_10000() -> None:
    plan_path = Path(__file__).resolve().parents[1] / "plans" / "fsmrepairbench_v0_10k_plan.yaml"
    plan = load_dataset_plan(plan_path)
    assert plan.name == "fsmrepairbench_v0_10k"
    assert plan.seed == 42
    assert sum(cell.count for cell in plan.cells) == 10_000


def test_enum_serialization_roundtrip() -> None:
    features = CaseFeatures(
        case_id="case_000001",
        machine_type=MachineType.MEALY,
        determinism=Determinism.DETERMINISTIC,
        completeness=Completeness.COMPLETE,
        arity_class=ArityClass.LOW,
        size_class=SizeClass.TINY,
        guard_complexity=GuardComplexity.NONE,
        time_features=[TimeFeature.NONE],
        graph_structure=[GraphStructure.ACYCLIC],
        oracle_depth=OracleDepth.SHALLOW,
        bug_type=BugType.MISSING_TRANSITION,
        num_states=3,
        num_events=2,
        num_transitions=2,
        avg_out_degree=1.0,
        max_out_degree=1,
        num_guards=0,
        num_timed_guards=0,
        num_timeouts=0,
        num_cycles=0,
        scc_count=1,
        seed=42,
    )
    payload = json.loads(features.model_dump_json())
    restored = CaseFeatures.model_validate(payload)
    assert restored.machine_type is MachineType.MEALY
    assert restored.bug_type is BugType.MISSING_TRANSITION


def test_infer_size_and_arity_classes() -> None:
    assert infer_size_class(3) is SizeClass.TINY
    assert infer_size_class(20) is SizeClass.LARGE
    assert infer_arity_class(1.2, 2) is ArityClass.LOW
    assert infer_arity_class(4.5, 7) is ArityClass.HIGH


def test_infer_determinism_and_completeness() -> None:
    deterministic = generate_synthetic_fsm(
        SyntheticGenerationParams(num_states=4, num_events=2, branching_factor=2, seed=1)
    )
    assert infer_determinism(deterministic) is Determinism.DETERMINISTIC
    assert infer_completeness(deterministic) in {Completeness.COMPLETE, Completeness.PARTIAL}

    nondeterministic = deterministic.model_copy(
        update={
            "transitions": [
                *deterministic.transitions,
                Transition(
                    id="t_nd",
                    source=deterministic.initial_state,
                    event=deterministic.events[0],
                    target=deterministic.states[-1].id,
                    guard=deterministic.transitions[0].guard,
                ),
            ]
        }
    )
    assert infer_determinism(nondeterministic) is Determinism.NONDETERMINISTIC


def test_compute_case_features_from_reference() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = generate_oracle_suite(reference, depth="shallow").suite
    features = compute_case_features(
        reference,
        oracle,
        BugType.WRONG_TARGET,
        seed=7,
        case_id="case_000001",
        oracle_depth=OracleDepth.SHALLOW,
    )
    assert features.case_id == "case_000001"
    assert features.num_states >= 1
    assert features.bug_type is BugType.WRONG_TARGET


def test_load_dataset_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_plan_yaml() + "\n", encoding="utf-8")
    plan = load_dataset_plan(plan_path)
    assert isinstance(plan, DatasetPlan)
    assert plan.name == "tiny-stratified"
    assert len(plan.cells) == 2
    assert plan.cells[0].bug_type is BugType.MISSING_TRANSITION


def test_build_stratified_dataset_from_tiny_plan(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_plan_yaml() + "\n", encoding="utf-8")
    output_dir = tmp_path / "dataset"

    result = build_stratified_dataset(plan_path, output_dir)

    assert len(result.cases) == 2
    assert result.case_index_path.is_file()
    assert result.feature_matrix_path.is_file()
    assert (output_dir / "cases" / "case_000001" / "case_features.json").is_file()
    assert (output_dir / "dataset_plan.json").is_file()
    assert (output_dir / "README.md").is_file()


def test_filter_cases_and_overlap(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_plan_yaml() + "\n", encoding="utf-8")
    output_dir = tmp_path / "dataset"
    build_stratified_dataset(plan_path, output_dir)

    deterministic = filter_cases(output_dir, {"determinism": "deterministic"})
    assert len(deterministic) == 2

    mealy = filter_cases(output_dir, {"machine_type": "mealy"})
    assert len(mealy) == 1

    subset_path = tmp_path / "subset.csv"
    write_filter_csv(subset_path, mealy)
    assert subset_path.is_file()

    overlap = compute_subset_overlap(
        output_dir,
        parse_predicate_string("determinism=deterministic,machine_type=mealy"),
        parse_predicate_string("bug_type=wrong_target"),
    )
    assert overlap.count_a == 1
    assert overlap.count_b == 1
    assert overlap.count_intersection == 1
    assert overlap.jaccard == pytest.approx(1.0)


def test_matches_filters_supports_list_fields() -> None:
    features = CaseFeatures(
        case_id="case_000001",
        machine_type=MachineType.PLAIN_FSM,
        determinism=Determinism.DETERMINISTIC,
        completeness=Completeness.COMPLETE,
        arity_class=ArityClass.LOW,
        size_class=SizeClass.TINY,
        guard_complexity=GuardComplexity.NONE,
        time_features=[TimeFeature.NONE],
        graph_structure=[GraphStructure.ACYCLIC, GraphStructure.SPARSE],
        oracle_depth=OracleDepth.SHALLOW,
        bug_type=BugType.MISSING_TRANSITION,
        num_states=3,
        num_events=2,
        num_transitions=2,
        avg_out_degree=1.0,
        max_out_degree=1,
        num_guards=0,
        num_timed_guards=0,
        num_timeouts=0,
        num_cycles=0,
        scc_count=1,
        seed=42,
    )
    assert matches_filters(features, {"graph_structure": "sparse"})
    assert not matches_filters(features, {"graph_structure": "dense"})


def test_cli_build_stratified_dataset(tmp_path: Path) -> None:
    plan_path = tmp_path / "plan.yaml"
    plan_path.write_text(_tiny_plan_yaml() + "\n", encoding="utf-8")
    output_dir = tmp_path / "dataset"

    result = runner.invoke(
        app,
        ["build-stratified-dataset", str(plan_path), str(output_dir)],
    )
    assert result.exit_code == 0
    assert "Built stratified dataset" in result.stdout


def test_new_bug_type_mutators_work() -> None:
    reference = generate_synthetic_fsm(
        SyntheticGenerationParams(num_states=5, num_events=3, branching_factor=2, seed=99)
    )
    for operator in ("guard_weaken", "nondeterminism_intro", "unreachable_state_intro"):
        faulty, metadata = mutate(reference, operator, 123)
        assert faulty.id != reference.id
        assert metadata.mutation_operator == operator
