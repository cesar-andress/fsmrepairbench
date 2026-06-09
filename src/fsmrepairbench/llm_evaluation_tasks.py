"""LLM evaluation task generation for finite-state machines."""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from fsmrepairbench.models import BugMetadata, FSM, OracleSuite, Transition
from fsmrepairbench.mutators import MutatorError, mutate
from fsmrepairbench.oracle_generator import (
    DepthLevel,
    OracleGeneratorError,
    generate_oracle_suite,
    reachable_state_ids,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm_json, load_model, load_oracle_suite, validate_fsm

LLMTaskType = Literal["A", "B", "C", "D", "E", "F", "G"]

SUPPORTED_LLM_TASK_TYPES: tuple[LLMTaskType, ...] = ("A", "B", "C", "D", "E", "F", "G")

TASK_TYPE_NAMES: dict[LLMTaskType, str] = {
    "A": "infer_transition_table",
    "B": "predict_next_state",
    "C": "predict_output",
    "D": "repair_mutated_fsm",
    "E": "generate_tests",
    "F": "detect_unreachable_states",
    "G": "minimize_machine",
}

SYSTEM_PROMPT = (
    "You are an expert in finite-state machines (FSMs). "
    "Follow the task instructions precisely and return only the requested JSON object."
)


class LLMEvaluationTaskError(ValueError):
    """Raised when LLM evaluation task generation fails."""


class LLMEvaluationTask(BaseModel):
    """One LLM evaluation task record."""

    task_id: str
    task_type: LLMTaskType
    task_name: str
    fsm_id: str
    instruction: str
    input: dict[str, Any]
    expected_output: dict[str, Any]
    output_schema: dict[str, Any]
    messages: list[dict[str, str]]
    metadata: dict[str, Any] = Field(default_factory=dict)


@dataclass(frozen=True)
class FSMTaskSource:
    """One FSM plus optional repair and oracle context."""

    reference: FSM
    oracle: OracleSuite | None = None
    faulty: FSM | None = None
    bug_metadata: BugMetadata | None = None
    source_id: str = ""


@dataclass(frozen=True)
class LLMTaskGenerationResult:
    """Paths and counts from a task generation run."""

    output_path: Path
    task_count: int
    task_counts_by_type: dict[str, int]
    source_count: int


def _reachable_transitions(fsm: FSM) -> list[Transition]:
    reachable = reachable_state_ids(fsm)
    return [transition for transition in fsm.transitions if transition.source in reachable]


def _transition_row(transition: Transition) -> dict[str, Any]:
    row: dict[str, Any] = {
        "id": transition.id,
        "source": transition.source,
        "event": transition.event,
        "target": transition.target,
    }
    if transition.guard is not None:
        row["guard"] = transition.guard
    if transition.action is not None:
        row["action"] = transition.action
    if transition.output is not None:
        row["output"] = transition.output
    return row


def _transition_signature(transition: Transition) -> tuple[str, str, str | None]:
    return (transition.source, transition.event, transition.guard)


def _predicted_output(transition: Transition, fsm: FSM) -> str | None:
    if transition.output is not None:
        return transition.output
    if transition.action is not None:
        return transition.action
    state_outputs = {
        state.id: state.state_output
        for state in fsm.states
        if state.state_output is not None
    }
    return state_outputs.get(transition.target)


def _has_output_signals(fsm: FSM) -> bool:
    if any(state.state_output for state in fsm.states):
        return True
    return any(
        transition.output is not None or transition.action is not None
        for transition in _reachable_transitions(fsm)
    )


def minimize_fsm(fsm: FSM) -> FSM:
    """Return a behaviour-preserving minimized FSM over the reachable subgraph."""
    reachable = reachable_state_ids(fsm)
    kept_states = [state for state in fsm.states if state.id in reachable]
    seen_signatures: set[tuple[str, str, str | None]] = set()
    kept_transitions: list[Transition] = []
    for transition in fsm.transitions:
        if transition.source not in reachable or transition.target not in reachable:
            continue
        signature = _transition_signature(transition)
        if signature in seen_signatures:
            continue
        seen_signatures.add(signature)
        kept_transitions.append(transition)
    return fsm.model_copy(
        update={
            "states": kept_states,
            "transitions": kept_transitions,
        }
    )


def unreachable_state_list(fsm: FSM) -> list[str]:
    """Return sorted state ids not reachable from the initial state."""
    reachable = reachable_state_ids(fsm)
    return sorted(state.id for state in fsm.states if state.id not in reachable)


def _build_messages(instruction: str) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": instruction},
    ]


