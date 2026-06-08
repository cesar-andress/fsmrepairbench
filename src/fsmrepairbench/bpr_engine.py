"""Benchmark Performance Rate (BPR) scoring engine."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from fsmrepairbench.coverage import compute_coverage_report
from fsmrepairbench.models import FSM, OracleScenario, OracleSuite
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.oracle_selection import MutantRecord, build_scenario_profiles, compute_mutation_score
from fsmrepairbench.scorer import score_oracle_suite

BPR_SUMMARY_CSV_COLUMNS: tuple[str, ...] = (
    "reference_fsm_id",
    "candidate_fsm_id",
    "oracle_suite_id",
    "bpr",
    "coverage_state",
    "coverage_transition",
    "coverage_path",
    "coverage_aggregate",
    "mutation_score",
    "oracle_accuracy",
    "oracle_agreement",
    "execution_cost",
    "mutant_count",
    "scenario_count",
)

BPR_SCENARIO_CSV_COLUMNS: tuple[str, ...] = (
    "reference_fsm_id",
    "candidate_fsm_id",
    "oracle_suite_id",
    "scenario_id",
    "passed",
    "passed_steps",
    "total_steps",
    "scenario_bpr",
    "oracle_agreement",
    "execution_cost",
)

BPR_MUTANT_CSV_COLUMNS: tuple[str, ...] = (
    "reference_fsm_id",
    "oracle_suite_id",
    "mutant_id",
    "detectable_pairs",
    "detected_pairs",
    "mutation_score",
    "killed",
)


class BPREngineError(ValueError):
    """Raised when BPR scoring fails."""


class StepPrediction(BaseModel):
    """Predicted outcome for one oracle step."""

    expected_state: str | None = None
    expected_output: str | None = None


class ScenarioPrediction(BaseModel):
    """Predicted outcomes for one oracle scenario."""

    scenario_id: str
    expected_states: list[str] = Field(default_factory=list)
    expected_outputs: list[str | None] = Field(default_factory=list)


class CandidatePrediction(BaseModel):
    """Candidate model output for oracle agreement evaluation."""

    candidate_fsm: FSM | None = None
    scenario_predictions: list[ScenarioPrediction] = Field(default_factory=list)


class CoverageMetrics(BaseModel):
    """Coverage ratios achieved by the oracle suite on the reference FSM."""

    state: float = Field(ge=0.0, le=1.0)
    transition: float = Field(ge=0.0, le=1.0)
    path: float = Field(ge=0.0, le=1.0)
    aggregate: float = Field(ge=0.0, le=1.0)


class ScenarioScoreRow(BaseModel):
    """Per-scenario scoring breakdown."""

    scenario_id: str
    passed: bool
    passed_steps: int
    total_steps: int
    scenario_bpr: float
    oracle_agreement: float
    execution_cost: int


class MutantScoreRow(BaseModel):
    """Per-mutant detection summary."""

    mutant_id: str
    detectable_pairs: int
    detected_pairs: int
    mutation_score: float
    killed: bool


class BPRScoreReport(BaseModel):
    """Aggregate BPR scoring output."""

    reference_fsm_id: str
    candidate_fsm_id: str
    oracle_suite_id: str
    bpr: float = Field(ge=0.0, le=1.0)
    coverage: CoverageMetrics
    mutation_score: float = Field(ge=0.0, le=1.0)
    oracle_accuracy: float = Field(ge=0.0, le=1.0)
    oracle_agreement: float = Field(ge=0.0, le=1.0)
    execution_cost: int = Field(ge=0)
    mutant_count: int = Field(ge=0)
    scenario_count: int = Field(ge=0)
    scenarios: list[ScenarioScoreRow] = Field(default_factory=list)
    mutants: list[MutantScoreRow] = Field(default_factory=list)


@dataclass(frozen=True)
class BPRScoreInput:
    """Inputs for one BPR scoring run."""

    reference: FSM
    oracle: OracleSuite
    candidate: CandidatePrediction
    mutants: tuple[MutantRecord, ...] = ()
    path_length: int = 3


def _aggregate_coverage(state: float, transition: float, path: float) -> float:
    return round((state + transition + path) / 3.0, 6)


def compute_oracle_coverage(reference: FSM, oracle: OracleSuite, *, path_length: int) -> CoverageMetrics:
    """Compute state, transition, and path coverage for *oracle* over *reference*."""
    report = compute_coverage_report(reference, oracle, sequence_depth=path_length)
    state = report.state.coverage
    transition = report.transition.coverage
    path = report.transition_sequence.coverage
    return CoverageMetrics(
        state=round(state, 6),
        transition=round(transition, 6),
        path=round(path, 6),
        aggregate=_aggregate_coverage(state, transition, path),
    )


def _prediction_map(candidate: CandidatePrediction) -> dict[str, ScenarioPrediction]:
    return {prediction.scenario_id: prediction for prediction in candidate.scenario_predictions}


def _step_agreement(
    *,
    oracle_state: str,
    oracle_output: str | None,
    predicted_state: str | None,
    predicted_output: str | None,
) -> bool:
    if predicted_state is None:
        return False
    if predicted_state != oracle_state:
        return False
    if predicted_output is None:
        return True
    if oracle_output is None:
        return True
    return predicted_output == oracle_output


def _extract_outputs_from_execution(reference: FSM, scenario: OracleScenario) -> list[str | None]:
    current_state = reference.initial_state
    outputs: list[str | None] = []
    state_lookup = {state.id: state for state in reference.states}
    transition_lookup = {
        (transition.source, transition.event, transition.guard): transition
        for transition in reference.transitions
    }

    for step in scenario.steps:
        transition = transition_lookup.get((current_state, step.event, step.guard))
        if transition is None:
            for transition_item in reference.transitions:
                if (
                    transition_item.source == current_state
                    and transition_item.event == step.event
                    and transition_item.guard == step.guard
                ):
                    transition = transition_item
                    break
        output: str | None = None
        if transition is not None:
            output = transition.output or transition.action
            if output is None:
                output = state_lookup.get(transition.target, reference.states[0]).state_output
            current_state = transition.target
        outputs.append(output)
    return outputs


def _scenario_agreement_from_candidate_fsm(
    reference: FSM,
    candidate: FSM,
    scenario: OracleScenario,
) -> tuple[float, int]:
    reference_result = execute_scenario(reference, scenario)
    candidate_result = execute_scenario(candidate, scenario)
    if reference_result.total_steps == 0:
        return 1.0, 0

    agreed = 0
    for ref_step, cand_step in zip(reference_result.steps, candidate_result.steps, strict=False):
        if cand_step.actual_state == ref_step.expected_state:
            agreed += 1
    comparable = min(len(reference_result.steps), len(candidate_result.steps))
    if comparable == 0:
        return 0.0, reference_result.total_steps
    return agreed / comparable, reference_result.total_steps


def _scenario_agreement_from_predictions(
    reference: FSM,
    scenario: OracleScenario,
    prediction: ScenarioPrediction | None,
) -> tuple[float, int]:
    if not scenario.steps:
        return 1.0, 0
    if prediction is None:
        return 0.0, len(scenario.steps)

    oracle_outputs = _extract_outputs_from_execution(reference, scenario)
    agreed = 0
    for index, step in enumerate(scenario.steps):
        predicted_state = (
            prediction.expected_states[index] if index < len(prediction.expected_states) else None
        )
        predicted_output = (
            prediction.expected_outputs[index]
            if index < len(prediction.expected_outputs)
            else None
        )
        oracle_output = oracle_outputs[index] if index < len(oracle_outputs) else None
        if _step_agreement(
            oracle_state=step.expected_state,
            oracle_output=oracle_output,
            predicted_state=predicted_state,
            predicted_output=predicted_output,
        ):
            agreed += 1
    return agreed / len(scenario.steps), len(scenario.steps)


def compute_oracle_agreement(
    reference: FSM,
    oracle: OracleSuite,
    candidate: CandidatePrediction,
) -> tuple[float, list[ScenarioScoreRow], int]:
    """Compute oracle agreement and per-scenario rows."""
    predictions = _prediction_map(candidate)
    rows: list[ScenarioScoreRow] = []
    total_agreed = 0.0
    total_weight = 0
    execution_cost = 0

    candidate_fsm = candidate.candidate_fsm
    for scenario in oracle.scenarios:
        if candidate_fsm is not None:
            candidate_result = execute_scenario(candidate_fsm, scenario)
            reference_result = execute_scenario(reference, scenario)
            agreement, step_cost = _scenario_agreement_from_candidate_fsm(
                reference,
                candidate_fsm,
                scenario,
            )
            passed = candidate_result.passed
            passed_steps = candidate_result.passed_steps
            total_steps = candidate_result.total_steps
            scenario_bpr = passed_steps / total_steps if total_steps else 0.0
            execution_cost += total_steps
            if reference_result.total_steps == 0 and total_steps == 0:
                agreement = 1.0
        else:
            agreement, step_cost = _scenario_agreement_from_predictions(
                reference,
                scenario,
                predictions.get(scenario.id),
            )
            reference_result = execute_scenario(reference, scenario)
            passed = agreement == 1.0
            passed_steps = int(round(agreement * len(scenario.steps)))
            total_steps = len(scenario.steps)
            scenario_bpr = agreement if total_steps else 1.0
            execution_cost += step_cost

        rows.append(
            ScenarioScoreRow(
                scenario_id=scenario.id,
                passed=passed,
                passed_steps=passed_steps,
                total_steps=total_steps,
                scenario_bpr=round(scenario_bpr, 6),
                oracle_agreement=round(agreement, 6),
                execution_cost=step_cost if candidate_fsm is None else total_steps,
            )
        )
        if total_steps or step_cost:
            total_agreed += agreement * (total_steps or step_cost)
            total_weight += total_steps or step_cost

    oracle_agreement = total_agreed / total_weight if total_weight else 1.0
    return round(oracle_agreement, 6), rows, execution_cost


def compute_mutant_rows(
    reference: FSM,
    oracle: OracleSuite,
    mutants: tuple[MutantRecord, ...],
) -> tuple[float, list[MutantScoreRow], int]:
    """Compute mutation score and per-mutant rows."""
    if not mutants:
        return 1.0, [], 0

    profiles = build_scenario_profiles(reference, oracle, mutants)
    overall_mutation_score = round(compute_mutation_score(profiles), 6)
    execution_cost = sum(len(scenario.steps) for scenario in oracle.scenarios) * len(mutants)

    rows: list[MutantScoreRow] = []
    for mutant_index, mutant in enumerate(mutants):
        detectable = 0
        detected = 0
        for profile in profiles:
            if not profile.reference_passes:
                continue
            detectable += 1
            if profile.detections[mutant_index]:
                detected += 1
        score = 1.0 if detectable == 0 else detected / detectable
        rows.append(
            MutantScoreRow(
                mutant_id=mutant.mutant_id,
                detectable_pairs=detectable,
                detected_pairs=detected,
                mutation_score=round(score, 6),
                killed=detectable > 0 and detected == detectable,
            )
        )
    return overall_mutation_score, rows, execution_cost


def score_bpr_benchmark(inputs: BPRScoreInput) -> BPRScoreReport:
    """Score a candidate prediction against reference FSM, mutants, and oracle suite."""
    reference = inputs.reference
    oracle = inputs.oracle
    candidate = inputs.candidate

    if candidate.candidate_fsm is None and not candidate.scenario_predictions:
        msg = "CandidatePrediction requires candidate_fsm and/or scenario_predictions"
        raise BPREngineError(msg)

    coverage = compute_oracle_coverage(reference, oracle, path_length=inputs.path_length)
    mutation_score, mutant_rows, mutant_execution_cost = compute_mutant_rows(
        reference,
        oracle,
        inputs.mutants,
    )
    oracle_agreement, scenario_rows, candidate_execution_cost = compute_oracle_agreement(
        reference,
        oracle,
        candidate,
    )

    if candidate.candidate_fsm is not None:
        bpr = round(score_oracle_suite(candidate.candidate_fsm, oracle).bpr, 6)
        candidate_fsm_id = candidate.candidate_fsm.id
    else:
        bpr = round(
            sum(row.scenario_bpr * row.total_steps for row in scenario_rows)
            / sum(row.total_steps for row in scenario_rows)
            if scenario_rows and sum(row.total_steps for row in scenario_rows)
            else 1.0,
            6,
        )
        candidate_fsm_id = reference.id

    oracle_accuracy = oracle_agreement
    execution_cost = candidate_execution_cost + mutant_execution_cost

    return BPRScoreReport(
        reference_fsm_id=reference.id,
        candidate_fsm_id=candidate_fsm_id,
        oracle_suite_id=oracle.id,
        bpr=bpr,
        coverage=coverage,
        mutation_score=mutation_score,
        oracle_accuracy=oracle_accuracy,
        oracle_agreement=oracle_agreement,
        execution_cost=execution_cost,
        mutant_count=len(inputs.mutants),
        scenario_count=len(oracle.scenarios),
        scenarios=scenario_rows,
        mutants=mutant_rows,
    )


def bpr_report_to_summary_dict(report: BPRScoreReport) -> dict[str, Any]:
    """Return the primary JSON summary payload."""
    return {
        "bpr": report.bpr,
        "coverage": report.coverage.model_dump(),
        "mutation_score": report.mutation_score,
        "oracle_accuracy": report.oracle_accuracy,
        "oracle_agreement": report.oracle_agreement,
        "execution_cost": report.execution_cost,
        "reference_fsm_id": report.reference_fsm_id,
        "candidate_fsm_id": report.candidate_fsm_id,
        "oracle_suite_id": report.oracle_suite_id,
        "mutant_count": report.mutant_count,
        "scenario_count": report.scenario_count,
    }


def write_bpr_score_json(path: Path, report: BPRScoreReport) -> None:
    """Write full BPR score report as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        **bpr_report_to_summary_dict(report),
        "scenarios": [row.model_dump() for row in report.scenarios],
        "mutants": [row.model_dump() for row in report.mutants],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_bpr_summary_csv(path: Path, report: BPRScoreReport) -> None:
    """Write one-row CSV summary for *report*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BPR_SUMMARY_CSV_COLUMNS))
        writer.writeheader()
        writer.writerow(
            {
                "reference_fsm_id": report.reference_fsm_id,
                "candidate_fsm_id": report.candidate_fsm_id,
                "oracle_suite_id": report.oracle_suite_id,
                "bpr": f"{report.bpr:.6f}",
                "coverage_state": f"{report.coverage.state:.6f}",
                "coverage_transition": f"{report.coverage.transition:.6f}",
                "coverage_path": f"{report.coverage.path:.6f}",
                "coverage_aggregate": f"{report.coverage.aggregate:.6f}",
                "mutation_score": f"{report.mutation_score:.6f}",
                "oracle_accuracy": f"{report.oracle_accuracy:.6f}",
                "oracle_agreement": f"{report.oracle_agreement:.6f}",
                "execution_cost": report.execution_cost,
                "mutant_count": report.mutant_count,
                "scenario_count": report.scenario_count,
            }
        )


def write_bpr_scenario_csv(path: Path, report: BPRScoreReport) -> None:
    """Write per-scenario CSV rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BPR_SCENARIO_CSV_COLUMNS))
        writer.writeheader()
        for row in report.scenarios:
            writer.writerow(
                {
                    "reference_fsm_id": report.reference_fsm_id,
                    "candidate_fsm_id": report.candidate_fsm_id,
                    "oracle_suite_id": report.oracle_suite_id,
                    "scenario_id": row.scenario_id,
                    "passed": row.passed,
                    "passed_steps": row.passed_steps,
                    "total_steps": row.total_steps,
                    "scenario_bpr": f"{row.scenario_bpr:.6f}",
                    "oracle_agreement": f"{row.oracle_agreement:.6f}",
                    "execution_cost": row.execution_cost,
                }
            )


