"""Information-theoretic oracle suite selection for compact fault detection."""

from __future__ import annotations

import json
import math
import random
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.coverage import compute_coverage_report
from fsmrepairbench.models import FSM, OracleScenario, OracleSuite
from fsmrepairbench.oracle import execute_scenario, trace_scenario_transitions
from fsmrepairbench.validators import load_fsm_json

OracleSelectionStrategy = Literal[
    "random",
    "transition_coverage_greedy",
    "mutation_score_greedy",
    "mutual_information",
    "failure_diversity",
]

SUPPORTED_ORACLE_SELECTION_STRATEGIES: tuple[OracleSelectionStrategy, ...] = (
    "random",
    "transition_coverage_greedy",
    "mutation_score_greedy",
    "mutual_information",
    "failure_diversity",
)


class OracleSelectionError(ValueError):
    """Raised when oracle selection fails."""


@dataclass(frozen=True)
class MutantRecord:
    """One mutant FSM in the evaluation pool."""

    mutant_id: str
    fsm: FSM


@dataclass(frozen=True)
class ScenarioProfile:
    """Detection and coverage profile for one oracle scenario."""

    scenario: OracleScenario
    reference_passes: bool
    detections: tuple[bool, ...]
    covered_transitions: frozenset[str]

    @property
    def scenario_id(self) -> str:
        return self.scenario.id

    @property
    def failure_signature(self) -> str:
        return "".join("1" if detected else "0" for detected in self.detections)


@dataclass(frozen=True)
class OracleSelectionReport:
    """Result of selecting a compact oracle suite."""

    reference_fsm_id: str
    source_oracle_suite_id: str
    selected_oracle_suite_id: str
    strategy: OracleSelectionStrategy
    budget: int
    coverage_retained: float
    mutation_score_retained: float
    full_transition_coverage: float
    selected_transition_coverage: float
    full_mutation_score: float
    selected_mutation_score: float
    selected_scenarios: tuple[str, ...]
    discarded_scenarios: tuple[str, ...]
    selected_suite: OracleSuite
    rationale: str


def load_mutant_pool(mutants_dir: Path) -> tuple[MutantRecord, ...]:
    """Load mutant FSMs from *mutants_dir*."""
    if not mutants_dir.is_dir():
        msg = f"Mutants directory not found: {mutants_dir}"
        raise OracleSelectionError(msg)

    mutants: list[MutantRecord] = []
    seen_ids: set[str] = set()

    for subdir in sorted(path for path in mutants_dir.iterdir() if path.is_dir()):
        faulty_path = subdir / "faulty_fsm.json"
        if not faulty_path.is_file():
            continue
        mutant_id = subdir.name
        if mutant_id in seen_ids:
            continue
        mutants.append(MutantRecord(mutant_id=mutant_id, fsm=load_fsm_json(faulty_path)))
        seen_ids.add(mutant_id)

    for path in sorted(mutants_dir.glob("*.json")):
        if path.name in {"reference_fsm.json", "oracle_suite.json", "bug_metadata.json"}:
            continue
        mutant_id = path.stem
        if mutant_id in seen_ids:
            continue
        mutants.append(MutantRecord(mutant_id=mutant_id, fsm=load_fsm_json(path)))
        seen_ids.add(mutant_id)

    if not mutants:
        msg = f"No mutant FSMs found under {mutants_dir}"
        raise OracleSelectionError(msg)
    return tuple(mutants)


def _scenario_detects_mutant(reference: FSM, mutant: FSM, scenario: OracleScenario) -> bool:
    reference_result = execute_scenario(reference, scenario)
    if not reference_result.passed:
        return False
    mutant_result = execute_scenario(mutant, scenario)
    return not mutant_result.passed


def build_scenario_profiles(
    reference: FSM,
    suite: OracleSuite,
    mutants: tuple[MutantRecord, ...],
) -> tuple[ScenarioProfile, ...]:
    """Build per-scenario detection and coverage profiles."""
    profiles: list[ScenarioProfile] = []
    for scenario in suite.scenarios:
        reference_passes = execute_scenario(reference, scenario).passed
        detections = tuple(
            _scenario_detects_mutant(reference, mutant.fsm, scenario) for mutant in mutants
        )
        covered = frozenset(trace_scenario_transitions(reference, scenario))
        profiles.append(
            ScenarioProfile(
                scenario=scenario,
                reference_passes=reference_passes,
                detections=detections,
                covered_transitions=covered,
            )
        )
    return tuple(profiles)


