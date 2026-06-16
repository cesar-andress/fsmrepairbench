"""Rescoring helpers for oracle-surface sensitivity studies."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from fsmrepairbench.models import FSM, OracleScenario, OracleSemanticsMode, OracleSuite, ScoreResult
from fsmrepairbench.oracle import _find_transition


class OracleSurfaceId(str, Enum):
    """Named oracle surfaces for controlled rescoring experiments."""

    S0_PUBLISHED = "S0"
    S1_ACTION_EXTENDED = "S1"


@dataclass(frozen=True)
class OracleSurfaceProfile:
    """Fields checked when deciding whether an executed step passes."""

    surface_id: OracleSurfaceId
    label: str
    check_state: bool = True
    check_action: bool = False


SURFACE_S0 = OracleSurfaceProfile(
    surface_id=OracleSurfaceId.S0_PUBLISHED,
    label="published",
    check_state=True,
    check_action=False,
)
SURFACE_S1 = OracleSurfaceProfile(
    surface_id=OracleSurfaceId.S1_ACTION_EXTENDED,
    label="action_extended",
    check_state=True,
    check_action=True,
)

SURFACE_PROFILES: dict[OracleSurfaceId, OracleSurfaceProfile] = {
    OracleSurfaceId.S0_PUBLISHED: SURFACE_S0,
    OracleSurfaceId.S1_ACTION_EXTENDED: SURFACE_S1,
}


def _acceptable_states(step, semantics_mode: OracleSemanticsMode | None) -> set[str]:
    if semantics_mode == "nondeterministic_accepting" and step.accepting_states:
        return set(step.accepting_states)
    return {step.expected_state}


def execute_scenario_with_surface(
    fsm: FSM,
    scenario: OracleScenario,
    *,
    reference: FSM,
    profile: OracleSurfaceProfile,
    semantics_mode: OracleSemanticsMode | None = None,
) -> tuple[bool, int, int]:
    """Execute *scenario* and return (passed, passed_steps, total_steps)."""
    current_state = fsm.initial_state
    reference_state = reference.initial_state
    passed_steps = 0
    scenario_passed = True

    for step in scenario.steps:
        transition = _find_transition(
            fsm,
            current_state,
            step,
            semantics_mode=semantics_mode,
        )
        reference_transition = _find_transition(
            reference,
            reference_state,
            step,
            semantics_mode=semantics_mode,
        )
        if transition is None or reference_transition is None:
            scenario_passed = False
            break

        current_state = transition.target
        reference_state = reference_transition.target
        acceptable = _acceptable_states(step, semantics_mode)

        passed = True
        if profile.check_state:
            passed = current_state in acceptable
        if profile.check_action:
            passed = passed and transition.action == reference_transition.action

        if passed:
            passed_steps += 1
        else:
            scenario_passed = False
            break

    return scenario_passed, passed_steps, len(scenario.steps)


def score_oracle_suite_with_surface(
    fsm: FSM,
    suite: OracleSuite,
    *,
    reference: FSM,
    profile: OracleSurfaceProfile,
) -> ScoreResult:
    """Score *fsm* against *suite* under the declared oracle surface."""
    semantics_mode = suite.semantics_mode or fsm.semantics_mode
    passed_steps = 0
    total_steps = 0
    passed_scenarios = 0
    total_scenarios = len(suite.scenarios)

    for scenario in suite.scenarios:
        scenario_passed, scenario_passed_steps, scenario_total_steps = execute_scenario_with_surface(
            fsm,
            scenario,
            reference=reference,
            profile=profile,
            semantics_mode=semantics_mode,
        )
        passed_steps += scenario_passed_steps
        total_steps += scenario_total_steps
        if scenario_passed:
            passed_scenarios += 1

    bpr = passed_steps / total_steps if total_steps else 0.0
    return ScoreResult(
        bpr=bpr,
        passed_steps=passed_steps,
        total_steps=total_steps,
        passed_scenarios=passed_scenarios,
        total_scenarios=total_scenarios,
        scenarios=(),
    )


def case_detected(reference_bpr: float, faulty_bpr: float) -> bool:
    """Return whether a fault is detectable under a surface (positive BPR delta)."""
    return (reference_bpr - faulty_bpr) > 0.0


def case_saturated(faulty_bpr: float) -> bool:
    """Return whether a fault is oracle-saturated (faulty BPR equals full pass)."""
    return faulty_bpr >= 1.0
