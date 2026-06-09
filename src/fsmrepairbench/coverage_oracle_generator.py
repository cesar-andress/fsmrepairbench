"""Multi-criterion oracle suite generation with coverage-aware minimization."""

from __future__ import annotations

import json
from collections import deque
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fsmrepairbench.coverage import _all_feasible_sequences, _reachable_transitions
from fsmrepairbench.literature_mutation import generate_literature_mutants
from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite, Transition
from fsmrepairbench.oracle import execute_scenario, trace_scenario_transitions
from fsmrepairbench.oracle_generator import (
    _scenario_for_state,
    _scenario_for_transition,
    find_path_to_state,
    reachable_state_ids,
)

CoverageSuiteType = Literal[
    "transition_coverage",
    "state_coverage",
    "path_coverage",
    "boundary_coverage",
    "mutation_killing",
]

SUPPORTED_COVERAGE_SUITE_TYPES: tuple[CoverageSuiteType, ...] = (
    "transition_coverage",
    "state_coverage",
    "path_coverage",
    "boundary_coverage",
    "mutation_killing",
)

DEFAULT_MAX_DEPTH = 25
DEFAULT_PATH_LENGTH = 3
DEFAULT_MUTATION_KILLING_COUNT = 10


class CoverageOracleGeneratorError(ValueError):
    """Raised when coverage oracle generation fails."""


class TestSequence(BaseModel):
    """One observable test sequence exported from an oracle scenario."""

    id: str
    description: str = ""
    inputs: list[str]
    expected_outputs: list[str | None]
    expected_states: list[str]


class CoverageOracleSuite(BaseModel):
    """One minimized oracle suite targeting a coverage criterion."""

    suite_type: CoverageSuiteType
    suite_id: str
    fsm_id: str
    sequence_count: int
    coverage_total: int
    coverage_covered: int
    coverage_ratio: float
    sequences: list[TestSequence]


class CoverageOracleExport(BaseModel):
    """All coverage oracle suites generated for one FSM."""

    fsm_id: str
    generation_seed: int
    max_depth: int
    path_length: int
    suites: dict[CoverageSuiteType, CoverageOracleSuite]


@dataclass(frozen=True)
class _MutantTarget:
    mutant_id: str
    fsm: FSM


def _match_transition(fsm: FSM, current_state: str, step: OracleStep) -> Transition | None:
    for transition in fsm.transitions:
        if transition.source != current_state:
            continue
        if transition.event != step.event:
            continue
        if step.guard != transition.guard:
            continue
        return transition
    return None


def _encode_input(step: OracleStep) -> str:
    if step.guard is None:
        return step.event
    return f"{step.event}::{step.guard}"


def _step_output(fsm: FSM, transition: Transition, target_state: str) -> str | None:
    if transition.output is not None:
        return transition.output
    state_lookup = {state.id: state for state in fsm.states}
    state_output = state_lookup.get(target_state)
    if state_output is not None and state_output.state_output is not None:
        return state_output.state_output
    return transition.action


def scenario_to_test_sequence(fsm: FSM, scenario: OracleScenario) -> TestSequence:
    """Convert an oracle scenario to exported input/output/state arrays."""
    inputs: list[str] = []
    expected_outputs: list[str | None] = []
    expected_states: list[str] = []
    current_state = fsm.initial_state

    for step in scenario.steps:
        inputs.append(_encode_input(step))
        transition = _match_transition(fsm, current_state, step)
        if transition is None:
            expected_outputs.append(None)
            expected_states.append(step.expected_state)
            break
        expected_outputs.append(_step_output(fsm, transition, transition.target))
        expected_states.append(step.expected_state)
        current_state = transition.target

    return TestSequence(
        id=scenario.id,
        description=scenario.description,
        inputs=inputs,
        expected_outputs=expected_outputs,
        expected_states=expected_states,
    )