def compute_mutation_score(profiles: tuple[ScenarioProfile, ...]) -> float:
    """Return the fraction of detectable mutant/scenario pairs that are detected."""
    detectable = 0
    detected = 0
    for profile in profiles:
        if not profile.reference_passes:
            continue
        for is_detected in profile.detections:
            detectable += 1
            if is_detected:
                detected += 1
    if detectable == 0:
        return 1.0
    return detected / detectable


def compute_transition_coverage(reference: FSM, profiles: tuple[ScenarioProfile, ...]) -> float:
    """Return transition coverage ratio for *profiles* over *reference*."""
    if not profiles:
        return 0.0
    scenarios = [profile.scenario for profile in profiles]
    suite = OracleSuite(id="coverage_probe", fsm_id=reference.id, scenarios=scenarios)
    report = compute_coverage_report(reference, suite, sequence_depth=1)
    return report.transition.coverage


def _selected_profiles(
    profiles: tuple[ScenarioProfile, ...],
    selected_ids: set[str],
) -> tuple[ScenarioProfile, ...]:
    return tuple(profile for profile in profiles if profile.scenario_id in selected_ids)


def _retained_ratio(selected: float, full: float) -> float:
    if full <= 0.0:
        return 1.0
    return min(1.0, selected / full)


def _binary_entropy(probability: float) -> float:
    if probability <= 0.0 or probability >= 1.0:
        return 0.0
    return -(probability * math.log2(probability) + (1.0 - probability) * math.log2(1.0 - probability))


def _information_gain(profile: ScenarioProfile, remaining_mutants: set[int]) -> float:
    if not remaining_mutants:
        return 0.0
    detected = {index for index in remaining_mutants if profile.detections[index]}
    not_detected = remaining_mutants - detected
    n = len(remaining_mutants)
    h_before = math.log2(n) if n > 1 else 0.0
    h_after = 0.0
    for group_size in (len(detected), len(not_detected)):
        if group_size == 0:
            continue
        probability = group_size / n
        h_after -= probability * math.log2(probability)
    return h_before - h_after


def _pairwise_mutual_information(left: ScenarioProfile, right: ScenarioProfile) -> float:
    if not left.detections or len(left.detections) != len(right.detections):
        return 0.0
    counts = {"00": 0, "01": 0, "10": 0, "11": 0}
    for left_bit, right_bit in zip(left.detections, right.detections, strict=True):
        key = f"{int(left_bit)}{int(right_bit)}"
        counts[key] += 1
    total = len(left.detections)
    if total == 0:
        return 0.0
    mi = 0.0
    for left_bit in (0, 1):
        for right_bit in (0, 1):
            joint = counts[f"{left_bit}{right_bit}"] / total
            if joint == 0.0:
                continue
            p_left = (counts[f"{left_bit}0"] + counts[f"{left_bit}1"]) / total
            p_right = (counts[f"0{right_bit}"] + counts[f"1{right_bit}"]) / total
            if p_left > 0.0 and p_right > 0.0:
                mi += joint * math.log2(joint / (p_left * p_right))
    return max(0.0, mi)


def _select_random(
    profiles: tuple[ScenarioProfile, ...],
    budget: int,
    seed: int,
) -> set[str]:
    rng = random.Random(seed)
    candidates = [profile.scenario_id for profile in profiles if profile.reference_passes]
    if not candidates:
        candidates = [profile.scenario_id for profile in profiles]
    if len(candidates) <= budget:
        return set(candidates)
    return set(rng.sample(candidates, budget))


def _select_transition_coverage_greedy(
    profiles: tuple[ScenarioProfile, ...],
    budget: int,
) -> set[str]:
    selected: set[str] = set()
    covered: set[str] = set()
    remaining = {profile.scenario_id for profile in profiles}

    while len(selected) < budget and remaining:
        best_id = ""
        best_gain = -1.0
        for profile in profiles:
            if profile.scenario_id not in remaining:
                continue
            gain = len(profile.covered_transitions - covered)
            if gain > best_gain or (gain == best_gain and profile.scenario_id < best_id):
                best_gain = gain
                best_id = profile.scenario_id
        if not best_id or best_gain <= 0:
            break
        profile = next(item for item in profiles if item.scenario_id == best_id)
        selected.add(best_id)
        remaining.remove(best_id)
        covered.update(profile.covered_transitions)

    if len(selected) < budget:
        for profile in profiles:
            if profile.scenario_id in selected:
                continue
            selected.add(profile.scenario_id)
            if len(selected) >= budget:
                break
    return selected


