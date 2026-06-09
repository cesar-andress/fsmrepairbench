"""Search-based multi-objective optimization of FSM test suites."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fsmrepairbench.models import FSM, OracleScenario, OracleSuite
from fsmrepairbench.oracle_selection import (
    MutantRecord,
    ScenarioProfile,
    build_scenario_profiles,
    compute_mutation_score,
    compute_transition_coverage,
)

OptimizerAlgorithm = Literal[
    "random_search",
    "hill_climbing",
    "simulated_annealing",
    "genetic_algorithm",
    "nsga2",
]

SUPPORTED_OPTIMIZER_ALGORITHMS: tuple[OptimizerAlgorithm, ...] = (
    "random_search",
    "hill_climbing",
    "simulated_annealing",
    "genetic_algorithm",
    "nsga2",
)


class TestSuiteOptimizerError(ValueError):
    """Raised when test suite optimization fails."""


class ObjectiveValues(BaseModel):
    """Multi-objective scores for one candidate test suite."""

    mutation_score: float = Field(ge=0.0, le=1.0)
    transition_coverage: float = Field(ge=0.0, le=1.0)
    suite_size: int = Field(ge=0)
    execution_cost: int = Field(ge=0)


class ParetoSolution(BaseModel):
    """One non-dominated test suite on the Pareto front."""

    algorithm: OptimizerAlgorithm
    scenario_ids: list[str]
    objectives: ObjectiveValues


class AlgorithmResult(BaseModel):
    """Optimization outcome for one algorithm."""

    algorithm: OptimizerAlgorithm
    evaluations: int
    pareto_front: list[ParetoSolution]


class TestSuiteOptimizationReport(BaseModel):
    """Combined optimization report across algorithms."""

    reference_fsm_id: str
    source_oracle_suite_id: str
    seed: int
    scenario_count: int
    mutant_count: int
    algorithms: dict[str, AlgorithmResult]
    combined_pareto_front: list[ParetoSolution]


@dataclass(frozen=True)
class _EvaluationContext:
    reference: FSM
    suite: OracleSuite
    profiles: tuple[ScenarioProfile, ...]
    scenario_ids: tuple[str, ...]
    step_costs: tuple[int, ...]
    full_mutation_score: float
    full_transition_coverage: float


@dataclass(frozen=True)
class _Candidate:
    mask: tuple[bool, ...]

    def selected_indices(self) -> tuple[int, ...]:
        return tuple(index for index, selected in enumerate(self.mask) if selected)

    def selected_ids(self, scenario_ids: Sequence[str]) -> tuple[str, ...]:
        return tuple(scenario_ids[index] for index in self.selected_indices())


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        msg = (
            "Plotting dependencies are missing. "
            f"Install them with: pip install -e '.[analytics]' ({exc})"
        )
        raise TestSuiteOptimizerError(msg) from exc
    return plt


def build_evaluation_context(
    reference: FSM,
    suite: OracleSuite,
    mutants: tuple[MutantRecord, ...],
) -> _EvaluationContext:
    """Precompute scenario profiles and baseline metrics."""
    if not suite.scenarios:
        msg = "Oracle suite must contain at least one scenario"
        raise TestSuiteOptimizerError(msg)
    profiles = build_scenario_profiles(reference, suite, mutants)
    scenario_ids = tuple(scenario.id for scenario in suite.scenarios)
    step_costs = tuple(len(scenario.steps) for scenario in suite.scenarios)
    return _EvaluationContext(
        reference=reference,
        suite=suite,
        profiles=profiles,
        scenario_ids=scenario_ids,
        step_costs=step_costs,
        full_mutation_score=compute_mutation_score(profiles),
        full_transition_coverage=compute_transition_coverage(reference, profiles),
    )


def evaluate_candidate(context: _EvaluationContext, candidate: _Candidate) -> ObjectiveValues:
    """Evaluate one candidate test suite selection."""
    selected = candidate.selected_indices()
    if not selected:
        return ObjectiveValues(
            mutation_score=0.0,
            transition_coverage=0.0,
            suite_size=0,
            execution_cost=0,
        )
    selected_profiles = tuple(context.profiles[index] for index in selected)
    return ObjectiveValues(
        mutation_score=round(compute_mutation_score(selected_profiles), 6),
        transition_coverage=round(
            compute_transition_coverage(context.reference, selected_profiles),
            6,
        ),
        suite_size=len(selected),
        execution_cost=sum(context.step_costs[index] for index in selected),
    )


def dominates(left: ObjectiveValues, right: ObjectiveValues) -> bool:
    """Return whether *left* Pareto-dominates *right*."""
    better_or_equal = (
        left.mutation_score >= right.mutation_score
        and left.transition_coverage >= right.transition_coverage
        and left.suite_size <= right.suite_size
        and left.execution_cost <= right.execution_cost
    )
    strictly_better = (
        left.mutation_score > right.mutation_score
        or left.transition_coverage > right.transition_coverage
        or left.suite_size < right.suite_size
        or left.execution_cost < right.execution_cost
    )
    return better_or_equal and strictly_better


def extract_pareto_front(
    *,
    algorithm: OptimizerAlgorithm,
    context: _EvaluationContext,
    candidates: Sequence[_Candidate],
) -> list[ParetoSolution]:
    """Extract the non-dominated subset from *candidates*."""
    evaluated: list[tuple[_Candidate, ObjectiveValues]] = [
        (candidate, evaluate_candidate(context, candidate)) for candidate in candidates
    ]
    pareto: list[ParetoSolution] = []
    for candidate, objectives in evaluated:
        if any(dominates(other_objectives, objectives) for _, other_objectives in evaluated):
            continue
        pareto.append(
            ParetoSolution(
                algorithm=algorithm,
                scenario_ids=list(candidate.selected_ids(context.scenario_ids)),
                objectives=objectives,
            )
        )
    pareto.sort(
        key=lambda item: (
            -item.objectives.mutation_score,
            -item.objectives.transition_coverage,
            item.objectives.suite_size,
            item.objectives.execution_cost,
        )
    )
    return pareto


def _scalar_fitness(objectives: ObjectiveValues) -> float:
    """Weighted scalar score for single-point metaheuristics."""
    return (
        objectives.mutation_score
        + objectives.transition_coverage
        - objectives.suite_size / 20.0
        - objectives.execution_cost / 100.0
    )


def _random_candidate(rng: random.Random, size: int, *, min_selected: int = 1) -> _Candidate:
    mask = [rng.random() < 0.5 for _ in range(size)]
    if sum(mask) < min_selected:
        index = rng.randrange(size)
        mask[index] = True
    return _Candidate(mask=tuple(mask))


def _flip_neighbor(candidate: _Candidate, rng: random.Random) -> _Candidate:
    index = rng.randrange(len(candidate.mask))
    mask = list(candidate.mask)
    mask[index] = not mask[index]
    return _Candidate(mask=tuple(mask))


def _fast_non_dominated_sort(
    objectives: Sequence[ObjectiveValues],
) -> list[list[int]]:
    fronts: list[list[int]] = []
    dominated_counts = [0] * len(objectives)
    dominatees: list[list[int]] = [[] for _ in objectives]
    first_front: list[int] = []

    for index, left in enumerate(objectives):
        for other_index, right in enumerate(objectives):
            if index == other_index:
                continue
            if dominates(left, right):
                dominatees[index].append(other_index)
            elif dominates(right, left):
                dominated_counts[index] += 1
        if dominated_counts[index] == 0:
            first_front.append(index)

    fronts.append(first_front)
    current = 0
    while current < len(fronts) and fronts[current]:
        next_front: list[int] = []
        for index in fronts[current]:
            for dominated_index in dominatees[index]:
                dominated_counts[dominated_index] -= 1
                if dominated_counts[dominated_index] == 0:
                    next_front.append(dominated_index)
        current += 1
        if next_front:
            fronts.append(next_front)
    return fronts


def _crowding_distance(front: Sequence[int], objectives: Sequence[ObjectiveValues]) -> dict[int, float]:
    if len(front) <= 2:
        return dict.fromkeys(front, float("inf"))

    distances = dict.fromkeys(front, 0.0)
    specs = (
        lambda item: item.mutation_score,
        lambda item: item.transition_coverage,
        lambda item: float(item.suite_size),
        lambda item: float(item.execution_cost),
    )
    maximize = (True, True, False, False)

    for spec, is_max in zip(specs, maximize, strict=True):
        ordered = sorted(front, key=lambda index: spec(objectives[index]))
        distances[ordered[0]] = float("inf")
        distances[ordered[-1]] = float("inf")
        min_value = spec(objectives[ordered[0]])
        max_value = spec(objectives[ordered[-1]])
        span = max_value - min_value
        if span == 0.0:
            continue
        for position in range(1, len(ordered) - 1):
            index = ordered[position]
            previous = spec(objectives[ordered[position - 1]])
            following = spec(objectives[ordered[position + 1]])
            if is_max:
                distances[index] += (following - previous) / span
            else:
                distances[index] += (previous - following) / span
    return distances


def _tournament_select(
    rng: random.Random,
    population: Sequence[_Candidate],
    ranks: Sequence[int],
    crowding: Sequence[float],
) -> _Candidate:
    first = rng.randrange(len(population))
    second = rng.randrange(len(population))
    if ranks[first] < ranks[second]:
        return population[first]
    if ranks[second] < ranks[first]:
        return population[second]
    return population[first if crowding[first] >= crowding[second] else second]


def _crossover(parent_a: _Candidate, parent_b: _Candidate, rng: random.Random) -> _Candidate:
    child = [
        left if rng.random() < 0.5 else right
        for left, right in zip(parent_a.mask, parent_b.mask, strict=True)
    ]
    if not any(child):
        child[rng.randrange(len(child))] = True
    return _Candidate(mask=tuple(child))


def _mutate(candidate: _Candidate, rng: random.Random, *, rate: float = 0.1) -> _Candidate:
    mask = [
        bit if rng.random() > rate else not bit
        for bit in candidate.mask
    ]
    if not any(mask):
        mask[rng.randrange(len(mask))] = True
    return _Candidate(mask=tuple(mask))


def optimize_random_search(
    context: _EvaluationContext,
    *,
    iterations: int,
    seed: int,
) -> tuple[list[_Candidate], int]:
    rng = random.Random(seed)
    candidates = [_random_candidate(rng, len(context.scenario_ids)) for _ in range(iterations)]
    return candidates, iterations


def optimize_hill_climbing(
    context: _EvaluationContext,
    *,
    iterations: int,
    seed: int,
) -> tuple[list[_Candidate], int]:
    rng = random.Random(seed)
    current = _random_candidate(rng, len(context.scenario_ids))
    archive = {current.mask: evaluate_candidate(context, current)}
    evaluations = 1

    for _ in range(iterations):
        neighbor = _flip_neighbor(current, rng)
        objectives = evaluate_candidate(context, neighbor)
        evaluations += 1
        archive[neighbor.mask] = objectives
        current_objectives = archive[current.mask]
        if dominates(objectives, current_objectives) or _scalar_fitness(objectives) > _scalar_fitness(
            current_objectives
        ):
            current = neighbor

    return [_Candidate(mask=mask) for mask in archive.keys()], evaluations


def optimize_simulated_annealing(
    context: _EvaluationContext,
    *,
    iterations: int,
    seed: int,
    initial_temperature: float = 1.0,
    cooling_rate: float = 0.95,
) -> tuple[list[_Candidate], int]:
    rng = random.Random(seed)
    current = _random_candidate(rng, len(context.scenario_ids))
    archive = {current.mask: evaluate_candidate(context, current)}
    evaluations = 1
    temperature = initial_temperature

    for _ in range(iterations):
        neighbor = _flip_neighbor(current, rng)
        current_objectives = archive[current.mask]
        neighbor_objectives = evaluate_candidate(context, neighbor)
        evaluations += 1
        archive[neighbor.mask] = neighbor_objectives
        delta = _scalar_fitness(neighbor_objectives) - _scalar_fitness(current_objectives)
        if delta >= 0 or rng.random() < math.exp(delta / max(temperature, 1e-9)):
            current = neighbor
        temperature *= cooling_rate

    return [_Candidate(mask=mask) for mask in archive.keys()], evaluations


def optimize_genetic_algorithm(
    context: _EvaluationContext,
    *,
    population_size: int,
    generations: int,
    seed: int,
) -> tuple[list[_Candidate], int]:
    rng = random.Random(seed)
    population = [_random_candidate(rng, len(context.scenario_ids)) for _ in range(population_size)]
    evaluations = population_size

    for _ in range(generations):
        objectives = [evaluate_candidate(context, candidate) for candidate in population]
        fronts = _fast_non_dominated_sort(objectives)
        ranks = [0] * len(population)
        crowding = [0.0] * len(population)
        for front_index, front in enumerate(fronts):
            for index in front:
                ranks[index] = front_index
            distance = _crowding_distance(front, objectives)
            for index, value in distance.items():
                crowding[index] = value

        next_population: list[_Candidate] = []
        while len(next_population) < population_size:
            parent_a = _tournament_select(rng, population, ranks, crowding)
            parent_b = _tournament_select(rng, population, ranks, crowding)
            child = _mutate(_crossover(parent_a, parent_b, rng), rng)
            next_population.append(child)
        population = next_population
        evaluations += population_size

    return population, evaluations


def optimize_nsga2(
    context: _EvaluationContext,
    *,
    population_size: int,
    generations: int,
    seed: int,
) -> tuple[list[_Candidate], int]:
    rng = random.Random(seed)
    population = [_random_candidate(rng, len(context.scenario_ids)) for _ in range(population_size)]
    evaluations = population_size

    for _ in range(generations):
        objectives = [evaluate_candidate(context, candidate) for candidate in population]
        fronts = _fast_non_dominated_sort(objectives)
        ranks = [0] * len(population)
        crowding = [0.0] * len(population)
        for front_index, front in enumerate(fronts):
            for index in front:
                ranks[index] = front_index
            distance = _crowding_distance(front, objectives)
            for index, value in distance.items():
                crowding[index] = value

        offspring: list[_Candidate] = []
        while len(offspring) < population_size:
            parent_a = _tournament_select(rng, population, ranks, crowding)
            parent_b = _tournament_select(rng, population, ranks, crowding)
            offspring.append(_mutate(_crossover(parent_a, parent_b, rng), rng))
        combined = population + offspring
        objectives = [evaluate_candidate(context, candidate) for candidate in combined]
        evaluations += len(offspring)
        fronts = _fast_non_dominated_sort(objectives)
        next_population: list[_Candidate] = []
        for front in fronts:
            if len(next_population) + len(front) <= population_size:
                next_population.extend(combined[index] for index in front)
            else:
                distance = _crowding_distance(front, objectives)
                remaining = population_size - len(next_population)
                ordered = sorted(front, key=lambda index: distance[index], reverse=True)
                next_population.extend(combined[index] for index in ordered[:remaining])
                break
        population = next_population

    return population, evaluations


ALGORITHM_IMPL: dict[
    OptimizerAlgorithm,
    Callable[..., tuple[list[_Candidate], int]],
] = {
    "random_search": optimize_random_search,
    "hill_climbing": optimize_hill_climbing,
    "simulated_annealing": optimize_simulated_annealing,
    "genetic_algorithm": optimize_genetic_algorithm,
    "nsga2": optimize_nsga2,
}


def run_algorithm(
    context: _EvaluationContext,
    algorithm: OptimizerAlgorithm,
    *,
    seed: int,
    iterations: int = 200,
    population_size: int = 40,
    generations: int = 30,
) -> AlgorithmResult:
    """Run one optimization algorithm and return its Pareto front."""
    if algorithm == "random_search":
        candidates, evaluations = optimize_random_search(context, iterations=iterations, seed=seed)
    elif algorithm in {"hill_climbing", "simulated_annealing"}:
        candidates, evaluations = ALGORITHM_IMPL[algorithm](
            context,
            iterations=iterations,
            seed=seed,
        )
    else:
        candidates, evaluations = ALGORITHM_IMPL[algorithm](
            context,
            population_size=population_size,
            generations=generations,
            seed=seed,
        )
    pareto_front = extract_pareto_front(
        algorithm=algorithm,
        context=context,
        candidates=candidates,
    )
    return AlgorithmResult(
        algorithm=algorithm,
        evaluations=evaluations,
        pareto_front=pareto_front,
    )


def merge_pareto_fronts(fronts: Sequence[Sequence[ParetoSolution]]) -> list[ParetoSolution]:
    """Merge algorithm-specific fronts into one combined Pareto front."""
    combined: list[ParetoSolution] = []
    for front in fronts:
        combined.extend(front)
    if not combined:
        return []

    kept: list[ParetoSolution] = []
    for candidate in combined:
        if any(dominates(other.objectives, candidate.objectives) for other in combined if other is not candidate):
            continue
        kept.append(candidate)
    kept.sort(
        key=lambda item: (
            -item.objectives.mutation_score,
            -item.objectives.transition_coverage,
            item.objectives.suite_size,
            item.objectives.execution_cost,
        )
    )
    return kept


def optimize_test_suites(
    reference: FSM,
    suite: OracleSuite,
    mutants: tuple[MutantRecord, ...],
    *,
    algorithms: Sequence[OptimizerAlgorithm] | None = None,
    seed: int = 42,
    iterations: int = 200,
    population_size: int = 40,
    generations: int = 30,
) -> TestSuiteOptimizationReport:
    """Run search-based optimizers and return Pareto fronts."""
    selected_algorithms = tuple(algorithms or SUPPORTED_OPTIMIZER_ALGORITHMS)
    context = build_evaluation_context(reference, suite, mutants)
    results: dict[str, AlgorithmResult] = {}

    for index, algorithm in enumerate(selected_algorithms):
        results[algorithm] = run_algorithm(
            context,
            algorithm,
            seed=seed + index * 1000,
            iterations=iterations,
            population_size=population_size,
            generations=generations,
        )

    combined = merge_pareto_fronts([result.pareto_front for result in results.values()])
    return TestSuiteOptimizationReport(
        reference_fsm_id=reference.id,
        source_oracle_suite_id=suite.id,
        seed=seed,
        scenario_count=len(suite.scenarios),
        mutant_count=len(mutants),
        algorithms=results,
        combined_pareto_front=combined,
    )


def selected_suite_from_solution(
    source: OracleSuite,
    solution: ParetoSolution,
    *,
    suffix: str,
) -> OracleSuite:
    """Materialize a Pareto solution as an ``OracleSuite``."""
    selected_ids = set(solution.scenario_ids)
    return OracleSuite(
        id=f"{source.id}__optimized__{suffix}",
        fsm_id=source.fsm_id,
        scenarios=[scenario for scenario in source.scenarios if scenario.id in selected_ids],
        semantics_mode=source.semantics_mode,
        probability_threshold=source.probability_threshold,
    )


def write_optimization_report_json(path: Path, report: TestSuiteOptimizationReport) -> None:
    """Write optimization report JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.model_dump_json(indent=2) + "\n", encoding="utf-8")


