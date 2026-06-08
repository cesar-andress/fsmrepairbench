"""Selective mutation planning for large-scale benchmark generation."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.difficulty import estimate_difficulty
from fsmrepairbench.models import FSM, Transition
from fsmrepairbench.mutators import BENCHMARK_MUTATION_OPERATORS, MUTATION_OPERATORS
from fsmrepairbench.oracle_generator import reachable_state_ids

MutationStrategy = Literal[
    "all",
    "balanced_by_operator",
    "random_sample",
    "cost_aware",
    "coverage_aware",
    "difficulty_aware",
]

SUPPORTED_STRATEGIES: tuple[MutationStrategy, ...] = (
    "all",
    "balanced_by_operator",
    "random_sample",
    "cost_aware",
    "coverage_aware",
    "difficulty_aware",
)

TRANSITION_OPERATORS: frozenset[str] = frozenset(
    {
        "missing_transition",
        "wrong_target",
        "wrong_source",
        "wrong_event",
        "duplicate_transition",
        "guard_flip",
        "guard_weaken",
        "guard_strengthen",
        "action_corruption",
        "timeout_corruption",
        "delay_corruption",
        "nondeterminism_intro",
        "guard_inter_class",
        "timed_selective_mutation",
    }
)

STATE_OPERATORS: frozenset[str] = frozenset(
    {
        "wrong_initial_state",
        "dead_state_intro",
    }
)

FSM_OPERATORS: frozenset[str] = frozenset(
    {
        "unreachable_state_intro",
        "variable_intra_class",
        "action_full_mutation",
    }
)

OPERATOR_COSTS: dict[str, float] = {
    "missing_transition": 1.0,
    "wrong_target": 1.0,
    "wrong_source": 1.0,
    "wrong_event": 1.0,
    "wrong_initial_state": 1.0,
    "duplicate_transition": 1.5,
    "dead_state_intro": 2.0,
    "guard_flip": 1.5,
    "guard_weaken": 1.5,
    "guard_strengthen": 1.5,
    "action_corruption": 1.5,
    "timeout_corruption": 2.0,
    "delay_corruption": 2.0,
    "nondeterminism_intro": 2.5,
    "unreachable_state_intro": 2.0,
    "variable_intra_class": 2.5,
    "guard_inter_class": 3.0,
    "action_full_mutation": 4.0,
    "timed_selective_mutation": 2.5,
}


class SelectiveMutationError(ValueError):
    """Raised when selective mutation planning fails."""


@dataclass(frozen=True)
class MutationLocation:
    """A mutable location within an FSM."""

    location_type: str
    location_id: str

    def key(self) -> tuple[str, str]:
        return (self.location_type, self.location_id)


@dataclass(frozen=True)
class PlannedMutation:
    """One planned first-order mutation."""

    operator: str
    location: MutationLocation

    def to_dict(self) -> dict[str, str]:
        return {
            "operator": self.operator,
            "location_type": self.location.location_type,
            "location_id": self.location.location_id,
        }


@dataclass(frozen=True)
class MutationPlan:
    """Selective mutation plan for an FSM."""

    fsm_id: str
    strategy: MutationStrategy
    budget: int
    selected_operators: tuple[str, ...]
    selected_locations: tuple[MutationLocation, ...]
    planned_mutations: tuple[PlannedMutation, ...]
    expected_cost: float
    expected_diversity: float
    rationale: str


def _reachable_transitions(fsm: FSM) -> list[Transition]:
    reachable = reachable_state_ids(fsm)
    return [transition for transition in fsm.transitions if transition.source in reachable]


def _guarded_transitions(fsm: FSM) -> list[Transition]:
    return [
        transition
        for transition in _reachable_transitions(fsm)
        if transition.guard is not None and transition.guard.strip()
    ]


def _timed_transitions(fsm: FSM) -> list[Transition]:
    return [
        transition
        for transition in _reachable_transitions(fsm)
        if transition.timeout is not None or transition.delay is not None
    ]


def _operator_applicable(fsm: FSM, operator: str) -> bool:
    transitions = _reachable_transitions(fsm)
    if operator in TRANSITION_OPERATORS:
        if operator == "guard_inter_class":
            return len(_guarded_transitions(fsm)) >= 2
        if operator == "timed_selective_mutation":
            return bool(_timed_transitions(fsm))
        return bool(transitions)
    if operator in STATE_OPERATORS:
        return len(fsm.states) >= 2
    if operator == "variable_intra_class":
        return bool(fsm.variables)
    if operator in FSM_OPERATORS:
        return True
    return operator in MUTATION_OPERATORS


def _locations_for_operator(fsm: FSM, operator: str) -> list[MutationLocation]:
    if operator in TRANSITION_OPERATORS:
        if operator == "guard_inter_class":
            return [
                MutationLocation("transition", transition.id)
                for transition in _guarded_transitions(fsm)
            ]
        if operator == "timed_selective_mutation":
            return [
                MutationLocation("transition", transition.id)
                for transition in _timed_transitions(fsm)
            ]
        return [
            MutationLocation("transition", transition.id)
            for transition in _reachable_transitions(fsm)
        ]
    if operator in STATE_OPERATORS:
        return [MutationLocation("state", state.id) for state in fsm.states]
    return [MutationLocation("fsm", fsm.id)]


def enumerate_candidates(
    fsm: FSM,
    *,
    operators: Sequence[str] | None = None,
) -> list[PlannedMutation]:
    """Enumerate feasible operator/location mutation candidates for *fsm*."""
    operator_list = list(operators or BENCHMARK_MUTATION_OPERATORS)
    candidates: list[PlannedMutation] = []
    for operator in operator_list:
        if operator not in MUTATION_OPERATORS:
            continue
        if not _operator_applicable(fsm, operator):
            continue
        for location in _locations_for_operator(fsm, operator):
            candidates.append(PlannedMutation(operator=operator, location=location))
    if not candidates:
        msg = f"No applicable mutation candidates found for FSM '{fsm.id}'"
        raise SelectiveMutationError(msg)
    return candidates


def _operator_cost(operator: str) -> float:
    return OPERATOR_COSTS.get(operator, 2.0)


def _location_weight(fsm: FSM, mutation: PlannedMutation) -> float:
    if mutation.location.location_type == "transition":
        transition = next(
            (item for item in fsm.transitions if item.id == mutation.location.location_id),
            None,
        )
        if transition is None:
            return 1.0
        weight = 1.0
        if transition.guard:
            weight += 0.5
        if transition.action:
            weight += 0.25
        if transition.timeout is not None or transition.delay is not None:
            weight += 0.75
        return weight
    if mutation.location.location_type == "state":
        return 1.0
    return 0.5


def _compute_diversity(mutations: Sequence[PlannedMutation], budget: int) -> float:
    if not mutations or budget <= 0:
        return 0.0
    operator_entropy = _entropy({mutation.operator for mutation in mutations})
    location_entropy = _entropy(
        {f"{mutation.location.location_type}:{mutation.location.location_id}" for mutation in mutations}
    )
    coverage_ratio = len(mutations) / budget
    return min(1.0, (operator_entropy + location_entropy) / 2.0 * coverage_ratio)


def _entropy(values: Iterable[str]) -> float:
    items = list(values)
    if not items:
        return 0.0
    counts: dict[str, int] = {}
    for item in items:
        counts[item] = counts.get(item, 0) + 1
    total = len(items)
    return -sum((count / total) * math.log2(count / total) for count in counts.values())


def _total_cost(mutations: Sequence[PlannedMutation]) -> float:
    return sum(_operator_cost(mutation.operator) for mutation in mutations)


def _finalize_plan(
    fsm: FSM,
    *,
    strategy: MutationStrategy,
    budget: int,
    selected: list[PlannedMutation],
    rationale: str,
) -> MutationPlan:
    if budget <= 0:
        msg = "budget must be greater than zero"
        raise SelectiveMutationError(msg)
    selected = selected[:budget]
    operators = tuple(dict.fromkeys(mutation.operator for mutation in selected))
    locations = tuple(dict.fromkeys(mutation.location for mutation in selected))
    return MutationPlan(
        fsm_id=fsm.id,
        strategy=strategy,
        budget=budget,
        selected_operators=operators,
        selected_locations=locations,
        planned_mutations=tuple(selected),
        expected_cost=_total_cost(selected),
        expected_diversity=_compute_diversity(selected, budget),
        rationale=rationale,
    )


def _select_all(fsm: FSM, budget: int) -> MutationPlan:
    candidates = enumerate_candidates(fsm)
    rationale = (
        f"Selected {min(len(candidates), budget)} of {len(candidates)} feasible candidates "
        "using exhaustive enumeration."
    )
    return _finalize_plan(
        fsm,
        strategy="all",
        budget=budget,
        selected=candidates,
        rationale=rationale,
    )


def _select_balanced_by_operator(fsm: FSM, budget: int) -> MutationPlan:
    candidates = enumerate_candidates(fsm)
    by_operator: dict[str, list[PlannedMutation]] = {}
    for candidate in candidates:
        by_operator.setdefault(candidate.operator, []).append(candidate)

    selected: list[PlannedMutation] = []
    operators = sorted(by_operator)
    while len(selected) < budget and operators:
        next_operators: list[str] = []
        for operator in operators:
            pool = by_operator[operator]
            if not pool:
                continue
            selected.append(pool.pop(0))
            if len(selected) >= budget:
                break
            if pool:
                next_operators.append(operator)
        operators = next_operators

    rationale = "Round-robin selection across applicable operators for balanced coverage."
    return _finalize_plan(
        fsm,
        strategy="balanced_by_operator",
        budget=budget,
        selected=selected,
        rationale=rationale,
    )


def _select_random_sample(fsm: FSM, budget: int, seed: int) -> MutationPlan:
    candidates = enumerate_candidates(fsm)
    rng = random.Random(seed)
    if len(candidates) <= budget:
        selected = list(candidates)
    else:
        selected = rng.sample(candidates, budget)
    rationale = f"Random sample of {len(selected)} candidates using seed={seed}."
    return _finalize_plan(
        fsm,
        strategy="random_sample",
        budget=budget,
        selected=selected,
        rationale=rationale,
    )


def _select_cost_aware(fsm: FSM, budget: int) -> MutationPlan:
    candidates = enumerate_candidates(fsm)
    ranked = sorted(
        candidates,
        key=lambda mutation: (_operator_cost(mutation.operator), mutation.operator, mutation.location.location_id),
    )
    selected: list[PlannedMutation] = []
    seen: set[tuple[str, tuple[str, str]]] = set()
    for candidate in ranked:
        key = (candidate.operator, candidate.location.key())
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= budget:
            break
    rationale = "Prefer lower-cost mutation operators before expensive structural mutations."
    return _finalize_plan(
        fsm,
        strategy="cost_aware",
        budget=budget,
        selected=selected,
        rationale=rationale,
    )


def _select_coverage_aware(fsm: FSM, budget: int) -> MutationPlan:
    candidates = enumerate_candidates(fsm)
    selected: list[PlannedMutation] = []
    covered_transitions: set[str] = set()
    covered_states: set[str] = set()

    def gain(candidate: PlannedMutation) -> float:
        score = 0.0
        if candidate.location.location_type == "transition":
            if candidate.location.location_id not in covered_transitions:
                score += 2.0
            score += _location_weight(fsm, candidate)
        elif candidate.location.location_type == "state":
            if candidate.location.location_id not in covered_states:
                score += 1.5
        else:
            score += 0.5
        score += 1.0 / _operator_cost(candidate.operator)
        return score

    remaining = candidates[:]
    while len(selected) < budget and remaining:
        remaining.sort(
            key=lambda mutation: (-gain(mutation), mutation.operator, mutation.location.location_id)
        )
        best = remaining.pop(0)
        selected.append(best)
        if best.location.location_type == "transition":
            covered_transitions.add(best.location.location_id)
        elif best.location.location_type == "state":
            covered_states.add(best.location.location_id)

    rationale = (
        "Greedy selection maximizing transition/state coverage and operator diversity "
        "without generating every possible mutant."
    )
    return _finalize_plan(
        fsm,
        strategy="coverage_aware",
        budget=budget,
        selected=selected,
        rationale=rationale,
    )


def _select_difficulty_aware(fsm: FSM, budget: int) -> MutationPlan:
    estimate = estimate_difficulty(fsm)
    difficulty_factor = estimate.difficulty_score / 100.0
    candidates = enumerate_candidates(fsm)
    ranked = sorted(
        candidates,
        key=lambda mutation: (
            -(_location_weight(fsm, mutation) * (1.0 + difficulty_factor)),
            _operator_cost(mutation.operator),
            mutation.operator,
            mutation.location.location_id,
        ),
    )
    selected: list[PlannedMutation] = []
    seen: set[tuple[str, tuple[str, str]]] = set()
    for candidate in ranked:
        key = (candidate.operator, candidate.location.key())
        if key in seen:
            continue
        seen.add(key)
        selected.append(candidate)
        if len(selected) >= budget:
            break
    rationale = (
        f"Prioritized structurally rich locations using difficulty score "
        f"{estimate.difficulty_score:.2f} ({estimate.category})."
    )
    return _finalize_plan(
        fsm,
        strategy="difficulty_aware",
        budget=budget,
        selected=selected,
        rationale=rationale,
    )


STRATEGY_IMPL: dict[MutationStrategy, Callable[..., MutationPlan]] = {
    "all": _select_all,
    "balanced_by_operator": _select_balanced_by_operator,
    "random_sample": _select_random_sample,
    "cost_aware": _select_cost_aware,
    "coverage_aware": _select_coverage_aware,
    "difficulty_aware": _select_difficulty_aware,
}


def plan_mutations(
    fsm: FSM,
    *,
    strategy: MutationStrategy = "coverage_aware",
    budget: int = 100,
    seed: int = 42,
) -> MutationPlan:
    """Build a selective mutation plan for *fsm*."""
    if strategy not in STRATEGY_IMPL:
        msg = f"Unknown strategy '{strategy}'. Supported: {', '.join(SUPPORTED_STRATEGIES)}"
        raise SelectiveMutationError(msg)

    if strategy == "random_sample":
        return _select_random_sample(fsm, budget, seed)
    return STRATEGY_IMPL[strategy](fsm, budget)


def mutation_plan_to_dict(plan: MutationPlan) -> dict[str, object]:
    """Convert a mutation plan to a JSON-serialisable mapping."""
    return {
        "fsm_id": plan.fsm_id,
        "strategy": plan.strategy,
        "budget": plan.budget,
        "selected_operators": list(plan.selected_operators),
        "selected_locations": [
            {
                "location_type": location.location_type,
                "location_id": location.location_id,
            }
            for location in plan.selected_locations
        ],
        "planned_mutations": [mutation.to_dict() for mutation in plan.planned_mutations],
        "expected_cost": plan.expected_cost,
        "expected_diversity": plan.expected_diversity,
        "rationale": plan.rationale,
    }


def write_mutation_plan_json(path: Path, plan: MutationPlan) -> None:
    """Write *plan* as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(mutation_plan_to_dict(plan), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
