"""Ollama-based LLM repair runner."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from fsmrepairbench.models import FSM, OracleSuite, RepairResult, ScoreResult
from fsmrepairbench.patch import FSMPatch, PatchError, apply_patch, validate_patch
from fsmrepairbench.scorer import score_oracle_suite

OllamaRunner = Callable[[str, str, float], str]

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"
FENCED_JSON_PATTERN = re.compile(
    r"```(?:json)?\s*(\{.*?\})\s*```",
    re.DOTALL | re.IGNORECASE,
)


class OllamaError(RuntimeError):
    """Raised when Ollama cannot be reached or returns an invalid response."""


def run_ollama(
    model: str,
    prompt: str,
    temperature: float = 0.0,
    *,
    runner: OllamaRunner | None = None,
) -> str:
    """Call a local Ollama model and return the response text."""
    call = runner or _call_ollama_http
    return call(model, prompt, temperature)


def _call_ollama_http(model: str, prompt: str, temperature: float) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        msg = f"Failed to reach Ollama at {OLLAMA_GENERATE_URL}: {exc}"
        raise OllamaError(msg) from exc
    except json.JSONDecodeError as exc:
        msg = "Ollama returned a non-JSON response body"
        raise OllamaError(msg) from exc

    if "response" not in body:
        raise OllamaError(f"Unexpected Ollama response: {body!r}")
    return str(body["response"])


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


def run_llm_repair_case(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float = 0.0,
    *,
    ollama_runner: OllamaRunner | None = None,
) -> RepairResult:
    """Iteratively ask Ollama for repair patches and re-score the FSM."""
    if max_iterations <= 0:
        msg = "max_iterations must be greater than zero"
        raise ValueError(msg)

    current_fsm = faulty_fsm.model_copy(deep=True)
    iterations: list[dict[str, Any]] = []
    runner = ollama_runner or run_ollama

    for iteration in range(1, max_iterations + 1):
        score_before = score_oracle_suite(current_fsm, oracle_suite)
        record: dict[str, Any] = {
            "iteration": iteration,
            "bpr_before": score_before.bpr,
            "passed_steps_before": score_before.passed_steps,
            "total_steps": score_before.total_steps,
        }

        if score_before.bpr == 1.0:
            record["bpr_after"] = score_before.bpr
            record["stopped_early"] = True
            iterations.append(record)
            break

        prompt = build_repair_prompt(current_fsm, oracle_suite, score_before)
        record["prompt_length"] = len(prompt)

        try:
            response = runner(model, prompt, temperature)
            record["raw_response"] = response
            patch = parse_patch_response(response, target_fsm_id=current_fsm.id)
            record["patch_id"] = patch.patch_id
            record["operations"] = [operation.model_dump() for operation in patch.operations]

            validation_errors = validate_patch(current_fsm, patch)
            if validation_errors:
                record["patch_valid"] = False
                record["patch_applied"] = False
                record["validation_errors"] = validation_errors
                record["bpr_after"] = score_before.bpr
            else:
                current_fsm = apply_patch(current_fsm, patch)
                score_after = score_oracle_suite(current_fsm, oracle_suite)
                record["patch_valid"] = True
                record["patch_applied"] = True
                record["validation_errors"] = []
                record["bpr_after"] = score_after.bpr
                record["passed_steps_after"] = score_after.passed_steps
        except (OllamaError, ValidationError, ValueError, PatchError) as exc:
            record["patch_valid"] = False
            record["patch_applied"] = False
            record["error"] = str(exc)
            record["bpr_after"] = score_before.bpr

        iterations.append(record)
        if record.get("bpr_after") == 1.0:
            break

    final_score = score_oracle_suite(current_fsm, oracle_suite)
    return RepairResult(
        bug_id=faulty_fsm.id,
        passed=final_score.bpr == 1.0,
        score=final_score.bpr,
        details={
            "model": model,
            "temperature": temperature,
            "max_iterations": max_iterations,
            "iterations": iterations,
            "final_fsm": current_fsm.model_dump(),
            "passed_steps": final_score.passed_steps,
            "total_steps": final_score.total_steps,
            "passed_scenarios": final_score.passed_scenarios,
            "total_scenarios": final_score.total_scenarios,
        },
    )
