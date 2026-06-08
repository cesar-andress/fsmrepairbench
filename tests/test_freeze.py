"""Tests for release freezing."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from fsmrepairbench.experiments import ExperimentConfig, run_experiment
from fsmrepairbench.freeze import (
    FreezeError,
    collect_environment_info,
    discover_result_files,
    freeze_release,
    sha256_file,
    validate_result_file,
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


def _fake_repair_runner(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float,
) -> RepairResult:
    _ = model, max_iterations, temperature
    initial_score = score_oracle_suite(faulty_fsm, oracle_suite)
    for engine in (
        OracleGuidedMissingTransitionRepair(),
        OracleGuidedWrongTargetRepair(),
    ):
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
            "iterations": [],
            "final_fsm": faulty_fsm.model_dump(),
            "passed_steps": initial_score.passed_steps,
            "total_steps": initial_score.total_steps,
            "passed_scenarios": initial_score.passed_scenarios,
            "total_scenarios": initial_score.total_scenarios,
        },
    )


def _build_results_dir(tmp_path: Path) -> Path:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    cases_dir = tmp_path / "cases"
    for index, operator in enumerate(("missing_transition", "wrong_target"), start=1):
        faulty, _ = mutate(reference, operator, 40 + index)
        _write_case(
            cases_dir / f"case_{index:06d}",
            reference=reference,
            faulty=faulty,
            oracle=oracle,
            mutation_operator=operator,
        )

    results_dir = tmp_path / "results"
    config = ExperimentConfig(
        models=["model-a"],
        cases_dir=cases_dir,
        iterations=2,
        temperature=0.0,
        output_dir=results_dir,
        resume=True,
    )
    run_experiment(config, repair_runner=_fake_repair_runner)
    return results_dir


def test_sha256_file_is_deterministic(tmp_path: Path) -> None:
    path = tmp_path / "sample.json"
    path.write_text('{"value": 1}\n', encoding="utf-8")

    first = sha256_file(path)
    second = sha256_file(path)

    assert first == second
    assert len(first) == 64


def test_validate_result_file_rejects_invalid_payload(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"case_id": "case_000001"}\n', encoding="utf-8")

    with pytest.raises(FreezeError, match="missing fields"):
        validate_result_file(path)


def test_freeze_release_creates_manifest_and_hashes(tmp_path: Path) -> None:
    results_dir = _build_results_dir(tmp_path)
    release_dir = tmp_path / "release"

    result = freeze_release(results_dir, release_dir)

    assert result.manifest_path.exists()
    assert result.summary_path.exists()
    assert result.cases_index_path.exists()
    assert result.environment_path.exists()
    assert result.hashes_path.exists()
    assert result.readme_path.exists()
    assert (release_dir / "results" / "case_000001__model-a.json").exists()

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["unique_cases"] == 2
    assert manifest["models"] == ["model-a"]
    assert manifest["repair_attempts"] >= 2
    assert len(manifest["files"]) >= 3

    with result.hashes_path.open(encoding="utf-8", newline="") as handle:
        hash_rows = list(csv.DictReader(handle))
    assert hash_rows
    summary_hash_row = next(row for row in hash_rows if row["path"] == "summary.csv")
    assert summary_hash_row["sha256"] == sha256_file(result.summary_path)

    readme = result.readme_path.read_text(encoding="utf-8")
    assert "Dataset size" in readme
    assert "Metrics definitions" in readme
    assert "model-a" in readme


def test_freeze_release_validates_before_copy(tmp_path: Path) -> None:
    results_dir = _build_results_dir(tmp_path)
    broken = results_dir / "case_000001__model-a.json"
    broken.write_text("{}\n", encoding="utf-8")
    release_dir = tmp_path / "release"

    with pytest.raises(FreezeError, match="missing fields"):
        freeze_release(results_dir, release_dir)


def test_discover_result_files_matches_experiment_outputs(tmp_path: Path) -> None:
    results_dir = _build_results_dir(tmp_path)
    discovered = discover_result_files(results_dir)
    assert len(discovered) == 2
    assert all(path.name.startswith("case_") for path in discovered)


def test_collect_environment_info_contains_version() -> None:
    environment = collect_environment_info()
    assert "fsmrepairbench_version" in environment
    assert "python_version" in environment
    assert "platform" in environment
