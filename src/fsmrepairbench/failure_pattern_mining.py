"""Discover recurring repair failure patterns from repair trajectories."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from fsmrepairbench.repair_trajectory import REPAIR_TRACE_FILENAME, is_repair_trace_file

FailurePattern = Literal[
    "invalid_json",
    "wrong_patch",
    "regression",
    "oscillation",
    "no_op_patch",
]

FAILURE_PATTERNS: tuple[FailurePattern, ...] = (
    "invalid_json",
    "wrong_patch",
    "regression",
    "oscillation",
    "no_op_patch",
)

FAILURE_PATTERNS_FILENAME = "failure_patterns.csv"
FAILURE_PATTERN_REPORT_FILENAME = "failure_pattern_report.json"

FAILURE_PATTERNS_COLUMNS: tuple[str, ...] = (
    "pattern",
    "trace_file",
    "bug_id",
    "model",
    "iteration",
    "before_bpr",
    "after_bpr",
    "final_bpr",
    "passed",
    "detail",
)


class FailurePatternMiningError(ValueError):
    """Raised when repair failure pattern mining fails."""


@dataclass(frozen=True)
class FailurePatternOccurrence:
    """One detected failure pattern in a repair trace."""

    pattern: FailurePattern
    trace_file: Path
    bug_id: str
    model: str | None
    iteration: int | None
    before_bpr: float | None
    after_bpr: float | None
    final_bpr: float
    passed: bool
    detail: str

    def to_csv_row(self) -> dict[str, str | float | int | bool]:
        return {
            "pattern": self.pattern,
            "trace_file": str(self.trace_file),
            "bug_id": self.bug_id,
            "model": self.model or "",
            "iteration": "" if self.iteration is None else self.iteration,
            "before_bpr": "" if self.before_bpr is None else round(self.before_bpr, 4),
            "after_bpr": "" if self.after_bpr is None else round(self.after_bpr, 4),
            "final_bpr": round(self.final_bpr, 4),
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class FailurePatternMiningResult:
    """Artifacts produced by failure pattern mining."""

    input_dir: Path
    patterns_path: Path
    report_path: Path
    occurrences: tuple[FailurePatternOccurrence, ...]
    report: dict[str, Any]


def _bpr(value: Any) -> float | None:
    if not isinstance(value, dict):
        return None
    raw = value.get("bpr")
    if raw is None:
        return None
    return float(raw)


def _iteration_bprs(step: dict[str, Any]) -> tuple[float | None, float | None]:
    score = step.get("score")
    if not isinstance(score, dict):
        return None, None
    return _bpr(score.get("before")), _bpr(score.get("after"))


def detect_oscillation(score_progression: list[float]) -> bool:
    """Return whether a score progression shows repair oscillation."""
    if len(score_progression) < 3:
        return False

    directions: list[int] = []
    for index in range(1, len(score_progression)):
        delta = score_progression[index] - score_progression[index - 1]
        if delta > 0:
            directions.append(1)
        elif delta < 0:
            directions.append(-1)

    if len(directions) < 2:
        return False

    sign_changes = sum(
        1 for index in range(1, len(directions)) if directions[index] != directions[index - 1]
    )
    return sign_changes >= 2


def classify_iteration_failure(step: dict[str, Any]) -> FailurePattern | None:
    """Classify one repair iteration into a failure pattern, if any."""
    before_bpr, after_bpr = _iteration_bprs(step)
    if before_bpr is None or after_bpr is None:
        return None

    response = step.get("response")
    patch = step.get("patch")
    error = step.get("error")
    validation_errors = step.get("validation_errors")

    if error and not isinstance(patch, dict):
        return "invalid_json"
    if response and not isinstance(patch, dict):
        return "invalid_json"

    if isinstance(patch, dict):
        operations = patch.get("operations") or []
        if not operations:
            return "no_op_patch"
        if validation_errors:
            return "wrong_patch"
        if after_bpr < before_bpr:
            return "regression"
        if after_bpr == before_bpr:
            return "wrong_patch"

    return None


def discover_repair_trace_files(root: Path) -> list[Path]:
    """Discover repair trace JSON files under *root*."""
    if not root.exists():
        msg = f"Input path not found: {root}"
        raise FailurePatternMiningError(msg)

    if root.is_file():
        if root.name == REPAIR_TRACE_FILENAME or is_repair_trace_file(root):
            return [root]
        msg = f"Not a repair trace file: {root}"
        raise FailurePatternMiningError(msg)

    discovered = [
        path
        for path in root.rglob("*.json")
        if path.is_file() and (path.name == REPAIR_TRACE_FILENAME or is_repair_trace_file(path))
    ]
    if not discovered:
        msg = f"No repair trace files found under {root}"
        raise FailurePatternMiningError(msg)
    return sorted(discovered)


def load_repair_trace_payload(path: Path) -> dict[str, Any]:
    """Load a repair trace JSON payload from *path*."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Failed to read repair trace {path}: {exc}"
        raise FailurePatternMiningError(msg) from exc

    if not isinstance(payload, dict):
        msg = f"Repair trace must be a JSON object: {path}"
        raise FailurePatternMiningError(msg)
    return payload


