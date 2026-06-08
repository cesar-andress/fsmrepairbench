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
    validate_patch,
)

BASELINE_ENGINE_NAMES: tuple[str, ...] = (
    "missing-transition",
    "wrong-target",
    "random",
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


def get_baseline_engine(name: str, *, seed: int = 0) -> BaselineRepairEngine:
    """Return a baseline repair engine instance for *name*."""
    if name == "missing-transition":
        return OracleGuidedMissingTransitionRepair()
    if name == "wrong-target":
        return OracleGuidedWrongTargetRepair()
    if name == "random":
        return RandomRepair(seed=seed)
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
