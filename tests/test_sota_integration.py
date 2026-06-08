"""Tests for SOTA integration modules."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.constrained_input import generate_constrained_inputs, validate_plan_coverage
from fsmrepairbench.coupling_tracker import track_coupling_effect
from fsmrepairbench.hierarchical_fsm import (
    HierarchicalFSM,
    flatten_hierarchical_fsm,
    generate_hierarchical_oracle,
)
from fsmrepairbench.mutators import mutate
from fsmrepairbench.mutation_advanced import ADVANCED_MUTATION_OPERATORS, classify_mutation_complexity
from fsmrepairbench.oracle_generator import generate_oracle_suite
from fsmrepairbench.spec_coverage import compute_spec_coverage
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_spec_coverage_reports_transition_pair_and_sequence_metrics() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    suite = load_oracle_suite(FIXTURES / "simple_oracle.json")

    report = compute_spec_coverage(fsm, suite, max_sequence_length=2)

    assert report.transition_coverage == 1.0
    assert report.transition_pair_coverage >= 0.0
    assert report.sequence_coverage >= 0.0
    assert report.machine_type.value in {"plain_fsm", "mealy", "moore"}


def test_advanced_mutation_operators_tag_complexity_and_scope() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "guard_inter_class", 7)

    assert metadata.mutation_operator == "guard_inter_class"
    assert metadata.mutation_complexity == "complex"
    assert metadata.mutation_scope == "inter_class"
    assert metadata.mutation_mode == "selective"
    assert faulty.id != reference.id


def test_coupling_report_detects_faulty_bpr_drop() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    suite = generate_oracle_suite(reference, depth="medium").suite
    faulty, metadata = mutate(reference, "wrong_target", 42)

    report = track_coupling_effect(reference, faulty, suite, metadata)

    assert classify_mutation_complexity(metadata.mutation_operator) == "simple"
    assert report.reference_bpr == 1.0
    assert report.faulty_bpr < 1.0
    assert report.fault_detectable


def test_hierarchical_fsm_flattens_and_generates_multi_level_oracle() -> None:
    payload = json.loads((FIXTURES / "hierarchical_web.json").read_text(encoding="utf-8"))
    hierarchical = HierarchicalFSM.model_validate(payload)

    flat = flatten_hierarchical_fsm(hierarchical)
    suite = generate_hierarchical_oracle(hierarchical, depth="shallow")

    assert any(state.id.startswith("checkout__") for state in flat.states)
    assert len(suite.scenarios) > 1
    assert suite.fsm_id == "web_portal"


def test_constrained_input_generation_meets_coverage_target() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    plan = generate_constrained_inputs(fsm, target_transition_coverage=1.0, max_path_length=4)

    assert plan.achieved_transition_coverage == 1.0
    assert len(plan.sequences) >= 1
    assert validate_plan_coverage(fsm, plan) == 1.0


def test_cli_spec_coverage_exports_json_and_csv(tmp_path: Path) -> None:
    json_path = tmp_path / "spec.json"
    csv_path = tmp_path / "spec.csv"
    result = runner.invoke(
        app,
        [
            "spec-coverage",
            str(FIXTURES / "simple_fsm.json"),
            str(FIXTURES / "simple_oracle.json"),
            "--out-json",
            str(json_path),
            "--out-csv",
            str(csv_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert "transition_coverage" in payload
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows
    assert rows[0]["metric"] == "transition"


def test_cli_coupling_report_exports_machine_readable_outputs(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, metadata = mutate(reference, "wrong_target", 42)
    oracle = generate_oracle_suite(reference, depth="medium").suite

    reference_path = tmp_path / "reference.json"
    faulty_path = tmp_path / "faulty.json"
    oracle_path = tmp_path / "oracle.json"
    metadata_path = tmp_path / "bug.json"
    json_path = tmp_path / "coupling.json"
    csv_path = tmp_path / "coupling.csv"

    reference_path.write_text(reference.model_dump_json(indent=2) + "\n", encoding="utf-8")
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")
    oracle_path.write_text(oracle.model_dump_json(indent=2) + "\n", encoding="utf-8")
    metadata_path.write_text(metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")

    result = runner.invoke(
        app,
        [
            "coupling-report",
            str(reference_path),
            str(faulty_path),
            str(oracle_path),
            str(metadata_path),
            "--out-json",
            str(json_path),
            "--out-csv",
            str(csv_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["fault_detectable"] is True
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0]["mutation_operator"] == "wrong_target"


def test_cli_generate_constrained_inputs_exports_json_and_csv(tmp_path: Path) -> None:
    json_path = tmp_path / "inputs.json"
    csv_path = tmp_path / "inputs.csv"
    result = runner.invoke(
        app,
        [
            "generate-constrained-inputs",
            str(FIXTURES / "simple_fsm.json"),
            "--out-json",
            str(json_path),
            "--out-csv",
            str(csv_path),
            "--quiet",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["sequences"]
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert rows

def test_advanced_operators_registered() -> None:
    from fsmrepairbench.mutators import MUTATION_OPERATORS

    for operator in ADVANCED_MUTATION_OPERATORS:
        assert operator in MUTATION_OPERATORS
