"""Tests for experiment orchestration."""

from __future__ import annotations

import csv
import json
import textwrap
from pathlib import Path

import pytest

from fsmrepairbench.experiments import (
    PROGRESS_COLUMNS,
    SUMMARY_COLUMNS,
    ExperimentConfig,
    load_existing_summary_row,
    load_experiment_config,
    result_path,
    run_experiment,
)
from fsmrepairbench.models import FSM, OracleSuite, RepairResult
from fsmrepairbench.mutators import mutate
from fsmrepairbench.patch import apply_patch, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    OracleGuidedMissingTransitionRepair,
    OracleGuidedWrongTargetRepair,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"


def _write_case(
    case_dir: Path,
    *,
    reference: FSM,
    faulty: FSM,
    oracle: OracleSuite,
    mutation_operator: str,
) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "reference_fsm.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "faulty_fsm.json").write_text(
        faulty.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "oracle_suite.json").write_text(
        oracle.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    (case_dir / "bug_metadata.json").write_text(
        json.dumps(
            {
                "bug_id": f"{reference.id}__{mutation_operator}__1",
                "reference_fsm_id": reference.id,
                "faulty_fsm_id": faulty.id,
                "mutation_operator": mutation_operator,
                "changed_transition_id": None,
                "description": "test",
                "seed": 1,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _setup_cases_root(root: Path) -> Path:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    faulty_missing, _ = mutate(reference, "missing_transition", 42)
    faulty_wrong, _ = mutate(reference, "wrong_target", 43)

    cases_dir = root / "cases"
    _write_case(
        cases_dir / "case_000001",
        reference=reference,
        faulty=faulty_missing,
        oracle=oracle,
        mutation_operator="missing_transition",
    )
    _write_case(
        cases_dir / "case_000002",
        reference=reference,
        faulty=faulty_wrong,
        oracle=oracle,
        mutation_operator="wrong_target",
    )
    return cases_dir


def _fake_repair_runner(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float,
) -> RepairResult:
    _ = model, max_iterations, temperature
    initial_score = score_oracle_suite(faulty_fsm, oracle_suite)
    engines = [
        OracleGuidedMissingTransitionRepair(),
        OracleGuidedWrongTargetRepair(),
    ]

    for engine in engines:
        patch = engine.propose_patch(faulty_fsm, oracle_suite)
        if validate_patch(faulty_fsm, patch):
            continue
        repaired = apply_patch(faulty_fsm, patch)
        final_score = score_oracle_suite(repaired, oracle_suite)
        if final_score.bpr <= initial_score.bpr:
            continue
        return RepairResult(
            bug_id=faulty_fsm.id,
            passed=final_score.bpr == 1.0,
            score=final_score.bpr,
            details={
                "model": model,
                "temperature": temperature,
                "max_iterations": max_iterations,
                "iterations": [
                    {
                        "iteration": 1,
                        "bpr_before": initial_score.bpr,
                        "bpr_after": final_score.bpr,
                        "patch_valid": True,
                        "patch_applied": True,
                        "validation_errors": [],
                    }
                ],
                "final_fsm": repaired.model_dump(),
                "passed_steps": final_score.passed_steps,
                "total_steps": final_score.total_steps,
                "passed_scenarios": final_score.passed_scenarios,
                "total_scenarios": final_score.total_scenarios,
            },
        )

    return RepairResult(
        bug_id=faulty_fsm.id,
        passed=False,
        score=initial_score.bpr,
        details={
            "model": model,
            "temperature": temperature,
            "max_iterations": max_iterations,
            "iterations": [
                {
                    "iteration": 1,
                    "bpr_before": initial_score.bpr,
                    "bpr_after": initial_score.bpr,
                    "patch_valid": False,
                    "patch_applied": False,
                    "error": "no baseline patch found",
                }
            ],
            "final_fsm": faulty_fsm.model_dump(),
            "passed_steps": initial_score.passed_steps,
            "total_steps": initial_score.total_steps,
            "passed_scenarios": initial_score.passed_scenarios,
            "total_scenarios": initial_score.total_scenarios,
        },
    )


def test_load_experiment_config(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        textwrap.dedent(
            """
            models:
              - qwen2.5-coder:7b
              - llama3.1:8b
            cases_dir: data/generated/cases
            iterations: 3
            temperature: 0.0
            output_dir: results/raw/exp001
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    config = load_experiment_config(config_path)
    assert config.models == ["qwen2.5-coder:7b", "llama3.1:8b"]
    assert config.cases_dir == Path("data/generated/cases")
    assert config.iterations == 3
    assert config.output_dir == Path("results/raw/exp001")


def test_run_experiment_writes_results_and_csv(tmp_path: Path) -> None:
    cases_dir = _setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a", "model-b"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )

    result = run_experiment(config, repair_runner=_fake_repair_runner)

    assert result.summary_path.exists()
    assert result.progress_path.exists()
    assert len(result.rows) == 4

    result_file = result_path(output_dir, "case_000001", "model-a")
    assert result_file.exists()
    payload = json.loads(result_file.read_text(encoding="utf-8"))
    assert payload["complete_repair"] is True
    assert payload["final_bpr"] == pytest.approx(1.0)

    with result.summary_path.open(encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    assert list(summary_rows[0].keys()) == list(SUMMARY_COLUMNS)
    assert len(summary_rows) == 4
    assert all(row["complete_repair"] == "True" for row in summary_rows)

    with result.progress_path.open(encoding="utf-8", newline="") as handle:
        progress_rows = list(csv.DictReader(handle))
    assert list(progress_rows[0].keys()) == list(PROGRESS_COLUMNS)


def test_run_experiment_resume_skips_completed_pairs(tmp_path: Path) -> None:
    cases_dir = _setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )

    calls = {"count": 0}

    def counting_runner(
        faulty_fsm: FSM,
        oracle_suite: OracleSuite,
        model: str,
        max_iterations: int,
        temperature: float,
    ) -> RepairResult:
        calls["count"] += 1
        return _fake_repair_runner(
            faulty_fsm,
            oracle_suite,
            model,
            max_iterations,
            temperature,
        )

    run_experiment(config, repair_runner=counting_runner)
    assert calls["count"] == 2

    run_experiment(config, repair_runner=counting_runner)
    assert calls["count"] == 2

    skipped = load_existing_summary_row(result_path(output_dir, "case_000001", "model-a"))
    assert skipped is not None
    assert skipped.status == "skipped"


def test_run_experiment_no_resume_reruns_all(tmp_path: Path) -> None:
    cases_dir = _setup_cases_root(tmp_path)
    output_dir = tmp_path / "results" / "exp001"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=output_dir,
        resume=True,
    )

    calls = {"count": 0}

    def counting_runner(
        faulty_fsm: FSM,
        oracle_suite: OracleSuite,
        model: str,
        max_iterations: int,
        temperature: float,
    ) -> RepairResult:
        calls["count"] += 1
        return _fake_repair_runner(
            faulty_fsm,
            oracle_suite,
            model,
            max_iterations,
            temperature,
        )

    run_experiment(config, repair_runner=counting_runner)
    run_experiment(config, repair_runner=counting_runner, resume=False)
    assert calls["count"] == 4
