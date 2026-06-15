"""Non-LLM baseline repair engines."""

from __future__ import annotations

import random
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from fsmrepairbench.models import FSM, OracleScenario, OracleStep, OracleSuite
from fsmrepairbench.oracle import _find_transition
from fsmrepairbench.patch import (
    AddTransitionOperation,
    FSMPatch,
    PatchOperation,
    ReplaceActionOperation,
    ReplaceGuardOperation,
    ReplaceInitialStateOperation,
    ReplaceTransitionEventOperation,
    ReplaceTransitionSourceOperation,
    ReplaceTransitionTargetOperation,
    apply_patch,
    validate_patch,
)
from fsmrepairbench.scorer import score_oracle_suite

BASELINE_ENGINE_NAMES: tuple[str, ...] = (
    "missing-transition",
    "wrong-target",
    "random",
    "search-bpr",
    "oracle-composite",
    "llm-template",
)


class BaselineEngineError(ValueError):
    """Raised when a baseline engine cannot be resolved or used."""


class BaselineRepairEngine(Protocol):
    """Protocol for baseline repair engines."""

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch: ...


@dataclass(frozen=True)
class OracleFailure:
    """A single oracle step failure with repair context."""

    scenario_id: str
    step_index: int
    current_state: str
    step: OracleStep
    failure_reason: str
    transition_id: str | None = None


def _state_ids(fsm: FSM) -> list[str]:
    return [state.id for state in fsm.states]


def _transition_ids(fsm: FSM) -> set[str]:
    return {transition.id for transition in fsm.transitions}


def _analyze_scenario_failures(
    fsm: FSM,
    scenario: OracleScenario,
) -> list[OracleFailure]:
    failures: list[OracleFailure] = []
    current_state = fsm.initial_state

    for step_index, step in enumerate(scenario.steps):
        transition = _find_transition(fsm, current_state, step)
        if transition is None:
            failures.append(
                OracleFailure(
                    scenario_id=scenario.id,
                    step_index=step_index,
                    current_state=current_state,
                    step=step,
                    failure_reason="no_matching_transition",
                )
            )
            break

        next_state = transition.target
        if next_state != step.expected_state:
            failures.append(
                OracleFailure(
                    scenario_id=scenario.id,
                    step_index=step_index,
                    current_state=current_state,
                    step=step,
                    failure_reason="unexpected_state",
                    transition_id=transition.id,
                )
            )
            break

        current_state = next_state

    return failures


def collect_oracle_failures(fsm: FSM, oracle_suite: OracleSuite) -> list[OracleFailure]:
    """Collect oracle step failures for *fsm* across all scenarios."""
    failures: list[OracleFailure] = []
    for scenario in oracle_suite.scenarios:
        failures.extend(_analyze_scenario_failures(fsm, scenario))
    return failures


def _make_patch(fsm: FSM, patch_id: str, operations: Sequence[PatchOperation]) -> FSMPatch:
    return FSMPatch(
        patch_id=patch_id,
        target_fsm_id=fsm.id,
        operations=list(operations),
    )


def _unique_transition_id(fsm: FSM, base: str) -> str:
    existing = _transition_ids(fsm)
    candidate = base
    suffix = 1
    while candidate in existing:
        candidate = f"{base}_{suffix}"
        suffix += 1
    return candidate


class OracleGuidedMissingTransitionRepair:
    """Add transitions for oracle steps with no matching transition."""

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch:
        operations: list[AddTransitionOperation] = []
        seen: set[tuple[str, str, str | None, str]] = set()
        existing_ids = _transition_ids(fsm)

        for failure in collect_oracle_failures(fsm, oracle_suite):
            if failure.failure_reason != "no_matching_transition":
                continue

            key = (
                failure.current_state,
                failure.step.event,
                failure.step.guard,
                failure.step.expected_state,
            )
            if key in seen:
                continue
            seen.add(key)

            transition_id = _unique_transition_id(
                fsm,
                f"baseline_add_{failure.scenario_id}_{failure.step_index}",
            )
            existing_ids.add(transition_id)
            operations.append(
                AddTransitionOperation(
                    id=transition_id,
                    source=failure.current_state,
                    event=failure.step.event,
                    target=failure.step.expected_state,
                    guard=failure.step.guard,
                )
            )

        return _make_patch(
            fsm,
            patch_id=f"baseline_missing_transition_{fsm.id}",
            operations=operations,
        )


class OracleGuidedWrongTargetRepair:
    """Fix transitions whose target does not match the oracle expectation."""

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch:
        operations: list[ReplaceTransitionTargetOperation] = []
        seen: set[tuple[str, str]] = set()

        for failure in collect_oracle_failures(fsm, oracle_suite):
            if failure.failure_reason != "unexpected_state":
                continue
            if failure.transition_id is None:
                continue

            key = (failure.transition_id, failure.step.expected_state)
            if key in seen:
                continue
            seen.add(key)

            operations.append(
                ReplaceTransitionTargetOperation(
                    transition_id=failure.transition_id,
                    target=failure.step.expected_state,
                )
            )

        return _make_patch(
            fsm,
            patch_id=f"baseline_wrong_target_{fsm.id}",
            operations=operations,
        )


