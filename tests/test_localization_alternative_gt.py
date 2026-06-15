"""Tests for alternative ground-truth localization definitions."""

from __future__ import annotations

from pathlib import Path

from fsmrepairbench.localization_alternative_gt import (
    multi_target_localization_metrics,
    resolve_alternative_gt_targets,
    resolve_deleted_transition_proxy_targets,
    resolve_initial_state_outgoing_targets,
)
from fsmrepairbench.models import FSM, State, Transition

FIXTURES = Path(__file__).parent / "fixtures"


def _simple_fsm(
    *,
    initial: str = "s0",
    transitions: list[Transition],
) -> FSM:
    states = {transition.source for transition in transitions} | {
        transition.target for transition in transitions
    }
    states.add(initial)
    events = sorted({transition.event for transition in transitions})
    return FSM(
        id="test_fsm",
        name="test_fsm",
        initial_state=initial,
        states=[State(id=state_id) for state_id in sorted(states)],
        transitions=transitions,
        events=events,
    )


def test_multi_target_localization_metrics_uses_best_rank() -> None:
    rank, reciprocal, top1, top3, top5 = multi_target_localization_metrics(
        ["t2", "t5"],
        ["t1", "t5", "t2"],
    )
    assert rank == 2
    assert reciprocal == 0.5
    assert top1 is False
    assert top3 is True
    assert top5 is True


def test_deleted_transition_proxy_finds_same_signature_neighbor() -> None:
    deleted = Transition(id="t_deleted", source="s0", event="e1", target="s1")
    reference = _simple_fsm(
        transitions=[
            deleted,
            Transition(id="t_other", source="s0", event="e2", target="s2"),
        ],
    )
    faulty = _simple_fsm(
        transitions=[
            Transition(id="t_proxy", source="s0", event="e1", target="s2"),
            Transition(id="t_other", source="s0", event="e2", target="s2"),
        ],
    )
    proxies = resolve_deleted_transition_proxy_targets(
        deleted_transition_id="t_deleted",
        reference=reference,
        faulty=faulty,
    )
    assert "t_proxy" in proxies


def test_initial_state_outgoing_targets() -> None:
    faulty = _simple_fsm(
        initial="s1",
        transitions=[
            Transition(id="t1", source="s1", event="a", target="s2"),
            Transition(id="t2", source="s0", event="b", target="s1"),
        ],
    )
    targets = resolve_initial_state_outgoing_targets(faulty=faulty)
    assert targets == ["t1"]


def test_resolve_alternative_gt_for_wrong_initial_state() -> None:
    reference = _simple_fsm(
        initial="s0",
        transitions=[Transition(id="t1", source="s0", event="a", target="s1")],
    )
    faulty = _simple_fsm(
        initial="s1",
        transitions=[Transition(id="t1", source="s1", event="a", target="s2")],
    )
    mode, targets = resolve_alternative_gt_targets(
        mutation_operator="wrong_initial_state",
        changed_transition_id=None,
        reference=reference,
        faulty=faulty,
    )
    assert mode == "initial_state_outgoing"
    assert targets == ("t1",)
