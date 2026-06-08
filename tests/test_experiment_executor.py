"""Tests for scalable experiment execution architecture."""

from __future__ import annotations

from pathlib import Path

from fsmrepairbench.experiment.executor import ExecutorConfig, ExperimentExecutor
from fsmrepairbench.experiment.queue import TaskQueue
from fsmrepairbench.experiment.tasks import build_repair_tasks
from fsmrepairbench.experiments import ExperimentConfig, discover_experiment_cases
from fsmrepairbench.llm.clients.base import ModelBackend, ModelSpec
from fsmrepairbench.llm.clients.registry import (
    client_label,
    create_model_client,
    parse_model_spec,
    parse_model_specs,
)
from fsmrepairbench.models import FSM, OracleSuite, RepairResult
from tests.helpers import fake_repair_runner, setup_cases_root


def test_parse_model_specs_supports_backends() -> None:
    specs = parse_model_specs(
        [
            "qwen2.5-coder:7b",
            {"name": "gpt-4o-mini", "backend": "openai"},
            {"name": "meta-llama/Llama-3.1-8B", "backend": "vllm"},
        ]
    )

    assert specs[0].backend is ModelBackend.OLLAMA
    assert specs[1].backend is ModelBackend.OPENAI
    assert specs[2].backend is ModelBackend.VLLM
    assert client_label(specs[0]) == "qwen2.5-coder:7b"
    assert client_label(specs[1]) == "openai::gpt-4o-mini"


def test_create_model_clients() -> None:
    assert create_model_client(ModelSpec(name="m", backend=ModelBackend.OLLAMA)).backend is (
        ModelBackend.OLLAMA
    )
    assert create_model_client(
        parse_model_spec({"name": "m", "backend": "openai"}, default_backend=ModelBackend.OLLAMA)
    ).backend is ModelBackend.OPENAI
    assert create_model_client(
        parse_model_spec({"name": "m", "backend": "vllm"}, default_backend=ModelBackend.OLLAMA)
    ).backend is ModelBackend.VLLM


def test_task_queue_persists_pending_tasks(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    cases = discover_experiment_cases(cases_dir)
    specs = [ModelSpec(name="model-a", backend=ModelBackend.OLLAMA)]
    tasks = build_repair_tasks(cases, specs, iterations=2, temperature=0.0)
    queue_dir = tmp_path / "queue"
    TaskQueue.from_tasks(tasks, queue_dir=queue_dir)

    assert (queue_dir / "pending.jsonl").is_file()
    restored = (queue_dir / "pending.jsonl").read_text(encoding="utf-8").strip().splitlines()
    assert len(restored) == len(tasks)


def test_executor_runs_with_worker_pool(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
        workers=2,
        checkpoint_interval=1,
    )

    executor = ExperimentExecutor(
        config,
        executor_config=ExecutorConfig(workers=2, checkpoint_interval=1),
        repair_runner=fake_repair_runner,
    )
    result = executor.run(resume=False)

    assert len(result.rows) == 2
    assert (output_dir / "queue" / "pending.jsonl").is_file()
    assert result.summary_path.exists()


def test_executor_resume_skips_completed_tasks(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
        workers=2,
    )

    calls = {"count": 0}

    def counting_runner(
        faulty_fsm: FSM,
        oracle_suite: OracleSuite,
        model: str,
        max_iterations: int,
        temperature: float,
    ) -> RepairResult:
        calls["count"] += 1
        return fake_repair_runner(
            faulty_fsm,
            oracle_suite,
            model,
            max_iterations,
            temperature,
        )

    executor = ExperimentExecutor(config, repair_runner=counting_runner)
    executor.run(resume=False)
    assert calls["count"] == 2

    executor.run(resume=True)
    assert calls["count"] == 2


def test_build_repair_tasks_scales_linearly(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    cases = discover_experiment_cases(cases_dir)
    specs = parse_model_specs(["model-a", "model-b", {"name": "gpt", "backend": "openai"}])
    tasks = build_repair_tasks(cases, specs, iterations=3, temperature=0.0)
    assert len(tasks) == len(cases) * len(specs)
