"""Tests for extended C1 baseline repair engines and exports."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fsmrepairbench.mutators import mutate
from fsmrepairbench.patch import apply_patch, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    OracleGuidedCompositeRepair,
    OracleGuidedSearchRepair,
    TemplateLLMRepair,
    get_baseline_engine,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"


def test_extended_engines_registered() -> None:
    for name in ("search-bpr", "oracle-composite", "llm-template"):
        engine = get_baseline_engine(name, seed=0)
        assert engine is not None


def test_search_bpr_improves_missing_transition_fixture() -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "simple_oracle.json")
    faulty = reference.model_copy(
        update={
            "transitions": [
                transition for transition in reference.transitions if transition.id != "t2"
            ]
        }
    )
    assert score_oracle_suite(faulty, oracle).bpr < 1.0

    patch = OracleGuidedSearchRepair(seed=0).propose_patch(faulty, oracle)
    assert validate_patch(faulty, patch) == []
    repaired = apply_patch(faulty, patch)
    assert score_oracle_suite(repaired, oracle).bpr == pytest.approx(1.0)


def test_oracle_composite_improves_wrong_target_fixture() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, _ = mutate(reference, "wrong_target", 42)
    assert score_oracle_suite(faulty, oracle).bpr < 1.0

    patch = OracleGuidedCompositeRepair().propose_patch(faulty, oracle)
    assert validate_patch(faulty, patch) == []
    repaired = apply_patch(faulty, patch)
    assert score_oracle_suite(repaired, oracle).bpr == pytest.approx(1.0)


def test_llm_template_matches_composite_on_fixture() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, _ = mutate(reference, "wrong_target", 42)

    composite = OracleGuidedCompositeRepair().propose_patch(faulty, oracle)
    template = TemplateLLMRepair(seed=0).propose_patch(faulty, oracle)
    assert len(template.operations) == len(composite.operations)


def test_extended_export_fixture(tmp_path: Path) -> None:
    from fsmrepairbench.c1_extended_baseline_repair import generate_c1_extended_baseline_exports

    dataset = FIXTURES / "stratified_coupling_dataset"
    cohort = tmp_path / "cohort.txt"
    cohort.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    out.mkdir()
    summary = out / "summary.csv"
    summary.write_text(
        "case_id,tool_id,tool_type,model,mutation_operator,status,failure_class,"
        "initial_bpr,final_bpr,delta_bpr,complete_repair,effective_repair,regression,"
        "patch_parse_failures,patch_validation_failures,patch_application_failures,"
        "iterations_completed,runtime_seconds\n"
        "case_000002,baseline_search_bpr,baseline,,wrong_target,completed,complete_repair,"
        "0.9,1.0,0.1,True,True,False,0,0,0,1,0.1\n",
        encoding="utf-8",
    )

    result = generate_c1_extended_baseline_exports(
        dataset,
        out_dir=out,
        cohort_file=cohort,
        tools_dir=Path("tools/baselines_c1_extended"),
        paper_export_dir=tmp_path / "paper",
        workers=1,
        repo_root=Path(__file__).resolve().parents[1],
    )
    assert result.leaderboard_path.is_file()
    assert result.localization_coupling_path.is_file()
    assert result.manifest_path.is_file()
    manifest = result.manifest_path.read_text(encoding="utf-8")
    assert "C1-extended-baseline-repair" in manifest
    rows = list(csv.DictReader(result.leaderboard_path.open(encoding="utf-8")))
    assert rows[0]["tool_id"] == "baseline_search_bpr"