def _task_a(source: FSMTaskSource) -> LLMEvaluationTask:
    fsm = source.reference
    transitions = _reachable_transitions(fsm)
    observations = [
        {
            "source": transition.source,
            "event": transition.event,
            "guard": transition.guard,
            "next_state": transition.target,
        }
        for transition in transitions
    ]
    instruction = (
        f"Infer the complete transition table for FSM '{fsm.id}'.\n"
        "You are given the state space, alphabet, initial state, and black-box observations.\n"
        "Return JSON with key 'transitions' containing one object per transition with fields "
        "id, source, event, target, and optional guard, action, output."
    )
    expected = {"transitions": [_transition_row(transition) for transition in transitions]}
    return LLMEvaluationTask(
        task_id=f"{fsm.id}__A__transition_table",
        task_type="A",
        task_name=TASK_TYPE_NAMES["A"],
        fsm_id=fsm.id,
        instruction=instruction,
        input={
            "fsm": {
                "id": fsm.id,
                "name": fsm.name,
                "description": fsm.description,
                "states": [state.model_dump(exclude_none=True) for state in fsm.states],
                "initial_state": fsm.initial_state,
                "events": list(fsm.events),
            },
            "observations": observations,
        },
        expected_output=expected,
        output_schema={
            "type": "object",
            "required": ["transitions"],
            "properties": {
                "transitions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["id", "source", "event", "target"],
                    },
                }
            },
        },
        messages=_build_messages(instruction),
        metadata={"transition_count": len(transitions), "source_id": source.source_id},
    )


def _tasks_b(source: FSMTaskSource) -> list[LLMEvaluationTask]:
    fsm = source.reference
    tasks: list[LLMEvaluationTask] = []
    for transition in _reachable_transitions(fsm):
        instruction = (
            f"Predict the next state after executing one step on FSM '{fsm.id}'.\n"
            f"Current state: {transition.source}\n"
            f"Event: {transition.event}\n"
            f"Guard: {transition.guard!r}\n"
            "Return JSON with key 'next_state'."
        )
        tasks.append(
            LLMEvaluationTask(
                task_id=f"{fsm.id}__B__{transition.id}",
                task_type="B",
                task_name=TASK_TYPE_NAMES["B"],
                fsm_id=fsm.id,
                instruction=instruction,
                input={
                    "fsm_summary": {
                        "id": fsm.id,
                        "initial_state": fsm.initial_state,
                        "states": [state.id for state in fsm.states],
                        "events": list(fsm.events),
                    },
                    "current_state": transition.source,
                    "event": transition.event,
                    "guard": transition.guard,
                },
                expected_output={"next_state": transition.target},
                output_schema={
                    "type": "object",
                    "required": ["next_state"],
                    "properties": {"next_state": {"type": "string"}},
                },
                messages=_build_messages(instruction),
                metadata={
                    "transition_id": transition.id,
                    "source_id": source.source_id,
                },
            )
        )
    return tasks


def _tasks_c(source: FSMTaskSource) -> list[LLMEvaluationTask]:
    fsm = source.reference
    if not _has_output_signals(fsm):
        return []

    tasks: list[LLMEvaluationTask] = []
    for transition in _reachable_transitions(fsm):
        predicted = _predicted_output(transition, fsm)
        if predicted is None:
            continue
        instruction = (
            f"Predict the output produced by FSM '{fsm.id}' on one transition step.\n"
            f"Current state: {transition.source}\n"
            f"Event: {transition.event}\n"
            f"Guard: {transition.guard!r}\n"
            "Return JSON with key 'output'."
        )
        tasks.append(
            LLMEvaluationTask(
                task_id=f"{fsm.id}__C__{transition.id}",
                task_type="C",
                task_name=TASK_TYPE_NAMES["C"],
                fsm_id=fsm.id,
                instruction=instruction,
                input={
                    "fsm_summary": {
                        "id": fsm.id,
                        "initial_state": fsm.initial_state,
                        "states": [
                            state.model_dump(exclude_none=True) for state in fsm.states
                        ],
                        "events": list(fsm.events),
                    },
                    "current_state": transition.source,
                    "event": transition.event,
                    "guard": transition.guard,
                },
                expected_output={"output": predicted},
                output_schema={
                    "type": "object",
                    "required": ["output"],
                    "properties": {"output": {"type": "string"}},
                },
                messages=_build_messages(instruction),
                metadata={
                    "transition_id": transition.id,
                    "source_id": source.source_id,
                },
            )
        )
    return tasks