def _scenario_signature(scenario: OracleScenario) -> tuple[tuple[str | None, str, str | None], ...]:
    return tuple((step.guard, step.event, step.expected_state) for step in scenario.steps)


def _dedupe_scenarios(scenarios: Iterable[OracleScenario]) -> list[OracleScenario]:
    seen: set[tuple[tuple[str | None, str, str | None], ...]] = set()
    unique: list[OracleScenario] = []
    for scenario in scenarios:
        signature = _scenario_signature(scenario)
        if signature in seen:
            continue
        seen.add(signature)
        unique.append(scenario)
    return unique


def _greedy_minimize(
    candidates: Sequence[OracleScenario],
    universe: set[str],
    cover: Callable[[OracleScenario], set[str]],
) -> list[OracleScenario]:
    """Select a minimum subset of scenarios covering *universe* greedily."""
    if not universe:
        return []
    selected: list[OracleScenario] = []
    uncovered = set(universe)
    remaining = list(candidates)

    while uncovered and remaining:
        best_index = max(
            range(len(remaining)),
            key=lambda index: len(cover(remaining[index]) & uncovered),
        )
        best = remaining[best_index]
        gain = cover(best) & uncovered
        if not gain:
            break
        selected.append(best)
        uncovered -= gain
        remaining.pop(best_index)
    return selected


def _transition_cover(fsm: FSM, scenario: OracleScenario) -> set[str]:
    return set(trace_scenario_transitions(fsm, scenario))


def _state_cover(fsm: FSM, scenario: OracleScenario) -> set[str]:
    reachable = reachable_state_ids(fsm)
    states = [fsm.initial_state]
    current_state = fsm.initial_state
    for step in scenario.steps:
        transition = _match_transition(fsm, current_state, step)
        if transition is None:
            break
        current_state = transition.target
        states.append(current_state)
    return {state_id for state_id in states if state_id in reachable}


def _path_cover(fsm: FSM, scenario: OracleScenario, *, max_length: int) -> set[str]:
    transition_path = trace_scenario_transitions(fsm, scenario)
    covered: set[str] = set()
    for length in range(1, min(max_length, len(transition_path)) + 1):
        for start in range(len(transition_path) - length + 1):
            fragment = transition_path[start : start + length]
            covered.add("->".join(fragment))
    return covered


def _boundary_cover(fsm: FSM, scenario: OracleScenario, boundary_universe: set[str]) -> set[str]:
    covered = set()
    if not scenario.steps:
        if f"boundary:initial:{fsm.initial_state}" in boundary_universe:
            covered.add(f"boundary:initial:{fsm.initial_state}")
        return covered

    current_state = fsm.initial_state
    if f"boundary:initial:{fsm.initial_state}" in boundary_universe:
        covered.add(f"boundary:initial:{fsm.initial_state}")

    for step in scenario.steps:
        transition = _match_transition(fsm, current_state, step)
        if transition is None:
            break
        if transition.guard:
            key = f"boundary:guard:{transition.id}"
            if key in boundary_universe:
                covered.add(key)
        else:
            key = f"boundary:unguarded:{transition.id}"
            if key in boundary_universe:
                covered.add(key)
        if transition.timeout is not None:
            key = f"boundary:timeout:{transition.id}"
            if key in boundary_universe:
                covered.add(key)
        sink_key = f"boundary:sink:{transition.target}"
        if sink_key in boundary_universe:
            covered.add(sink_key)
        out_degree_key = f"boundary:max_out_degree:{transition.source}"
        if out_degree_key in boundary_universe:
            covered.add(out_degree_key)
        event_key = f"boundary:event:{transition.event}"
        if event_key in boundary_universe:
            covered.add(event_key)
        current_state = transition.target
    return covered & boundary_universe


def _mutation_cover(reference: FSM, mutants: Sequence[_MutantTarget], scenario: OracleScenario) -> set[str]:
    if not execute_scenario(reference, scenario).passed:
        return set()
    detected: set[str] = set()
    for mutant in mutants:
        if not execute_scenario(mutant.fsm, scenario).passed:
            detected.add(mutant.mutant_id)
    return detected


