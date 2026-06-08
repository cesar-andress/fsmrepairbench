"""Inject controlled ambiguity into clear natural-language requirements."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fsmrepairbench.models import FSM, Transition
from fsmrepairbench.requirement_generation import (
    RequirementGenerationError,
    RequirementGenerationResult,
    RequirementItem,
    RequirementStyle,
    _humanize,
    generate_requirements,
)

AmbiguityClass = Literal[
    "lexical_ambiguity",
    "temporal_ambiguity",
    "missing_condition",
    "incomplete_exception",
    "underspecified_transition",
]

AMBIGUITY_CLASSES: tuple[AmbiguityClass, ...] = (
    "lexical_ambiguity",
    "temporal_ambiguity",
    "missing_condition",
    "incomplete_exception",
    "underspecified_transition",
)

AMBIGUITY_METADATA_FILENAME = "ambiguity_metadata.json"

CLASS_NOTES: dict[AmbiguityClass, str] = {
    "lexical_ambiguity": "Replaced precise terms with vague lexical alternatives.",
    "temporal_ambiguity": "Removed or softened explicit timing constraints.",
    "missing_condition": "Omitted guard or precondition details from the requirement.",
    "incomplete_exception": "Left exception handling underspecified.",
    "underspecified_transition": "Omitted or vague about the destination state.",
}


class AmbiguityInjectionError(ValueError):
    """Raised when ambiguity injection fails."""


@dataclass(frozen=True)
class AmbiguityInjection:
    """One requirement transformed from clear to ambiguous wording."""

    requirement_id: str
    transition_id: str | None
    ambiguity_class: AmbiguityClass
    original_text: str
    ambiguous_text: str
    dropped_elements: tuple[str, ...] = ()
    notes: str = ""


@dataclass(frozen=True)
class AmbiguityInjectionResult:
    """Ambiguous requirements and metadata linked to an FSM."""

    fsm_id: str
    fsm_name: str
    clear_style: RequirementStyle
    clear_requirements: RequirementGenerationResult
    injections: tuple[AmbiguityInjection, ...]

    @property
    def ambiguous_lines(self) -> tuple[str, ...]:
        return tuple(
            f"{injection.requirement_id}: {injection.ambiguous_text}"
            for injection in self.injections
        )


def _select_ambiguity_class(
    item: RequirementItem,
    transition: Transition | None,
) -> AmbiguityClass:
    if transition is None:
        return "lexical_ambiguity"
    if transition.timeout is not None:
        return "temporal_ambiguity"
    if transition.source == transition.target and transition.guard:
        return "incomplete_exception"
    if transition.guard:
        return "missing_condition"
    return "underspecified_transition"


def _apply_lexical_ambiguity(text: str) -> tuple[str, tuple[str, ...]]:
    result = text
    replacements = [
        (" shall ", " might "),
        (" starts in ", " begins around "),
        (" go to ", " move toward "),
        ("On ", "When possibly "),
        ("When ", "If perhaps "),
        (" remain in ", " stay near "),
    ]
    for old, new in replacements:
        result = result.replace(old, new)
    return result, ()


def _apply_temporal_ambiguity(
    text: str,
    transition: Transition | None,
) -> tuple[str, tuple[str, ...]]:
    dropped: list[str] = []
    result = text

    if transition is not None and transition.timeout is not None:
        dropped.append(f"timeout={transition.timeout}")
        timeout = transition.timeout
        for phrase in (
            f" after {timeout}s",
            f" after a timeout of {timeout} seconds",
            f" following some delay around {timeout} seconds",
            f" AFTER timeout={timeout}s",
        ):
            result = result.replace(phrase, " eventually")

    result = re.sub(r" after [\d.]+\s*seconds?", " eventually", result, flags=re.IGNORECASE)
    result = re.sub(r" after [\d.]+s", " eventually", result, flags=re.IGNORECASE)

    if "eventually" not in result.lower():
        result = result.rstrip(".") + " at an unspecified time."

    return result, tuple(dropped)


def _apply_missing_condition(
    text: str,
    transition: Transition | None,
) -> tuple[str, tuple[str, ...]]:
    if transition is None or not transition.guard:
        return _apply_lexical_ambiguity(text)

    guard = _humanize(transition.guard)
    dropped = (transition.guard,)
    result = text
    for phrase in (
        f" when {guard}",
        f" and guard '{guard}' holds",
        f" under conditions resembling {guard}",
        f" AND guard={transition.guard.upper()}",
    ):
        result = result.replace(phrase, "")
    return result, dropped


def _apply_incomplete_exception(
    text: str,
    transition: Transition | None,
) -> tuple[str, tuple[str, ...]]:
    if transition is None:
        return _apply_lexical_ambiguity(text)

    dropped: list[str] = []
    if transition.guard:
        dropped.append(transition.guard)
    if transition.action:
        dropped.append(transition.action)

    source = _humanize(transition.source)
    result = text
    for phrase in (
        f"remain in {source}",
        f"shall remain in state '{source}'",
        f"stays around {source}",
        f"stay near {source}",
        f"THEN remain_in={source.upper()}",
    ):
        if phrase in result:
            result = result.replace(phrase, "handles the event")

    if transition.guard:
        guard = _humanize(transition.guard)
        for phrase in (
            f" when {guard}",
            f" and guard '{guard}' holds",
            f" under conditions resembling {guard}",
            f" AND guard={transition.guard.upper()}",
        ):
            result = result.replace(phrase, "")

    if transition.action:
        action = _humanize(transition.action)
        for phrase in (f" ({action})", f", executing action '{action}'", f"; action={action.upper()}"):
            result = result.replace(phrase, "")

    return result, tuple(dropped)


def _apply_underspecified_transition(
    text: str,
    transition: Transition | None,
) -> tuple[str, tuple[str, ...]]:
    if transition is None:
        return _apply_lexical_ambiguity(text)

    target = _humanize(transition.target)
    dropped = (transition.target,)
    result = text
    for phrase in (
        f", go to {target}",
        f" to state '{target}'",
        f"transition to state '{target}'",
        f" move toward {target}",
        f" THEN next_state={target.upper()}",
        f" go to {target}.",
    ):
        result = result.replace(phrase, "")

    if result == text:
        result = result.replace(f" toward {target}", "")

    result = result.rstrip()
    if not result.endswith("."):
        result += "."
    if "another state" not in result.lower() and "unspecified" not in result.lower():
        result = result.rstrip(".") + " toward another state."

    return result, dropped


def _apply_injection(
    item: RequirementItem,
    transition: Transition | None,
    ambiguity_class: AmbiguityClass,
) -> AmbiguityInjection:
    original = item.text
    if ambiguity_class == "lexical_ambiguity":
        ambiguous, dropped = _apply_lexical_ambiguity(original)
    elif ambiguity_class == "temporal_ambiguity":
        ambiguous, dropped = _apply_temporal_ambiguity(original, transition)
    elif ambiguity_class == "missing_condition":
        ambiguous, dropped = _apply_missing_condition(original, transition)
    elif ambiguity_class == "incomplete_exception":
        ambiguous, dropped = _apply_incomplete_exception(original, transition)
    else:
        ambiguous, dropped = _apply_underspecified_transition(original, transition)

    if ambiguous == original:
        ambiguous, extra_dropped = _apply_lexical_ambiguity(original)
        dropped = dropped + extra_dropped

    return AmbiguityInjection(
        requirement_id=item.requirement_id,
        transition_id=item.transition_id,
        ambiguity_class=ambiguity_class,
        original_text=original,
        ambiguous_text=ambiguous,
        dropped_elements=dropped,
        notes=CLASS_NOTES[ambiguity_class],
    )


def inject_requirement_ambiguity(
    fsm: FSM,
    *,
    clear_style: RequirementStyle = "concise",
) -> AmbiguityInjectionResult:
    """Transform clear requirements into ambiguous requirements with metadata."""
    try:
        clear = generate_requirements(fsm, style=clear_style)
    except RequirementGenerationError as exc:
        raise AmbiguityInjectionError(str(exc)) from exc

    transition_by_id = {transition.id: transition for transition in fsm.transitions}
    injections = [
        _apply_injection(
            item,
            transition_by_id.get(item.transition_id) if item.transition_id else None,
            _select_ambiguity_class(
                item,
                transition_by_id.get(item.transition_id) if item.transition_id else None,
            ),
        )
        for item in clear.items
    ]

    return AmbiguityInjectionResult(
        fsm_id=fsm.id,
        fsm_name=fsm.name,
        clear_style=clear_style,
        clear_requirements=clear,
        injections=tuple(injections),
    )


def build_ambiguity_metadata_payload(result: AmbiguityInjectionResult) -> dict[str, Any]:
    """Build JSON-serialisable ambiguity metadata."""
    return {
        "fsm_id": result.fsm_id,
        "fsm_name": result.fsm_name,
        "clear_style": result.clear_style,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "ambiguity_classes": list(AMBIGUITY_CLASSES),
        "injections": [
            {
                "requirement_id": injection.requirement_id,
                "transition_id": injection.transition_id,
                "ambiguity_class": injection.ambiguity_class,
                "original_text": injection.original_text,
                "ambiguous_text": injection.ambiguous_text,
                "dropped_elements": list(injection.dropped_elements),
                "notes": injection.notes,
            }
            for injection in result.injections
        ],
    }


def export_ambiguity_metadata(result: AmbiguityInjectionResult, path: Path) -> None:
    """Write ambiguity metadata JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = build_ambiguity_metadata_payload(result)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def export_injected_requirements_txt(result: AmbiguityInjectionResult, path: Path) -> None:
    """Write ambiguous requirements to *path* in benchmark text format."""
    path.parent.mkdir(parents=True, exist_ok=True)
    header = [
        f"FSM-ID: {result.fsm_id}",
        f"Name: {result.fsm_name}",
        f"Clear-Style: {result.clear_style}",
        "Style: injected_ambiguity",
        "",
    ]
    body = list(result.ambiguous_lines)
    path.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def inject_requirement_ambiguity_from_path(
    fsm_path: Path,
    *,
    clear_style: RequirementStyle = "concise",
) -> AmbiguityInjectionResult:
    """Load an FSM JSON file and inject requirement ambiguity."""
    from fsmrepairbench.validators import load_fsm_json

    fsm = load_fsm_json(fsm_path)
    return inject_requirement_ambiguity(fsm, clear_style=clear_style)
