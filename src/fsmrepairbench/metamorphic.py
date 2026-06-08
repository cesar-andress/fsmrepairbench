"""Metamorphic testing support for FSMRepairBench benchmark cases."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal

from fsmrepairbench.models import (
    BugMetadata,
    FSM,
    OracleSuite,
    ScoreResult,
    State,
    Transition,
)
from fsmrepairbench.oracle import trace_scenario_transitions
from fsmrepairbench.scorer import scenario_bpr, score_oracle_suite
from fsmrepairbench.validators import load_fsm_json, load_model, load_oracle_suite

MetamorphicRelationId = Literal[
    "state_renaming_invariance",
    "transition_order_invariance",
    "unreachable_state_invariance",
    "equivalent_guard_rewriting",
    "timeout_scaling_relation",
    "event_alias_relation",
    "deterministic_refinement_relation",
]

SUPPORTED_RELATIONS: tuple[MetamorphicRelationId, ...] = (
    "state_renaming_invariance",
    "transition_order_invariance",
    "unreachable_state_invariance",
    "equivalent_guard_rewriting",
    "timeout_scaling_relation",
    "event_alias_relation",
    "deterministic_refinement_relation",
)

ScoreRelationKind = Literal["equal_bpr", "followup_at_least_source_bpr"]

BPR_EPSILON = 1e-9
STATE_RENAME_PREFIX = "meta_"
EVENT_ALIAS_PREFIX = "meta_"
UNREACHABLE_STATE_ID = "meta_unreachable"
UNREACHABLE_EVENT = "meta_unreachable_event"
REFINEMENT_BLOCK_GUARD = "__meta_blocked__"

GUARD_REWRITES: dict[str, str] = {
    "ticket_valid": "ticket_valid && true",
    "ticket_invalid": "ticket_invalid || false",
}


class MetamorphicError(ValueError):
    """Raised when metamorphic testing fails."""


@dataclass(frozen=True)
class ExpectedScoreRelation:
    """Expected behavioural relation between source and follow-up scores."""

    kind: ScoreRelationKind
    description: str


@dataclass(frozen=True)
class MetamorphicViolation:
    """One detected metamorphic relation violation."""

    message: str
    source_bpr: float
    followup_bpr: float
    scenario_id: str | None = None


@dataclass(frozen=True)
class MetamorphicRelationSpec:
    """Definition of one metamorphic relation."""

    relation_id: MetamorphicRelationId
    description: str
    expected_relation: ExpectedScoreRelation
    transform_reference: Callable[[FSM, OracleSuite], tuple[FSM, OracleSuite] | None]
    transform_faulty: Callable[[FSM, OracleSuite], tuple[FSM, OracleSuite] | None]


@dataclass(frozen=True)
class MetamorphicCaseBundle:
    """Source benchmark case plus transformed follow-up artefacts."""

    relation_id: MetamorphicRelationId
    source_case_dir: Path
    followup_case_dir: Path
    source_reference: FSM
    source_faulty: FSM
    source_oracle: OracleSuite
    followup_reference: FSM
    followup_faulty: FSM
    followup_oracle: OracleSuite
    expected_relation: ExpectedScoreRelation
    transform_summary: str
    bug_metadata: BugMetadata | None = None


@dataclass(frozen=True)
class MetamorphicGenerationReport:
    """Summary of metamorphic follow-up cases generated from a source case."""

    source_case_dir: Path
    output_dir: Path
    generated: tuple[MetamorphicCaseBundle, ...]
    skipped: tuple[tuple[MetamorphicRelationId, str], ...]


@dataclass(frozen=True)
class MetamorphicCheckReport:
    """Result of checking a metamorphic score relation."""

    relation_id: MetamorphicRelationId
    expected_relation: ExpectedScoreRelation
    source_score: ScoreResult
    followup_score: ScoreResult
    holds: bool
    violations: tuple[MetamorphicViolation, ...]
    rationale: str


def _clone_fsm(fsm: FSM, *, suffix: str) -> FSM:
    payload = fsm.model_dump()
    payload["id"] = f"{fsm.id}__{suffix}"
    return FSM.model_validate(payload)


def _clone_oracle(suite: OracleSuite, *, fsm_id: str, suffix: str) -> OracleSuite:
    payload = suite.model_dump()
    payload["id"] = f"{suite.id}__{suffix}"
    payload["fsm_id"] = fsm_id
    return OracleSuite.model_validate(payload)


def _rename_states(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite]:
    mapping = {state.id: f"{STATE_RENAME_PREFIX}{state.id}" for state in fsm.states}
    renamed_states = [
        State(id=mapping[state.id], state_output=state.state_output) for state in fsm.states
    ]
    renamed_transitions = [
        Transition(
            id=transition.id,
            source=mapping[transition.source],
            event=transition.event,
            target=mapping[transition.target],
            guard=transition.guard,
            action=transition.action,
            output=transition.output,
            timeout=transition.timeout,
            delay=transition.delay,
            requirements=list(transition.requirements),
        )
        for transition in fsm.transitions
    ]
    renamed_fsm = FSM.model_validate(
        {
            **fsm.model_dump(),
            "id": f"{fsm.id}__state_renamed",
            "states": [state.model_dump() for state in renamed_states],
            "initial_state": mapping[fsm.initial_state],
            "transitions": [transition.model_dump() for transition in renamed_transitions],
        }
    )
    renamed_oracle = OracleSuite.model_validate(
        {
            **oracle.model_dump(),
            "id": f"{oracle.id}__state_renamed",
            "fsm_id": renamed_fsm.id,
            "scenarios": [
                {
                    **scenario.model_dump(),
                    "steps": [
                        {
                            **step.model_dump(),
                            "expected_state": mapping.get(step.expected_state, step.expected_state),
                        }
                        for step in scenario.steps
                    ],
                }
                for scenario in oracle.scenarios
            ],
        }
    )
    return renamed_fsm, renamed_oracle


def _reverse_transition_order(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite]:
    payload = fsm.model_dump()
    payload["id"] = f"{fsm.id}__transition_order"
    payload["transitions"] = list(reversed(payload["transitions"]))
    return FSM.model_validate(payload), oracle.model_copy(deep=True)


def _add_unreachable_state(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite]:
    if any(state.id == UNREACHABLE_STATE_ID for state in fsm.states):
        return _clone_fsm(fsm, suffix="unreachable"), oracle.model_copy(deep=True)

    unreachable_state = State(id=UNREACHABLE_STATE_ID)
    unreachable_transition = Transition(
        id="t_meta_unreachable",
        source=UNREACHABLE_STATE_ID,
        event=UNREACHABLE_EVENT,
        target=UNREACHABLE_STATE_ID,
    )
    updated_fsm = FSM.model_validate(
        {
            **fsm.model_dump(),
            "id": f"{fsm.id}__unreachable",
            "states": [*(state.model_dump() for state in fsm.states), unreachable_state.model_dump()],
            "events": sorted(set(fsm.events) | {UNREACHABLE_EVENT}),
            "transitions": [
                *(transition.model_dump() for transition in fsm.transitions),
                unreachable_transition.model_dump(),
            ],
        }
    )
    return updated_fsm, oracle.model_copy(deep=True)


def _rewrite_guard(guard: str | None) -> str | None:
    if guard is None:
        return None
    stripped = guard.strip()
    if not stripped:
        return guard
    return GUARD_REWRITES.get(stripped, stripped)


def _rewrite_guards(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite] | None:
    applicable = any(
        transition.guard in GUARD_REWRITES
        for transition in fsm.transitions
        if transition.guard is not None
    ) or any(step.guard in GUARD_REWRITES for scenario in oracle.scenarios for step in scenario.steps)
    if not applicable:
        return None

    rewritten_transitions = [
        Transition(
            **{
                **transition.model_dump(),
                "guard": _rewrite_guard(transition.guard),
            }
        )
        for transition in fsm.transitions
    ]
    rewritten_fsm = FSM.model_validate(
        {
            **fsm.model_dump(),
            "id": f"{fsm.id}__guard_rewrite",
            "transitions": [transition.model_dump() for transition in rewritten_transitions],
        }
    )
    rewritten_oracle = OracleSuite.model_validate(
        {
            **oracle.model_dump(),
            "id": f"{oracle.id}__guard_rewrite",
            "fsm_id": rewritten_fsm.id,
            "scenarios": [
                {
                    **scenario.model_dump(),
                    "steps": [
                        {**step.model_dump(), "guard": _rewrite_guard(step.guard)}
                        for step in scenario.steps
                    ],
                }
                for scenario in oracle.scenarios
            ],
        }
    )
    return rewritten_fsm, rewritten_oracle


def _scale_timeouts(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite] | None:
    if not any(transition.timeout is not None for transition in fsm.transitions):
        return None

    scaled_transitions = [
        Transition(
            **{
                **transition.model_dump(),
                "timeout": transition.timeout * 2.0 if transition.timeout is not None else None,
                "delay": transition.delay * 2.0 if transition.delay is not None else None,
            }
        )
        for transition in fsm.transitions
    ]
    scaled_fsm = FSM.model_validate(
        {
            **fsm.model_dump(),
            "id": f"{fsm.id}__timeout_scaled",
            "transitions": [transition.model_dump() for transition in scaled_transitions],
        }
    )
    return scaled_fsm, oracle.model_copy(deep=True)


def _alias_events(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite]:
    mapping = {event: f"{EVENT_ALIAS_PREFIX}{event}" for event in fsm.events}
    aliased_transitions = [
        Transition(
            **{
                **transition.model_dump(),
                "event": mapping[transition.event],
            }
        )
        for transition in fsm.transitions
    ]
    aliased_fsm = FSM.model_validate(
        {
            **fsm.model_dump(),
            "id": f"{fsm.id}__event_alias",
            "events": [mapping[event] for event in fsm.events],
            "transitions": [transition.model_dump() for transition in aliased_transitions],
        }
    )
    aliased_oracle = OracleSuite.model_validate(
        {
            **oracle.model_dump(),
            "id": f"{oracle.id}__event_alias",
            "fsm_id": aliased_fsm.id,
            "scenarios": [
                {
                    **scenario.model_dump(),
                    "steps": [
                        {**step.model_dump(), "event": mapping[step.event]} for step in scenario.steps
                    ],
                }
                for scenario in oracle.scenarios
            ],
        }
    )
    return aliased_fsm, aliased_oracle


def _covered_transition_ids(fsm: FSM, oracle: OracleSuite) -> set[str]:
    covered: set[str] = set()
    for scenario in oracle.scenarios:
        covered.update(trace_scenario_transitions(fsm, scenario))
    return covered


def _deterministic_refinement(fsm: FSM, oracle: OracleSuite) -> tuple[FSM, OracleSuite]:
    covered = _covered_transition_ids(fsm, oracle)
    refined_transitions: list[Transition] = []
    for transition in fsm.transitions:
        if transition.id in covered:
            refined_transitions.append(transition)
            continue
        refined_transitions.append(
            Transition(
                **{
                    **transition.model_dump(),
                    "guard": REFINEMENT_BLOCK_GUARD,
                }
            )
        )
    refined_fsm = FSM.model_validate(
        {
            **fsm.model_dump(),
            "id": f"{fsm.id}__refined",
            "transitions": [transition.model_dump() for transition in refined_transitions],
        }
    )
    return refined_fsm, oracle.model_copy(deep=True)


def _transform_pair(
    fsm: FSM,
    oracle: OracleSuite,
    transform: Callable[[FSM, OracleSuite], tuple[FSM, OracleSuite] | None],
) -> tuple[FSM, OracleSuite] | None:
    return transform(fsm, oracle)


RELATION_SPECS: dict[MetamorphicRelationId, MetamorphicRelationSpec] = {
    "state_renaming_invariance": MetamorphicRelationSpec(
        relation_id="state_renaming_invariance",
        description="Renaming states consistently in the FSM and oracle preserves BPR.",
        expected_relation=ExpectedScoreRelation(
            kind="equal_bpr",
            description="followup_bpr == source_bpr",
        ),
        transform_reference=_rename_states,
        transform_faulty=_rename_states,
    ),
    "transition_order_invariance": MetamorphicRelationSpec(
        relation_id="transition_order_invariance",
        description="Reordering transition declarations does not change executable behaviour.",
        expected_relation=ExpectedScoreRelation(
            kind="equal_bpr",
            description="followup_bpr == source_bpr",
        ),
        transform_reference=_reverse_transition_order,
        transform_faulty=_reverse_transition_order,
    ),
    "unreachable_state_invariance": MetamorphicRelationSpec(
        relation_id="unreachable_state_invariance",
        description="Adding unreachable states must not affect oracle-visible behaviour.",
        expected_relation=ExpectedScoreRelation(
            kind="equal_bpr",
            description="followup_bpr == source_bpr",
        ),
        transform_reference=_add_unreachable_state,
        transform_faulty=_add_unreachable_state,
    ),
    "equivalent_guard_rewriting": MetamorphicRelationSpec(
        relation_id="equivalent_guard_rewriting",
        description="Equivalent guard rewrites applied consistently preserve oracle matching.",
        expected_relation=ExpectedScoreRelation(
            kind="equal_bpr",
            description="followup_bpr == source_bpr",
        ),
        transform_reference=_rewrite_guards,
        transform_faulty=_rewrite_guards,
    ),
    "timeout_scaling_relation": MetamorphicRelationSpec(
        relation_id="timeout_scaling_relation",
        description="Scaling timed transition metadata does not affect untimed oracle execution.",
        expected_relation=ExpectedScoreRelation(
            kind="equal_bpr",
            description="followup_bpr == source_bpr",
        ),
        transform_reference=_scale_timeouts,
        transform_faulty=_scale_timeouts,
    ),
    "event_alias_relation": MetamorphicRelationSpec(
        relation_id="event_alias_relation",
        description="Consistent event aliasing in FSM and oracle preserves BPR.",
        expected_relation=ExpectedScoreRelation(
            kind="equal_bpr",
            description="followup_bpr == source_bpr",
        ),
        transform_reference=_alias_events,
        transform_faulty=_alias_events,
    ),
    "deterministic_refinement_relation": MetamorphicRelationSpec(
        relation_id="deterministic_refinement_relation",
        description="Blocking untested transitions refines the FSM without reducing oracle BPR.",
        expected_relation=ExpectedScoreRelation(
            kind="followup_at_least_source_bpr",
            description="followup_bpr >= source_bpr",
        ),
        transform_reference=_deterministic_refinement,
        transform_faulty=_deterministic_refinement,
    ),
}


def load_score_result(path: Path) -> ScoreResult:
    """Load a score JSON document exported by :func:`fsmrepairbench.scorer.write_score_json`."""
    return load_model(path, ScoreResult)


def _compare_bpr(
    *,
    source_bpr: float,
    followup_bpr: float,
    relation: ExpectedScoreRelation,
) -> tuple[bool, str | None]:
    if relation.kind == "equal_bpr":
        if abs(source_bpr - followup_bpr) <= BPR_EPSILON:
            return True, None
        return False, (
            f"Expected equal BPR but source={source_bpr:.6f} "
            f"and followup={followup_bpr:.6f}"
        )
    if relation.kind == "followup_at_least_source_bpr":
        if followup_bpr + BPR_EPSILON >= source_bpr:
            return True, None
        return False, (
            f"Expected followup BPR >= source BPR but source={source_bpr:.6f} "
            f"and followup={followup_bpr:.6f}"
        )
    msg = f"Unsupported score relation kind '{relation.kind}'"
    raise MetamorphicError(msg)


def detect_violations(
    *,
    relation_id: MetamorphicRelationId,
    source_score: ScoreResult,
    followup_score: ScoreResult,
) -> tuple[bool, tuple[MetamorphicViolation, ...], str]:
    """Detect whether the metamorphic relation holds between two score results."""
    spec = RELATION_SPECS[relation_id]
    holds, aggregate_message = _compare_bpr(
        source_bpr=source_score.bpr,
        followup_bpr=followup_score.bpr,
        relation=spec.expected_relation,
    )
    violations: list[MetamorphicViolation] = []
    if aggregate_message is not None:
        violations.append(
            MetamorphicViolation(
                message=aggregate_message,
                source_bpr=source_score.bpr,
                followup_bpr=followup_score.bpr,
            )
        )

    source_by_id = {scenario.scenario_id: scenario for scenario in source_score.scenarios}
    followup_by_id = {scenario.scenario_id: scenario for scenario in followup_score.scenarios}
    for scenario_id, source_scenario in source_by_id.items():
        followup_scenario = followup_by_id.get(scenario_id)
        if followup_scenario is None:
            violations.append(
                MetamorphicViolation(
                    message=f"Follow-up score missing scenario '{scenario_id}'",
                    source_bpr=source_score.bpr,
                    followup_bpr=followup_score.bpr,
                    scenario_id=scenario_id,
                )
            )
            holds = False
            continue
        if spec.expected_relation.kind == "equal_bpr":
            if source_scenario.passed != followup_scenario.passed:
                violations.append(
                    MetamorphicViolation(
                        message=(
                            f"Scenario '{scenario_id}' pass status changed: "
                            f"source={source_scenario.passed}, "
                            f"followup={followup_scenario.passed}"
                        ),
                        source_bpr=scenario_bpr(source_scenario),
                        followup_bpr=scenario_bpr(followup_scenario),
                        scenario_id=scenario_id,
                    )
                )
                holds = False
        elif not followup_scenario.passed and source_scenario.passed:
            violations.append(
                MetamorphicViolation(
                    message=(
                        f"Scenario '{scenario_id}' passed in source but failed in follow-up"
                    ),
                    source_bpr=scenario_bpr(source_scenario),
                    followup_bpr=scenario_bpr(followup_scenario),
                    scenario_id=scenario_id,
                )
            )
            holds = False

    rationale = spec.description if holds else "; ".join(violation.message for violation in violations)
    return holds, tuple(violations), rationale


def check_metamorphic_relation(
    source_score: ScoreResult,
    followup_score: ScoreResult,
    *,
    relation: MetamorphicRelationId,
) -> MetamorphicCheckReport:
    """Check whether *followup_score* satisfies the metamorphic relation for *source_score*."""
    if relation not in RELATION_SPECS:
        msg = f"Unknown relation '{relation}'. Supported: {', '.join(SUPPORTED_RELATIONS)}"
        raise MetamorphicError(msg)

    spec = RELATION_SPECS[relation]
    holds, violations, rationale = detect_violations(
        relation_id=relation,
        source_score=source_score,
        followup_score=followup_score,
    )
    return MetamorphicCheckReport(
        relation_id=relation,
        expected_relation=spec.expected_relation,
        source_score=source_score,
        followup_score=followup_score,
        holds=holds,
        violations=violations,
        rationale=rationale,
    )


def load_source_case(case_dir: Path) -> tuple[FSM, FSM, OracleSuite, BugMetadata | None]:
    """Load the minimum artefacts required to generate metamorphic follow-up cases."""
    reference_path = case_dir / "reference_fsm.json"
    faulty_path = case_dir / "faulty_fsm.json"
    oracle_path = case_dir / "oracle_suite.json"
    for path in (reference_path, faulty_path, oracle_path):
        if not path.is_file():
            msg = f"Missing required case file: {path}"
            raise MetamorphicError(msg)

    reference = load_fsm_json(reference_path)
    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    bug_metadata: BugMetadata | None = None
    metadata_path = case_dir / "bug_metadata.json"
    if metadata_path.is_file():
        bug_metadata = load_model(metadata_path, BugMetadata)
    return reference, faulty, oracle, bug_metadata


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, (FSM, OracleSuite, BugMetadata)):
        path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _transform_summary(relation_id: MetamorphicRelationId) -> str:
    summaries = {
        "state_renaming_invariance": f"Renamed states with prefix '{STATE_RENAME_PREFIX}'",
        "transition_order_invariance": "Reversed transition declaration order",
        "unreachable_state_invariance": f"Added unreachable state '{UNREACHABLE_STATE_ID}'",
        "equivalent_guard_rewriting": "Applied equivalent guard rewrites in FSM and oracle",
        "timeout_scaling_relation": "Scaled transition timeout/delay metadata by 2.0",
        "event_alias_relation": f"Aliased events with prefix '{EVENT_ALIAS_PREFIX}'",
        "deterministic_refinement_relation": (
            f"Blocked oracle-unreachable transitions with guard '{REFINEMENT_BLOCK_GUARD}'"
        ),
    }
    return summaries[relation_id]


def generate_metamorphic_case(
    case_dir: Path,
    *,
    relation: MetamorphicRelationId,
) -> MetamorphicCaseBundle | None:
    """Generate one metamorphic follow-up case for *relation*."""
    reference, faulty, oracle, bug_metadata = load_source_case(case_dir)
    spec = RELATION_SPECS[relation]

    reference_pair = _transform_pair(reference, oracle, spec.transform_reference)
    faulty_pair = _transform_pair(faulty, oracle, spec.transform_faulty)
    if reference_pair is None or faulty_pair is None:
        return None

    followup_reference, followup_oracle = reference_pair
    followup_faulty, _ = faulty_pair

    return MetamorphicCaseBundle(
        relation_id=relation,
        source_case_dir=case_dir,
        followup_case_dir=case_dir,
        source_reference=reference,
        source_faulty=faulty,
        source_oracle=oracle,
        followup_reference=followup_reference,
        followup_faulty=followup_faulty,
        followup_oracle=followup_oracle,
        expected_relation=spec.expected_relation,
        transform_summary=_transform_summary(relation),
        bug_metadata=bug_metadata,
    )


def write_metamorphic_case(out_dir: Path, bundle: MetamorphicCaseBundle) -> Path:
    """Write one metamorphic follow-up case directory under *out_dir*."""
    followup_dir = out_dir / bundle.relation_id
    followup_dir.mkdir(parents=True, exist_ok=True)
    _write_json(followup_dir / "reference_fsm.json", bundle.followup_reference)
    _write_json(followup_dir / "faulty_fsm.json", bundle.followup_faulty)
    _write_json(followup_dir / "oracle_suite.json", bundle.followup_oracle)

    if bundle.bug_metadata is not None:
        followup_metadata = bundle.bug_metadata.model_copy(
            update={
                "bug_id": f"{bundle.bug_metadata.bug_id}__{bundle.relation_id}",
                "reference_fsm_id": bundle.followup_reference.id,
                "faulty_fsm_id": bundle.followup_faulty.id,
                "description": (
                    f"{bundle.bug_metadata.description} "
                    f"(metamorphic follow-up: {bundle.relation_id})"
                ),
            }
        )
        _write_json(followup_dir / "bug_metadata.json", followup_metadata)

    source_ref_score = score_oracle_suite(bundle.source_reference, bundle.source_oracle)
    source_faulty_score = score_oracle_suite(bundle.source_faulty, bundle.source_oracle)
    followup_ref_score = score_oracle_suite(bundle.followup_reference, bundle.followup_oracle)
    followup_faulty_score = score_oracle_suite(bundle.followup_faulty, bundle.followup_oracle)

    _write_json(
        followup_dir / "metamorphic_metadata.json",
        {
            "relation_id": bundle.relation_id,
            "source_case_dir": str(bundle.source_case_dir),
            "expected_score_relation": bundle.expected_relation.kind,
            "expected_score_relation_description": bundle.expected_relation.description,
            "transform_summary": bundle.transform_summary,
            "source_reference_bpr": source_ref_score.bpr,
            "source_faulty_bpr": source_faulty_score.bpr,
            "followup_reference_bpr": followup_ref_score.bpr,
            "followup_faulty_bpr": followup_faulty_score.bpr,
        },
    )
    return followup_dir


def generate_metamorphic_cases(
    case_dir: Path,
    out_dir: Path,
    *,
    relations: tuple[MetamorphicRelationId, ...] | None = None,
) -> MetamorphicGenerationReport:
    """Generate metamorphic follow-up cases for all applicable relations."""
    selected = relations or SUPPORTED_RELATIONS
    generated: list[MetamorphicCaseBundle] = []
    skipped: list[tuple[MetamorphicRelationId, str]] = []

    out_dir.mkdir(parents=True, exist_ok=True)
    for relation in selected:
        if relation not in RELATION_SPECS:
            skipped.append((relation, "unknown relation"))
            continue
        bundle = generate_metamorphic_case(case_dir, relation=relation)
        if bundle is None:
            skipped.append((relation, "relation not applicable to source case"))
            continue
        followup_dir = write_metamorphic_case(out_dir, bundle)
        generated.append(replace(bundle, followup_case_dir=followup_dir))

    manifest = {
        "source_case_dir": str(case_dir),
        "output_dir": str(out_dir),
        "generated_relations": [
            {
                "relation_id": bundle.relation_id,
                "followup_case_dir": str(bundle.followup_case_dir),
                "expected_score_relation": bundle.expected_relation.kind,
                "transform_summary": bundle.transform_summary,
            }
            for bundle in generated
        ],
        "skipped_relations": [
            {"relation_id": relation_id, "reason": reason} for relation_id, reason in skipped
        ],
    }
    _write_json(out_dir / "metamorphic_manifest.json", manifest)

    return MetamorphicGenerationReport(
        source_case_dir=case_dir,
        output_dir=out_dir,
        generated=tuple(generated),
        skipped=tuple(skipped),
    )


def metamorphic_check_to_dict(report: MetamorphicCheckReport) -> dict[str, object]:
    """Convert a metamorphic check report to a JSON-serialisable mapping."""
    return {
        "relation_id": report.relation_id,
        "holds": report.holds,
        "expected_score_relation": report.expected_relation.kind,
        "expected_score_relation_description": report.expected_relation.description,
        "source_bpr": report.source_score.bpr,
        "followup_bpr": report.followup_score.bpr,
        "violations": [
            {
                "message": violation.message,
                "source_bpr": violation.source_bpr,
                "followup_bpr": violation.followup_bpr,
                "scenario_id": violation.scenario_id,
            }
            for violation in report.violations
        ],
        "rationale": report.rationale,
    }


def write_metamorphic_check_json(path: Path, report: MetamorphicCheckReport) -> None:
    """Write a metamorphic check report as JSON to *path*."""
    _write_json(path, metamorphic_check_to_dict(report))
