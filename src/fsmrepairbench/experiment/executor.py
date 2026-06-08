"""Scalable experiment executor with worker pool and queue scheduling."""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass

from fsmrepairbench.experiment.progress import ProgressTracker
from fsmrepairbench.experiment.queue import TaskQueue
from fsmrepairbench.experiment.tasks import RepairTask, build_repair_tasks
from fsmrepairbench.experiment.worker import RepairRunner, WorkerResult, execute_repair_task
from fsmrepairbench.experiments import (
    ExperimentConfig,
    ExperimentResult,
    discover_experiment_cases,
    load_existing_summary_row,
    result_path,
)
from fsmrepairbench.llm.clients.base import ModelBackend
from fsmrepairbench.llm.clients.registry import parse_model_specs

DEFAULT_CHECKPOINT_INTERVAL = 100


@dataclass(frozen=True)
class ExecutorConfig:
    """Runtime configuration for scalable experiment execution."""

    workers: int = 4
    checkpoint_interval: int = DEFAULT_CHECKPOINT_INTERVAL
    default_backend: ModelBackend = ModelBackend.OLLAMA


class ExperimentExecutor:
    """Queue-driven experiment runner suitable for large execution counts."""

    def __init__(
        self,
        config: ExperimentConfig,
        *,
        executor_config: ExecutorConfig | None = None,
        repair_runner: RepairRunner | None = None,
    ) -> None:
        self.config = config
        self.executor_config = executor_config or ExecutorConfig(
            workers=config.workers,
            checkpoint_interval=config.checkpoint_interval,
            default_backend=config.default_backend,
        )
        self.repair_runner = repair_runner

    def run(self, *, resume: bool | None = None) -> ExperimentResult:
        should_resume = self.config.resume if resume is None else resume
        cases = discover_experiment_cases(self.config.cases_dir)
        model_specs = parse_model_specs(
            self.config.models,
            default_backend=self.executor_config.default_backend,
        )
        tasks = build_repair_tasks(
            cases,
            model_specs,
            iterations=self.config.iterations,
            temperature=self.config.temperature,
        )

        self.config.output_dir.mkdir(parents=True, exist_ok=True)
        progress_path = self.config.output_dir / "progress.csv"
        summary_path = self.config.output_dir / "summary.csv"
        tracker = ProgressTracker(
            progress_path=progress_path,
            summary_path=summary_path,
            checkpoint_interval=self.executor_config.checkpoint_interval,
        )

        pending_tasks: list[RepairTask] = []
        for task in tasks:
            if should_resume:
                existing = load_existing_summary_row(
                    result_path(self.config.output_dir, task.case_id, task.model_label)
                )
                if existing is not None:
                    tracker.add_row(existing)
                    continue
            pending_tasks.append(task)

        queue_dir = self.config.output_dir / "queue"
        TaskQueue.from_tasks(pending_tasks, queue_dir=queue_dir)

        if pending_tasks:
            self._run_worker_pool(pending_tasks, tracker, resume=should_resume)

        rows = tracker.finalize()
        return ExperimentResult(
            output_dir=self.config.output_dir,
            progress_path=progress_path,
            summary_path=summary_path,
            rows=rows,
        )

    def _run_worker_pool(
        self,
        tasks: list[RepairTask],
        tracker: ProgressTracker,
        *,
        resume: bool,
    ) -> None:
        worker_count = max(1, self.executor_config.workers)

        def submit_fn(task: RepairTask) -> WorkerResult:
            return execute_repair_task(
                task,
                output_dir=self.config.output_dir,
                resume=resume,
                repair_runner=self.repair_runner,
            )

        with ThreadPoolExecutor(max_workers=worker_count) as executor:
            futures: dict[Future[WorkerResult], RepairTask] = {
                executor.submit(submit_fn, task): task for task in tasks
            }
            for future in as_completed(futures):
                worker_result = future.result()
                tracker.add_row(worker_result.summary_row)
