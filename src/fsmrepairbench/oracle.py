"""Oracle execution helpers."""

from __future__ import annotations

from fsmrepairbench.models import (
    FSM,
    OracleScenario,
    OracleSemanticsMode,
    OracleStep,
    OracleSuite,
    QUIESCENCE_EVENTS,
    REFUSAL_EVENTS,
    ScenarioResult,
    StepResult,
    Transition,
)


def count_steps(suite: OracleSuite) -> int:
    """Return the total number of oracle steps across all scenarios."""
    return sum(len(scenario.steps) for scenario in suite.scenarios)


def scenario_ids(suite: OracleSuite) -> list[str]:
    """Return scenario ids in declaration order."""
    return [scenario.id for scenario in suite.scenarios]


def scenario_names(suite: OracleSuite) -> list[str]:
    """Return scenario ids in declaration order (alias for :func:`scenario_ids`)."""
    return scenario_ids(suite)


def _find_matching_transitions(
    fsm: FSM,
    current_state: str,
    step: OracleStep,
) -> list[Transition]:
    matches: list[Transition] = []
    for transition in fsm.transitions:
        if transition.source != current_state:
            continue
        if transition.event != step.event:
            continue
        if step.guard != transition.guard:
            continue
        matches.append(transition)
    return matches


def _find_transition(
    fsm: FSM,
    current_state: str,
    step: OracleStep,
    *,
    semantics_mode: OracleSemanticsMode | None = None,
) -> Transition | None:
    matches = _find_matching_transitions(fsm, current_state, step)
    if not matches:
        return None
    if semantics_mode == "nondeterministic_accepting" and step.accepting_states:
        for transition in matches:
            if transition.target in step.accepting_states:
                return transition
    if semantics_mode == "probabilistic_threshold":
        threshold = step.probability_threshold or 0.0
        cumulative = 0.0
        ranked = sorted(
            matches,
            key=lambda transition: transition.probability or 0.0,
            reverse=True,
        )
        for transition in ranked:
            cumulative += transition.probability or 0.0
            if cumulative + 1e-9 >= threshold:
                return transition
    if semantics_mode == "refusal_aware":
        if step.refusal_expected:
            for transition in matches:
                if transition.refusal or transition.event in REFUSAL_EVENTS:
                    return transition
        if step.quiescence_expected:
            for transition in matches:
                if transition.quiescence or transition.event in QUIESCENCE_EVENTS:
                    return transition
    if semantics_mode == "timed_discrete" and step.discrete_time is not None:
        timed = [
            transition
            for transition in matches
            if transition.discrete_time == step.discrete_time
        ]
        if timed:
            return timed[0]
    return matches[0]


def execute_scenario(
    fsm: FSM,
    scenario: OracleScenario,
    *,
    semantics_mode: OracleSemanticsMode | None = None,
) -> ScenarioResult:
    """Execute *scenario* against *fsm* and return step-level results."""
    current_state = fsm.initial_state
    step_results: list[StepResult] = []
    scenario_passed = True

    for step_index, step in enumerate(scenario.steps):
        transition = _find_transition(
            fsm,
            current_state,
            step,
            semantics_mode=semantics_mode,
        )
        if transition is None:
            step_results.append(
                StepResult(
                    step_index=step_index,
                    event=step.event,
                    guard=step.guard,
                    expected_state=step.expected_state,
                    actual_state=current_state,
                    passed=False,
                    failure_reason="no_matching_transition",
                )
            )
            scenario_passed = False
            break

        current_state = transition.target
        acceptable_states = (
            set(step.accepting_states)
            if semantics_mode == "nondeterministic_accepting" and step.accepting_states
            else {step.expected_state}
        )
        passed = current_state in acceptable_states
        step_results.append(
            StepResult(
                step_index=step_index,
                event=step.event,
                guard=step.guard,
                expected_state=step.expected_state,
                actual_state=current_state,
                passed=passed,
                failure_reason=None if passed else "unexpected_state",
            )
        )
        if not passed:
            scenario_passed = False
            break

    passed_steps = sum(1 for result in step_results if result.passed)
    return ScenarioResult(
        scenario_id=scenario.id,
        passed=scenario_passed,
        steps=step_results,
        passed_steps=passed_steps,
        total_steps=len(scenario.steps),
    )


def simulate_scenario(
    fsm: FSM,
    scenario: OracleScenario,
    *,
    semantics_mode: OracleSemanticsMode | None = None,
) -> bool:
    """Return whether *scenario* passes when executed against *fsm*."""
    return execute_scenario(fsm, scenario, semantics_mode=semantics_mode).passed


def trace_scenario_transitions(
    fsm: FSM,
    scenario: OracleScenario,
    *,
    semantics_mode: OracleSemanticsMode | None = None,
) -> list[str]:
    """Return transition ids executed when *scenario* is run against *fsm*."""
    current_state = fsm.initial_state
    executed: list[str] = []

    for step in scenario.steps:
        transition = _find_transition(
            fsm,
            current_state,
            step,
            semantics_mode=semantics_mode,
        )
        if transition is None:
            break
        executed.append(transition.id)
        current_state = transition.target
        acceptable_states = (
            set(step.accepting_states)
            if semantics_mode == "nondeterministic_accepting" and step.accepting_states
            else {step.expected_state}
        )
        if current_state not in acceptable_states:
            break

    return executed
