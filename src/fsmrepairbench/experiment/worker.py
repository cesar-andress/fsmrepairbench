"""Worker execution for queued repair tasks."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.experiment.tasks import RepairTask
from fsmrepairbench.experiments import ExperimentCase, ExperimentSummaryRow
from fsmrepairbench.models import FSM, BugMetadata, OracleSuite, RepairResult

RepairRunner = Callable[[FSM, OracleSuite, str, int, float], RepairResult]


@dataclass(frozen=True)
class WorkerResult:
    """Outcome of one worker task execution."""

    task: RepairTask
    summary_row: ExperimentSummaryRow
    result_path: Path
    skipped: bool = False


def load_experiment_case(case_dir: Path, *, mutation_operator: str | None = None) -> ExperimentCase:
    """Load one experiment case from disk."""
    from fsmrepairbench.validators import load_fsm_json, load_model, load_oracle_suite

    faulty_fsm = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle_suite = load_oracle_suite(case_dir / "oracle_suite.json")
    operator = mutation_operator or "unknown"
    metadata_path = case_dir / "bug_metadata.json"
    if metadata_path.is_file():
        metadata = load_model(metadata_path, BugMetadata)
        operator = metadata.mutation_operator
    return ExperimentCase(
        case_id=case_dir.name,
        case_dir=case_dir,
        faulty_fsm=faulty_fsm,
        oracle_suite=oracle_suite,
        mutation_operator=operator,
    )


def execute_repair_task(
    task: RepairTask,
    *,
    output_dir: Path,
    resume: bool,
    repair_runner: RepairRunner | None = None,
) -> WorkerResult:
    """Execute one repair task and persist its result."""
    from fsmrepairbench.experiments import (
        build_summary_row,
        load_existing_summary_row,
        result_path,
        write_case_result,
    )
    from fsmrepairbench.llm.clients.registry import create_model_client
    from fsmrepairbench.llm.repair import run_llm_repair_with_client
    from fsmrepairbench.scorer import score_oracle_suite

    case_dir = Path(task.case_dir)
    case = load_experiment_case(case_dir, mutation_operator=task.mutation_operator)
    result_file = result_path(output_dir, case.case_id, task.model_label)

    if resume:
        existing = load_existing_summary_row(result_file)
        if existing is not None:
            return WorkerResult(
                task=task,
                summary_row=existing,
                result_path=result_file,
                skipped=True,
            )

    initial_bpr = score_oracle_suite(case.faulty_fsm, case.oracle_suite).bpr
    if repair_runner is not None:
        repair_result = repair_runner(
            case.faulty_fsm,
            case.oracle_suite,
            task.model_name,
            task.iterations,
            task.temperature,
        )
    else:
        client = create_model_client(task.model_spec)
        repair_result = run_llm_repair_with_client(
            case.faulty_fsm,
            case.oracle_suite,
            model=task.model_name,
            max_iterations=task.iterations,
            temperature=task.temperature,
            client=client,
        )

    summary_row = build_summary_row(
        case=case,
        model=task.model_label,
        initial_bpr=initial_bpr,
        repair_result=repair_result,
        status="completed",
    )
    write_case_result(
        result_file,
        case=case,
        model=task.model_label,
        initial_bpr=initial_bpr,
        repair_result=repair_result,
        summary_row=summary_row,
    )
    return WorkerResult(task=task, summary_row=summary_row, result_path=result_file)
