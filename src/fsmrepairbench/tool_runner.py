"""SmartBugs-style multi-tool execution framework for FSMRepairBench."""

from __future__ import annotations

import csv
import json
import os
import shlex
import subprocess
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeoutError, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator

from fsmrepairbench.experiments import (
    ExperimentCase,
    build_summary_row,
    discover_experiment_cases,
    sanitize_model_name,
)
from fsmrepairbench.leaderboard import (
    CaseResultRecord,
    compute_leaderboard_entries,
    write_leaderboard_csv,
)
from fsmrepairbench.llm.clients.base import ModelBackend
from fsmrepairbench.llm.clients.registry import create_model_client, parse_model_spec
from fsmrepairbench.llm.repair import run_llm_repair_with_client
from fsmrepairbench.models import FSM, OracleSuite, RepairResult
from fsmrepairbench.patch import PatchError, apply_patch, validate_patch
from fsmrepairbench.repair_engines.baselines import BaselineEngineError, get_baseline_engine
from fsmrepairbench.scorer import score_oracle_suite

ToolType = Literal["llm", "baseline", "external"]
ToolRunStatus = Literal["completed", "failed", "skipped", "timeout"]
FailureClass = Literal[
    "complete_repair",
    "effective_repair",
    "no_improvement",
    "regression",
    "timeout",
    "tool_error",
    "parse_error",
    "skipped",
]

SUPPORTED_INPUT_FORMATS: frozenset[str] = frozenset({"fsmrepairbench_case_v1"})
SUPPORTED_OUTPUT_FORMATS: frozenset[str] = frozenset({"fsmrepairbench_repair_result_v1"})

TOOL_SUMMARY_COLUMNS: tuple[str, ...] = (
    "case_id",
    "tool_id",
    "tool_type",
    "model",
    "mutation_operator",
    "status",
    "failure_class",
    "initial_bpr",
    "final_bpr",
    "delta_bpr",
    "complete_repair",
    "effective_repair",
    "regression",
    "patch_parse_failures",
    "patch_validation_failures",
    "patch_application_failures",
    "iterations_completed",
    "runtime_seconds",
)


class ToolRunnerError(ValueError):
    """Raised when tool configuration or execution fails."""


class ToolConfig(BaseModel):
    """YAML configuration for one repair tool."""

    tool_id: str
    tool_type: ToolType
    command: str
    timeout_seconds: int = Field(default=300, ge=1)
    environment: dict[str, str] = Field(default_factory=dict)
    input_format: str = "fsmrepairbench_case_v1"
    output_format: str = "fsmrepairbench_repair_result_v1"
    iterations: int = Field(default=3, ge=1)
    temperature: float = 0.0

    @field_validator("environment", mode="before")
    @classmethod
    def _coerce_environment(cls, value: object) -> dict[str, str]:
        if value is None:
            return {}
        if not isinstance(value, dict):
            msg = "environment must be a mapping of strings"
            raise ValueError(msg)
        return {str(key): str(item) for key, item in value.items()}


@dataclass(frozen=True)
class ToolRunTask:
    """One case/tool execution unit."""

    case: ExperimentCase
    tool: ToolConfig


@dataclass(frozen=True)
class ToolRunSummaryRow:
    """One row in tool-run summary output."""

    case_id: str
    tool_id: str
    tool_type: ToolType
    model: str
    mutation_operator: str
    status: ToolRunStatus
    failure_class: FailureClass
    initial_bpr: float
    final_bpr: float
    delta_bpr: float
    complete_repair: bool
    effective_repair: bool
    regression: bool
    patch_parse_failures: int
    patch_validation_failures: int
    patch_application_failures: int
    iterations_completed: int
    runtime_seconds: float

    def to_dict(self) -> dict[str, str | float | bool | int]:
        return {
            "case_id": self.case_id,
            "tool_id": self.tool_id,
            "tool_type": self.tool_type,
            "model": self.model,
            "mutation_operator": self.mutation_operator,
            "status": self.status,
            "failure_class": self.failure_class,
            "initial_bpr": self.initial_bpr,
            "final_bpr": self.final_bpr,
            "delta_bpr": self.delta_bpr,
            "complete_repair": self.complete_repair,
            "effective_repair": self.effective_repair,
            "regression": self.regression,
            "patch_parse_failures": self.patch_parse_failures,
            "patch_validation_failures": self.patch_validation_failures,
            "patch_application_failures": self.patch_application_failures,
            "iterations_completed": self.iterations_completed,
            "runtime_seconds": self.runtime_seconds,
        }


