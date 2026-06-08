"""Tests for information-theoretic oracle suite selection."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import OracleScenario, OracleStep, OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.oracle_selection import (
    SUPPORTED_ORACLE_SELECTION_STRATEGIES,
    OracleSelectionError,
    build_scenario_profiles,
    compute_mutation_score,
    load_mutant_pool,
    oracle_selection_report_to_dict,
    select_oracle_suite,
)
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture
def mutant_pool(tmp_path: Path):
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    mutants_dir = tmp_path / "mutants"
    mutants_dir.mkdir()

    for seed, operator in ((42, "wrong_target"), (43, "missing_transition"), (44, "guard_flip")):
        faulty, _ = mutate(reference, operator, seed)
        mutant_dir = mutants_dir / f"mutant_{operator}_{seed}"
        mutant_dir.mkdir()
        (mutant_dir / "faulty_fsm.json").write_text(
            faulty.model_dump_json(indent=2) + "\n",
            encoding="utf-8",
        )

    return reference, mutants_dir


def _expanded_oracle(reference_id: str) -> OracleSuite:
    base = load_oracle_suite(FIXTURES / "valid_oracle.json")
    extra = OracleScenario(
        id="duplicate_valid_path",
        steps=[OracleStep(event="car_arrives", guard="ticket_valid", expected_state="open")],
    )
    return OracleSuite(
        id=base.id,
        fsm_id=reference_id,
        scenarios=[*base.scenarios, extra],
    )


@pytest.mark.parametrize("strategy", SUPPORTED_ORACLE_SELECTION_STRATEGIES)
def test_select_oracle_suite_respects_budget(mutant_pool, strategy: str) -> None:
    reference, mutants_dir = mutant_pool
    suite = _expanded_oracle(reference.id)
    mutants = load_mutant_pool(mutants_dir)
    budget = 2

    report = select_oracle_suite(
        reference,
        suite,
        mutants,
        strategy=strategy,  # type: ignore[arg-type]
        budget=budget,
        seed=7,
    )

    assert len(report.selected_scenarios) <= budget
    assert len(report.selected_scenarios) + len(report.discarded_scenarios) == len(suite.scenarios)
    assert 0.0 <= report.coverage_retained <= 1.0
    assert 0.0 <= report.mutation_score_retained <= 1.0
    assert report.selected_suite.scenarios


def test_mutation_score_greedy_retains_fault_detection(mutant_pool) -> None:
    reference, mutants_dir = mutant_pool
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = load_mutant_pool(mutants_dir)
    profiles = build_scenario_profiles(reference, suite, mutants)
    full_score = compute_mutation_score(profiles)

    report = select_oracle_suite(
        reference,
        suite,
        mutants,
        strategy="mutation_score_greedy",
        budget=2,
    )

    assert report.selected_mutation_score > 0.0
    assert report.mutation_score_retained >= min(1.0, report.selected_mutation_score / max(full_score, 1e-9))


def test_mutual_information_prefers_informative_scenarios(mutant_pool) -> None:
    reference, mutants_dir = mutant_pool
    suite = _expanded_oracle(reference.id)
    mutants = load_mutant_pool(mutants_dir)

    report = select_oracle_suite(
        reference,
        suite,
        mutants,
        strategy="mutual_information",
        budget=2,
    )

    assert "invalid_ticket_stays_closed" in report.selected_scenarios or (
        "valid_ticket_opens_gate" in report.selected_scenarios
    )


def test_load_mutant_pool_reads_top_level_json(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    faulty, _ = mutate(reference, "wrong_target", 1)
    mutants_dir = tmp_path / "mutants"
    mutants_dir.mkdir()
    (mutants_dir / "wrong_target.json").write_text(
        faulty.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    mutants = load_mutant_pool(mutants_dir)
    assert len(mutants) == 1
    assert mutants[0].mutant_id == "wrong_target"


def test_load_mutant_pool_empty_dir_raises(tmp_path: Path) -> None:
    mutants_dir = tmp_path / "empty"
    mutants_dir.mkdir()
    with pytest.raises(OracleSelectionError, match="No mutant FSMs found"):
        load_mutant_pool(mutants_dir)


def test_oracle_selection_report_to_dict(mutant_pool) -> None:
    reference, mutants_dir = mutant_pool
    suite = load_oracle_suite(FIXTURES / "valid_oracle.json")
    mutants = load_mutant_pool(mutants_dir)
    report = select_oracle_suite(reference, suite, mutants, strategy="random", budget=2, seed=1)
    payload = oracle_selection_report_to_dict(report)

    assert payload["strategy"] == "random"
    assert payload["selected_scenarios"]
    assert "mutation_score_retained" in payload


def test_cli_select_oracles(mutant_pool, tmp_path: Path) -> None:
    reference, mutants_dir = mutant_pool
    oracle_path = FIXTURES / "valid_oracle.json"
    out_path = tmp_path / "selected_oracle.json"
    report_path = tmp_path / "oracle_selection_report.json"

    result = runner.invoke(
        app,
        [
            "select-oracles",
            str(FIXTURES / "valid_fsm.json"),
            str(oracle_path),
            str(mutants_dir),
            "--strategy",
            "mutual_information",
            "--budget",
            "2",
            "--out",
            str(out_path),
            "--report",
            str(report_path),
        ],
    )

    assert result.exit_code == 0, result.stdout
    selected = json.loads(out_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert selected["scenarios"]
    assert report["strategy"] == "mutual_information"