def _select_mutation_score_greedy(
    profiles: tuple[ScenarioProfile, ...],
    budget: int,
) -> set[str]:
    selected: set[str] = set()
    covered_pairs: set[tuple[int, int]] = set()
    remaining = {profile.scenario_id for profile in profiles}

    while len(selected) < budget and remaining:
        best_id = ""
        best_gain = -1
        for scenario_index, profile in enumerate(profiles):
            if profile.scenario_id not in remaining or not profile.reference_passes:
                continue
            gain = 0
            for mutant_index, detected in enumerate(profile.detections):
                if detected and (scenario_index, mutant_index) not in covered_pairs:
                    gain += 1
            if gain > best_gain or (gain == best_gain and profile.scenario_id < best_id):
                best_gain = gain
                best_id = profile.scenario_id
        if not best_id:
            break
        scenario_index = next(
            index for index, profile in enumerate(profiles) if profile.scenario_id == best_id
        )
        profile = profiles[scenario_index]
        selected.add(best_id)
        remaining.remove(best_id)
        for mutant_index, detected in enumerate(profile.detections):
            if detected:
                covered_pairs.add((scenario_index, mutant_index))

    if len(selected) < budget:
        for profile in profiles:
            if profile.scenario_id in selected:
                continue
            selected.add(profile.scenario_id)
            if len(selected) >= budget:
                break
    return selected


def _select_mutual_information(
    profiles: tuple[ScenarioProfile, ...],
    budget: int,
) -> set[str]:
    selected: set[str] = set()
    remaining_mutants = {
        mutant_index
        for mutant_index in range(len(profiles[0].detections) if profiles else 0)
    }
    remaining = {profile.scenario_id for profile in profiles if profile.reference_passes}
    if not remaining:
        remaining = {profile.scenario_id for profile in profiles}

    while len(selected) < budget and remaining:
        best_id = ""
        best_score = -1.0
        for profile in profiles:
            if profile.scenario_id not in remaining:
                continue
            gain = _information_gain(profile, remaining_mutants)
            redundancy = 0.0
            if selected:
                selected_profiles = _selected_profiles(profiles, selected)
                redundancy = sum(
                    _pairwise_mutual_information(profile, other) for other in selected_profiles
                ) / len(selected_profiles)
            score = gain - redundancy
            if score > best_score or (math.isclose(score, best_score) and profile.scenario_id < best_id):
                best_score = score
                best_id = profile.scenario_id
        if not best_id or best_score <= 0.0:
            break
        profile = next(item for item in profiles if item.scenario_id == best_id)
        selected.add(best_id)
        remaining.remove(best_id)
        remaining_mutants = {
            index
            for index in remaining_mutants
            if not profile.detections[index]
        }

    if len(selected) < budget:
        for profile in profiles:
            if profile.scenario_id in selected:
                continue
            selected.add(profile.scenario_id)
            if len(selected) >= budget:
                break
    return selected


def _select_failure_diversity(
    profiles: tuple[ScenarioProfile, ...],
    budget: int,
) -> set[str]:
    selected: set[str] = set()
    selected_signatures: set[str] = set()
    remaining = {profile.scenario_id for profile in profiles if profile.reference_passes}
    if not remaining:
        remaining = {profile.scenario_id for profile in profiles}

    while len(selected) < budget and remaining:
        best_id = ""
        best_score = -1.0
        for profile in profiles:
            if profile.scenario_id not in remaining:
                continue
            signature = profile.failure_signature
            novelty = 0 if signature in selected_signatures else 1
            entropy = _binary_entropy(sum(profile.detections) / len(profile.detections))
            score = novelty + entropy
            if score > best_score or (math.isclose(score, best_score) and profile.scenario_id < best_id):
                best_score = score
                best_id = profile.scenario_id
        if not best_id:
            break
        profile = next(item for item in profiles if item.scenario_id == best_id)
        selected.add(best_id)
        remaining.remove(best_id)
        selected_signatures.add(profile.failure_signature)

    if len(selected) < budget:
        for profile in profiles:
            if profile.scenario_id in selected:
                continue
            selected.add(profile.scenario_id)
            if len(selected) >= budget:
                break
    return selected


STRATEGY_IMPL: dict[OracleSelectionStrategy, Callable[..., set[str]]] = {
    "random": _select_random,
    "transition_coverage_greedy": _select_transition_coverage_greedy,
    "mutation_score_greedy": _select_mutation_score_greedy,
    "mutual_information": _select_mutual_information,
    "failure_diversity": _select_failure_diversity,
}