@dataclass(frozen=True)
class ToolRunResult:
    """Paths and rows produced by a multi-tool run."""

    output_dir: Path
    summary_path: Path
    leaderboard_path: Path
    rows: tuple[ToolRunSummaryRow, ...]


def load_tool_config(path: Path) -> ToolConfig:
    """Load one tool YAML configuration from *path*."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Failed to read tool config {path}: {exc}"
        raise ToolRunnerError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in tool config {path}: {exc}"
        raise ToolRunnerError(msg) from exc

    if not isinstance(raw, dict):
        msg = f"Tool config {path} must be a YAML mapping"
        raise ToolRunnerError(msg)

    try:
        config = ToolConfig.model_validate(raw)
    except Exception as exc:
        msg = f"Invalid tool config schema in {path}: {exc}"
        raise ToolRunnerError(msg) from exc

    if config.input_format not in SUPPORTED_INPUT_FORMATS:
        msg = (
            f"Unsupported input_format '{config.input_format}' in {path}. "
            f"Supported: {', '.join(sorted(SUPPORTED_INPUT_FORMATS))}"
        )
        raise ToolRunnerError(msg)
    if config.output_format not in SUPPORTED_OUTPUT_FORMATS:
        msg = (
            f"Unsupported output_format '{config.output_format}' in {path}. "
            f"Supported: {', '.join(sorted(SUPPORTED_OUTPUT_FORMATS))}"
        )
        raise ToolRunnerError(msg)
    return config


def load_tool_configs(tools_dir: Path) -> list[ToolConfig]:
    """Load all ``*.yaml`` tool configs from *tools_dir*."""
    if not tools_dir.is_dir():
        msg = f"Tools directory not found: {tools_dir}"
        raise ToolRunnerError(msg)

    configs = [load_tool_config(path) for path in sorted(tools_dir.glob("*.yaml"))]
    if not configs:
        msg = f"No tool configs (*.yaml) found in {tools_dir}"
        raise ToolRunnerError(msg)

    tool_ids = [config.tool_id for config in configs]
    duplicates = sorted({tool_id for tool_id in tool_ids if tool_ids.count(tool_id) > 1})
    if duplicates:
        msg = f"Duplicate tool_id values in {tools_dir}: {', '.join(duplicates)}"
        raise ToolRunnerError(msg)
    return configs


def resolve_cases_dir(dataset_dir: Path) -> Path:
    """Return the benchmark cases directory under *dataset_dir*."""
    cases_dir = dataset_dir / "cases"
    if cases_dir.is_dir():
        return cases_dir
    if any(path.is_dir() for path in dataset_dir.iterdir() if path.name.startswith("case_")):
        return dataset_dir
    msg = f"No cases directory found under {dataset_dir}"
    raise ToolRunnerError(msg)


def tool_result_path(output_dir: Path, case_id: str, tool_id: str) -> Path:
    """Return the JSON result path for one case/tool pair."""
    return output_dir / f"{case_id}__{sanitize_model_name(tool_id)}.json"


def classify_failure(
    *,
    status: ToolRunStatus,
    initial_bpr: float,
    final_bpr: float,
    complete_repair: bool,
    effective_repair: bool,
    regression: bool,
    error_kind: str | None = None,
) -> FailureClass:
    """Map execution outcome to a failure/success class."""
    if status == "skipped":
        return "skipped"
    if status == "timeout" or error_kind == "timeout":
        return "timeout"
    if error_kind == "parse_error":
        return "parse_error"
    if status == "failed" or error_kind == "tool_error":
        return "tool_error"
    if complete_repair:
        return "complete_repair"
    if regression:
        return "regression"
    if effective_repair:
        return "effective_repair"
    if final_bpr == initial_bpr:
        return "no_improvement"
    return "no_improvement"


def _backend_from_environment(environment: dict[str, str]) -> ModelBackend:
    backend_raw = environment.get("FSMREPAIRBENCH_BACKEND", ModelBackend.OLLAMA.value)
    try:
        return ModelBackend(str(backend_raw))
    except ValueError as exc:
        msg = f"Unsupported FSMREPAIRBENCH_BACKEND value: {backend_raw!r}"
        raise ToolRunnerError(msg) from exc


def _baseline_seed(tool: ToolConfig) -> int:
    """Return the deterministic seed for baseline engines (default 0)."""
    raw = tool.environment.get("baseline_seed") or tool.environment.get("random_seed")
    if raw is None:
        return 0
    try:
        return int(raw)
    except ValueError as exc:
        msg = f"Invalid baseline seed in tool environment: {raw!r}"
        raise ToolRunnerError(msg) from exc


def _model_spec_from_tool(tool: ToolConfig) -> Any:
    backend = _backend_from_environment(tool.environment)
    base_url = tool.environment.get("OLLAMA_HOST") or tool.environment.get("OPENAI_BASE_URL")
    api_key = tool.environment.get("OPENAI_API_KEY")
    payload: dict[str, str] = {"name": tool.command, "backend": backend.value}
    if base_url:
        payload["base_url"] = base_url
    if api_key:
        payload["api_key"] = api_key
    return parse_model_spec(payload, default_backend=backend)


def _run_baseline_tool(task: ToolRunTask) -> RepairResult:
    tool = task.tool
    case = task.case
    started_at = time.perf_counter()
    current_fsm = case.faulty_fsm.model_copy(deep=True)
    iterations: list[dict[str, Any]] = []

    baseline_seed = _baseline_seed(tool)

    try:
        get_baseline_engine(tool.command, seed=baseline_seed)
    except BaselineEngineError as exc:
        msg = str(exc)
        raise ToolRunnerError(msg) from exc

    for iteration in range(1, tool.iterations + 1):
        score_before = score_oracle_suite(current_fsm, case.oracle_suite)
        record: dict[str, Any] = {
            "iteration": iteration,
            "bpr_before": score_before.bpr,
            "patch_valid": False,
            "patch_applied": False,
        }
        if score_before.bpr == 1.0:
            record["stopped_early"] = True
            record["bpr_after"] = score_before.bpr
            iterations.append(record)
            break

        try:
            engine = get_baseline_engine(tool.command, seed=baseline_seed)
            patch = engine.propose_patch(current_fsm, case.oracle_suite)
            record["patch"] = patch.model_dump()
            validation_errors = validate_patch(current_fsm, patch)
            if validation_errors:
                record["patch_valid"] = False
                record["validation_errors"] = validation_errors
                record["bpr_after"] = score_before.bpr
            else:
                current_fsm = apply_patch(current_fsm, patch)
                score_after = score_oracle_suite(current_fsm, case.oracle_suite)
                record["patch_valid"] = True
                record["patch_applied"] = True
                record["validation_errors"] = []
                record["bpr_after"] = score_after.bpr
        except (BaselineEngineError, PatchError, ValueError) as exc:
            record["error"] = str(exc)
            record["bpr_after"] = score_before.bpr

        iterations.append(record)
        if record.get("bpr_after") == 1.0:
            break

    final_score = score_oracle_suite(current_fsm, case.oracle_suite)
    runtime_seconds = round(time.perf_counter() - started_at, 4)
    return RepairResult(
        bug_id=case.faulty_fsm.id,
        passed=final_score.bpr == 1.0,
        score=final_score.bpr,
        details={
            "model": tool.tool_id,
            "backend": "baseline",
            "baseline_engine": tool.command,
            "baseline_seed": baseline_seed,
            "temperature": tool.temperature,
            "max_iterations": tool.iterations,
            "runtime_seconds": runtime_seconds,
            "iterations": iterations,
            "final_fsm": current_fsm.model_dump(),
            "passed_steps": final_score.passed_steps,
            "total_steps": final_score.total_steps,
            "passed_scenarios": final_score.passed_scenarios,
            "total_scenarios": final_score.total_scenarios,
        },
    )


def _run_llm_tool(task: ToolRunTask) -> RepairResult:
    tool = task.tool
    spec = _model_spec_from_tool(tool)
    client = create_model_client(spec)
    return run_llm_repair_with_client(
        task.case.faulty_fsm,
        task.case.oracle_suite,
        model=spec.name,
        max_iterations=tool.iterations,
        temperature=tool.temperature,
        client=client,
    )


def _format_command(command: str, *, values: dict[str, str]) -> str:
    try:
        return command.format(**values)
    except KeyError as exc:
        msg = f"Unknown command placeholder: {exc}"
        raise ToolRunnerError(msg) from exc


def _run_external_tool(task: ToolRunTask, *, output_path: Path) -> RepairResult:
    tool = task.tool
    case = task.case
    work_dir = output_path.parent / ".work" / f"{case.case_id}__{tool.tool_id}"
    work_dir.mkdir(parents=True, exist_ok=True)

    faulty_path = work_dir / "faulty_fsm.json"
    oracle_path = work_dir / "oracle_suite.json"
    faulty_path.write_text(case.faulty_fsm.model_dump_json(indent=2) + "\n", encoding="utf-8")
    oracle_path.write_text(case.oracle_suite.model_dump_json(indent=2) + "\n", encoding="utf-8")

    command_values = {
        "case_dir": str(case.case_dir),
        "case_id": case.case_id,
        "faulty_fsm": str(faulty_path),
        "oracle": str(oracle_path),
        "output": str(output_path),
        "tool_id": tool.tool_id,
    }
    command = _format_command(tool.command, values=command_values)
    env = os.environ.copy()
    env.update(tool.environment)

    try:
        completed = subprocess.run(
            shlex.split(command),
            check=False,
            capture_output=True,
            text=True,
            timeout=tool.timeout_seconds,
            env=env,
            cwd=work_dir,
        )
    except subprocess.TimeoutExpired as exc:
        msg = f"External tool timed out after {tool.timeout_seconds}s"
        raise TimeoutError(msg) from exc

    if completed.returncode != 0:
        stderr = completed.stderr.strip() or completed.stdout.strip() or "unknown error"
        msg = f"External tool exited with code {completed.returncode}: {stderr}"
        raise ToolRunnerError(msg)

    if not output_path.is_file():
        msg = f"External tool did not write output file: {output_path}"
        raise ToolRunnerError(msg)

    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Failed to parse external tool output: {exc}"
        raise ToolRunnerError(msg) from exc

    if "repair_result" in payload:
        repair_result = RepairResult.model_validate(payload["repair_result"])
    else:
        repair_result = RepairResult.model_validate(payload)

    details = dict(repair_result.details)
    details.setdefault("backend", "external")
    details.setdefault("model", tool.tool_id)
    return repair_result.model_copy(update={"details": details})


def _execute_tool(task: ToolRunTask, *, output_path: Path) -> RepairResult:
    if task.tool.tool_type == "baseline":
        return _run_baseline_tool(task)
    if task.tool.tool_type == "llm":
        return _run_llm_tool(task)
    if task.tool.tool_type == "external":
        return _run_external_tool(task, output_path=output_path)
    msg = f"Unsupported tool_type '{task.tool.tool_type}'"
    raise ToolRunnerError(msg)


def _summary_from_experiment_row(
    *,
    task: ToolRunTask,
    summary_row: Any,
    status: ToolRunStatus,
    failure_class: FailureClass,
    runtime_seconds: float,
) -> ToolRunSummaryRow:
    return ToolRunSummaryRow(
        case_id=task.case.case_id,
        tool_id=task.tool.tool_id,
        tool_type=task.tool.tool_type,
        model=task.tool.tool_id,
        mutation_operator=task.case.mutation_operator,
        status=status,
        failure_class=failure_class,
        initial_bpr=summary_row.initial_bpr,
        final_bpr=summary_row.final_bpr,
        delta_bpr=summary_row.delta_bpr,
        complete_repair=summary_row.complete_repair,
        effective_repair=summary_row.effective_repair,
        regression=summary_row.regression,
        patch_parse_failures=summary_row.patch_parse_failures,
        patch_validation_failures=summary_row.patch_validation_failures,
        patch_application_failures=summary_row.patch_application_failures,
        iterations_completed=summary_row.iterations_completed,
        runtime_seconds=runtime_seconds,
    )


def _failure_summary_row(
    *,
    task: ToolRunTask,
    initial_bpr: float,
    status: ToolRunStatus,
    failure_class: FailureClass,
    runtime_seconds: float = 0.0,
) -> ToolRunSummaryRow:
    return ToolRunSummaryRow(
        case_id=task.case.case_id,
        tool_id=task.tool.tool_id,
        tool_type=task.tool.tool_type,
        model=task.tool.tool_id,
        mutation_operator=task.case.mutation_operator,
        status=status,
        failure_class=failure_class,
        initial_bpr=initial_bpr,
        final_bpr=initial_bpr,
        delta_bpr=0.0,
        complete_repair=False,
        effective_repair=False,
        regression=False,
        patch_parse_failures=0,
        patch_validation_failures=0,
        patch_application_failures=0,
        iterations_completed=0,
        runtime_seconds=runtime_seconds,
    )


def write_tool_result(
    path: Path,
    *,
    task: ToolRunTask,
    initial_bpr: float,
    repair_result: RepairResult | None,
    summary_row: ToolRunSummaryRow,
) -> None:
    """Write one JSON result file for a case/tool pair."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "case_id": task.case.case_id,
        "tool_id": task.tool.tool_id,
        "tool_type": task.tool.tool_type,
        "model": task.tool.tool_id,
        "mutation_operator": task.case.mutation_operator,
        "status": summary_row.status,
        "failure_class": summary_row.failure_class,
        "input_format": task.tool.input_format,
        "output_format": task.tool.output_format,
        "initial_bpr": initial_bpr,
        "final_bpr": summary_row.final_bpr,
        "delta_bpr": summary_row.delta_bpr,
        "complete_repair": summary_row.complete_repair,
        "effective_repair": summary_row.effective_repair,
        "regression": summary_row.regression,
        "patch_parse_failures": summary_row.patch_parse_failures,
        "patch_validation_failures": summary_row.patch_validation_failures,
        "patch_application_failures": summary_row.patch_application_failures,
        "iterations_completed": summary_row.iterations_completed,
        "runtime_seconds": summary_row.runtime_seconds,
    }
    if repair_result is not None:
        payload["repair_result"] = repair_result.model_dump()
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def execute_tool_task(task: ToolRunTask, *, output_dir: Path) -> ToolRunSummaryRow:
    """Execute one case/tool pair and persist its JSON result."""
    result_path = tool_result_path(output_dir, task.case.case_id, task.tool.tool_id)
    initial_bpr = score_oracle_suite(task.case.faulty_fsm, task.case.oracle_suite).bpr
    started_at = time.perf_counter()

    try:
        repair_result = _execute_tool(task, output_path=result_path)
    except TimeoutError:
        runtime_seconds = round(time.perf_counter() - started_at, 4)
        summary_row = _failure_summary_row(
            task=task,
            initial_bpr=initial_bpr,
            status="timeout",
            failure_class="timeout",
            runtime_seconds=runtime_seconds,
        )
        write_tool_result(
            result_path,
            task=task,
            initial_bpr=initial_bpr,
            repair_result=None,
            summary_row=summary_row,
        )
        return summary_row
    except ToolRunnerError:
        runtime_seconds = round(time.perf_counter() - started_at, 4)
        summary_row = _failure_summary_row(
            task=task,
            initial_bpr=initial_bpr,
            status="failed",
            failure_class="tool_error",
            runtime_seconds=runtime_seconds,
        )
        write_tool_result(
            result_path,
            task=task,
            initial_bpr=initial_bpr,
            repair_result=None,
            summary_row=summary_row,
        )
        return summary_row

    experiment_row = build_summary_row(
        case=task.case,
        model=task.tool.tool_id,
        initial_bpr=initial_bpr,
        repair_result=repair_result,
    )
    runtime_seconds = float(repair_result.details.get("runtime_seconds", time.perf_counter() - started_at))
    failure_class = classify_failure(
        status="completed",
        initial_bpr=initial_bpr,
        final_bpr=experiment_row.final_bpr,
        complete_repair=experiment_row.complete_repair,
        effective_repair=experiment_row.effective_repair,
        regression=experiment_row.regression,
    )
    summary_row = _summary_from_experiment_row(
        task=task,
        summary_row=experiment_row,
        status="completed",
        failure_class=failure_class,
        runtime_seconds=round(runtime_seconds, 4),
    )
    write_tool_result(
        result_path,
        task=task,
        initial_bpr=initial_bpr,
        repair_result=repair_result,
        summary_row=summary_row,
    )
    return summary_row


