"""Tests for higher-order mutation and coupling analysis."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.higher_order_mutation import (
    analyze_dataset_coupling,
    is_first_order_mutant,
    is_higher_order_mutant,
    mutate_higher_order,
    write_dataset_coupling_report,
)
from fsmrepairbench.dataset_builder import (
    COUPLING_CASE_FILES,
    STRATIFIED_CASE_LAYOUT_FILES,
    discover_coupling_case_directories,
    format_coupling_case_discovery,
    inspect_coupling_case_directory,
)
from fsmrepairbench.models import OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.oracle_generator import generate_oracle_suite
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.taxonomy import (
    ArityClass,
    BugType,
    CaseFeatures,
    Completeness,
    Determinism,
    GraphStructure,
    GuardComplexity,
    MachineType,
    OracleDepth,
    SizeClass,
    TimeFeature,
)
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _minimal_case_metadata(
    case_id: str,
    reference_id: str,
    faulty_id: str,
    mutation_operator: str,
    *,
    reference_bpr: float = 1.0,
    faulty_bpr: float = 0.5,
) -> dict[str, object]:
    return {
        "case_id": case_id,
        "reference_fsm_id": reference_id,
        "faulty_fsm_id": faulty_id,
        "complexity": "medium",
        "state_count": 2,
        "transition_count": 3,
        "event_count": 3,
        "mutation_operator": mutation_operator,
        "difficulty_score": 10.0,
        "oracle_coverage": {
            "state_coverage": 1.0,
            "transition_coverage": 1.0,
            "event_coverage": 1.0,
        },
        "reference_bpr": reference_bpr,
        "faulty_bpr": faulty_bpr,
        "bpr_delta": reference_bpr - faulty_bpr,
        "valid_reference": True,
        "valid_faulty": True,
    }


def _write_complete_case(
    case_dir: Path,
    *,
    reference,
    faulty,
    oracle: OracleSuite,
    metadata,
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
        metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    ref_bpr = score_oracle_suite(reference, oracle).bpr
    faulty_bpr = score_oracle_suite(faulty, oracle).bpr
    (case_dir / "case_metadata.json").write_text(
        json.dumps(
            _minimal_case_metadata(
                case_dir.name,
                reference.id,
                faulty.id,
                metadata.mutation_operator,
                reference_bpr=ref_bpr,
                faulty_bpr=faulty_bpr,
            ),
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def _write_stratified_case(
    case_dir: Path,
    *,
    reference,
    faulty,
    oracle: OracleSuite,
    metadata,
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
        metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    features = CaseFeatures(
        case_id=case_dir.name,
        machine_type=MachineType.PLAIN_FSM,
        determinism=Determinism.DETERMINISTIC,
        completeness=Completeness.COMPLETE,
        arity_class=ArityClass.LOW,
        size_class=SizeClass.TINY,
        guard_complexity=GuardComplexity.NONE,
        time_features=[TimeFeature.NONE],
        graph_structure=[GraphStructure.ACYCLIC],
        oracle_depth=OracleDepth.SHALLOW,
        bug_type=BugType.WRONG_TARGET,
        num_states=len(reference.states),
        num_events=len(reference.events),
        num_transitions=len(reference.transitions),
        avg_out_degree=1.0,
        max_out_degree=1,
        num_guards=0,
        num_timed_guards=0,
        num_timeouts=0,
        num_cycles=0,
        scc_count=1,
        seed=42,
    )
    (case_dir / "case_features.json").write_text(
        features.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )


def test_first_order_mutant_via_higher_order_api() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate_higher_order(reference, "wrong_target", 42)

    assert is_first_order_mutant(metadata)
    assert not is_higher_order_mutant(metadata)
    assert metadata.mutation_order == 1
    assert len(metadata.component_faults) == 1
    assert metadata.coupled_to_simple_faults is None
    assert faulty.reference_fsm_id == reference.id


def test_higher_order_mutant_chains_operators() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    operators = "wrong_target,guard_flip,missing_transition"
    faulty, metadata = mutate_higher_order(reference, operators, 42)

    assert metadata.is_higher_order is True
    assert metadata.mutation_order == 3
    assert len(metadata.component_faults) == 3
    assert metadata.coupled_to_simple_faults is not None
    assert len(metadata.coupled_to_simple_faults) == 3
    assert metadata.mutation_operator == operators
    assert faulty.id.endswith("__42")
    assert "hom" in faulty.id


def test_higher_order_fault_is_detected_by_oracle() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, _ = mutate_higher_order(
        reference,
        "wrong_target,guard_flip,missing_transition",
        42,
    )

    assert score_oracle_suite(reference, oracle).bpr == 1.0
    assert score_oracle_suite(faulty, oracle).bpr < 1.0


def test_coupling_analysis_estimates_detection_relationship(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")

    first_faulty, first_meta = mutate(reference, "wrong_target", 0)
    higher_faulty, higher_meta = mutate_higher_order(
        reference,
        "wrong_target,guard_flip,missing_transition",
        42,
    )

    dataset_dir = tmp_path / "dataset"
    cases_dir = dataset_dir / "cases"
    _write_complete_case(
        cases_dir / "case_000001",
        reference=reference,
        faulty=first_faulty,
        oracle=oracle,
        metadata=first_meta,
    )
    _write_complete_case(
        cases_dir / "case_000002",
        reference=reference,
        faulty=higher_faulty,
        oracle=oracle,
        metadata=higher_meta,
    )

    report = analyze_dataset_coupling(dataset_dir)

    assert report.case_count == 2
    assert report.first_order_case_count == 1
    assert report.higher_order_case_count == 1
    assert report.first_order_detection_rate == 1.0
    assert report.higher_order_detection_rate == 1.0
    assert report.coupling_effect_estimate == 1.0


def test_coupling_analysis_works_on_legacy_dataset(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)

    dataset_dir = tmp_path / "legacy_dataset"
    _write_complete_case(
        dataset_dir / "cases" / "case_000001",
        reference=reference,
        faulty=faulty,
        oracle=oracle,
        metadata=metadata,
    )

    inspection = inspect_coupling_case_directory(dataset_dir / "cases" / "case_000001")
    assert inspection.is_complete
    assert inspection.layout == "legacy"
    assert set(inspection.detected_files) >= set(COUPLING_CASE_FILES)

    report = analyze_dataset_coupling(dataset_dir)
    assert report.case_count == 1
    assert report.discovery.complete_count == 1


def test_coupling_analysis_works_on_stratified_dataset(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate_higher_order(
        reference,
        "wrong_target,guard_flip,missing_transition",
        42,
    )

    dataset_dir = tmp_path / "stratified_dataset"
    _write_stratified_case(
        dataset_dir / "cases" / "case_000001",
        reference=reference,
        faulty=faulty,
        oracle=oracle,
        metadata=metadata,
    )

    inspection = inspect_coupling_case_directory(dataset_dir / "cases" / "case_000001")
    assert inspection.is_complete
    assert inspection.layout == "stratified"
    assert set(inspection.expected_files) == set(STRATIFIED_CASE_LAYOUT_FILES)

    report = analyze_dataset_coupling(dataset_dir)
    assert report.case_count == 1
    assert report.higher_order_case_count == 1


def test_coupling_analysis_skips_incomplete_cases_with_diagnostics(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 0)

    dataset_dir = tmp_path / "mixed_dataset"
    complete_dir = dataset_dir / "cases" / "case_000001"
    incomplete_dir = dataset_dir / "cases" / "case_000002"
    _write_stratified_case(
        complete_dir,
        reference=reference,
        faulty=faulty,
        oracle=oracle,
        metadata=metadata,
    )
    incomplete_dir.mkdir(parents=True)
    (incomplete_dir / "reference_fsm.json").write_text(
        reference.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    discovery = discover_coupling_case_directories(dataset_dir / "cases")
    assert discovery.total_directories == 2
    assert discovery.complete_count == 1
    assert len(discovery.skipped) == 1
    skipped = discovery.skipped[0]
    assert skipped.case_id == "case_000002"
    assert "missing required file(s)" in (skipped.skip_reason or "")
    assert set(skipped.detected_files) == {"reference_fsm.json"}

    diagnostics = format_coupling_case_discovery(discovery)
    assert "Case directories found: 2" in diagnostics
    assert "Complete cases: 1" in diagnostics
    assert "Expected legacy layout:" in diagnostics
    assert "Expected stratified layout:" in diagnostics
    assert "case_000002" in diagnostics

    report = analyze_dataset_coupling(dataset_dir)
    assert report.case_count == 1
    assert report.discovery.skipped[0].case_id == "case_000002"


def test_cli_mutate_higher_order(tmp_path: Path) -> None:
    faulty_path = tmp_path / "faulty.json"
    meta_path = tmp_path / "bug.json"
    result = runner.invoke(
        app,
        [
            "mutate-higher-order",
            str(FIXTURES / "valid_fsm.json"),
            "--operators",
            "wrong_target,guard_flip,missing_transition",
            "--seed",
            "42",
            "--out",
            str(faulty_path),
            "--meta",
            str(meta_path),
        ],
    )

    assert result.exit_code == 0
    metadata = json.loads(meta_path.read_text(encoding="utf-8"))
    assert metadata["is_higher_order"] is True
    assert metadata["mutation_order"] == 3


def test_cli_coupling_analysis(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate_higher_order(
        reference,
        "wrong_target,guard_flip,missing_transition",
        42,
    )

    dataset_dir = tmp_path / "dataset"
    _write_complete_case(
        dataset_dir / "cases" / "case_000001",
        reference=reference,
        faulty=faulty,
        oracle=oracle,
        metadata=metadata,
    )

    out_path = tmp_path / "coupling_report.json"
    result = runner.invoke(
        app,
        [
            "coupling-analysis",
            str(dataset_dir),
            "--out",
            str(out_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["higher_order_case_count"] == 1
    assert "coupling_effect_estimate" in payload


def test_write_dataset_coupling_report(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "simple_fsm.json")
    oracle = generate_oracle_suite(reference, depth="medium").suite
    faulty, metadata = mutate(reference, "missing_transition", 42)

    dataset_dir = tmp_path / "dataset"
    _write_complete_case(
        dataset_dir / "cases" / "case_000001",
        reference=reference,
        faulty=faulty,
        oracle=oracle,
        metadata=metadata,
    )

    report = analyze_dataset_coupling(dataset_dir)
    out_path = tmp_path / "report.json"
    write_dataset_coupling_report(out_path, report)

    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["first_order_case_count"] == 1