def mine_failure_patterns_for_trace(
    path: Path,
    payload: dict[str, Any],
) -> list[FailurePatternOccurrence]:
    """Detect failure patterns in one repair trace."""
    bug_id = str(payload.get("bug_id", path.stem))
    model = str(payload["model"]) if payload.get("model") is not None else None
    final_bpr = float(payload.get("final_bpr", 0.0))
    passed = bool(payload.get("passed", False))
    iterations = payload.get("iterations", [])
    if not isinstance(iterations, list):
        msg = f"Repair trace missing iterations list: {path}"
        raise FailurePatternMiningError(msg)

    occurrences: list[FailurePatternOccurrence] = []
    score_progression: list[float] = []

    for step in iterations:
        if not isinstance(step, dict):
            continue
        before_bpr, after_bpr = _iteration_bprs(step)
        if after_bpr is not None:
            score_progression.append(after_bpr)

        pattern = classify_iteration_failure(step)
        if pattern is None:
            continue

        iteration_number = step.get("iteration")
        detail = _pattern_detail(pattern, step)
        occurrences.append(
            FailurePatternOccurrence(
                pattern=pattern,
                trace_file=path,
                bug_id=bug_id,
                model=model,
                iteration=int(iteration_number) if iteration_number is not None else None,
                before_bpr=before_bpr,
                after_bpr=after_bpr,
                final_bpr=final_bpr,
                passed=passed,
                detail=detail,
            )
        )

    if detect_oscillation(score_progression):
        progression_text = ", ".join(f"{value:.2f}" for value in score_progression)
        occurrences.append(
            FailurePatternOccurrence(
                pattern="oscillation",
                trace_file=path,
                bug_id=bug_id,
                model=model,
                iteration=None,
                before_bpr=score_progression[0] if score_progression else None,
                after_bpr=score_progression[-1] if score_progression else None,
                final_bpr=final_bpr,
                passed=passed,
                detail=f"Score oscillation across iterations: {progression_text}",
            )
        )

    return occurrences


def _pattern_detail(pattern: FailurePattern, step: dict[str, Any]) -> str:
    if pattern == "invalid_json":
        error = step.get("error")
        if error:
            return f"Patch parse failed: {error}"
        return "Model response could not be parsed into a valid patch JSON object"
    if pattern == "no_op_patch":
        return "Patch contained no repair operations"
    if pattern == "regression":
        before_bpr, after_bpr = _iteration_bprs(step)
        return f"BPR decreased from {before_bpr:.2f} to {after_bpr:.2f}"
    if pattern == "wrong_patch":
        validation_errors = step.get("validation_errors") or []
        if validation_errors:
            return f"Patch validation failed: {validation_errors[0]}"
        before_bpr, after_bpr = _iteration_bprs(step)
        return f"Patch applied or proposed without BPR improvement ({before_bpr:.2f} -> {after_bpr:.2f})"
    return "Repair score oscillated without stabilizing"


def mine_failure_patterns(
    input_dir: Path,
    *,
    output_dir: Path | None = None,
) -> FailurePatternMiningResult:
    """Mine recurring failure patterns from repair traces under *input_dir*."""
    trace_files = discover_repair_trace_files(input_dir)
    occurrences: list[FailurePatternOccurrence] = []
    for trace_path in trace_files:
        payload = load_repair_trace_payload(trace_path)
        occurrences.extend(mine_failure_patterns_for_trace(trace_path, payload))

    destination = output_dir or input_dir
    patterns_path = destination / FAILURE_PATTERNS_FILENAME
    report_path = destination / FAILURE_PATTERN_REPORT_FILENAME
    report = build_failure_pattern_report(
        input_dir=input_dir,
        trace_files=trace_files,
        occurrences=tuple(occurrences),
    )
    write_failure_patterns_csv(patterns_path, tuple(occurrences))
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    return FailurePatternMiningResult(
        input_dir=input_dir,
        patterns_path=patterns_path,
        report_path=report_path,
        occurrences=tuple(occurrences),
        report=report,
    )


def build_failure_pattern_report(
    *,
    input_dir: Path,
    trace_files: list[Path],
    occurrences: tuple[FailurePatternOccurrence, ...],
) -> dict[str, Any]:
    """Build a JSON summary of mined failure patterns."""
    pattern_counts = Counter(occurrence.pattern for occurrence in occurrences)
    traces_by_pattern: dict[str, set[str]] = {pattern: set() for pattern in FAILURE_PATTERNS}
    for occurrence in occurrences:
        traces_by_pattern[occurrence.pattern].add(str(occurrence.trace_file))

    return {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "input_dir": str(input_dir),
        "trace_count": len(trace_files),
        "occurrence_count": len(occurrences),
        "patterns": list(FAILURE_PATTERNS),
        "pattern_counts": dict(sorted(pattern_counts.items())),
        "affected_traces": {
            pattern: len(traces_by_pattern[pattern]) for pattern in FAILURE_PATTERNS
        },
        "top_patterns": [
            {"pattern": pattern, "occurrences": count}
            for pattern, count in pattern_counts.most_common()
        ],
    }


def write_failure_patterns_csv(
    path: Path,
    occurrences: tuple[FailurePatternOccurrence, ...],
) -> None:
    """Write mined failure pattern occurrences to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(FAILURE_PATTERNS_COLUMNS))
        writer.writeheader()
        for occurrence in occurrences:
            writer.writerow(occurrence.to_csv_row())