class RandomRepair:
    """Apply random valid patch operations using a deterministic seed."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch:
        _ = oracle_suite
        rng = random.Random(self.seed)
        candidates = _random_operation_candidates(fsm)
        rng.shuffle(candidates)

        selected: list[PatchOperation] = []
        operation_count = rng.randint(1, min(3, max(1, len(candidates))))

        for candidate in candidates:
            trial = selected + [candidate]
            patch = _make_patch(
                fsm,
                patch_id=f"baseline_random_{self.seed}_{fsm.id}",
                operations=trial,
            )
            if not validate_patch(fsm, patch):
                selected.append(candidate)
            if len(selected) >= operation_count:
                break

        return _make_patch(
            fsm,
            patch_id=f"baseline_random_{self.seed}_{fsm.id}",
            operations=selected,
        )


def _random_operation_candidates(fsm: FSM) -> list[PatchOperation]:
    states = _state_ids(fsm)
    events = list(fsm.events)
    candidates: list[PatchOperation] = []

    if len(states) >= 2:
        current = fsm.initial_state
        alternative = next(state for state in states if state != current)
        candidates.append(ReplaceInitialStateOperation(initial_state=alternative))

    for transition in fsm.transitions:
        other_targets = [state for state in states if state != transition.target]
        if other_targets:
            candidates.append(
                ReplaceTransitionTargetOperation(
                    transition_id=transition.id,
                    target=other_targets[0],
                )
            )

        other_sources = [state for state in states if state != transition.source]
        if other_sources:
            candidates.append(
                ReplaceTransitionSourceOperation(
                    transition_id=transition.id,
                    source=other_sources[0],
                )
            )

        other_events = [event for event in events if event != transition.event]
        if other_events:
            candidates.append(
                ReplaceTransitionEventOperation(
                    transition_id=transition.id,
                    event=other_events[0],
                )
            )

        candidates.append(
            ReplaceGuardOperation(
                transition_id=transition.id,
                guard=f"random_guard_{transition.id}",
            )
        )
        candidates.append(
            ReplaceActionOperation(
                transition_id=transition.id,
                action=f"random_action_{transition.id}",
            )
        )

        candidates.append(
            AddTransitionOperation(
                id=f"random_add_{transition.id}",
                source=transition.source,
                event=transition.event,
                target=transition.target,
                guard=f"random_guard_{transition.id}",
            )
        )

    return candidates


def _operation_sort_key(operation: PatchOperation) -> tuple[str, ...]:
    payload = operation.model_dump()
    op_name = str(payload.get("op", ""))
    parts = [op_name]
    for key in sorted(payload):
        if key == "op":
            continue
        parts.append(f"{key}={payload[key]!r}")
    return tuple(parts)


def _dedupe_operations(operations: Sequence[PatchOperation]) -> list[PatchOperation]:
    seen: set[tuple[str, ...]] = set()
    deduped: list[PatchOperation] = []
    for operation in operations:
        key = _operation_sort_key(operation)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(operation)
    return deduped


def _oracle_repair_candidates(fsm: FSM, oracle_suite: OracleSuite) -> list[PatchOperation]:
    """Build deterministic oracle-guided repair candidates for search/composite engines."""
    candidates: list[PatchOperation] = []
    candidates.extend(OracleGuidedMissingTransitionRepair().propose_patch(fsm, oracle_suite).operations)
    candidates.extend(OracleGuidedWrongTargetRepair().propose_patch(fsm, oracle_suite).operations)

    failures = collect_oracle_failures(fsm, oracle_suite)
    transition_by_id = {transition.id: transition for transition in fsm.transitions}

    for failure in failures:
        if failure.failure_reason == "no_matching_transition":
            for transition in fsm.transitions:
                if transition.source == failure.current_state and transition.event != failure.step.event:
                    candidates.append(
                        ReplaceTransitionEventOperation(
                            transition_id=transition.id,
                            event=failure.step.event,
                        )
                    )
                if (
                    transition.event == failure.step.event
                    and transition.target == failure.step.expected_state
                    and transition.source != failure.current_state
                ):
                    candidates.append(
                        ReplaceTransitionSourceOperation(
                            transition_id=transition.id,
                            source=failure.current_state,
                        )
                    )

        if failure.failure_reason == "unexpected_state" and failure.transition_id is not None:
            transition = transition_by_id.get(failure.transition_id)
            if transition is not None and transition.event != failure.step.event:
                candidates.append(
                    ReplaceTransitionEventOperation(
                        transition_id=transition.id,
                        event=failure.step.event,
                    )
                )

        if failure.step_index == 0 and failure.failure_reason == "no_matching_transition":
            candidates.append(
                ReplaceInitialStateOperation(initial_state=failure.current_state)
            )

    return _dedupe_operations(candidates)


def _merge_valid_operations(
    fsm: FSM,
    operations: Sequence[PatchOperation],
) -> list[PatchOperation]:
    """Keep the largest valid prefix of *operations* under cumulative patch validation."""
    selected: list[PatchOperation] = []
    for operation in operations:
        trial = selected + [operation]
        patch = _make_patch(fsm, patch_id="trial", operations=trial)
        if validate_patch(fsm, patch):
            continue
        selected.append(operation)
    return selected


class OracleGuidedCompositeRepair:
    """Apply oracle-guided structural alignment repairs without conflicting operations."""

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch:
        candidates = _oracle_repair_candidates(fsm, oracle_suite)
        operations = _merge_valid_operations(fsm, candidates)
        return _make_patch(
            fsm,
            patch_id=f"baseline_oracle_composite_{fsm.id}",
            operations=operations,
        )


class OracleGuidedSearchRepair:
    """Greedy search over oracle-guided candidates to maximize behavioural pass rate."""

    def __init__(self, seed: int = 0, max_iterations: int = 20) -> None:
        self.seed = seed
        self.max_iterations = max_iterations

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch:
        candidates = _oracle_repair_candidates(fsm, oracle_suite)
        if not candidates:
            return _make_patch(
                fsm,
                patch_id=f"baseline_search_bpr_{self.seed}_{fsm.id}",
                operations=[],
            )

        selected: list[PatchOperation] = []
        current = fsm.model_copy(deep=True)
        rng = random.Random(self.seed)

        for _ in range(self.max_iterations):
            current_bpr = score_oracle_suite(current, oracle_suite).bpr
            if current_bpr >= 1.0 - 1e-9:
                break

            best_operation: PatchOperation | None = None
            best_bpr = current_bpr
            shuffled = list(candidates)
            rng.shuffle(shuffled)
            shuffled.sort(key=_operation_sort_key)

            for operation in shuffled:
                if any(_operation_sort_key(operation) == _operation_sort_key(chosen) for chosen in selected):
                    continue
                trial_ops = selected + [operation]
                patch = _make_patch(
                    current,
                    patch_id=f"trial_{self.seed}",
                    operations=trial_ops,
                )
                if validate_patch(current, patch):
                    continue
                trial_fsm = apply_patch(current, patch)
                trial_bpr = score_oracle_suite(trial_fsm, oracle_suite).bpr
                if trial_bpr > best_bpr + 1e-9:
                    best_bpr = trial_bpr
                    best_operation = operation

            if best_operation is None:
                break

            selected.append(best_operation)
            trial_patch = _make_patch(
                current,
                patch_id=f"trial_{self.seed}",
                operations=selected,
            )
            current = apply_patch(current, trial_patch)

        return _make_patch(
            fsm,
            patch_id=f"baseline_search_bpr_{self.seed}_{fsm.id}",
            operations=selected,
        )


class TemplateLLMRepair:
    """Deterministic LLM-style template baseline without a live model API."""

    def __init__(self, seed: int = 0) -> None:
        self.seed = seed

    def propose_patch(self, fsm: FSM, oracle_suite: OracleSuite) -> FSMPatch:
        _ = self.seed
        composite = OracleGuidedCompositeRepair().propose_patch(fsm, oracle_suite)
        return composite.model_copy(
            update={"patch_id": f"baseline_llm_template_{fsm.id}"},
        )


def get_baseline_engine(name: str, *, seed: int = 0) -> BaselineRepairEngine:
    """Return a baseline repair engine instance for *name*."""
    if name == "missing-transition":
        return OracleGuidedMissingTransitionRepair()
    if name == "wrong-target":
        return OracleGuidedWrongTargetRepair()
    if name == "random":
        return RandomRepair(seed=seed)
    if name == "search-bpr":
        return OracleGuidedSearchRepair(seed=seed)
    if name == "oracle-composite":
        return OracleGuidedCompositeRepair()
    if name == "llm-template":
        return TemplateLLMRepair(seed=seed)
    known = ", ".join(BASELINE_ENGINE_NAMES)
    msg = f"Unknown baseline engine '{name}'. Known: {known}"
    raise BaselineEngineError(msg)


def propose_baseline_patch(
    fsm: FSM,
    oracle_suite: OracleSuite,
    *,
    engine: str,
    seed: int = 0,
) -> FSMPatch:
    """Propose a repair patch using the named baseline *engine*."""
    repair_engine = get_baseline_engine(engine, seed=seed)
    return repair_engine.propose_patch(fsm, oracle_suite)
