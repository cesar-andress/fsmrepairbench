"""Spectrum-based fault localization for FSM oracle execution traces."""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.models import FSM, OracleScenario, OracleSemanticsMode, OracleSuite, Transition
from fsmrepairbench.oracle import execute_scenario, trace_scenario_transitions
from fsmrepairbench.oracle_generator import reachable_state_ids

SuspiciousnessMethod = Literal["ochiai", "tarantula", "jaccard"]

ElementType = Literal["state", "transition", "guard", "action", "timeout"]


@dataclass(frozen=True)
class ScenarioSpectrum:
    """Execution spectrum for one oracle scenario."""

    scenario_id: str
    passed: bool
    covered_states: frozenset[str]
    covered_transitions: frozenset[str]
    covered_guards: frozenset[str]
    covered_actions: frozenset[str]
    covered_timeouts: frozenset[str]


@dataclass(frozen=True)
class SuspiciousElement:
    """Ranked suspicious FSM element from spectrum analysis."""

    element_type: ElementType
    element_id: str
    suspiciousness: float
    failed_cover_count: int
    passed_cover_count: int


@dataclass(frozen=True)
class FaultLocalizationReport:
    """Spectrum-based fault localization result."""

    fsm_id: str
    oracle_suite_id: str
    method: SuspiciousnessMethod
    ranked_elements: tuple[SuspiciousElement, ...]


def _transition_lookup(fsm: FSM) -> dict[str, Transition]:
    return {transition.id: transition for transition in fsm.transitions}


def _resolve_semantics_mode(
    fsm: FSM,
    suite: OracleSuite,
) -> OracleSemanticsMode | None:
    return suite.semantics_mode or fsm.semantics_mode


def trace_scenario_spectrum(
    fsm: FSM,
    scenario: OracleScenario,
    *,
    semantics_mode: OracleSemanticsMode | None = None,
) -> ScenarioSpectrum:
    """Record pass/fail and covered FSM elements using oracle execution traces."""
    mode = semantics_mode
    result = execute_scenario(fsm, scenario, semantics_mode=mode)
    transition_ids = trace_scenario_transitions(fsm, scenario, semantics_mode=mode)
    by_id = _transition_lookup(fsm)

    covered_states: set[str] = {fsm.initial_state}
    covered_transitions: set[str] = set()
    covered_guards: set[str] = set()
    covered_actions: set[str] = set()
    covered_timeouts: set[str] = set()

    for transition_id in transition_ids:
        transition = by_id[transition_id]
        covered_transitions.add(transition_id)
        covered_states.add(transition.source)
        covered_states.add(transition.target)
        if transition.guard is not None and transition.guard.strip():
            covered_guards.add(transition.guard)
        if transition.action is not None and transition.action.strip():
            covered_actions.add(transition.action)
        if transition.timeout is not None:
            covered_timeouts.add(str(transition.timeout))

    return ScenarioSpectrum(
        scenario_id=scenario.id,
        passed=result.passed,
        covered_states=frozenset(covered_states),
        covered_transitions=frozenset(covered_transitions),
        covered_guards=frozenset(covered_guards),
        covered_actions=frozenset(covered_actions),
        covered_timeouts=frozenset(covered_timeouts),
    )


def collect_scenario_spectra(
    fsm: FSM,
    suite: OracleSuite,
) -> tuple[ScenarioSpectrum, ...]:
    """Collect execution spectra for all scenarios in *suite*."""
    semantics_mode = _resolve_semantics_mode(fsm, suite)
    return tuple(
        trace_scenario_spectrum(fsm, scenario, semantics_mode=semantics_mode)
        for scenario in suite.scenarios
    )


def _all_fsm_elements(fsm: FSM) -> dict[ElementType, set[str]]:
    reachable = reachable_state_ids(fsm)
    states = {state.id for state in fsm.states if state.id in reachable}
    transitions: set[str] = set()
    guards: set[str] = set()
    actions: set[str] = set()
    timeouts: set[str] = set()

    for transition in fsm.transitions:
        if transition.source not in reachable:
            continue
        transitions.add(transition.id)
        if transition.guard is not None and transition.guard.strip():
            guards.add(transition.guard)
        if transition.action is not None and transition.action.strip():
            actions.add(transition.action)
        if transition.timeout is not None:
            timeouts.add(str(transition.timeout))

    return {
        "state": states,
        "transition": transitions,
        "guard": guards,
        "action": actions,
        "timeout": timeouts,
    }


def _element_in_spectrum(element_type: ElementType, element_id: str, spectrum: ScenarioSpectrum) -> bool:
    mapping = {
        "state": spectrum.covered_states,
        "transition": spectrum.covered_transitions,
        "guard": spectrum.covered_guards,
        "action": spectrum.covered_actions,
        "timeout": spectrum.covered_timeouts,
    }
    return element_id in mapping[element_type]


