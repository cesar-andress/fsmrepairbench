"""Oracle execution helpers."""

from __future__ import annotations

from fsmrepairbench.models import (
    FSM,
    OracleScenario,
    OracleStep,
    OracleSuite,
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


def _find_transition(
    fsm: FSM,
    current_state: str,
    step: OracleStep,
) -> Transition | None:
    for transition in fsm.transitions:
        if transition.source != current_state:
            continue
        if transition.event != step.event:
            continue
        if step.guard != transition.guard:
            continue
        return transition
    return None


def execute_scenario(fsm: FSM, scenario: OracleScenario) -> ScenarioResult:
    """Execute *scenario* against *fsm* and return step-level results."""
    current_state = fsm.initial_state
    step_results: list[StepResult] = []
    scenario_passed = True

    for step_index, step in enumerate(scenario.steps):
        transition = _find_transition(fsm, current_state, step)
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
        passed = current_state == step.expected_state
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


def simulate_scenario(fsm: FSM, scenario: OracleScenario) -> bool:
    """Return whether *scenario* passes when executed against *fsm*."""
    return execute_scenario(fsm, scenario).passed