def select_oracle_suite(
    reference: FSM,
    suite: OracleSuite,
    mutants: tuple[MutantRecord, ...],
    *,
    strategy: OracleSelectionStrategy = "mutual_information",
    budget: int = 50,
    seed: int = 42,
) -> OracleSelectionReport:
    """Select a compact oracle suite preserving fault detection power."""
    if strategy not in STRATEGY_IMPL:
        msg = (
            f"Unknown strategy '{strategy}'. "
            f"Supported: {', '.join(SUPPORTED_ORACLE_SELECTION_STRATEGIES)}"
        )
        raise OracleSelectionError(msg)
    if budget <= 0:
        msg = "budget must be greater than zero"
        raise OracleSelectionError(msg)
    if not suite.scenarios:
        msg = "Oracle suite must contain at least one scenario"
        raise OracleSelectionError(msg)

    profiles = build_scenario_profiles(reference, suite, mutants)
    full_mutation_score = compute_mutation_score(profiles)
    full_transition_coverage = compute_transition_coverage(reference, profiles)

    effective_budget = min(budget, len(suite.scenarios))
    if strategy == "random":
        selected_ids = _select_random(profiles, effective_budget, seed)
    else:
        selected_ids = STRATEGY_IMPL[strategy](profiles, effective_budget)

    selected_profiles = _selected_profiles(profiles, selected_ids)
    selected_mutation_score = compute_mutation_score(selected_profiles)
    selected_transition_coverage = compute_transition_coverage(reference, selected_profiles)

    selected_scenarios = tuple(
        scenario.id for scenario in suite.scenarios if scenario.id in selected_ids
    )
    discarded_scenarios = tuple(
        scenario.id for scenario in suite.scenarios if scenario.id not in selected_ids
    )
    selected_suite = OracleSuite(
        id=f"{suite.id}__selected__{strategy}",
        fsm_id=suite.fsm_id,
        scenarios=[scenario for scenario in suite.scenarios if scenario.id in selected_ids],
        semantics_mode=suite.semantics_mode,
        probability_threshold=suite.probability_threshold,
    )

    rationale = (
        f"Selected {len(selected_scenarios)} of {len(suite.scenarios)} scenarios using "
        f"{strategy}; mutation score retained "
        f"{_retained_ratio(selected_mutation_score, full_mutation_score):.2%}, "
        f"transition coverage retained "
        f"{_retained_ratio(selected_transition_coverage, full_transition_coverage):.2%}."
    )

    return OracleSelectionReport(
        reference_fsm_id=reference.id,
        source_oracle_suite_id=suite.id,
        selected_oracle_suite_id=selected_suite.id,
        strategy=strategy,
        budget=budget,
        coverage_retained=_retained_ratio(selected_transition_coverage, full_transition_coverage),
        mutation_score_retained=_retained_ratio(selected_mutation_score, full_mutation_score),
        full_transition_coverage=full_transition_coverage,
        selected_transition_coverage=selected_transition_coverage,
        full_mutation_score=full_mutation_score,
        selected_mutation_score=selected_mutation_score,
        selected_scenarios=selected_scenarios,
        discarded_scenarios=discarded_scenarios,
        selected_suite=selected_suite,
        rationale=rationale,
    )


def oracle_selection_report_to_dict(report: OracleSelectionReport) -> dict[str, object]:
    """Convert an oracle selection report to JSON-serialisable data."""
    return {
        "reference_fsm_id": report.reference_fsm_id,
        "source_oracle_suite_id": report.source_oracle_suite_id,
        "selected_oracle_suite_id": report.selected_oracle_suite_id,
        "strategy": report.strategy,
        "budget": report.budget,
        "coverage_retained": report.coverage_retained,
        "mutation_score_retained": report.mutation_score_retained,
        "full_transition_coverage": report.full_transition_coverage,
        "selected_transition_coverage": report.selected_transition_coverage,
        "full_mutation_score": report.full_mutation_score,
        "selected_mutation_score": report.selected_mutation_score,
        "selected_scenarios": list(report.selected_scenarios),
        "discarded_scenarios": list(report.discarded_scenarios),
        "rationale": report.rationale,
    }


def write_oracle_selection_report_json(path: Path, report: OracleSelectionReport) -> None:
    """Write an oracle selection report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(oracle_selection_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_selected_oracle_json(path: Path, report: OracleSelectionReport) -> None:
    """Write the reduced oracle suite JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(report.selected_suite.model_dump_json(indent=2) + "\n", encoding="utf-8")
