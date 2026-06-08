"""Prompt construction and patch response parsing for LLM repair."""

from __future__ import annotations

import json
import re
from typing import Any

from fsmrepairbench.models import FSM, OracleSuite, ScoreResult
from fsmrepairbench.patch import FSMPatch

FENCED_JSON_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


def build_repair_prompt(fsm: FSM, oracle_suite: OracleSuite, score_result: ScoreResult) -> str:
    """Build a repair prompt that asks for FSMPatch JSON only."""
    failures = _format_failures(score_result)
    patch_schema = {
        "patch_id": "string",
        "target_fsm_id": fsm.id,
        "operations": [
            {"op": "add_transition", "id": "t_new", "source": "s0", "event": "e", "target": "s1"},
            {"op": "remove_transition", "transition_id": "t1"},
            {"op": "replace_transition_source", "transition_id": "t1", "source": "s0"},
            {"op": "replace_transition_target", "transition_id": "t1", "target": "s1"},
            {"op": "replace_transition_event", "transition_id": "t1", "event": "e"},
            {"op": "replace_initial_state", "initial_state": "s0"},
            {"op": "replace_guard", "transition_id": "t1", "guard": "g"},
            {"op": "replace_action", "transition_id": "t1", "action": "a"},
        ],
    }

    return (
        "You are repairing a behavioural finite-state machine (FSM).\n"
        "Return ONLY one valid JSON object matching the FSMPatch schema below.\n"
        "Do not include markdown fences, commentary, or extra text.\n\n"
        f"Current BPR: {score_result.bpr:.4f} "
        f"({score_result.passed_steps}/{score_result.total_steps} steps passed)\n\n"
        "Oracle failures:\n"
        f"{failures}\n\n"
        "Current FSM JSON:\n"
        f"{fsm.model_dump_json(indent=2)}\n\n"
        "Oracle suite JSON:\n"
        f"{oracle_suite.model_dump_json(indent=2)}\n\n"
        "FSMPatch schema example:\n"
        f"{json.dumps(patch_schema, indent=2)}\n"
    )


def _format_failures(score_result: ScoreResult) -> str:
    lines: list[str] = []
    for scenario in score_result.scenarios:
        for step in scenario.steps:
            if step.passed:
                continue
            lines.append(
                "- "
                f"scenario={scenario.scenario_id} "
                f"step={step.step_index} "
                f"event={step.event} "
                f"guard={step.guard!r} "
                f"expected_state={step.expected_state} "
                f"actual_state={step.actual_state!r} "
                f"reason={step.failure_reason}"
            )
    return "\n".join(lines) if lines else "No failing steps recorded."


def extract_json_object(text: str) -> dict[str, Any]:
    """Extract the first JSON object from *text*."""
    stripped = text.strip()
    if not stripped:
        msg = "No JSON object found in empty text"
        raise ValueError(msg)

    fenced_match = FENCED_JSON_PATTERN.search(stripped)
    if fenced_match is not None:
        return _loads_json_object(fenced_match.group(1))

    start = stripped.find("{")
    if start == -1:
        msg = "No JSON object found"
        raise ValueError(msg)

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return _loads_json_object(stripped[start : index + 1])

    msg = "Unbalanced JSON object"
    raise ValueError(msg)


def _loads_json_object(raw: str) -> dict[str, Any]:
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        msg = "Expected a JSON object"
        raise ValueError(msg)
    return parsed


def parse_patch_response(text: str, *, target_fsm_id: str) -> FSMPatch:
    """Parse an FSMPatch from model output text."""
    data = extract_json_object(text)
    if data.get("target_fsm_id") != target_fsm_id:
        data["target_fsm_id"] = target_fsm_id
    return FSMPatch.model_validate(data)
