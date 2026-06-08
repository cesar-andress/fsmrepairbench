"""Literature-inspired FSM mutation operators and mutant generation."""

from __future__ import annotations

import json
import random
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fsmrepairbench.generators.synthetic_factory import reachable_state_ids
from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.validators import load_fsm_json, validate_fsm

LiteratureMutationType = Literal[
    "state_deletion",
    "state_insertion",
    "transition_deletion",
    "transition_insertion",
    "transition_target_replacement",
    "transition_label_replacement",
    "guard_negation",
    "guard_weakening",
    "guard_strengthening",
    "output_mutation",
    "initial_state_mutation",
    "final_state_mutation",
]

LITERATURE_MUTATION_OPERATORS: tuple[LiteratureMutationType, ...] = (
    "state_deletion",
    "state_insertion",
    "transition_deletion",
    "transition_insertion",
    "transition_target_replacement",
    "transition_label_replacement",
    "guard_negation",
    "guard_weakening",
    "guard_strengthening",
    "output_mutation",
    "initial_state_mutation",
    "final_state_mutation",
)

MutationOrderClass = Literal["first_order", "second_order", "higher_order"]

DEFAULT_FIRST_ORDER_COUNT = 10
DEFAULT_SECOND_ORDER_COUNT = 10
DEFAULT_HIGHER_ORDER_COUNT = 10
HIGHER_ORDER_ARITY = 3


class LiteratureMutationError(ValueError):
    """Raised when a literature mutation operator cannot be applied."""


class MutantRecord(BaseModel):
    """Metadata for one generated mutant FSM."""

    mutant_id: str
    parent_id: str
    mutation_type: str
    mutation_description: str
    mutation_order: int = Field(ge=1)
    order_class: MutationOrderClass
    seed: int
    operators: list[str] = Field(default_factory=list)
    fsm: FSM | None = None


class MutantStatistics(BaseModel):
    """Aggregate statistics for a mutant generation run."""

    total_mutants: int
    first_order_count: int
    second_order_count: int
    higher_order_count: int
    by_mutation_type: dict[str, int] = Field(default_factory=dict)
    by_order_class: dict[str, int] = Field(default_factory=dict)
    by_operator: dict[str, int] = Field(default_factory=dict)


class MutantGenerationReport(BaseModel):
    """Full mutant generation output for one parent FSM."""

    parent_fsm_id: str
    generation_seed: int
    statistics: MutantStatistics
    mutants: list[MutantRecord]


MutationFn = Callable[[FSM, random.Random, int], tuple[FSM, str]]


def _pick_index(rng: random.Random, size: int) -> int:
    if size <= 0:
        msg = "Cannot pick from an empty collection"
        raise LiteratureMutationError(msg)
    return rng.randrange(size)


def _pick_other(rng: random.Random, options: list[str], current: str) -> str:
    alternatives = [option for option in options if option != current]
    if not alternatives:
        msg = f"No alternative value available besides {current!r}"
        raise LiteratureMutationError(msg)
    return rng.choice(alternatives)


def _state_ids(fsm: FSM) -> list[str]:
    return [state.id for state in fsm.states]


def _pick_transition(fsm: FSM, rng: random.Random) -> tuple[int, Transition]:
    index = _pick_index(rng, len(fsm.transitions))
    return index, fsm.transitions[index]


def _clone_mutant(parent: FSM, mutant_id: str, *, root_id: str) -> FSM:
    mutant = parent.model_copy(deep=True)
    mutant.id = mutant_id
    mutant.parent_fsm_id = root_id
    mutant.reference_fsm_id = root_id
    return mutant


def _mutant_id(root_id: str, order_class: MutationOrderClass, seed: int, operators: Sequence[str]) -> str:
    operator_tag = "__".join(operators)
    return f"{root_id}__mut__{order_class}__{operator_tag}__{seed}"


