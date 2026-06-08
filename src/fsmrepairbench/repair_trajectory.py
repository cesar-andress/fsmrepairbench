"""Persistence for complete LLM repair trajectories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.models import RepairResult, ScoreResult

REPAIR_TRACE_FILENAME = "repair_trace.json"
TRACE_FILE_PREFIX = "trace__"


class RepairTrajectoryError(ValueError):
    """Raised when repair trajectory persistence fails."""


@dataclass(frozen=True)
class RepairTraceStep:
    """One iteration in a repair trajectory."""

    iteration: int
    input_fsm: dict[str, Any] | None
    prompt: str | None
    response: str | None
    patch: dict[str, Any] | None
    score: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "input_fsm": self.input_fsm,
            "prompt": self.prompt,
            "response": self.response,
            "patch": self.patch,
            "score": self.score,
        }


@dataclass(frozen=True)
class RepairTrace:
    """Complete repair trajectory for convergence and stability studies."""

    bug_id: str
    passed: bool
    final_bpr: float
    model: str | None
    backend: str | None
    temperature: float | None
    max_iterations: int | None
    runtime_seconds: float
    initial_score: dict[str, Any] | None
    final_score: dict[str, Any] | None
    steps: tuple[RepairTraceStep, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "bug_id": self.bug_id,
            "passed": self.passed,
            "final_bpr": self.final_bpr,
            "model": self.model,
            "backend": self.backend,
            "temperature": self.temperature,
            "max_iterations": self.max_iterations,
            "runtime_seconds": self.runtime_seconds,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "initial_score": self.initial_score,
            "final_score": self.final_score,
            "iterations": [step.to_dict() for step in self.steps],
            "score_progression": [
                step.score.get("after", {}).get("bpr")
                for step in self.steps
                if isinstance(step.score.get("after"), dict)
            ],
        }


def _score_snapshot(score: ScoreResult | dict[str, Any] | None) -> dict[str, Any] | None:
    if score is None:
        return None
    if isinstance(score, ScoreResult):
        return score.model_dump()
    if isinstance(score, dict):
        return dict(score)
    return None


def _normalize_iteration_record(record: dict[str, Any]) -> RepairTraceStep:
    score_payload = record.get("score")
    if not isinstance(score_payload, dict):
        score_payload = {
            "before": {"bpr": record.get("bpr_before")},
            "after": {"bpr": record.get("bpr_after")},
        }

    patch_payload = record.get("patch")
    if patch_payload is None and record.get("operations") is not None:
        patch_payload = {
            "patch_id": record.get("patch_id"),
            "target_fsm_id": record.get("target_fsm_id"),
            "operations": record.get("operations"),
        }

    response = record.get("response")
    if response is None and record.get("raw_response") is not None:
        response = record.get("raw_response")

    return RepairTraceStep(
        iteration=int(record.get("iteration", 0)),
        input_fsm=record.get("input_fsm"),
        prompt=record.get("prompt"),
        response=response if isinstance(response, str) else None,
        patch=patch_payload if isinstance(patch_payload, dict) else None,
        score={
            "before": _score_snapshot(score_payload.get("before")),
            "after": _score_snapshot(score_payload.get("after")),
        },
    )


def build_repair_trace(repair_result: RepairResult) -> RepairTrace:
    """Build a structured repair trajectory from a repair result."""
    details = repair_result.details
    iterations = details.get("iterations", [])
    if not isinstance(iterations, list):
        msg = "Repair result details missing iteration history"
        raise RepairTrajectoryError(msg)

    steps = tuple(_normalize_iteration_record(record) for record in iterations if isinstance(record, dict))
    initial_score = steps[0].score.get("before") if steps else None
    final_score = steps[-1].score.get("after") if steps else None
    if final_score is None:
        final_score = {"bpr": repair_result.score}

    return RepairTrace(
        bug_id=repair_result.bug_id,
        passed=repair_result.passed,
        final_bpr=repair_result.score,
        model=str(details.get("model")) if details.get("model") is not None else None,
        backend=str(details.get("backend")) if details.get("backend") is not None else None,
        temperature=float(details["temperature"]) if details.get("temperature") is not None else None,
        max_iterations=int(details["max_iterations"]) if details.get("max_iterations") is not None else None,
        runtime_seconds=float(details.get("runtime_seconds", 0.0)),
        initial_score=initial_score,
        final_score=final_score,
        steps=steps,
    )


def repair_trace_path_for_result(result_path: Path, *, single_repair: bool = False) -> Path:
    """Resolve the repair trace path associated with a result JSON file."""
    if single_repair:
        return result_path.parent / REPAIR_TRACE_FILENAME
    return result_path.parent / f"{TRACE_FILE_PREFIX}{result_path.name}"


def is_repair_trace_file(path: Path) -> bool:
    """Return whether *path* is a persisted repair trajectory artifact."""
    if path.name == REPAIR_TRACE_FILENAME:
        return True
    return path.name.startswith(TRACE_FILE_PREFIX) and path.name.endswith(".json")


def export_repair_trace(repair_result: RepairResult, path: Path) -> RepairTrace:
    """Write *repair_result* trajectory to ``repair_trace.json`` format."""
    trace = build_repair_trace(repair_result)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace.to_dict(), indent=2) + "\n", encoding="utf-8")
    return trace