def _task_d(source: FSMTaskSource, *, seed: int) -> LLMEvaluationTask | None:
    fsm = source.reference
    faulty = source.faulty
    bug_metadata = source.bug_metadata
    oracle = source.oracle

    if faulty is None or oracle is None:
        try:
            faulty, bug_metadata = mutate(fsm, "wrong_target", seed)
        except MutatorError:
            try:
                faulty, bug_metadata = mutate(fsm, "missing_transition", seed)
            except MutatorError:
                return None
        try:
            oracle = generate_oracle_suite(fsm, depth="medium").suite
        except OracleGeneratorError:
            return None

    assert faulty is not None
    assert bug_metadata is not None
    assert oracle is not None

    score = score_oracle_suite(faulty, oracle)
    instruction = (
        f"Repair the faulty FSM '{faulty.id}' so that it passes the behavioural oracle.\n"
        f"Mutation operator: {bug_metadata.mutation_operator}\n"
        f"Bug description: {bug_metadata.description}\n"
        f"Current BPR: {score.bpr:.4f}\n"
        "Return JSON with key 'fsm' containing the repaired FSM object."
    )
    return LLMEvaluationTask(
        task_id=f"{fsm.id}__D__{bug_metadata.mutation_operator}__{bug_metadata.seed}",
        task_type="D",
        task_name=TASK_TYPE_NAMES["D"],
        fsm_id=fsm.id,
        instruction=instruction,
        input={
            "reference_fsm_id": fsm.id,
            "faulty_fsm": faulty.model_dump(exclude_none=True),
            "oracle_suite": oracle.model_dump(exclude_none=True),
            "bug_metadata": bug_metadata.model_dump(exclude_none=True),
            "current_bpr": round(score.bpr, 6),
        },
        expected_output={"fsm": fsm.model_dump(exclude_none=True)},
        output_schema={
            "type": "object",
            "required": ["fsm"],
            "properties": {"fsm": {"type": "object"}},
        },
        messages=_build_messages(instruction),
        metadata={
            "mutation_operator": bug_metadata.mutation_operator,
            "seed": bug_metadata.seed,
            "source_id": source.source_id,
        },
    )


def _task_e(source: FSMTaskSource, *, depth: DepthLevel = "medium") -> LLMEvaluationTask | None:
    fsm = source.reference
    oracle = source.oracle
    if oracle is None:
        try:
            oracle = generate_oracle_suite(fsm, depth=depth).suite
        except OracleGeneratorError:
            return None

    instruction = (
        f"Generate a behavioural test suite for FSM '{fsm.id}'.\n"
        "Return JSON with key 'oracle_suite' matching the OracleSuite schema "
        "(id, fsm_id, scenarios with steps containing event, expected_state, optional guard)."
    )
    return LLMEvaluationTask(
        task_id=f"{fsm.id}__E__oracle_suite",
        task_type="E",
        task_name=TASK_TYPE_NAMES["E"],
        fsm_id=fsm.id,
        instruction=instruction,
        input={
            "fsm": fsm.model_dump(exclude_none=True),
            "requirements": {
                "minimum_transition_coverage": 1.0,
                "include_scenario_ids": True,
            },
        },
        expected_output={"oracle_suite": oracle.model_dump(exclude_none=True)},
        output_schema={
            "type": "object",
            "required": ["oracle_suite"],
            "properties": {"oracle_suite": {"type": "object"}},
        },
        messages=_build_messages(instruction),
        metadata={
            "scenario_count": len(oracle.scenarios),
            "source_id": source.source_id,
        },
    )


