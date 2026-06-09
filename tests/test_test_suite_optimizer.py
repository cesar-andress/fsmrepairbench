"""Tests for search-based multi-objective test suite optimization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.literature_mutation import generate_literature_mutants
from fsmrepairbench.oracle_selection import MutantRecord
from fsmrepairbench.test_suite_optimizer import (
    ObjectiveValues,
    SUPPORTED_OPTIMIZER_ALGORITHMS,
    TestSuiteOptimizerError as OptimizerError,
    build_evaluation_context,
    dominates,
    extract_pareto_front,
    merge_pareto_fronts,
    optimize_test_suites,
    run_algorithm,
    visualize_pareto_results,
    write_optimization_report_json,
    _Candidate,
)
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _first_order_mutants(reference_path: Path) -> tuple[MutantRecord, ...]:
    reference = load_fsm(reference_path)
    report = generate_literature_mutants(
        reference,
        seed=42,
        first_order_count=5,
        second_order_count=0,
        higher_order_count=0,
        include_fsm=True,
    )
    return tuple(
        MutantRecord(mutant_id=record.mutant_id, fsm=record.fsm)
        for record in report.mutants
        if record.fsm is not None
    )


def test_dominates_and_merge_pareto_fronts() -> None:
    better = ObjectiveValues(
        mutation_score=0.8,
        transition_coverage=0.9,
        suite_size=2,
        execution_cost=5,
    )
    worse = ObjectiveValues(
        mutation_score=0.5,
        transition_coverage=0.7,
        suite_size=3,
        execution_cost=8,
    )
    assert dominates(better, worse)
    assert not dominates(worse, better)

    from fsmrepairbench.test_suite_optimizer import ParetoSolution

    front_a = [
        ParetoSolution(
            algorithm="random_search",
            scenario_ids=["a"],
            objectives=better,
        )
    ]
    front_b = [
        ParetoSolution(
            algorithm="hill_climbing",
            scenario_ids=["b"],
            objectives=worse,
        )
    ]
    merged = merge_pareto_fronts([front_a, front_b])
    assert len(merged) == 1
    assert merged[0].scenario_ids == ["a"]


def test_extract_pareto_front_from_candidates() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = _first_order_mutants(FIXTURES / "valid_fsm.json")
    context = build_evaluation_context(reference, oracle, mutants)

    candidates = [
        _Candidate(mask=(True, False, False)),
        _Candidate(mask=(False, True, False)),
        _Candidate(mask=(True, True, True)),
    ]
    pareto = extract_pareto_front(
        algorithm="random_search",
        context=context,
        candidates=candidates,
    )

    assert pareto
    assert all(solution.objectives.suite_size >= 1 for solution in pareto)
    assert len(pareto) <= len(candidates)
    assert not any(
        dominates(other.objectives, candidate.objectives)
        for candidate in pareto
        for other in pareto
        if other is not candidate
    )


def test_run_all_algorithms(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = _first_order_mutants(FIXTURES / "valid_fsm.json")

    report = optimize_test_suites(
        reference,
        oracle,
        mutants,
        algorithms=SUPPORTED_OPTIMIZER_ALGORITHMS,
        seed=7,
        iterations=30,
        population_size=10,
        generations=5,
    )

    assert report.reference_fsm_id == reference.id
    assert report.scenario_count == len(oracle.scenarios)
    assert report.mutant_count == len(mutants)
    assert set(report.algorithms) == set(SUPPORTED_OPTIMIZER_ALGORITHMS)
    for algorithm in SUPPORTED_OPTIMIZER_ALGORITHMS:
        result = report.algorithms[algorithm]
        assert result.evaluations > 0
        assert result.pareto_front

    report_path = tmp_path / "optimization_report.json"
    write_optimization_report_json(report_path, report)
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["combined_pareto_front"]
    assert "algorithms" in payload


def test_random_search_evaluates_requested_iterations() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = _first_order_mutants(FIXTURES / "valid_fsm.json")
    context = build_evaluation_context(reference, oracle, mutants)

    result = run_algorithm(context, "random_search", seed=1, iterations=25)
    assert result.evaluations == 25
    assert result.pareto_front


def test_visualize_pareto_results(tmp_path: Path) -> None:
    pytest.importorskip("matplotlib")
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = _first_order_mutants(FIXTURES / "valid_fsm.json")
    report = optimize_test_suites(
        reference,
        oracle,
        mutants,
        algorithms=("random_search", "nsga2"),
        seed=3,
        iterations=20,
        population_size=8,
        generations=3,
    )

    plots_dir = tmp_path / "plots"
    written = visualize_pareto_results(report, plots_dir)
    assert (plots_dir / "pareto_mutation_vs_transition.png").exists()
    assert (plots_dir / "pareto_size_vs_cost.png").exists()
    assert (plots_dir / "pareto_combined.png").exists()
    assert (plots_dir / "pareto_plots.json").exists()
    assert len(written) >= 4


def test_build_evaluation_context_rejects_empty_suite() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    empty = oracle.model_copy(deep=True)
    empty.scenarios = []

    with pytest.raises(OptimizerError, match="at least one scenario"):
        build_evaluation_context(reference, empty, ())


def test_cli_optimize_test_suite(tmp_path: Path) -> None:
    mutants_dir = tmp_path / "mutants"
    mutants_dir.mkdir()
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    mutant_report = generate_literature_mutants(
        reference,
        seed=42,
        first_order_count=3,
        second_order_count=0,
        higher_order_count=0,
        include_fsm=True,
    )
    for record in mutant_report.mutants:
        if record.fsm is None:
            continue
        path = mutants_dir / f"{record.mutant_id}.json"
        path.write_text(record.fsm.model_dump_json(indent=2) + "\n", encoding="utf-8")

    out_path = tmp_path / "report.json"
    result = runner.invoke(
        app,
        [
            "optimize-test-suite",
            str(FIXTURES / "valid_fsm.json"),
            str(FIXTURES / "valid_oracle.json"),
            str(mutants_dir),
            "--out",
            str(out_path),
            "--algorithm",
            "random_search",
            "--algorithm",
            "hill_climbing",
            "--iterations",
            "15",
            "--seed",
            "99",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert set(payload["algorithms"]) == {"random_search", "hill_climbing"}
    assert payload["combined_pareto_front"]