def _ochiai(ef: int, ep: int, nf: int, np: int) -> float:
    _ = np
    denominator = math.sqrt((ef + ep) * (ef + nf))
    if denominator == 0.0:
        return 0.0
    return ef / denominator


def _tarantula(ef: int, ep: int, nf: int, np: int) -> float:
    if ef + ep == 0 or nf + np == 0:
        return 0.0
    fail_ratio = ef / (ef + ep)
    pass_ratio = nf / (nf + np)
    denominator = fail_ratio + pass_ratio
    if denominator == 0.0:
        return 0.0
    return fail_ratio / denominator


def _jaccard(ef: int, ep: int, nf: int, np: int) -> float:
    _ = np
    denominator = ef + ep + nf
    if denominator == 0:
        return 0.0
    return ef / denominator


SUSPICIOUSNESS_FORMULAE: dict[SuspiciousnessMethod, Callable[[int, int, int, int], float]] = {
    "ochiai": _ochiai,
    "tarantula": _tarantula,
    "jaccard": _jaccard,
}


def suspiciousness_score(
    *,
    method: SuspiciousnessMethod,
    failed_cover_count: int,
    passed_cover_count: int,
    total_failed_scenarios: int,
    total_passed_scenarios: int,
) -> float:
    """Compute a suspiciousness score for one element."""
    ef = failed_cover_count
    ep = passed_cover_count
    nf = total_failed_scenarios - ef
    np = total_passed_scenarios - ep
    return SUSPICIOUSNESS_FORMULAE[method](ef, ep, nf, np)


def rank_suspicious_elements(
    fsm: FSM,
    spectra: Iterable[ScenarioSpectrum],
    *,
    method: SuspiciousnessMethod = "ochiai",
) -> tuple[SuspiciousElement, ...]:
    """Rank FSM elements by suspiciousness using execution spectra."""
    spectrum_list = tuple(spectra)
    total_failed = sum(1 for spectrum in spectrum_list if not spectrum.passed)
    total_passed = sum(1 for spectrum in spectrum_list if spectrum.passed)
    elements = _all_fsm_elements(fsm)

    ranked: list[SuspiciousElement] = []
    for element_type, element_ids in elements.items():
        for element_id in sorted(element_ids):
            failed_cover = sum(
                1
                for spectrum in spectrum_list
                if not spectrum.passed and _element_in_spectrum(element_type, element_id, spectrum)
            )
            passed_cover = sum(
                1
                for spectrum in spectrum_list
                if spectrum.passed and _element_in_spectrum(element_type, element_id, spectrum)
            )
            suspiciousness = suspiciousness_score(
                method=method,
                failed_cover_count=failed_cover,
                passed_cover_count=passed_cover,
                total_failed_scenarios=total_failed,
                total_passed_scenarios=total_passed,
            )
            ranked.append(
                SuspiciousElement(
                    element_type=element_type,
                    element_id=element_id,
                    suspiciousness=suspiciousness,
                    failed_cover_count=failed_cover,
                    passed_cover_count=passed_cover,
                )
            )

    ranked.sort(
        key=lambda item: (
            -item.suspiciousness,
            -item.failed_cover_count,
            item.element_type,
            item.element_id,
        )
    )
    return tuple(ranked)


def localize_fault(
    fsm: FSM,
    suite: OracleSuite,
    *,
    method: SuspiciousnessMethod = "ochiai",
) -> FaultLocalizationReport:
    """Run spectrum-based fault localization for *fsm* against *suite*."""
    if method not in SUSPICIOUSNESS_FORMULAE:
        msg = f"Unknown suspiciousness method '{method}'"
        raise ValueError(msg)

    spectra = collect_scenario_spectra(fsm, suite)
    failed_count = sum(1 for spectrum in spectra if not spectrum.passed)
    if failed_count == 0:
        msg = "Fault localization requires at least one failing oracle scenario"
        raise ValueError(msg)

    ranked_elements = rank_suspicious_elements(fsm, spectra, method=method)

    return FaultLocalizationReport(
        fsm_id=fsm.id,
        oracle_suite_id=suite.id,
        method=method,
        ranked_elements=ranked_elements,
    )


def fault_localization_to_dict(report: FaultLocalizationReport) -> dict[str, object]:
    """Convert a localization report to a JSON-serialisable mapping."""
    return {
        "fsm_id": report.fsm_id,
        "oracle_suite_id": report.oracle_suite_id,
        "method": report.method,
        "ranked_elements": [
            {
                "element_type": element.element_type,
                "element_id": element.element_id,
                "suspiciousness": element.suspiciousness,
                "failed_cover_count": element.failed_cover_count,
                "passed_cover_count": element.passed_cover_count,
            }
            for element in report.ranked_elements
        ],
    }


def write_localization_json(path: Path, report: FaultLocalizationReport) -> None:
    """Write a localization report as JSON to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(fault_localization_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