def _task_f(source: FSMTaskSource) -> LLMEvaluationTask:
    fsm = source.reference
    unreachable = unreachable_state_list(fsm)
    instruction = (
        f"Detect all unreachable states in FSM '{fsm.id}'.\n"
        "A state is unreachable when no path exists from the initial state.\n"
        "Return JSON with key 'unreachable_states' as a sorted list of state ids."
    )
    return LLMEvaluationTask(
        task_id=f"{fsm.id}__F__unreachable_states",
        task_type="F",
        task_name=TASK_TYPE_NAMES["F"],
        fsm_id=fsm.id,
        instruction=instruction,
        input={"fsm": fsm.model_dump(exclude_none=True)},
        expected_output={"unreachable_states": unreachable},
        output_schema={
            "type": "object",
            "required": ["unreachable_states"],
            "properties": {
                "unreachable_states": {
                    "type": "array",
                    "items": {"type": "string"},
                }
            },
        },
        messages=_build_messages(instruction),
        metadata={
            "unreachable_count": len(unreachable),
            "source_id": source.source_id,
        },
    )


def _task_g(source: FSMTaskSource) -> LLMEvaluationTask:
    fsm = source.reference
    minimized = minimize_fsm(fsm)
    instruction = (
        f"Minimize FSM '{fsm.id}' while preserving behaviour on the reachable subgraph.\n"
        "Remove unreachable states, unreachable transitions, and duplicate transitions "
        "with the same source, event, and guard.\n"
        "Return JSON with key 'fsm' containing the minimized FSM."
    )
    return LLMEvaluationTask(
        task_id=f"{fsm.id}__G__minimized",
        task_type="G",
        task_name=TASK_TYPE_NAMES["G"],
        fsm_id=fsm.id,
        instruction=instruction,
        input={"fsm": fsm.model_dump(exclude_none=True)},
        expected_output={"fsm": minimized.model_dump(exclude_none=True)},
        output_schema={
            "type": "object",
            "required": ["fsm"],
            "properties": {"fsm": {"type": "object"}},
        },
        messages=_build_messages(instruction),
        metadata={
            "original_state_count": len(fsm.states),
            "minimized_state_count": len(minimized.states),
            "original_transition_count": len(fsm.transitions),
            "minimized_transition_count": len(minimized.transitions),
            "source_id": source.source_id,
        },
    )


def generate_tasks_for_source(
    source: FSMTaskSource,
    *,
    task_types: Sequence[LLMTaskType] | None = None,
    seed: int = 42,
    oracle_depth: DepthLevel = "medium",
) -> list[LLMEvaluationTask]:
    """Generate evaluation tasks for one FSM source."""
    selected = tuple(task_types or SUPPORTED_LLM_TASK_TYPES)
    tasks: list[LLMEvaluationTask] = []

    if "A" in selected:
        tasks.append(_task_a(source))
    if "B" in selected:
        tasks.extend(_tasks_b(source))
    if "C" in selected:
        tasks.extend(_tasks_c(source))
    if "D" in selected:
        task_d = _task_d(source, seed=seed)
        if task_d is not None:
            tasks.append(task_d)
    if "E" in selected:
        task_e = _task_e(source, depth=oracle_depth)
        if task_e is not None:
            tasks.append(task_e)
    if "F" in selected:
        tasks.append(_task_f(source))
    if "G" in selected:
        tasks.append(_task_g(source))
    return tasks


def load_task_source_from_path(path: Path) -> FSMTaskSource:
    """Load one task source from an FSM JSON file or benchmark case directory."""
    if path.is_dir():
        reference_path = path / "reference_fsm.json"
        if reference_path.is_file():
            reference = load_fsm_json(reference_path)
            errors = validate_fsm(reference)
            if errors:
                msg = f"Invalid reference FSM in {path}: {errors[0]}"
                raise LLMEvaluationTaskError(msg)
            oracle = None
            oracle_path = path / "oracle_suite.json"
            if oracle_path.is_file():
                oracle = load_oracle_suite(oracle_path)
            faulty = None
            faulty_path = path / "faulty_fsm.json"
            if faulty_path.is_file():
                faulty = load_fsm_json(faulty_path)
            bug_metadata = None
            bug_path = path / "bug_metadata.json"
            if bug_path.is_file():
                bug_metadata = load_model(bug_path, BugMetadata)
            return FSMTaskSource(
                reference=reference,
                oracle=oracle,
                faulty=faulty,
                bug_metadata=bug_metadata,
                source_id=path.name,
            )
        json_files = sorted(path.glob("*.json"))
        if len(json_files) == 1:
            reference = load_fsm_json(json_files[0])
            errors = validate_fsm(reference)
            if errors:
                msg = f"Invalid FSM in {json_files[0]}: {errors[0]}"
                raise LLMEvaluationTaskError(msg)
            return FSMTaskSource(reference=reference, source_id=json_files[0].stem)
        msg = f"Expected benchmark case or single JSON file in directory: {path}"
        raise LLMEvaluationTaskError(msg)

    if path.suffix.lower() != ".json":
        msg = f"Unsupported task source path: {path}"
        raise LLMEvaluationTaskError(msg)
    reference = load_fsm_json(path)
    errors = validate_fsm(reference)
    if errors:
        msg = f"Invalid FSM in {path}: {errors[0]}"
        raise LLMEvaluationTaskError(msg)
    return FSMTaskSource(reference=reference, source_id=path.stem)


