"""Backend-agnostic iterative LLM repair loop."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from pydantic import ValidationError

from fsmrepairbench.llm.clients.base import ModelClient
from fsmrepairbench.llm.prompts import build_repair_prompt, parse_patch_response
from fsmrepairbench.models import FSM, OracleSuite, RepairResult, ScoreResult
from fsmrepairbench.patch import PatchError, apply_patch, validate_patch
from fsmrepairbench.scorer import score_oracle_suite

GenerateFn = Callable[[str, str, float], str]


def _score_snapshot(score: ScoreResult) -> dict[str, object]:
    return score.model_dump()


def run_llm_repair_with_client(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    *,
    model: str,
    max_iterations: int,
    temperature: float = 0.0,
    client: ModelClient | None = None,
    generate_fn: GenerateFn | None = None,
) -> RepairResult:
    """Iteratively ask an LLM for repair patches and re-score the FSM."""
    if max_iterations <= 0:
        msg = "max_iterations must be greater than zero"
        raise ValueError(msg)

    if client is None and generate_fn is None:
        msg = "Either client or generate_fn must be provided"
        raise ValueError(msg)

    if generate_fn is None:
        assert client is not None

        def _generate(model_name: str, prompt: str, temp: float) -> str:
            return client.generate(model=model_name, prompt=prompt, temperature=temp)

        generate_fn = _generate

    started_at = time.perf_counter()
    current_fsm = faulty_fsm.model_copy(deep=True)
    iterations: list[dict[str, Any]] = []

    for iteration in range(1, max_iterations + 1):
        score_before = score_oracle_suite(current_fsm, oracle_suite)
        record: dict[str, Any] = {
            "iteration": iteration,
            "input_fsm": current_fsm.model_dump(),
            "prompt": None,
            "response": None,
            "patch": None,
            "score": {
                "before": _score_snapshot(score_before),
                "after": None,
            },
            "bpr_before": score_before.bpr,
            "passed_steps_before": score_before.passed_steps,
            "total_steps": score_before.total_steps,
        }

        if score_before.bpr == 1.0:
            record["score"]["after"] = _score_snapshot(score_before)
            record["bpr_after"] = score_before.bpr
            record["stopped_early"] = True
            iterations.append(record)
            break

        prompt = build_repair_prompt(current_fsm, oracle_suite, score_before)
        record["prompt"] = prompt
        record["prompt_length"] = len(prompt)

        try:
            response = generate_fn(model, prompt, temperature)
            record["response"] = response
            record["raw_response"] = response
            patch = parse_patch_response(response, target_fsm_id=current_fsm.id)
            record["patch"] = patch.model_dump()
            record["patch_id"] = patch.patch_id
            record["operations"] = [operation.model_dump() for operation in patch.operations]

            validation_errors = validate_patch(current_fsm, patch)
            if validation_errors:
                record["patch_valid"] = False
                record["patch_applied"] = False
                record["validation_errors"] = validation_errors
                record["bpr_after"] = score_before.bpr
                record["score"]["after"] = _score_snapshot(score_before)
            else:
                current_fsm = apply_patch(current_fsm, patch)
                score_after = score_oracle_suite(current_fsm, oracle_suite)
                record["patch_valid"] = True
                record["patch_applied"] = True
                record["validation_errors"] = []
                record["bpr_after"] = score_after.bpr
                record["passed_steps_after"] = score_after.passed_steps
                record["score"]["after"] = _score_snapshot(score_after)
        except (ValidationError, ValueError, PatchError) as exc:
            record["patch_valid"] = False
            record["patch_applied"] = False
            record["error"] = str(exc)
            record["bpr_after"] = score_before.bpr
            record["score"]["after"] = _score_snapshot(score_before)

        iterations.append(record)
        if record.get("bpr_after") == 1.0:
            break

    final_score = score_oracle_suite(current_fsm, oracle_suite)
    runtime_seconds = round(time.perf_counter() - started_at, 4)
    backend = client.backend.value if client is not None else "custom"
    return RepairResult(
        bug_id=faulty_fsm.id,
        passed=final_score.bpr == 1.0,
        score=final_score.bpr,
        details={
            "model": model,
            "backend": backend,
            "temperature": temperature,
            "max_iterations": max_iterations,
            "runtime_seconds": runtime_seconds,
            "iterations": iterations,
            "final_fsm": current_fsm.model_dump(),
            "passed_steps": final_score.passed_steps,
            "total_steps": final_score.total_steps,
            "passed_scenarios": final_score.passed_scenarios,
            "total_scenarios": final_score.total_scenarios,
        },
    )