def visualize_pareto_results(
    report: TestSuiteOptimizationReport,
    output_dir: Path,
) -> list[Path]:
    """Write Pareto front visualization plots to *output_dir*."""
    plt = _pyplot()
    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    algorithm_colors = {
        "random_search": "#1f77b4",
        "hill_climbing": "#ff7f0e",
        "simulated_annealing": "#2ca02c",
        "genetic_algorithm": "#d62728",
        "nsga2": "#9467bd",
    }

    fig, axis = plt.subplots(figsize=(8, 6))
    for algorithm, result in report.algorithms.items():
        if not result.pareto_front:
            continue
        xs = [solution.objectives.mutation_score for solution in result.pareto_front]
        ys = [solution.objectives.transition_coverage for solution in result.pareto_front]
        sizes = [40 + 10 * solution.objectives.suite_size for solution in result.pareto_front]
        axis.scatter(
            xs,
            ys,
            s=sizes,
            alpha=0.75,
            label=algorithm,
            c=algorithm_colors.get(algorithm, "#333333"),
        )
    axis.set_xlabel("Mutation score (maximize)")
    axis.set_ylabel("Transition coverage (maximize)")
    axis.set_title("Pareto fronts: mutation score vs transition coverage")
    axis.legend()
    axis.grid(True, alpha=0.3)
    path = output_dir / "pareto_mutation_vs_transition.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    fig, axis = plt.subplots(figsize=(8, 6))
    for algorithm, result in report.algorithms.items():
        if not result.pareto_front:
            continue
        xs = [solution.objectives.suite_size for solution in result.pareto_front]
        ys = [solution.objectives.execution_cost for solution in result.pareto_front]
        axis.scatter(
            xs,
            ys,
            alpha=0.75,
            label=algorithm,
            c=algorithm_colors.get(algorithm, "#333333"),
        )
    axis.set_xlabel("Test suite size (minimize)")
    axis.set_ylabel("Execution cost (minimize)")
    axis.set_title("Pareto fronts: suite size vs execution cost")
    axis.legend()
    axis.grid(True, alpha=0.3)
    path = output_dir / "pareto_size_vs_cost.png"
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)
    written.append(path)

    if report.combined_pareto_front:
        fig, axis = plt.subplots(figsize=(8, 6))
        xs = [solution.objectives.mutation_score for solution in report.combined_pareto_front]
        ys = [solution.objectives.transition_coverage for solution in report.combined_pareto_front]
        colors = [algorithm_colors.get(solution.algorithm, "#333333") for solution in report.combined_pareto_front]
        axis.scatter(xs, ys, c=colors, s=70, alpha=0.85)
        for solution, x_value, y_value in zip(report.combined_pareto_front, xs, ys, strict=True):
            axis.annotate(
                f"n={solution.objectives.suite_size}",
                (x_value, y_value),
                textcoords="offset points",
                xytext=(4, 4),
                fontsize=8,
            )
        axis.set_xlabel("Mutation score")
        axis.set_ylabel("Transition coverage")
        axis.set_title("Combined Pareto front")
        axis.grid(True, alpha=0.3)
        path = output_dir / "pareto_combined.png"
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)
        written.append(path)

    manifest = {
        "plots": [str(item.name) for item in written],
        "combined_pareto_size": len(report.combined_pareto_front),
    }
    manifest_path = output_dir / "pareto_plots.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    written.append(manifest_path)
    return written
