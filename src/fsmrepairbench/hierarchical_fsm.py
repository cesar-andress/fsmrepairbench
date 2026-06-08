"""Hierarchical FSM models and multi-level oracle composition."""

from __future__ import annotations

from pydantic import BaseModel, Field

from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite, State, Transition
from fsmrepairbench.oracle_generator import DepthLevel, generate_oracle_suite

HIERARCHICAL_CSV_COLUMNS: tuple[str, ...] = (
    "level",
    "component_id",
    "scenario_id",
    "step_count",
)


class Subsystem(BaseModel):
    """Nested FSM representing a web-like subsystem."""

    id: str
    name: str
    fsm: FSM
    entry_event: str | None = None
    exit_event: str | None = None


class HierarchicalFSM(BaseModel):
    """Root FSM with attached subsystems for hierarchical modelling."""

    id: str
    name: str
    root: FSM
    subsystems: list[Subsystem] = Field(default_factory=list)


def flatten_hierarchical_fsm(hierarchical: HierarchicalFSM) -> FSM:
    """Flatten a hierarchical FSM into a single flat FSM for scoring."""
    states = [state.model_copy(deep=True) for state in hierarchical.root.states]
    transitions = [transition.model_copy(deep=True) for transition in hierarchical.root.transitions]
    events = list(hierarchical.root.events)
    state_ids = {state.id for state in states}

    for subsystem in hierarchical.subsystems:
        prefix = f"{subsystem.id}__"
        for state in subsystem.fsm.states:
            prefixed_id = f"{prefix}{state.id}"
            if prefixed_id not in state_ids:
                states.append(state.model_copy(update={"id": prefixed_id}))
                state_ids.add(prefixed_id)
        for transition in subsystem.fsm.transitions:
            transitions.append(
                transition.model_copy(
                    update={
                        "id": f"{prefix}{transition.id}",
                        "source": f"{prefix}{transition.source}",
                        "target": f"{prefix}{transition.target}",
                    }
                )
            )
            if transition.event not in events:
                events.append(transition.event)

        if subsystem.entry_event and subsystem.exit_event:
            entry_target = f"{prefix}{subsystem.fsm.initial_state}"
            transitions.append(
                Transition(
                    id=f"{prefix}entry",
                    source=hierarchical.root.initial_state,
                    event=subsystem.entry_event,
                    target=entry_target,
                )
            )
            transitions.append(
                Transition(
                    id=f"{prefix}exit",
                    source=entry_target,
                    event=subsystem.exit_event,
                    target=hierarchical.root.initial_state,
                )
            )
            for event in (subsystem.entry_event, subsystem.exit_event):
                if event not in events:
                    events.append(event)

    return FSM(
        id=hierarchical.id,
        name=hierarchical.name,
        description=f"Flattened hierarchy of {hierarchical.name}",
        states=states,
        initial_state=hierarchical.root.initial_state,
        events=events,
        transitions=transitions,
        variables=hierarchical.root.variables,
    )


def generate_hierarchical_oracle(
    hierarchical: HierarchicalFSM,
    *,
    depth: DepthLevel = "medium",
) -> OracleSuite:
    """Generate oracles for the root and each subsystem, then compose them."""
    flat = flatten_hierarchical_fsm(hierarchical)
    root_result = generate_oracle_suite(flat, depth=depth)

    scenarios: list[OracleScenario] = [
        scenario.model_copy(update={"id": f"root__{scenario.id}"})
        for scenario in root_result.suite.scenarios
    ]

    for subsystem in hierarchical.subsystems:
        subsystem_result = generate_oracle_suite(subsystem.fsm, depth=depth)
        prefix = subsystem.id
        for scenario in subsystem_result.suite.scenarios:
            prefixed_steps = [
                OracleStep(
                    event=step.event,
                    guard=step.guard,
                    expected_state=f"{prefix}__{step.expected_state}",
                )
                for step in scenario.steps
            ]
            scenarios.append(
                OracleScenario(
                    id=f"{prefix}__{scenario.id}",
                    description=f"Subsystem {prefix}: {scenario.description}",
                    steps=prefixed_steps,
                )
            )

    return OracleSuite(
        id=f"{hierarchical.id}_hierarchical_oracles",
        fsm_id=hierarchical.id,
        scenarios=scenarios,
    )


def hierarchical_oracle_to_csv_rows(suite: OracleSuite) -> list[dict[str, object]]:
    """Flatten hierarchical oracle scenarios to CSV rows."""
    rows: list[dict[str, object]] = []
    for scenario in suite.scenarios:
        level = "root"
        component_id = suite.fsm_id or ""
        if "__" in scenario.id:
            level, _ = scenario.id.split("__", maxsplit=1)
        rows.append(
            {
                "level": level,
                "component_id": component_id,
                "scenario_id": scenario.id,
                "step_count": len(scenario.steps),
            }
        )
    return rows
