"""Constraint-based symbolic input generation for FSM path coverage."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass

from fsmrepairbench.models import FSM, OracleScenario, OracleStep, Transition
from fsmrepairbench.oracle import trace_scenario_transitions

CONSTRAINED_INPUT_CSV_COLUMNS: tuple[str, ...] = (
    "sequence_id",
    "step_index",
    "event",
    "guard",
    "expected_state",
    "transition_id",
)


@dataclass(frozen=True)
class ConstrainedInputSequence:
    """One generated input sequence with symbolic guard parameters."""

    sequence_id: str
    events: tuple[str, ...]
    guards: tuple[str | None, ...]
    expected_states: tuple[str, ...]
    transition_ids: tuple[str, ...]
    symbolic_params: dict[str, str]


@dataclass(frozen=True)
class ConstrainedInputPlan:
    """Plan of input sequences satisfying coverage constraints."""

    target_transition_coverage: float
    achieved_transition_coverage: float
    sequences: tuple[ConstrainedInputSequence, ...]
    uncovered_transitions: tuple[str, ...]


def _find_transition(fsm: FSM, current_state: str, event: str) -> Transition | None:
    for transition in fsm.transitions:
        if transition.source == current_state and transition.event == event:
            return transition
    return None


def _symbolic_params(transition: Transition) -> dict[str, str]:
    params: dict[str, str] = {"event": transition.event}
    if transition.guard:
        params["guard"] = transition.guard
    if transition.action:
        params["action"] = transition.action
    if transition.timeout is not None:
        params["timeout"] = str(transition.timeout)
    if transition.delay is not None:
        params["delay"] = str(transition.delay)
    return params


def _path_to_sequence(
    fsm: FSM,
    path: list[tuple[Transition, str]],
    *,
    sequence_id: str,
) -> ConstrainedInputSequence:
    events: list[str] = []
    guards: list[str | None] = []
    expected_states: list[str] = []
    transition_ids: list[str] = []
    symbolic: dict[str, str] = {}

    for index, (transition, expected_state) in enumerate(path):
        events.append(transition.event)
        guards.append(transition.guard)
        expected_states.append(expected_state)
        transition_ids.append(transition.id)
        symbolic.update({f"step_{index}_{key}": value for key, value in _symbolic_params(transition).items()})

    return ConstrainedInputSequence(
        sequence_id=sequence_id,
        events=tuple(events),
        guards=tuple(guards),
        expected_states=tuple(expected_states),
        transition_ids=tuple(transition_ids),
        symbolic_params=symbolic,
    )


def generate_constrained_inputs(
    fsm: FSM,
    *,
    target_transition_coverage: float = 1.0,
    max_path_length: int = 8,
    max_sequences: int = 32,
) -> ConstrainedInputPlan:
    """Generate event sequences that satisfy transition coverage constraints."""
    if not 0.0 <= target_transition_coverage <= 1.0:
        msg = "target_transition_coverage must be between 0 and 1"
        raise ValueError(msg)
    if max_path_length < 1:
        msg = "max_path_length must be at least 1"
        raise ValueError(msg)

    all_transition_ids = {transition.id for transition in fsm.transitions}
    covered: set[str] = set()
    sequences: list[ConstrainedInputSequence] = []

    queue: deque[tuple[str, list[tuple[Transition, str]]]] = deque(
        [(fsm.initial_state, [])]
    )
    seen_paths: set[tuple[str, ...]] = set()

    while queue and len(sequences) < max_sequences:
        state, path = queue.popleft()
        if len(path) >= max_path_length:
            continue

        for transition in fsm.transitions:
            if transition.source != state:
                continue
            next_path = path + [(transition, transition.target)]
            signature = tuple(item[0].id for item in next_path)
            if signature in seen_paths:
                continue
            seen_paths.add(signature)

            sequence = _path_to_sequence(
                fsm,
                next_path,
                sequence_id=f"seq_{len(sequences):04d}",
            )
            sequences.append(sequence)
            covered.update(sequence.transition_ids)

            coverage_ratio = len(covered) / len(all_transition_ids) if all_transition_ids else 1.0
            if coverage_ratio >= target_transition_coverage:
                queue.clear()
                break

            queue.append((transition.target, next_path))

    achieved = len(covered) / len(all_transition_ids) if all_transition_ids else 1.0
    uncovered = tuple(sorted(all_transition_ids - covered))

    return ConstrainedInputPlan(
        target_transition_coverage=target_transition_coverage,
        achieved_transition_coverage=achieved,
        sequences=tuple(sequences),
        uncovered_transitions=uncovered,
    )


def constrained_plan_to_oracle_scenarios(plan: ConstrainedInputPlan) -> list[OracleScenario]:
    """Convert constrained sequences into oracle scenarios."""
    scenarios: list[OracleScenario] = []
    for sequence in plan.sequences:
        scenarios.append(
            OracleScenario(
                id=sequence.sequence_id,
                description="Constraint-generated path",
                steps=[
                    OracleStep(
                        event=event,
                        guard=guard,
                        expected_state=expected_state,
                    )
                    for event, guard, expected_state in zip(
                        sequence.events,
                        sequence.guards,
                        sequence.expected_states,
                        strict=True,
                    )
                ],
            )
        )
    return scenarios


def constrained_plan_to_json_dict(plan: ConstrainedInputPlan) -> dict[str, object]:
    """Convert a constrained input plan to JSON."""
    return {
        "target_transition_coverage": plan.target_transition_coverage,
        "achieved_transition_coverage": plan.achieved_transition_coverage,
        "uncovered_transitions": list(plan.uncovered_transitions),
        "sequences": [
            {
                "sequence_id": sequence.sequence_id,
                "events": list(sequence.events),
                "guards": list(sequence.guards),
                "expected_states": list(sequence.expected_states),
                "transition_ids": list(sequence.transition_ids),
                "symbolic_params": sequence.symbolic_params,
            }
            for sequence in plan.sequences
        ],
    }


def constrained_plan_to_csv_rows(plan: ConstrainedInputPlan) -> list[dict[str, object]]:
    """Flatten constrained sequences to CSV rows."""
    rows: list[dict[str, object]] = []
    for sequence in plan.sequences:
        for index, (event, guard, expected_state, transition_id) in enumerate(
            zip(
                sequence.events,
                sequence.guards,
                sequence.expected_states,
                sequence.transition_ids,
                strict=True,
            )
        ):
            rows.append(
                {
                    "sequence_id": sequence.sequence_id,
                    "step_index": index,
                    "event": event,
                    "guard": guard or "",
                    "expected_state": expected_state,
                    "transition_id": transition_id,
                }
            )
    return rows


def validate_plan_coverage(fsm: FSM, plan: ConstrainedInputPlan) -> float:
    """Return achieved transition coverage when plan scenarios are traced on *fsm*."""
    covered: set[str] = set()
    for scenario in constrained_plan_to_oracle_scenarios(plan):
        covered.update(trace_scenario_transitions(fsm, scenario))
    total = len(fsm.transitions)
    return len(covered) / total if total else 1.0