def build_tool_tasks(cases: list[ExperimentCase], tools: list[ToolConfig]) -> list[ToolRunTask]:
    """Build the cartesian product of *cases* and *tools*."""
    return [ToolRunTask(case=case, tool=tool) for case in cases for tool in tools]


def _load_existing_tool_summary(path: Path, task: ToolRunTask) -> ToolRunSummaryRow | None:
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None

    required = ("case_id", "tool_id", "status", "failure_class", "initial_bpr", "final_bpr")
    if not all(key in payload for key in required):
        return None

    if payload.get("case_id") != task.case.case_id or payload.get("tool_id") != task.tool.tool_id:
        return None

    return ToolRunSummaryRow(
        case_id=str(payload["case_id"]),
        tool_id=str(payload["tool_id"]),
        tool_type=str(payload.get("tool_type", task.tool.tool_type)),  # type: ignore[arg-type]
        model=str(payload.get("model", task.tool.tool_id)),
        mutation_operator=str(payload.get("mutation_operator", task.case.mutation_operator)),
        status=str(payload["status"]),  # type: ignore[arg-type]
        failure_class=str(payload["failure_class"]),  # type: ignore[arg-type]
        initial_bpr=float(payload["initial_bpr"]),
        final_bpr=float(payload["final_bpr"]),
        delta_bpr=float(payload.get("delta_bpr", float(payload["final_bpr"]) - float(payload["initial_bpr"]))),
        complete_repair=bool(payload.get("complete_repair", False)),
        effective_repair=bool(payload.get("effective_repair", False)),
        regression=bool(payload.get("regression", False)),
        patch_parse_failures=int(payload.get("patch_parse_failures", 0)),
        patch_validation_failures=int(payload.get("patch_validation_failures", 0)),
        patch_application_failures=int(payload.get("patch_application_failures", 0)),
        iterations_completed=int(payload.get("iterations_completed", 0)),
        runtime_seconds=float(payload.get("runtime_seconds", 0.0)),
    )