def write_bpr_mutant_csv(path: Path, report: BPRScoreReport) -> None:
    """Write per-mutant CSV rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BPR_MUTANT_CSV_COLUMNS))
        writer.writeheader()
        for row in report.mutants:
            writer.writerow(
                {
                    "reference_fsm_id": report.reference_fsm_id,
                    "oracle_suite_id": report.oracle_suite_id,
                    "mutant_id": row.mutant_id,
                    "detectable_pairs": row.detectable_pairs,
                    "detected_pairs": row.detected_pairs,
                    "mutation_score": f"{row.mutation_score:.6f}",
                    "killed": row.killed,
                }
            )


def write_bpr_csv_summaries(output_dir: Path, report: BPRScoreReport) -> None:
    """Write all CSV summaries for *report*."""
    write_bpr_summary_csv(output_dir / "bpr_summary.csv", report)
    write_bpr_scenario_csv(output_dir / "bpr_scenarios.csv", report)
    write_bpr_mutant_csv(output_dir / "bpr_mutants.csv", report)


def load_candidate_prediction(path: Path) -> CandidatePrediction:
    """Load a candidate FSM and/or explicit scenario predictions from JSON."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "candidate_fsm" in payload:
        return CandidatePrediction.model_validate(payload)
    if "states" in payload and "transitions" in payload:
        return CandidatePrediction(candidate_fsm=FSM.model_validate(payload))
    if "predictions" in payload:
        scenarios = [
            ScenarioPrediction(
                scenario_id=item["scenario_id"],
                expected_states=item.get("expected_states", []),
                expected_outputs=item.get("expected_outputs", []),
            )
            for item in payload["predictions"]
        ]
        candidate_fsm = None
        if "candidate_fsm" in payload:
            candidate_fsm = FSM.model_validate(payload["candidate_fsm"])
        return CandidatePrediction(candidate_fsm=candidate_fsm, scenario_predictions=scenarios)
    msg = f"Unsupported candidate prediction format in {path}"
    raise BPREngineError(msg)