def _build_transition_candidates(fsm: FSM, *, max_depth: int) -> list[OracleScenario]:
    scenarios: list[OracleScenario] = []
    for transition in _reachable_transitions(fsm):
        scenario = _scenario_for_transition(fsm, transition, max_depth=max_depth)
        if scenario is not None:
            scenarios.append(scenario)
    return _dedupe_scenarios(scenarios)


def _build_state_candidates(fsm: FSM, *, max_depth: int) -> list[OracleScenario]:
    scenarios: list[OracleScenario] = []
    for state_id in sorted(reachable_state_ids(fsm)):
        scenario = _scenario_for_state(fsm, state_id, max_depth=max_depth)
        if scenario is not None:
            scenarios.append(scenario)
    return _dedupe_scenarios(scenarios)


def _build_path_candidates(fsm: FSM, *, max_depth: int, path_length: int) -> list[OracleScenario]:
    scenarios: list[OracleScenario] = []
    queue: deque[tuple[str, list[OracleStep], list[str]]] = deque(
        [(fsm.initial_state, [], [])]
    )
    seen_paths: set[tuple[str, ...]] = set()

    while queue:
        state, steps, transition_ids = queue.popleft()
        if transition_ids:
            signature = tuple(transition_ids)
            if signature not in seen_paths and len(transition_ids) <= path_length:
                seen_paths.add(signature)
                scenarios.append(
                    OracleScenario(
                        id=f"path_{'_'.join(transition_ids)}",
                        description=f"Path covering transitions {' -> '.join(transition_ids)}",
                        steps=steps,
                    )
                )
        if len(steps) >= max_depth or len(transition_ids) >= path_length:
            continue
        for transition in _reachable_transitions(fsm):
            if transition.source != state:
                continue
            next_steps = steps + [
                OracleStep(
                    event=transition.event,
                    guard=transition.guard,
                    expected_state=transition.target,
                )
            ]
            next_ids = [*transition_ids, transition.id]
            queue.append((transition.target, next_steps, next_ids))

    return _dedupe_scenarios(scenarios)


def _sink_states(fsm: FSM) -> list[str]:
    reachable = reachable_state_ids(fsm)
    outgoing: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable:
            outgoing[transition.source] += 1
    return [state_id for state_id in reachable if outgoing[state_id] == 0]


def _max_out_degree_states(fsm: FSM) -> list[str]:
    reachable = reachable_state_ids(fsm)
    outgoing: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable:
            outgoing[transition.source] += 1
    if not outgoing:
        return []
    maximum = max(outgoing.values())
    return sorted(state_id for state_id, count in outgoing.items() if count == maximum)


def _boundary_universe(fsm: FSM) -> set[str]:
    universe = {f"boundary:initial:{fsm.initial_state}"}
    for state_id in _sink_states(fsm):
        universe.add(f"boundary:sink:{state_id}")
    for state_id in _max_out_degree_states(fsm):
        universe.add(f"boundary:max_out_degree:{state_id}")
    for transition in _reachable_transitions(fsm):
        if transition.guard:
            universe.add(f"boundary:guard:{transition.id}")
        else:
            universe.add(f"boundary:unguarded:{transition.id}")
        if transition.timeout is not None:
            universe.add(f"boundary:timeout:{transition.id}")
        universe.add(f"boundary:event:{transition.event}")
    return universe