def discover_task_sources(root: Path) -> list[FSMTaskSource]:
    """Discover FSM task sources from a file, case directory, or dataset root."""
    if not root.exists():
        msg = f"Task source path not found: {root}"
        raise LLMEvaluationTaskError(msg)

    cases_root = root / "cases"
    if cases_root.is_dir():
        sources: list[FSMTaskSource] = []
        for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
            reference_path = case_dir / "reference_fsm.json"
            if not reference_path.is_file():
                continue
            sources.append(load_task_source_from_path(case_dir))
        if not sources:
            msg = f"No benchmark cases found under {cases_root}"
            raise LLMEvaluationTaskError(msg)
        return sources

    if root.is_dir():
        case_like = root / "reference_fsm.json"
        if case_like.is_file():
            return [load_task_source_from_path(root)]

        json_files = sorted(
            path
            for path in root.glob("*.json")
            if path.name
            not in {
                "metadata.json",
                "case_metadata.json",
                "bug_metadata.json",
                "oracle_suite.json",
                "requirements.json",
            }
        )
        if json_files:
            sources: list[FSMTaskSource] = []
            for json_path in json_files:
                try:
                    sources.append(load_task_source_from_path(json_path))
                except LLMEvaluationTaskError:
                    continue
            if sources:
                return sources

    return [load_task_source_from_path(root)]


def generate_llm_evaluation_tasks(
    source_root: Path,
    *,
    task_types: Sequence[LLMTaskType] | None = None,
    seed: int = 42,
    oracle_depth: DepthLevel = "medium",
) -> list[LLMEvaluationTask]:
    """Generate LLM evaluation tasks for every discovered FSM source."""
    sources = discover_task_sources(source_root)
    tasks: list[LLMEvaluationTask] = []
    for index, source in enumerate(sources):
        tasks.extend(
            generate_tasks_for_source(
                source,
                task_types=task_types,
                seed=seed + index * 1000,
                oracle_depth=oracle_depth,
            )
        )
    return tasks


def write_tasks_jsonl(path: Path, tasks: Iterable[LLMEvaluationTask]) -> int:
    """Write tasks to a JSON Lines file and return the number of records."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for task in tasks:
            handle.write(task.model_dump_json() + "\n")
            count += 1
    return count


def write_llm_evaluation_tasks(
    source_root: Path,
    output_path: Path,
    *,
    task_types: Sequence[LLMTaskType] | None = None,
    seed: int = 42,
    oracle_depth: DepthLevel = "medium",
) -> LLMTaskGenerationResult:
    """Generate tasks for every FSM and write them to JSONL."""
    sources = discover_task_sources(source_root)
    tasks = generate_llm_evaluation_tasks(
        source_root,
        task_types=task_types,
        seed=seed,
        oracle_depth=oracle_depth,
    )
    if not tasks:
        msg = "No LLM evaluation tasks were generated"
        raise LLMEvaluationTaskError(msg)

    task_count = write_tasks_jsonl(output_path, tasks)
    counts_by_type: dict[str, int] = {}
    for task in tasks:
        counts_by_type[task.task_type] = counts_by_type.get(task.task_type, 0) + 1

    manifest_path = output_path.with_name(output_path.stem + "_manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "source_root": str(source_root),
                "task_count": task_count,
                "task_counts_by_type": counts_by_type,
                "source_count": len(sources),
                "task_types": list(task_types or SUPPORTED_LLM_TASK_TYPES),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )

    return LLMTaskGenerationResult(
        output_path=output_path,
        task_count=task_count,
        task_counts_by_type=counts_by_type,
        source_count=len(sources),
    )
