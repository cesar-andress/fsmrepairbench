"""Error propagation and fault masking analysis for FSM benchmark cases."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.models import BugMetadata, FSM, OracleScenario, OracleSuite, Transition
from fsmrepairbench.oracle import execute_scenario, trace_scenario_transitions
from fsmrepairbench.validators import load_fsm_json, load_model, load_oracle_suite

MutantClass = str


class ErrorPropagationError(ValueError):
    """Raised when error propagation analysis fails."""


@dataclass(frozen=True)
class ScenarioTrace:
    """Execution trace for one scenario on one FSM."""

    transition_ids: tuple[str, ...]
    states_after_steps: tuple[str, ...]
    passed: bool


@dataclass(frozen=True)
class PropagationRecord:
    """Propagation outcome for one scenario/mutant pair."""

    scenario_id: str
    mutant_id: str
    activated_fault: bool
    infected_state: bool
    propagated_to_observable_state: bool
    oracle_detected_failure: bool
    masked_fault: bool
    reference_passes: bool
    faulty_passes: bool
    fault_transitions_executed: tuple[str, ...]
    first_divergence_step: int | None

    def to_dict(self) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "mutant_id": self.mutant_id,
            "activated_fault": self.activated_fault,
            "infected_state": self.infected_state,
            "propagated_to_observable_state": self.propagated_to_observable_state,
            "oracle_detected_failure": self.oracle_detected_failure,
            "masked_fault": self.masked_fault,
            "reference_passes": self.reference_passes,
            "faulty_passes": self.faulty_passes,
            "fault_transitions_executed": list(self.fault_transitions_executed),
            "first_divergence_step": self.first_divergence_step,
        }


@dataclass(frozen=True)
class PropagationSummary:
    """Aggregate mutant classification for a case."""

    scenarios_analyzed: int
    activated_count: int
    infected_count: int
    propagated_count: int
    detected_count: int
    masked_count: int
    easy_mutant: bool
    hard_to_kill_mutant: bool
    masked_mutant: bool
    equivalent_or_near_equivalent: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "scenarios_analyzed": self.scenarios_analyzed,
            "activated_count": self.activated_count,
            "infected_count": self.infected_count,
            "propagated_count": self.propagated_count,
            "detected_count": self.detected_count,
            "masked_count": self.masked_count,
            "easy_mutant": self.easy_mutant,
            "hard_to_kill_mutant": self.hard_to_kill_mutant,
            "masked_mutant": self.masked_mutant,
            "equivalent_or_near_equivalent": self.equivalent_or_near_equivalent,
        }


@dataclass(frozen=True)
class ErrorPropagationReport:
    """Full error propagation report for a benchmark case."""

    case_id: str
    reference_fsm_id: str
    mutant_id: str
    mutation_operator: str
    fault_sites: tuple[str, ...]
    records: tuple[PropagationRecord, ...]
    summary: PropagationSummary


def _transition_signature(transition: Transition) -> tuple[str, str, str, str | None, str | None]:
    return (
        transition.source,
        transition.event,
        transition.target,
        transition.guard,
        transition.action,
    )


def _identify_fault_sites(
    reference: FSM,
    faulty: FSM,
    metadata: BugMetadata | None,
) -> frozenset[str]:
    sites: set[str] = set()
    if metadata is not None and metadata.changed_transition_id:
        sites.add(metadata.changed_transition_id)

    reference_by_id = {transition.id: transition for transition in reference.transitions}
    faulty_by_id = {transition.id: transition for transition in faulty.transitions}

    for transition_id, faulty_transition in faulty_by_id.items():
        reference_transition = reference_by_id.get(transition_id)
        if reference_transition is None:
            sites.add(transition_id)
            continue
        if _transition_signature(reference_transition) != _transition_signature(faulty_transition):
            sites.add(transition_id)

    for transition_id in reference_by_id:
        if transition_id not in faulty_by_id:
            sites.add(transition_id)

    if metadata is not None and metadata.mutation_operator == "wrong_initial_state":
        sites.add("__initial_state__")

    return frozenset(sites)


def trace_scenario_execution(fsm: FSM, scenario: OracleScenario) -> ScenarioTrace:
    """Trace transition ids and post-step states for *scenario* on *fsm*."""
    transition_ids = trace_scenario_transitions(fsm, scenario)
    result = execute_scenario(fsm, scenario)
    states: list[str] = []
    current_state = fsm.initial_state
    for step_index, step in enumerate(scenario.steps):
        if step_index >= len(result.steps):
            break
        step_result = result.steps[step_index]
        if step_result.actual_state is not None:
            current_state = step_result.actual_state
        states.append(current_state)
    return ScenarioTrace(
        transition_ids=tuple(transition_ids),
        states_after_steps=tuple(states),
        passed=result.passed,
    )


def _reference_states_for_scenario(reference: FSM, scenario: OracleScenario) -> tuple[str, ...]:
    states: list[str] = []
    current_state = reference.initial_state
    for step in scenario.steps:
        matched: Transition | None = None
        for transition in reference.transitions:
            if transition.source != current_state:
                continue
            if transition.event != step.event:
                continue
            if step.guard != transition.guard:
                continue
            matched = transition
            break
        if matched is None:
            break
        current_state = matched.target
        states.append(current_state)
    return tuple(states)


def _first_divergence_step(
    reference_states: tuple[str, ...],
    faulty_states: tuple[str, ...],
) -> int | None:
    limit = min(len(reference_states), len(faulty_states))
    for index in range(limit):
        if reference_states[index] != faulty_states[index]:
            return index
    if len(reference_states) != len(faulty_states):
        return limit
    return None


def analyze_scenario_propagation(
    *,
    reference: FSM,
    faulty: FSM,
    scenario: OracleScenario,
    mutant_id: str,
    fault_sites: frozenset[str],
) -> PropagationRecord:
    """Analyze fault propagation for one scenario on the case mutant."""
    reference_trace = trace_scenario_execution(reference, scenario)
    faulty_trace = trace_scenario_execution(faulty, scenario)
    reference_states = _reference_states_for_scenario(reference, scenario)
    faulty_states = faulty_trace.states_after_steps

    fault_transitions_executed = tuple(
        transition_id
        for transition_id in faulty_trace.transition_ids
        if transition_id in fault_sites
    )
    activated_fault = bool(fault_transitions_executed) or reference.initial_state != faulty.initial_state

    divergence_step = _first_divergence_step(reference_states, faulty_states)
    infected_state = divergence_step is not None

    propagated_to_observable_state = False
    if divergence_step is not None and divergence_step < len(scenario.steps):
        propagated_to_observable_state = True
    elif divergence_step is not None:
        propagated_to_observable_state = infected_state

    reference_passes = reference_trace.passed
    faulty_passes = faulty_trace.passed
    oracle_detected_failure = reference_passes and not faulty_passes
    masked_fault = reference_passes and faulty_passes and (activated_fault or infected_state)

    return PropagationRecord(
        scenario_id=scenario.id,
        mutant_id=mutant_id,
        activated_fault=activated_fault,
        infected_state=infected_state,
        propagated_to_observable_state=propagated_to_observable_state,
        oracle_detected_failure=oracle_detected_failure,
        masked_fault=masked_fault,
        reference_passes=reference_passes,
        faulty_passes=faulty_passes,
        fault_transitions_executed=fault_transitions_executed,
        first_divergence_step=divergence_step,
    )


def _build_summary(records: tuple[PropagationRecord, ...]) -> PropagationSummary:
    activated_count = sum(1 for record in records if record.activated_fault)
    infected_count = sum(1 for record in records if record.infected_state)
    propagated_count = sum(1 for record in records if record.propagated_to_observable_state)
    detected_count = sum(1 for record in records if record.oracle_detected_failure)
    masked_count = sum(1 for record in records if record.masked_fault)

    any_detected = detected_count > 0
    any_activated = activated_count > 0
    any_masked = masked_count > 0
    any_infected_not_detected = any(
        record.infected_state and not record.oracle_detected_failure for record in records
    )

    equivalent_or_near_equivalent = (
        not any_activated
        and not any(record.infected_state for record in records)
        and all(record.reference_passes == record.faulty_passes for record in records)
    )
    easy_mutant = any_detected
    masked_mutant = any_masked and not any_detected
    hard_to_kill_mutant = (
        (any_activated or any_infected_not_detected) and not any_detected and not any_masked
    )

    return PropagationSummary(
        scenarios_analyzed=len(records),
        activated_count=activated_count,
        infected_count=infected_count,
        propagated_count=propagated_count,
        detected_count=detected_count,
        masked_count=masked_count,
        easy_mutant=easy_mutant,
        hard_to_kill_mutant=hard_to_kill_mutant,
        masked_mutant=masked_mutant,
        equivalent_or_near_equivalent=equivalent_or_near_equivalent,
    )


def load_case_artifacts(case_dir: Path) -> tuple[FSM, FSM, OracleSuite, BugMetadata | None]:
    """Load artefacts required for error propagation analysis."""
    reference_path = case_dir / "reference_fsm.json"
    faulty_path = case_dir / "faulty_fsm.json"
    oracle_path = case_dir / "oracle_suite.json"
    for path in (reference_path, faulty_path, oracle_path):
        if not path.is_file():
            msg = f"Missing required case file: {path}"
            raise ErrorPropagationError(msg)

    reference = load_fsm_json(reference_path)
    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    metadata: BugMetadata | None = None
    metadata_path = case_dir / "bug_metadata.json"
    if metadata_path.is_file():
        metadata = load_model(metadata_path, BugMetadata)
    return reference, faulty, oracle, metadata


def analyze_error_propagation(case_dir: Path) -> ErrorPropagationReport:
    """Analyze fault activation, propagation, and masking for *case_dir*."""
    if not case_dir.is_dir():
        msg = f"Case directory not found: {case_dir}"
        raise ErrorPropagationError(msg)

    reference, faulty, oracle, metadata = load_case_artifacts(case_dir)
    if not oracle.scenarios:
        msg = f"Oracle suite in {case_dir} contains no scenarios"
        raise ErrorPropagationError(msg)

    fault_sites = _identify_fault_sites(reference, faulty, metadata)
    mutant_id = faulty.id
    mutation_operator = metadata.mutation_operator if metadata is not None else "unknown"

    records = tuple(
        analyze_scenario_propagation(
            reference=reference,
            faulty=faulty,
            scenario=scenario,
            mutant_id=mutant_id,
            fault_sites=fault_sites,
        )
        for scenario in oracle.scenarios
    )

    return ErrorPropagationReport(
        case_id=case_dir.name,
        reference_fsm_id=reference.id,
        mutant_id=mutant_id,
        mutation_operator=mutation_operator,
        fault_sites=tuple(sorted(fault_sites)),
        records=records,
        summary=_build_summary(records),
    )


def error_propagation_report_to_dict(report: ErrorPropagationReport) -> dict[str, object]:
    """Convert an error propagation report to JSON-serialisable data."""
    return {
        "case_id": report.case_id,
        "reference_fsm_id": report.reference_fsm_id,
        "mutant_id": report.mutant_id,
        "mutation_operator": report.mutation_operator,
        "fault_sites": list(report.fault_sites),
        "records": [record.to_dict() for record in report.records],
        "summary": report.summary.to_dict(),
    }


def write_error_propagation_report_json(path: Path, report: ErrorPropagationReport) -> None:
    """Write *report* as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(error_propagation_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