def _build_boundary_candidates(fsm: FSM, *, max_depth: int) -> list[OracleScenario]:
    scenarios: list[OracleScenario] = []
    scenarios.append(
        OracleScenario(
            id="boundary_initial",
            description=f"Boundary case for initial state '{fsm.initial_state}'",
            steps=[],
        )
    )

    for state_id in _sink_states(fsm):
        prefix = find_path_to_state(fsm, state_id, max_depth=max_depth)
        if prefix is None:
            continue
        scenarios.append(
            OracleScenario(
                id=f"boundary_sink_{state_id}",
                description=f"Boundary case for sink state '{state_id}'",
                steps=prefix,
            )
        )

    for state_id in _max_out_degree_states(fsm):
        prefix = find_path_to_state(fsm, state_id, max_depth=max_depth)
        if prefix is None:
            continue
        outgoing = [transition for transition in _reachable_transitions(fsm) if transition.source == state_id]
        if not outgoing:
            continue
        transition = outgoing[0]
        scenarios.append(
            OracleScenario(
                id=f"boundary_max_out_degree_{state_id}",
                description=f"Boundary case for max out-degree state '{state_id}'",
                steps=prefix
                + [
                    OracleStep(
                        event=transition.event,
                        guard=transition.guard,
                        expected_state=transition.target,
                    )
                ],
            )
        )

    for transition in _reachable_transitions(fsm):
        scenario = _scenario_for_transition(fsm, transition, max_depth=max_depth)
        if scenario is not None:
            scenarios.append(
                OracleScenario(
                    id=f"boundary_transition_{transition.id}",
                    description=f"Boundary case for transition '{transition.id}'",
                    steps=scenario.steps,
                )
            )

    if fsm.events:
        first_event = fsm.events[0]
        last_event = fsm.events[-1]
        for event, label in ((first_event, "first_event"), (last_event, "last_event")):
            for transition in _reachable_transitions(fsm):
                if transition.event != event:
                    continue
                scenario = _scenario_for_transition(fsm, transition, max_depth=max_depth)
                if scenario is None:
                    continue
                scenarios.append(
                    OracleScenario(
                        id=f"boundary_{label}_{event}",
                        description=f"Boundary case for alphabet {label} '{event}'",
                        steps=scenario.steps,
                    )
                )
                break

    return _dedupe_scenarios(scenarios)


def _load_mutants_for_killing(fsm: FSM, *, seed: int, count: int) -> list[_MutantTarget]:
    report = generate_literature_mutants(
        fsm,
        seed=seed,
        first_order_count=count,
        second_order_count=0,
        higher_order_count=0,
        include_fsm=True,
    )
    mutants: list[_MutantTarget] = []
    for record in report.mutants:
        if record.fsm is None:
            continue
        mutants.append(_MutantTarget(mutant_id=record.mutant_id, fsm=record.fsm))
    if not mutants:
        msg = "Could not generate mutants for mutation-killing suite"
        raise CoverageOracleGeneratorError(msg)
    return mutants


def _build_suite(
    *,
    fsm: FSM,
    suite_type: CoverageSuiteType,
    selected: Sequence[OracleScenario],
    coverage_total: int,
    coverage_covered: int,
) -> CoverageOracleSuite:
    sequences = [scenario_to_test_sequence(fsm, scenario) for scenario in selected]
    ratio = 1.0 if coverage_total <= 0 else coverage_covered / coverage_total
    return CoverageOracleSuite(
        suite_type=suite_type,
        suite_id=f"{fsm.id}_{suite_type}",
        fsm_id=fsm.id,
        sequence_count=len(sequences),
        coverage_total=coverage_total,
        coverage_covered=coverage_covered,
        coverage_ratio=round(ratio, 6),
        sequences=sequences,
    )