def _sink_state_ids(fsm: FSM) -> list[str]:
    reachable = reachable_state_ids(fsm)
    outgoing: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable:
            outgoing[transition.source] += 1
    sinks = [state_id for state_id in reachable if outgoing[state_id] == 0]
    if sinks:
        return sinks
    return [state.id for state in fsm.states if state.id in reachable]


def _mutate_state_deletion(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if len(fsm.states) < 2:
        raise LiteratureMutationError("state_deletion requires at least two states")
    candidates = [state.id for state in fsm.states if state.id != fsm.initial_state]
    if not candidates:
        raise LiteratureMutationError("state_deletion requires a non-initial state")
    deleted = rng.choice(candidates)
    states = [state for state in fsm.states if state.id != deleted]
    transitions = [
        transition
        for transition in fsm.transitions
        if transition.source != deleted and transition.target != deleted
    ]
    updated = fsm.model_copy(update={"states": states, "transitions": transitions})
    return updated, f"Deleted state '{deleted}' and incident transitions"


def _mutate_state_insertion(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    new_state_id = f"state_insert_{seed}"
    existing = set(_state_ids(fsm))
    suffix = 0
    while new_state_id in existing:
        suffix += 1
        new_state_id = f"state_insert_{seed}_{suffix}"
    source = rng.choice(_state_ids(fsm))
    event = rng.choice(fsm.events)
    states = [*fsm.states, State(id=new_state_id)]
    transition = Transition(
        id=f"t_insert_{seed}",
        source=source,
        event=event,
        target=new_state_id,
    )
    transitions = [*fsm.transitions, transition]
    updated = fsm.model_copy(update={"states": states, "transitions": transitions})
    return updated, f"Inserted state '{new_state_id}' with incoming transition from '{source}'"


def _mutate_transition_deletion(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.transitions:
        raise LiteratureMutationError("transition_deletion requires at least one transition")
    index, transition = _pick_transition(fsm, rng)
    transitions = [item for item_index, item in enumerate(fsm.transitions) if item_index != index]
    updated = fsm.model_copy(update={"transitions": transitions})
    return updated, f"Deleted transition '{transition.id}'"


def _mutate_transition_insertion(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.states or not fsm.events:
        raise LiteratureMutationError("transition_insertion requires states and events")
    source = rng.choice(_state_ids(fsm))
    target = rng.choice(_state_ids(fsm))
    event = rng.choice(fsm.events)
    transition = Transition(
        id=f"t_insert_{seed}",
        source=source,
        event=event,
        target=target,
        guard=None,
    )
    transitions = [*fsm.transitions, transition]
    updated = fsm.model_copy(update={"transitions": transitions})
    return updated, f"Inserted transition '{transition.id}' ({source} --{event}--> {target})"


def _mutate_transition_target_replacement(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.transitions:
        raise LiteratureMutationError("transition_target_replacement requires transitions")
    index, transition = _pick_transition(fsm, rng)
    new_target = _pick_other(rng, _state_ids(fsm), transition.target)
    transitions = list(fsm.transitions)
    transitions[index] = transition.model_copy(update={"target": new_target})
    updated = fsm.model_copy(update={"transitions": transitions})
    return (
        updated,
        f"Replaced target of transition '{transition.id}' from '{transition.target}' to '{new_target}'",
    )


def _mutate_transition_label_replacement(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.transitions or len(fsm.events) < 2:
        raise LiteratureMutationError("transition_label_replacement requires transitions and >=2 events")
    index, transition = _pick_transition(fsm, rng)
    new_event = _pick_other(rng, list(fsm.events), transition.event)
    transitions = list(fsm.transitions)
    transitions[index] = transition.model_copy(update={"event": new_event})
    updated = fsm.model_copy(update={"transitions": transitions})
    return (
        updated,
        f"Replaced label of transition '{transition.id}' from '{transition.event}' to '{new_event}'",
    )


def _mutate_guard_negation(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.transitions:
        raise LiteratureMutationError("guard_negation requires transitions")
    index, transition = _pick_transition(fsm, rng)
    if transition.guard is None:
        new_guard = "false"
        description = f"Added negated guard '{new_guard}' to transition '{transition.id}'"
    else:
        new_guard = f"not ({transition.guard})"
        description = f"Negated guard on transition '{transition.id}' to '{new_guard}'"
    transitions = list(fsm.transitions)
    transitions[index] = transition.model_copy(update={"guard": new_guard})
    return fsm.model_copy(update={"transitions": transitions}), description


def _mutate_guard_weakening(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.transitions:
        raise LiteratureMutationError("guard_weakening requires transitions")
    index, transition = _pick_transition(fsm, rng)
    transitions = list(fsm.transitions)
    transitions[index] = transition.model_copy(update={"guard": "true"})
    return (
        fsm.model_copy(update={"transitions": transitions}),
        f"Weakened guard on transition '{transition.id}' to 'true'",
    )


def _mutate_guard_strengthening(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if not fsm.transitions:
        raise LiteratureMutationError("guard_strengthening requires transitions")
    index, transition = _pick_transition(fsm, rng)
    base_guard = transition.guard or "cond"
    new_guard = f"({base_guard}) and strict_check_{seed}"
    transitions = list(fsm.transitions)
    transitions[index] = transition.model_copy(update={"guard": new_guard})
    return (
        fsm.model_copy(update={"transitions": transitions}),
        f"Strengthened guard on transition '{transition.id}'",
    )


def _mutate_output_mutation(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if fsm.transitions:
        index, transition = _pick_transition(fsm, rng)
        if transition.output is not None:
            new_output = f"mutated_output_{seed}"
            transitions = list(fsm.transitions)
            transitions[index] = transition.model_copy(update={"output": new_output})
            return (
                fsm.model_copy(update={"transitions": transitions}),
                f"Mutated Mealy output on transition '{transition.id}' to '{new_output}'",
            )
        if transition.action is not None:
            new_action = f"mutated_action_{seed}"
            transitions = list(fsm.transitions)
            transitions[index] = transition.model_copy(update={"action": new_action})
            return (
                fsm.model_copy(update={"transitions": transitions}),
                f"Mutated action output on transition '{transition.id}' to '{new_action}'",
            )
        transitions = list(fsm.transitions)
        transitions[index] = transition.model_copy(update={"output": f"output_{seed}"})
        return (
            fsm.model_copy(update={"transitions": transitions}),
            f"Added output '{f'output_{seed}'}' to transition '{transition.id}'",
        )

    if fsm.states:
        state_index = _pick_index(rng, len(fsm.states))
        state = fsm.states[state_index]
        new_output = f"state_output_{seed}"
        states = list(fsm.states)
        states[state_index] = state.model_copy(update={"state_output": new_output})
        return (
            fsm.model_copy(update={"states": states}),
            f"Mutated Moore output on state '{state.id}' to '{new_output}'",
        )

    raise LiteratureMutationError("output_mutation requires states or transitions")


def _mutate_initial_state_mutation(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    if len(fsm.states) < 2:
        raise LiteratureMutationError("initial_state_mutation requires at least two states")
    new_initial = _pick_other(rng, _state_ids(fsm), fsm.initial_state)
    updated = fsm.model_copy(update={"initial_state": new_initial})
    return updated, f"Changed initial state from '{fsm.initial_state}' to '{new_initial}'"


def _mutate_final_state_mutation(fsm: FSM, rng: random.Random, seed: int) -> tuple[FSM, str]:
    sinks = _sink_state_ids(fsm)
    final_state = rng.choice(sinks)
    event = rng.choice(fsm.events) if fsm.events else f"final_event_{seed}"
    transition = Transition(
        id=f"t_final_mut_{seed}",
        source=final_state,
        event=event,
        target=final_state,
    )
    transitions = [*fsm.transitions, transition]
    updated = fsm.model_copy(update={"transitions": transitions})
    return (
        updated,
        f"Added unexpected self-loop on final/sink state '{final_state}' via event '{event}'",
    )


_OPERATOR_IMPL: dict[LiteratureMutationType, MutationFn] = {
    "state_deletion": _mutate_state_deletion,
    "state_insertion": _mutate_state_insertion,
    "transition_deletion": _mutate_transition_deletion,
    "transition_insertion": _mutate_transition_insertion,
    "transition_target_replacement": _mutate_transition_target_replacement,
    "transition_label_replacement": _mutate_transition_label_replacement,
    "guard_negation": _mutate_guard_negation,
    "guard_weakening": _mutate_guard_weakening,
    "guard_strengthening": _mutate_guard_strengthening,
    "output_mutation": _mutate_output_mutation,
    "initial_state_mutation": _mutate_initial_state_mutation,
    "final_state_mutation": _mutate_final_state_mutation,
}


def apply_literature_operator(
    fsm: FSM,
    operator: LiteratureMutationType,
    *,
    seed: int,
) -> tuple[FSM, str]:
    """Apply one literature mutation operator to *fsm*."""
    if operator not in _OPERATOR_IMPL:
        msg = f"Unknown literature mutation operator '{operator}'"
        raise LiteratureMutationError(msg)
    rng = random.Random(seed)
    mutated, description = _OPERATOR_IMPL[operator](fsm, rng, seed)
    errors = validate_fsm(mutated, allow_nondeterminism=True)
    if errors:
        raise LiteratureMutationError(errors[0])
    return mutated, description


def apply_literature_operator_chain(
    fsm: FSM,
    operators: Sequence[LiteratureMutationType],
    *,
    base_seed: int,
) -> tuple[FSM, list[str], list[str]]:
    """Apply *operators* sequentially, returning descriptions for each step."""
    if not operators:
        msg = "At least one operator is required"
        raise LiteratureMutationError(msg)

    current = fsm.model_copy(deep=True)
    descriptions: list[str] = []
    applied: list[str] = []
    for step_index, operator in enumerate(operators):
        step_seed = base_seed + step_index * 997
        current, description = apply_literature_operator(current, operator, seed=step_seed)
        applied.append(operator)
        descriptions.append(description)
    return current, applied, descriptions


def _operator_schedule(index: int, arity: int, base_seed: int) -> list[LiteratureMutationType]:
    operators = list(LITERATURE_MUTATION_OPERATORS)
    rng = random.Random(base_seed + index * 17 + arity * 131)
    chosen: list[LiteratureMutationType] = []
    for offset in range(arity):
        operator = operators[(index + offset) % len(operators)]
        if arity > 1 and offset > 0 and operator == chosen[-1]:
            operator = operators[(index + offset + 1) % len(operators)]
        chosen.append(operator)
    if len(set(chosen)) < arity:
        shuffled = operators[:]
        rng.shuffle(shuffled)
        chosen = shuffled[:arity]
    return chosen


def _try_generate_mutant(
    parent: FSM,
    *,
    root_id: str,
    order_class: MutationOrderClass,
    mutation_order: int,
    operators: Sequence[LiteratureMutationType],
    seed: int,
    include_fsm: bool,
) -> MutantRecord | None:
    try:
        if len(operators) == 1:
            mutated, description = apply_literature_operator(parent, operators[0], seed=seed)
            mutation_type = operators[0]
        else:
            mutated, applied, descriptions = apply_literature_operator_chain(
                parent,
                operators,
                base_seed=seed,
            )
            mutation_type = ", ".join(applied)
            description = "; ".join(descriptions)
            operators = applied
        mutant_id = _mutant_id(root_id, order_class, seed, operators)
        mutated = _clone_mutant(mutated, mutant_id, root_id=root_id)
        return MutantRecord(
            mutant_id=mutant_id,
            parent_id=root_id,
            mutation_type=mutation_type,
            mutation_description=description,
            mutation_order=mutation_order,
            order_class=order_class,
            seed=seed,
            operators=list(operators),
            fsm=mutated if include_fsm else None,
        )
    except LiteratureMutationError:
        return None


def _generate_mutants_of_order(
    parent: FSM,
    *,
    root_id: str,
    order_class: MutationOrderClass,
    mutation_order: int,
    count: int,
    base_seed: int,
    include_fsm: bool,
) -> list[MutantRecord]:
    mutants: list[MutantRecord] = []
    attempt = 0
    while len(mutants) < count and attempt < count * 20:
        operators = _operator_schedule(len(mutants) + attempt, mutation_order, base_seed + attempt)
        seed = base_seed + len(mutants) * 1009 + attempt
        record = _try_generate_mutant(
            parent,
            root_id=root_id,
            order_class=order_class,
            mutation_order=mutation_order,
            operators=operators,
            seed=seed,
            include_fsm=include_fsm,
        )
        attempt += 1
        if record is None:
            continue
        if any(existing.mutant_id == record.mutant_id for existing in mutants):
            continue
        mutants.append(record)
    if len(mutants) < count:
        msg = (
            f"Generated only {len(mutants)} {order_class} mutants for '{root_id}' "
            f"(requested {count})"
        )
        raise LiteratureMutationError(msg)
    return mutants


def compute_mutant_statistics(mutants: Sequence[MutantRecord]) -> MutantStatistics:
    """Compute aggregate statistics over generated mutants."""
    by_mutation_type: Counter[str] = Counter()
    by_order_class: Counter[str] = Counter()
    by_operator: Counter[str] = Counter()

    for mutant in mutants:
        by_order_class[mutant.order_class] += 1
        for operator in mutant.operators:
            by_operator[operator] += 1
        if len(mutant.operators) == 1:
            by_mutation_type[mutant.mutation_type] += 1
        else:
            by_mutation_type[mutant.mutation_type] += 1

    return MutantStatistics(
        total_mutants=len(mutants),
        first_order_count=by_order_class.get("first_order", 0),
        second_order_count=by_order_class.get("second_order", 0),
        higher_order_count=by_order_class.get("higher_order", 0),
        by_mutation_type=dict(sorted(by_mutation_type.items())),
        by_order_class=dict(sorted(by_order_class.items())),
        by_operator=dict(sorted(by_operator.items())),
    )


def generate_literature_mutants(
    parent: FSM,
    *,
    seed: int = 42,
    first_order_count: int = DEFAULT_FIRST_ORDER_COUNT,
    second_order_count: int = DEFAULT_SECOND_ORDER_COUNT,
    higher_order_count: int = DEFAULT_HIGHER_ORDER_COUNT,
    include_fsm: bool = True,
) -> MutantGenerationReport:
    """Generate first-, second-, and higher-order mutants for *parent*."""
    root_id = parent.id
    first_order = _generate_mutants_of_order(
        parent,
        root_id=root_id,
        order_class="first_order",
        mutation_order=1,
        count=first_order_count,
        base_seed=seed,
        include_fsm=include_fsm,
    )
    second_order = _generate_mutants_of_order(
        parent,
        root_id=root_id,
        order_class="second_order",
        mutation_order=2,
        count=second_order_count,
        base_seed=seed + 10_000,
        include_fsm=include_fsm,
    )
    higher_order = _generate_mutants_of_order(
        parent,
        root_id=root_id,
        order_class="higher_order",
        mutation_order=HIGHER_ORDER_ARITY,
        count=higher_order_count,
        base_seed=seed + 20_000,
        include_fsm=include_fsm,
    )
    mutants = [*first_order, *second_order, *higher_order]
    return MutantGenerationReport(
        parent_fsm_id=root_id,
        generation_seed=seed,
        statistics=compute_mutant_statistics(mutants),
        mutants=mutants,
    )


def report_to_dict(report: MutantGenerationReport, *, include_fsm: bool = True) -> dict[str, object]:
    """Convert a generation report to a JSON-serialisable mapping."""
    return {
        "parent_fsm_id": report.parent_fsm_id,
        "generation_seed": report.generation_seed,
        "statistics": report.statistics.model_dump(),
        "mutants": [
            {
                "mutant_id": mutant.mutant_id,
                "parent_id": mutant.parent_id,
                "mutation_type": mutant.mutation_type,
                "mutation_description": mutant.mutation_description,
                "mutation_order": mutant.mutation_order,
                "order_class": mutant.order_class,
                "seed": mutant.seed,
                "operators": mutant.operators,
                **(
                    {"fsm": mutant.fsm.model_dump(mode="json")}
                    if include_fsm and mutant.fsm is not None
                    else {}
                ),
            }
            for mutant in report.mutants
        ],
    }


def write_mutant_report_json(path: Path, report: MutantGenerationReport, *, include_fsm: bool = True) -> None:
    """Write a mutant generation report to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report_to_dict(report, include_fsm=include_fsm), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def generate_literature_mutants_for_path(
    fsm_path: Path,
    *,
    seed: int = 42,
    include_fsm: bool = True,
) -> MutantGenerationReport:
    """Load an FSM from disk and generate literature mutants."""
    parent = load_fsm_json(fsm_path)
    return generate_literature_mutants(parent, seed=seed, include_fsm=include_fsm)


@dataclass(frozen=True)
class BatchMutantGenerationSummary:
    """Aggregate statistics across multiple parent FSMs."""

    fsm_count: int
    total_mutants: int
    first_order_count: int
    second_order_count: int
    higher_order_count: int
    by_mutation_type: dict[str, int]
    by_operator: dict[str, int]
    output_files: tuple[str, ...]


def generate_literature_mutants_for_directory(
    input_dir: Path,
    output_dir: Path,
    *,
    seed: int = 42,
    include_fsm: bool = True,
) -> BatchMutantGenerationSummary:
    """Generate literature mutants for every ``fsm_*.json`` file in *input_dir*."""
    fsm_paths = sorted(input_dir.glob("fsm_*.json"))
    if not fsm_paths:
        msg = f"No fsm_*.json files found in {input_dir}"
        raise LiteratureMutationError(msg)

    output_dir.mkdir(parents=True, exist_ok=True)
    output_files: list[str] = []
    total_mutants = 0
    first_order_total = 0
    second_order_total = 0
    higher_order_total = 0
    by_mutation_type: Counter[str] = Counter()
    by_operator: Counter[str] = Counter()

    for index, fsm_path in enumerate(fsm_paths, start=1):
        report = generate_literature_mutants_for_path(
            fsm_path,
            seed=seed + index * 10_000,
            include_fsm=include_fsm,
        )
        out_path = output_dir / f"{fsm_path.stem}_mutants.json"
        write_mutant_report_json(out_path, report, include_fsm=include_fsm)
        output_files.append(out_path.name)
        total_mutants += report.statistics.total_mutants
        first_order_total += report.statistics.first_order_count
        second_order_total += report.statistics.second_order_count
        higher_order_total += report.statistics.higher_order_count
        by_mutation_type.update(report.statistics.by_mutation_type)
        by_operator.update(report.statistics.by_operator)

    summary = BatchMutantGenerationSummary(
        fsm_count=len(fsm_paths),
        total_mutants=total_mutants,
        first_order_count=first_order_total,
        second_order_count=second_order_total,
        higher_order_count=higher_order_total,
        by_mutation_type=dict(sorted(by_mutation_type.items())),
        by_operator=dict(sorted(by_operator.items())),
        output_files=tuple(output_files),
    )
    summary_path = output_dir / "statistics.json"
    summary_path.write_text(
        json.dumps(
            {
                "fsm_count": summary.fsm_count,
                "generation_seed": seed,
                "total_mutants": summary.total_mutants,
                "first_order_count": summary.first_order_count,
                "second_order_count": summary.second_order_count,
                "higher_order_count": summary.higher_order_count,
                "by_mutation_type": summary.by_mutation_type,
                "by_operator": summary.by_operator,
                "output_files": list(summary.output_files),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return summary
