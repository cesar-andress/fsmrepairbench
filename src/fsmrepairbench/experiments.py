"""Experiment orchestration for FSMRepairBench."""

from __future__ import annotations

import csv
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from fsmrepairbench.llm.ollama import run_llm_repair_case
from fsmrepairbench.models import FSM, BugMetadata, OracleSuite, RepairResult
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm_json, load_model, load_oracle_suite

RepairRunner = Callable[[FSM, OracleSuite, str, int, float], RepairResult]

SUMMARY_COLUMNS: tuple[str, ...] = (
    "case_id",
    "model",
    "mutation_operator",
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
)

PROGRESS_COLUMNS: tuple[str, ...] = SUMMARY_COLUMNS + ("status",)


class ExperimentConfigError(ValueError):
    """Raised when experiment configuration is invalid."""


class ExperimentConfig(BaseModel):
    """YAML experiment configuration."""

    models: list[str]
    cases_dir: Path
    iterations: int = Field(default=3, ge=1)
    temperature: float = 0.0
    output_dir: Path
    resume: bool = True

    @field_validator("cases_dir", "output_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)


@dataclass(frozen=True)
class ExperimentCase:
    """Benchmark case inputs loaded from disk."""

    case_id: str
    case_dir: Path
    faulty_fsm: FSM
    oracle_suite: OracleSuite
    mutation_operator: str


@dataclass(frozen=True)
class ExperimentSummaryRow:
    """One row in experiment summary/progress output."""

    case_id: str
    model: str
    mutation_operator: str
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
    status: str = "completed"

    def to_summary_dict(self) -> dict[str, str | float | bool | int]:
        return {
            "case_id": self.case_id,
            "model": self.model,
            "mutation_operator": self.mutation_operator,
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
        }

    def to_progress_dict(self) -> dict[str, str | float | bool | int]:
        row = self.to_summary_dict()
        row["status"] = self.status
        return row


@dataclass(frozen=True)
class ExperimentResult:
    """Result of running an experiment."""

    output_dir: Path
    progress_path: Path
    summary_path: Path
    rows: tuple[ExperimentSummaryRow, ...]


def load_experiment_config(path: Path) -> ExperimentConfig:
    """Load experiment configuration from a YAML file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Failed to read experiment config: {exc}"
        raise ExperimentConfigError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in experiment config: {exc}"
        raise ExperimentConfigError(msg) from exc

    if not isinstance(raw, dict):
        msg = "Experiment config must be a YAML mapping"
        raise ExperimentConfigError(msg)

    try:
        return ExperimentConfig.model_validate(raw)
    except Exception as exc:
        msg = f"Invalid experiment config schema: {exc}"
        raise ExperimentConfigError(msg) from exc


def discover_experiment_cases(cases_dir: Path) -> list[ExperimentCase]:
    """Discover benchmark cases under *cases_dir*."""
    if not cases_dir.is_dir():
        msg = f"Cases directory not found: {cases_dir}"
        raise ExperimentConfigError(msg)

    cases: list[ExperimentCase] = []
    for case_dir in sorted(path for path in cases_dir.iterdir() if path.is_dir()):
        faulty_path = case_dir / "faulty_fsm.json"
        oracle_path = case_dir / "oracle_suite.json"
        metadata_path = case_dir / "bug_metadata.json"
        if not faulty_path.is_file() or not oracle_path.is_file():
            continue

        faulty_fsm = load_fsm_json(faulty_path)
        oracle_suite = load_oracle_suite(oracle_path)
        mutation_operator = "unknown"
        if metadata_path.is_file():
            metadata = load_model(metadata_path, BugMetadata)
            mutation_operator = metadata.mutation_operator

        cases.append(
            ExperimentCase(
                case_id=case_dir.name,
                case_dir=case_dir,
                faulty_fsm=faulty_fsm,
                oracle_suite=oracle_suite,
                mutation_operator=mutation_operator,
            )
        )

    if not cases:
        msg = f"No valid cases found under {cases_dir}"
        raise ExperimentConfigError(msg)

    return cases


def sanitize_model_name(model: str) -> str:
    """Return a filesystem-safe model identifier."""
    return model.replace(":", "__").replace("/", "_")


def result_path(output_dir: Path, case_id: str, model: str) -> Path:
    """Return the JSON result path for a case/model pair."""
    return output_dir / f"{case_id}__{sanitize_model_name(model)}.json"


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _count_patch_failures(
    iterations: list[dict[str, Any]],
) -> tuple[int, int, int]:
    parse_failures = 0
    validation_failures = 0
    application_failures = 0

    for record in iterations:
        if record.get("stopped_early"):
            continue
        validation_errors = record.get("validation_errors") or []
        if validation_errors:
            validation_failures += 1
            continue
        if record.get("patch_applied"):
            continue
        if "error" in record:
            error = str(record["error"])
            if error.startswith("Unknown transition") or "cannot be applied" in error:
                application_failures += 1
            else:
                parse_failures += 1
        elif record.get("patch_valid") is False:
            validation_failures += 1

    return parse_failures, validation_failures, application_failures


def _iterations_completed(repair_result: RepairResult) -> int:
    iterations = repair_result.details.get("iterations", [])
    if not isinstance(iterations, list):
        return 0
    return len(iterations)


def build_summary_row(
    *,
    case: ExperimentCase,
    model: str,
    initial_bpr: float,
    repair_result: RepairResult,
    status: str = "completed",
) -> ExperimentSummaryRow:
    """Build a summary row from a repair result."""
    final_bpr = repair_result.score
    delta_bpr = final_bpr - initial_bpr
    iterations = repair_result.details.get("iterations", [])
    if not isinstance(iterations, list):
        iterations = []
    parse_failures, validation_failures, application_failures = _count_patch_failures(
        iterations
    )

    return ExperimentSummaryRow(
        case_id=case.case_id,
        model=model,
        mutation_operator=case.mutation_operator,
        initial_bpr=initial_bpr,
        final_bpr=final_bpr,
        delta_bpr=delta_bpr,
        complete_repair=final_bpr == 1.0,
        effective_repair=final_bpr > initial_bpr,
        regression=final_bpr < initial_bpr,
        patch_parse_failures=parse_failures,
        patch_validation_failures=validation_failures,
        patch_application_failures=application_failures,
        iterations_completed=_iterations_completed(repair_result),
        status=status,
    )


def load_existing_summary_row(path: Path) -> ExperimentSummaryRow | None:
    """Load a summary row from an existing result JSON file."""
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        RepairResult.model_validate(payload["repair_result"])
        return ExperimentSummaryRow(
            case_id=str(payload["case_id"]),
            model=str(payload["model"]),
            mutation_operator=str(payload["mutation_operator"]),
            initial_bpr=float(payload["initial_bpr"]),
            final_bpr=float(payload["final_bpr"]),
            delta_bpr=float(payload["delta_bpr"]),
            complete_repair=bool(payload["complete_repair"]),
            effective_repair=bool(payload["effective_repair"]),
            regression=bool(payload["regression"]),
            patch_parse_failures=int(payload["patch_parse_failures"]),
            patch_validation_failures=int(payload["patch_validation_failures"]),
            patch_application_failures=int(payload["patch_application_failures"]),
            iterations_completed=int(payload["iterations_completed"]),
            status="skipped",
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError):
        return None


def write_case_result(
    path: Path,
    *,
    case: ExperimentCase,
    model: str,
    initial_bpr: float,
    repair_result: RepairResult,
    summary_row: ExperimentSummaryRow,
) -> None:
    """Write one JSON result file for a case/model pair."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "case_id": case.case_id,
        "model": model,
        "mutation_operator": case.mutation_operator,
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
        "repair_result": repair_result.model_dump(),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def run_experiment(
    config: ExperimentConfig,
    *,
    repair_runner: RepairRunner | None = None,
    resume: bool | None = None,
) -> ExperimentResult:
    """Run all case/model repair experiments defined by *config*."""
    runner = repair_runner or _default_repair_runner
    should_resume = config.resume if resume is None else resume
    cases = discover_experiment_cases(config.cases_dir)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    progress_path = config.output_dir / "progress.csv"
    summary_path = config.output_dir / "summary.csv"
    rows: list[ExperimentSummaryRow] = []

    for case in cases:
        for model in config.models:
            result_file = result_path(config.output_dir, case.case_id, model)
            if should_resume:
                existing = load_existing_summary_row(result_file)
                if existing is not None:
                    rows.append(existing)
                    _write_csv(
                        progress_path,
                        PROGRESS_COLUMNS,
                        [row.to_progress_dict() for row in rows],
                    )
                    continue

            initial_bpr = score_oracle_suite(case.faulty_fsm, case.oracle_suite).bpr
            repair_result = runner(
                case.faulty_fsm,
                case.oracle_suite,
                model,
                config.iterations,
                config.temperature,
            )
            summary_row = build_summary_row(
                case=case,
                model=model,
                initial_bpr=initial_bpr,
                repair_result=repair_result,
                status="completed",
            )
            write_case_result(
                result_file,
                case=case,
                model=model,
                initial_bpr=initial_bpr,
                repair_result=repair_result,
                summary_row=summary_row,
            )
            rows.append(summary_row)
            _write_csv(
                progress_path,
                PROGRESS_COLUMNS,
                [row.to_progress_dict() for row in rows],
            )

    _write_csv(
        summary_path,
        SUMMARY_COLUMNS,
        [row.to_summary_dict() for row in rows],
    )

    return ExperimentResult(
        output_dir=config.output_dir,
        progress_path=progress_path,
        summary_path=summary_path,
        rows=tuple(rows),
    )


def _default_repair_runner(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float,
) -> RepairResult:
    return run_llm_repair_case(
        faulty_fsm,
        oracle_suite,
        model=model,
        max_iterations=max_iterations,
        temperature=temperature,
    )