def generate_transition_coverage_suite(
    fsm: FSM,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> CoverageOracleSuite:
    """Generate a minimized transition coverage oracle suite."""
    universe = {transition.id for transition in _reachable_transitions(fsm)}
    candidates = _build_transition_candidates(fsm, max_depth=max_depth)
    selected = _greedy_minimize(
        candidates,
        universe,
        lambda scenario: _transition_cover(fsm, scenario),
    )
    covered = set().union(*(_transition_cover(fsm, scenario) for scenario in selected))
    return _build_suite(
        fsm=fsm,
        suite_type="transition_coverage",
        selected=selected,
        coverage_total=len(universe),
        coverage_covered=len(covered & universe),
    )


def generate_state_coverage_suite(
    fsm: FSM,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> CoverageOracleSuite:
    """Generate a minimized state coverage oracle suite."""
    universe = set(reachable_state_ids(fsm))
    candidates = _build_state_candidates(fsm, max_depth=max_depth)
    selected = _greedy_minimize(
        candidates,
        universe,
        lambda scenario: _state_cover(fsm, scenario),
    )
    covered = set().union(*(_state_cover(fsm, scenario) for scenario in selected))
    return _build_suite(
        fsm=fsm,
        suite_type="state_coverage",
        selected=selected,
        coverage_total=len(universe),
        coverage_covered=len(covered & universe),
    )


def generate_path_coverage_suite(
    fsm: FSM,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
    path_length: int = DEFAULT_PATH_LENGTH,
) -> CoverageOracleSuite:
    """Generate a minimized transition-path coverage oracle suite."""
    universe = {"->".join(sequence) for sequence in _all_feasible_sequences(fsm, max_length=path_length)}
    candidates = _build_path_candidates(fsm, max_depth=max_depth, path_length=path_length)
    selected = _greedy_minimize(
        candidates,
        universe,
        lambda scenario: _path_cover(fsm, scenario, max_length=path_length),
    )
    covered = set().union(
        *(_path_cover(fsm, scenario, max_length=path_length) for scenario in selected)
    )
    return _build_suite(
        fsm=fsm,
        suite_type="path_coverage",
        selected=selected,
        coverage_total=len(universe),
        coverage_covered=len(covered & universe),
    )


def generate_boundary_coverage_suite(
    fsm: FSM,
    *,
    max_depth: int = DEFAULT_MAX_DEPTH,
) -> CoverageOracleSuite:
    """Generate a minimized boundary coverage oracle suite."""
    universe = _boundary_universe(fsm)
    candidates = _build_boundary_candidates(fsm, max_depth=max_depth)
    selected = _greedy_minimize(
        candidates,
        universe,
        lambda scenario: _boundary_cover(fsm, scenario, universe),
    )
    covered = set().union(
        *(_boundary_cover(fsm, scenario, universe) for scenario in selected)
    )
    return _build_suite(
        fsm=fsm,
        suite_type="boundary_coverage",
        selected=selected,
        coverage_total=len(universe),
        coverage_covered=len(covered & universe),
    )


def generate_mutation_killing_suite(
    fsm: FSM,
    *,
    seed: int,
    max_depth: int = DEFAULT_MAX_DEPTH,
    mutant_count: int = DEFAULT_MUTATION_KILLING_COUNT,
) -> CoverageOracleSuite:
    """Generate a minimized mutation-killing oracle suite."""
    mutants = _load_mutants_for_killing(fsm, seed=seed, count=mutant_count)
    universe = {mutant.mutant_id for mutant in mutants}
    candidates = _build_transition_candidates(fsm, max_depth=max_depth)
    candidates.extend(_build_path_candidates(fsm, max_depth=max_depth, path_length=2))
    candidates = _dedupe_scenarios(candidates)
    selected = _greedy_minimize(
        candidates,
        universe,
        lambda scenario: _mutation_cover(fsm, mutants, scenario),
    )
    covered = set().union(
        *(_mutation_cover(fsm, mutants, scenario) for scenario in selected)
    )
    return _build_suite(
        fsm=fsm,
        suite_type="mutation_killing",
        selected=selected,
        coverage_total=len(universe),
        coverage_covered=len(covered & universe),
    )


def generate_all_coverage_oracle_suites(
    fsm: FSM,
    *,
    seed: int = 42,
    max_depth: int = DEFAULT_MAX_DEPTH,
    path_length: int = DEFAULT_PATH_LENGTH,
    mutant_count: int = DEFAULT_MUTATION_KILLING_COUNT,
) -> CoverageOracleExport:
    """Generate all five coverage oracle suites for *fsm*."""
    if not reachable_state_ids(fsm):
        msg = "FSM has no reachable states"
        raise CoverageOracleGeneratorError(msg)

    suites: dict[CoverageSuiteType, CoverageOracleSuite] = {
        "transition_coverage": generate_transition_coverage_suite(fsm, max_depth=max_depth),
        "state_coverage": generate_state_coverage_suite(fsm, max_depth=max_depth),
        "path_coverage": generate_path_coverage_suite(
            fsm,
            max_depth=max_depth,
            path_length=path_length,
        ),
        "boundary_coverage": generate_boundary_coverage_suite(fsm, max_depth=max_depth),
        "mutation_killing": generate_mutation_killing_suite(
            fsm,
            seed=seed,
            max_depth=max_depth,
            mutant_count=mutant_count,
        ),
    }
    return CoverageOracleExport(
        fsm_id=fsm.id,
        generation_seed=seed,
        max_depth=max_depth,
        path_length=path_length,
        suites=suites,
    )


def export_to_oracle_suite(export_suite: CoverageOracleSuite) -> OracleSuite:
    """Convert an export suite back to benchmark ``OracleSuite`` scenarios."""
    scenarios: list[OracleScenario] = []
    for sequence in export_suite.sequences:
        steps = [
            OracleStep(
                event=step_input.split("::", 1)[0],
                guard=step_input.split("::", 1)[1] if "::" in step_input else None,
                expected_state=expected_state,
            )
            for step_input, expected_state in zip(
                sequence.inputs,
                sequence.expected_states,
                strict=True,
            )
        ]
        scenarios.append(
            OracleScenario(
                id=sequence.id,
                description=sequence.description,
                steps=steps,
            )
        )
    return OracleSuite(id=export_suite.suite_id, fsm_id=export_suite.fsm_id, scenarios=scenarios)


def export_coverage_oracles_json(path: Path, export: CoverageOracleExport) -> None:
    """Write all suites for one FSM to a single JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(export.model_dump_json(indent=2) + "\n", encoding="utf-8")


def export_coverage_oracles_directory(output_dir: Path, export: CoverageOracleExport) -> None:
    """Write one JSON file per suite plus a manifest."""
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "fsm_id": export.fsm_id,
        "generation_seed": export.generation_seed,
        "max_depth": export.max_depth,
        "path_length": export.path_length,
        "suite_files": {},
    }
    for suite_type, suite in export.suites.items():
        filename = f"{suite_type}.json"
        suite_path = output_dir / filename
        suite_path.write_text(suite.model_dump_json(indent=2) + "\n", encoding="utf-8")
        manifest["suite_files"][suite_type] = filename
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def generate_coverage_oracles_for_directory(
    input_dir: Path,
    output_dir: Path,
    *,
    seed: int = 42,
    max_depth: int = DEFAULT_MAX_DEPTH,
    path_length: int = DEFAULT_PATH_LENGTH,
) -> list[Path]:
    """Generate coverage oracle suites for every ``fsm_*.json`` in *input_dir*."""
    fsm_paths = sorted(input_dir.glob("fsm_*.json"))
    if not fsm_paths and (input_dir / "reference_fsm.json").exists():
        fsm_paths = [input_dir / "reference_fsm.json"]
    if not fsm_paths:
        msg = f"No FSM JSON files found in {input_dir}"
        raise CoverageOracleGeneratorError(msg)

    from fsmrepairbench.validators import load_fsm_json

    written: list[Path] = []
    output_dir.mkdir(parents=True, exist_ok=True)
    for index, fsm_path in enumerate(fsm_paths, start=1):
        fsm = load_fsm_json(fsm_path)
        export = generate_all_coverage_oracle_suites(
            fsm,
            seed=seed + index * 1000,
            max_depth=max_depth,
            path_length=path_length,
        )
        target_dir = output_dir / fsm.id
        export_coverage_oracles_directory(target_dir, export)
        written.append(target_dir / "manifest.json")
    return written