def write_tool_summary_csv(path: Path, rows: list[ToolRunSummaryRow]) -> None:
    """Write per-case/tool summary rows to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(TOOL_SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(row.to_dict() for row in rows)


def write_tool_leaderboard_csv(path: Path, rows: list[ToolRunSummaryRow]) -> None:
    """Aggregate *rows* into a tool leaderboard CSV."""
    records = [
        CaseResultRecord(
            case_id=row.case_id,
            model=row.tool_id,
            initial_bpr=row.initial_bpr,
            final_bpr=row.final_bpr,
            delta_bpr=row.delta_bpr,
            complete_repair=row.complete_repair,
            effective_repair=row.effective_repair,
            iterations_completed=row.iterations_completed,
            runtime_seconds=row.runtime_seconds,
        )
        for row in rows
        if row.status == "completed"
    ]
    if not records:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(TOOL_SUMMARY_COLUMNS[:1]))
            writer.writeheader()
        return
    entries = compute_leaderboard_entries(records)
    write_leaderboard_csv(path, entries)


def run_tools(
    dataset_dir: Path,
    tools_dir: Path,
    output_dir: Path,
    *,
    resume: bool = True,
    workers: int = 1,
    executor: Callable[[ToolRunTask, Path], ToolRunSummaryRow] | None = None,
) -> ToolRunResult:
    """Run all configured tools on all cases in *dataset_dir*."""
    if workers < 1:
        msg = "workers must be at least 1"
        raise ToolRunnerError(msg)

    tools = load_tool_configs(tools_dir)
    cases = discover_experiment_cases(resolve_cases_dir(dataset_dir))
    tasks = build_tool_tasks(cases, tools)
    output_dir.mkdir(parents=True, exist_ok=True)

    invoke = executor or (lambda task, out: execute_tool_task(task, output_dir=out))
    rows: list[ToolRunSummaryRow] = []
    pending: list[ToolRunTask] = []

    for task in tasks:
        result_path = tool_result_path(output_dir, task.case.case_id, task.tool.tool_id)
        if resume:
            existing = _load_existing_tool_summary(result_path, task)
            if existing is not None:
                rows.append(existing)
                continue
        pending.append(task)

    if pending:
        if workers == 1:
            for task in pending:
                rows.append(invoke(task, output_dir))
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(invoke, task, output_dir): task for task in pending}
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        rows.append(future.result(timeout=task.tool.timeout_seconds + 30))
                    except FuturesTimeoutError:
                        rows.append(
                            _failure_summary_row(
                                task=task,
                                initial_bpr=score_oracle_suite(
                                    task.case.faulty_fsm,
                                    task.case.oracle_suite,
                                ).bpr,
                                status="timeout",
                                failure_class="timeout",
                            )
                        )

    rows.sort(key=lambda row: (row.case_id, row.tool_id))
    summary_path = output_dir / "summary.csv"
    leaderboard_path = output_dir / "leaderboard.csv"
    write_tool_summary_csv(summary_path, rows)
    write_tool_leaderboard_csv(leaderboard_path, rows)

    manifest = {
        "dataset_dir": str(dataset_dir),
        "tools_dir": str(tools_dir),
        "output_dir": str(output_dir),
        "tool_ids": [tool.tool_id for tool in tools],
        "case_count": len(cases),
        "run_count": len(rows),
        "resume": resume,
        "workers": workers,
    }
    (output_dir / "tool_run_manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return ToolRunResult(
        output_dir=output_dir,
        summary_path=summary_path,
        leaderboard_path=leaderboard_path,
        rows=tuple(rows),
    )
