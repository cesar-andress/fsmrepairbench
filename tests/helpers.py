"""Shared helpers for FSMRepairBench tests."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

from fsmrepairbench.models import FSM, OracleSuite, RepairResult
from fsmrepairbench.mutators import mutate
from fsmrepairbench.patch import apply_patch, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    OracleGuidedMissingTransitionRepair,
    OracleGuidedWrongTargetRepair,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def write_minimal_matrix(path: Path) -> None:
    """Write a small feature matrix CSV for coverage and quality tests."""
    path.write_text(
        textwrap.dedent(
            """
            case_id,machine_type,determinism,completeness,arity_class,size_class,guard_complexity,time_features,graph_structure,oracle_depth,bug_type,num_states,num_events,num_transitions,avg_out_degree,max_out_degree,num_guards,num_timed_guards,num_timeouts,num_cycles,scc_count,seed
            case_000001,plain_fsm,deterministic,complete,low,tiny,none,none,acyclic,shallow,missing_transition,3,2,2,1.0,1,0,0,0,0,1,42
            case_000002,mealy,deterministic,complete,medium,small,simple,none,sparse,medium,wrong_target,5,3,4,1.5,2,2,0,0,0,1,43
            case_000003,efsm,deterministic,complete,high,medium,compound,none,dense,deep,guard_flip,10,5,12,2.0,4,8,0,0,1,2,44
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )


def write_case(
    case_dir: Path,
    *,
    reference: FSM,
    faulty: FSM,
    oracle: OracleSuite,
    mutation_operator: str,
) -> None:
    """Write a minimal benchmark case directory for experiment tests."""
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


def setup_cases_root(root: Path) -> Path:
    """Create a tiny two-case benchmark tree under *root*/cases."""
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    faulty_missing, _ = mutate(reference, "missing_transition", 42)
    faulty_wrong, _ = mutate(reference, "wrong_target", 43)

    cases_dir = root / "cases"
    write_case(
        cases_dir / "case_000001",
        reference=reference,
        faulty=faulty_missing,
        oracle=oracle,
        mutation_operator="missing_transition",
    )
    write_case(
        cases_dir / "case_000002",
        reference=reference,
        faulty=faulty_wrong,
        oracle=oracle,
        mutation_operator="wrong_target",
    )
    return cases_dir


def fake_repair_runner(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float,
) -> RepairResult:
    """Deterministic baseline repair runner for experiment tests."""
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