def load_mutants_from_json(path: Path) -> tuple[MutantRecord, ...]:
    """Load mutants from a literature mutant report or list JSON file."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutants: list[MutantRecord] = []

    if isinstance(payload, dict) and "mutants" in payload:
        for item in payload["mutants"]:
            fsm_payload = item.get("fsm")
            if fsm_payload is None:
                continue
            mutants.append(
                MutantRecord(
                    mutant_id=item["mutant_id"],
                    fsm=FSM.model_validate(fsm_payload),
                )
            )
        return tuple(mutants)

    if isinstance(payload, list):
        for item in payload:
            if "fsm" in item:
                mutants.append(
                    MutantRecord(
                        mutant_id=item["mutant_id"],
                        fsm=FSM.model_validate(item["fsm"]),
                    )
                )
            else:
                mutants.append(
                    MutantRecord(
                        mutant_id=item["id"],
                        fsm=FSM.model_validate(item),
                    )
                )
        return tuple(mutants)

    msg = f"Unsupported mutant JSON format in {path}"
    raise BPREngineError(msg)


def load_mutants_from_directory(mutants_dir: Path) -> tuple[MutantRecord, ...]:
    """Load mutant FSM JSON files from a directory."""
    from fsmrepairbench.oracle_selection import load_mutant_pool

    return load_mutant_pool(mutants_dir)
