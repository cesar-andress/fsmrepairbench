"""Natural-language requirement generation from reference FSMs."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.models import FSM, Transition
from fsmrepairbench.oracle_generator import reachable_state_ids

RequirementStyle = Literal["concise", "verbose", "ambiguous", "industrial"]

INITIAL_REQUIREMENT_KEY = "__initial_state__"


class RequirementGenerationError(ValueError):
    """Raised when requirement generation fails."""


@dataclass(frozen=True)
class RequirementItem:
    """One generated natural-language requirement."""

    requirement_id: str
    text: str
    transition_id: str | None = None


@dataclass(frozen=True)
class RequirementGenerationResult:
    """Generated requirement set linked to an FSM."""

    fsm_id: str
    fsm_name: str
    style: RequirementStyle
    items: tuple[RequirementItem, ...]

    @property
    def lines(self) -> tuple[str, ...]:
        return tuple(f"{item.requirement_id}: {item.text}" for item in self.items)


def _humanize(value: str) -> str:
    return value.replace("_", " ").strip()


def _next_requirement_id(counter: int) -> str:
    return f"R{counter}"


def _assign_requirement_ids(fsm: FSM) -> dict[str, str]:
    """Map initial state and transitions to unique requirement identifiers."""
    used: set[str] = set()
    assignments: dict[str, str] = {}

    for transition in fsm.transitions:
        if not transition.requirements:
            continue
        requirement_id = transition.requirements[0]
        if requirement_id in used:
            continue
        assignments[transition.id] = requirement_id
        used.add(requirement_id)

    counter = 1
    while _next_requirement_id(counter) in used:
        counter += 1
    assignments[INITIAL_REQUIREMENT_KEY] = _next_requirement_id(counter)
    used.add(assignments[INITIAL_REQUIREMENT_KEY])
    counter += 1

    for transition in sorted(fsm.transitions, key=lambda item: item.id):
        if transition.id in assignments:
            continue
        while _next_requirement_id(counter) in used:
            counter += 1
        requirement_id = _next_requirement_id(counter)
        assignments[transition.id] = requirement_id
        used.add(requirement_id)
        counter += 1

    return assignments


def _guard_clause(transition: Transition, style: RequirementStyle) -> str:
    if not transition.guard:
        return ""

    guard = _humanize(transition.guard)
    if style == "concise":
        return f" when {guard}"
    if style == "verbose":
        return f" and guard '{guard}' holds"
    if style == "ambiguous":
        return f" under conditions resembling {guard}"
    return f" AND guard={guard.upper()}"


def _action_clause(transition: Transition, style: RequirementStyle) -> str:
    if not transition.action:
        return ""

    action = _humanize(transition.action)
    if style == "concise":
        return f" ({action})"
    if style == "verbose":
        return f", executing action '{action}'"
    if style == "ambiguous":
        return f", possibly triggering {action}"
    return f"; action={action.upper()}"


def _timeout_clause(transition: Transition, style: RequirementStyle) -> str:
    if transition.timeout is None:
        return ""

    timeout = transition.timeout
    if style == "concise":
        return f" after {timeout}s"
    if style == "verbose":
        return f" after a timeout of {timeout} seconds"
    if style == "ambiguous":
        return f" following some delay around {timeout} seconds"
    return f" AFTER timeout={timeout}s"


def _format_initial_requirement(
    fsm: FSM,
    *,
    requirement_id: str,
    style: RequirementStyle,
) -> str:
    initial_state = _humanize(fsm.initial_state)
    system_name = fsm.name or fsm.id

    if style == "concise":
        return f"{system_name} starts in {initial_state}."
    if style == "verbose":
        description = f" ({fsm.description})" if fsm.description else ""
        return (
            f"The {system_name} system shall begin in the '{initial_state}' state"
            f"{description}."
        )
    if style == "ambiguous":
        return f"The system should initially be in a {initial_state}-like state."
    return f"REQ-{requirement_id}: {system_name.upper()} SHALL enter state {initial_state.upper()} at startup."


def _format_transition_requirement(
    transition: Transition,
    *,
    requirement_id: str,
    style: RequirementStyle,
) -> str:
    source = _humanize(transition.source)
    target = _humanize(transition.target)
    event = _humanize(transition.event)
    guard = _guard_clause(transition, style)
    action = _action_clause(transition, style)
    timeout = _timeout_clause(transition, style)
    self_loop = transition.source == transition.target

    if self_loop and transition.guard:
        if style == "concise":
            return f"On {event} from {source}{guard}, remain in {source}{action}."
        if style == "verbose":
            return (
                f"When event '{event}' occurs in state '{source}'{guard}{action}, "
                f"the system shall remain in state '{source}'."
            )
        if style == "ambiguous":
            return (
                f"If {event} happens while near {source}{guard}, the system likely "
                f"stays around {source}{action}."
            )
        return (
            f"REQ-{requirement_id}: IF state={source.upper()} AND event={event.upper()}"
            f"{guard} THEN remain_in={source.upper()}{action}."
        )

    if style == "concise":
        return f"On {event} from {source}{guard}{timeout}, go to {target}{action}."
    if style == "verbose":
        return (
            f"When event '{event}' occurs while the system is in state '{source}'"
            f"{guard}{timeout}{action}, the system shall transition to state '{target}'."
        )
    if style == "ambiguous":
        return (
            f"When something like '{event}' occurs from {source}{guard}{timeout}, "
            f"the system may move toward {target}{action}."
        )
    return (
        f"REQ-{requirement_id}: IF state={source.upper()} AND event={event.upper()}"
        f"{guard}{timeout} THEN next_state={target.upper()}{action}."
    )


def generate_requirements(
    fsm: FSM,
    *,
    style: RequirementStyle = "concise",
) -> RequirementGenerationResult:
    """Generate natural-language requirements that preserve FSM semantics."""
    reachable = reachable_state_ids(fsm)
    if not reachable:
        msg = f"FSM '{fsm.id}' has no reachable states"
        raise RequirementGenerationError(msg)

    transitions = [
        transition
        for transition in fsm.transitions
        if transition.source in reachable and transition.target in reachable
    ]
    if fsm.initial_state not in reachable:
        msg = f"FSM '{fsm.id}' initial state is not reachable"
        raise RequirementGenerationError(msg)

    assignments = _assign_requirement_ids(fsm)
    items: list[RequirementItem] = []

    initial_id = assignments[INITIAL_REQUIREMENT_KEY]
    items.append(
        RequirementItem(
            requirement_id=initial_id,
            text=_format_initial_requirement(fsm, requirement_id=initial_id, style=style),
        )
    )

    for transition in sorted(transitions, key=lambda item: item.id):
        requirement_id = assignments[transition.id]
        items.append(
            RequirementItem(
                requirement_id=requirement_id,
                text=_format_transition_requirement(
                    transition,
                    requirement_id=requirement_id,
                    style=style,
                ),
                transition_id=transition.id,
            )
        )

    return RequirementGenerationResult(
        fsm_id=fsm.id,
        fsm_name=fsm.name,
        style=style,
        items=tuple(items),
    )


def export_requirements_txt(result: RequirementGenerationResult, path: Path) -> None:
    """Write generated requirements to *path* in benchmark text format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        f"FSM-ID: {result.fsm_id}",
        f"Name: {result.fsm_name}",
        f"Style: {result.style}",
        "",
    ]
    body = [f"{item.requirement_id}: {item.text}" for item in result.items]
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def generate_requirements_from_path(
    fsm_path: Path,
    *,
    style: RequirementStyle = "concise",
) -> RequirementGenerationResult:
    """Load an FSM JSON file and generate requirements."""
    from fsmrepairbench.validators import load_fsm_json

    fsm = load_fsm_json(fsm_path)
    return generate_requirements(fsm, style=style)
