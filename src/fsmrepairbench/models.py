"""Pydantic schemas for FSMRepairBench."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class State(BaseModel):
    """A single state in a finite-state machine."""

    id: str
    state_output: str | None = None


class Transition(BaseModel):
    """A directed edge triggered by an event."""

    id: str
    source: str
    event: str
    target: str
    guard: str | None = None
    action: str | None = None
    output: str | None = None
    timeout: float | None = None
    delay: float | None = None
    requirements: list[str] = Field(default_factory=list)


class FSM(BaseModel):
    """Behavioural finite-state machine definition."""

    id: str
    name: str
    description: str = ""
    states: list[State]
    initial_state: str
    events: list[str]
    transitions: list[Transition] = Field(default_factory=list)
    variables: dict[str, str] = Field(default_factory=dict)
    parent_fsm_id: str | None = None
    reference_fsm_id: str | None = None


class OracleStep(BaseModel):
    """One step in an oracle scenario: apply an event and expect a state."""

    event: str
    expected_state: str
    guard: str | None = None


class OracleScenario(BaseModel):
    """Named sequence of oracle steps."""

    id: str
    description: str = ""
    steps: list[OracleStep] = Field(default_factory=list)


class OracleSuite(BaseModel):
    """Collection of oracle scenarios for validating FSM behaviour."""

    id: str
    fsm_id: str | None = None
    scenarios: list[OracleScenario] = Field(default_factory=list)


class StepResult(BaseModel):
    """Outcome of executing a single oracle step."""

    step_index: int
    event: str
    guard: str | None = None
    expected_state: str
    actual_state: str | None = None
    passed: bool
    failure_reason: str | None = None


class ScenarioResult(BaseModel):
    """Outcome of executing an oracle scenario."""

    scenario_id: str
    passed: bool
    steps: list[StepResult] = Field(default_factory=list)
    passed_steps: int = 0
    total_steps: int = 0


class ScoreResult(BaseModel):
    """Aggregate scoring outcome for an oracle suite."""

    bpr: float = Field(ge=0.0, le=1.0)
    passed_steps: int = 0
    total_steps: int = 0
    passed_scenarios: int = 0
    total_scenarios: int = 0
    scenarios: list[ScenarioResult] = Field(default_factory=list)


class BugMetadata(BaseModel):
    """Metadata describing an injected bug used in a benchmark instance."""

    bug_id: str
    reference_fsm_id: str
    faulty_fsm_id: str
    mutation_operator: str
    changed_transition_id: str | None = None
    description: str
    seed: int
    mutation_complexity: str | None = None
    mutation_scope: str | None = None
    mutation_mode: str | None = None
    mutation_order: int | None = None
    component_faults: list[dict[str, str | int | None]] = Field(default_factory=list)
    is_higher_order: bool = False
    coupled_to_simple_faults: list[str] | None = None


class RepairResult(BaseModel):
    """Outcome of evaluating a candidate FSM repair against an oracle."""

    bug_id: str
    passed: bool
    score: float = Field(ge=0.0, le=1.0)
    details: dict[str, Any] = Field(default_factory=dict)
