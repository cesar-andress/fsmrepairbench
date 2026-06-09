"""Tests for LLM evaluation task generation."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.llm_evaluation_tasks import (
    LLMEvaluationTaskError as TaskGenError,
    SUPPORTED_LLM_TASK_TYPES,
    TASK_TYPE_NAMES,
    discover_task_sources,
    generate_tasks_for_source,
    load_task_source_from_path,
    minimize_fsm,
    unreachable_state_list,
    write_llm_evaluation_tasks,
    FSMTaskSource,
)
from fsmrepairbench.models import State, Transition
from fsmrepairbench.mutators import mutate
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_unreachable_states_and_minimize() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    assert unreachable_state_list(fsm) == []

    dead_state = State(id="dead")
    fsm_with_dead = fsm.model_copy(
        update={
            "states": [*fsm.states, dead_state],
            "transitions": [
                *fsm.transitions,
                Transition(
                    id="t_dead",
                    source="dead",
                    event="noop",
                    target="dead",
                ),
            ],
        }
    )
    assert unreachable_state_list(fsm_with_dead) == ["dead"]

    minimized = minimize_fsm(fsm_with_dead)
    assert unreachable_state_list(minimized) == []
    assert len(minimized.states) == len(fsm.states)


def test_generate_all_task_types_for_valid_fsm() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    source = FSMTaskSource(reference=reference, source_id="valid_fsm")
    tasks = generate_tasks_for_source(source, seed=7)

    task_types = {task.task_type for task in tasks}
    assert "A" in task_types
    assert "B" in task_types
    assert "D" in task_types
    assert "E" in task_types
    assert "F" in task_types
    assert "G" in task_types
    assert len([task for task in tasks if task.task_type == "B"]) == 3

    for task in tasks:
        assert task.task_id
        assert task.task_name == TASK_TYPE_NAMES[task.task_type]
        assert task.instruction
        assert task.expected_output
        assert len(task.messages) == 2
        assert task.messages[0]["role"] == "system"
        assert task.messages[1]["role"] == "user"


def test_task_c_uses_actions_when_no_explicit_output() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    source = FSMTaskSource(reference=reference)
    tasks = generate_tasks_for_source(source, task_types=("C",))
    assert tasks
    assert all(task.expected_output["output"] for task in tasks)


def test_task_d_uses_benchmark_case_context(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "wrong_target", 11)
    case_dir = tmp_path / "case_001"
    case_dir.mkdir()
    (case_dir / "reference_fsm.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "faulty_fsm.json").write_text(
        faulty.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "bug_metadata.json").write_text(
        metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "oracle_suite.json").write_text(
        (FIXTURES / "valid_oracle.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    source = load_task_source_from_path(case_dir)
    tasks = generate_tasks_for_source(source, task_types=("D",))
    assert len(tasks) == 1
    assert tasks[0].input["faulty_fsm"]["id"] == faulty.id
    assert tasks[0].expected_output["fsm"]["id"] == reference.id


def test_write_llm_evaluation_tasks_jsonl(tmp_path: Path) -> None:
    fixtures_dir = tmp_path / "fsms"
    fixtures_dir.mkdir()
    for name in ("simple_fsm.json", "valid_fsm.json"):
        source = FIXTURES / name
        (fixtures_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")

    out_path = tmp_path / "llm_tasks.jsonl"
    result = write_llm_evaluation_tasks(fixtures_dir, out_path, seed=1)
    assert result.task_count > 0
    assert result.source_count >= 2

    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == result.task_count
    first = json.loads(lines[0])
    assert first["task_type"] in SUPPORTED_LLM_TASK_TYPES
    assert "messages" in first
    assert "expected_output" in first

    manifest = json.loads(
        (tmp_path / "llm_tasks_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["task_count"] == result.task_count


def test_discover_task_sources_from_single_json() -> None:
    sources = discover_task_sources(FIXTURES / "simple_fsm.json")
    assert len(sources) == 1
    assert sources[0].reference.id == "toggle_001"


def test_generate_tasks_rejects_missing_path(tmp_path: Path) -> None:
    with pytest.raises(TaskGenError, match="not found"):
        write_llm_evaluation_tasks(tmp_path / "missing", tmp_path / "out.jsonl")


def test_cli_generate_llm_tasks(tmp_path: Path) -> None:
    out_path = tmp_path / "tasks.jsonl"
    result = runner.invoke(
        app,
        [
            "generate-llm-tasks",
            str(FIXTURES / "simple_fsm.json"),
            "--out",
            str(out_path),
            "--task-type",
            "A",
            "--task-type",
            "B",
            "--quiet",
        ],
    )
    assert result.exit_code == 0
    lines = out_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 3
    payload = json.loads(lines[0])
    assert payload["task_type"] == "A"
