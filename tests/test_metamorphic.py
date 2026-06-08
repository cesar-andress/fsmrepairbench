"""Tests for metamorphic testing support."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.metamorphic import (
    SUPPORTED_RELATIONS,
    MetamorphicError,
    check_metamorphic_relation,
    generate_metamorphic_case,
    generate_metamorphic_cases,
    load_score_result,
    metamorphic_check_to_dict,
)
from fsmrepairbench.models import BugMetadata, FSM, OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.scorer import score_oracle_suite, write_score_json
from fsmrepairbench.validators import load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _write_complete_case(
    case_dir: Path,
    *,
    reference: FSM,
    faulty: FSM,
    oracle: OracleSuite,
    metadata: BugMetadata,
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


@pytest.fixture
def parking_case(tmp_path: Path) -> Path:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, metadata = mutate(reference, "wrong_target", 42)
    case_dir = tmp_path / "case_000001"
    _write_complete_case(case_dir, reference=reference, faulty=faulty, oracle=oracle, metadata=metadata)
    return case_dir


@pytest.mark.parametrize("relation", SUPPORTED_RELATIONS)
def test_metamorphic_relations_preserve_reference_bpr(
    parking_case: Path,
    relation: str,
) -> None:
    bundle = generate_metamorphic_case(parking_case, relation=relation)  # type: ignore[arg-type]
    if bundle is None:
        pytest.skip(f"Relation '{relation}' not applicable to parking gate case")

    source_score = score_oracle_suite(bundle.source_reference, bundle.source_oracle)
    followup_score = score_oracle_suite(bundle.followup_reference, bundle.followup_oracle)
    report = check_metamorphic_relation(
        source_score,
        followup_score,
        relation=relation,  # type: ignore[arg-type]
    )

    assert report.holds, report.rationale


def test_generate_metamorphic_cases_writes_manifest(parking_case: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "metamorphic"
    report = generate_metamorphic_cases(parking_case, out_dir)

    assert report.generated
    manifest = json.loads((out_dir / "metamorphic_manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_case_dir"] == str(parking_case)
    assert len(manifest["generated_relations"]) == len(report.generated)

    first = report.generated[0]
    followup_dir = out_dir / first.relation_id
    assert (followup_dir / "reference_fsm.json").is_file()
    assert (followup_dir / "faulty_fsm.json").is_file()
    assert (followup_dir / "oracle_suite.json").is_file()
    assert (followup_dir / "metamorphic_metadata.json").is_file()


def test_check_metamorphic_detects_bpr_violation() -> None:
    source = score_oracle_suite(
        load_fsm(FIXTURES / "valid_fsm.json"),
        load_oracle_suite(FIXTURES / "valid_oracle.json"),
    )
    faulty, _ = mutate(load_fsm(FIXTURES / "valid_fsm.json"), "wrong_target", 42)
    followup = score_oracle_suite(faulty, load_oracle_suite(FIXTURES / "valid_oracle.json"))

    report = check_metamorphic_relation(
        source,
        followup,
        relation="state_renaming_invariance",
    )

    assert not report.holds
    assert report.violations


def test_timeout_scaling_relation_on_timed_fsm(tmp_path: Path) -> None:
    timed_fsm = FSM.model_validate(
        {
            "id": "timed_gate",
            "name": "Timed Gate",
            "states": [{"id": "closed"}, {"id": "open"}],
            "initial_state": "closed",
            "events": ["open", "timeout"],
            "transitions": [
                {
                    "id": "t_open",
                    "source": "closed",
                    "event": "open",
                    "target": "open",
                },
                {
                    "id": "t_timeout",
                    "source": "open",
                    "event": "timeout",
                    "target": "closed",
                    "timeout": 5.0,
                },
            ],
        }
    )
    oracle = OracleSuite(
        id="timed_oracle",
        fsm_id=timed_fsm.id,
        scenarios=[
            {
                "id": "open_close",
                "steps": [
                    {"event": "open", "expected_state": "open"},
                    {"event": "timeout", "expected_state": "closed"},
                ],
            }
        ],
    )
    faulty, metadata = mutate(timed_fsm, "timeout_corruption", 7)
    case_dir = tmp_path / "timed_case"
    _write_complete_case(
        case_dir,
        reference=timed_fsm,
        faulty=faulty,
        oracle=oracle,
        metadata=metadata,
    )

    bundle = generate_metamorphic_case(case_dir, relation="timeout_scaling_relation")
    assert bundle is not None

    source_score = score_oracle_suite(bundle.source_reference, bundle.source_oracle)
    followup_score = score_oracle_suite(bundle.followup_reference, bundle.followup_oracle)
    report = check_metamorphic_relation(
        source_score,
        followup_score,
        relation="timeout_scaling_relation",
    )
    assert report.holds


def test_metamorphic_check_to_dict() -> None:
    source = score_oracle_suite(
        load_fsm(FIXTURES / "simple_fsm.json"),
        load_oracle_suite(FIXTURES / "simple_oracle.json"),
    )
    report = check_metamorphic_relation(
        source,
        source,
        relation="transition_order_invariance",
    )
    payload = metamorphic_check_to_dict(report)

    assert payload["relation_id"] == "transition_order_invariance"
    assert payload["holds"] is True


def test_cli_generate_metamorphic_cases(parking_case: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "meta_out"
    result = runner.invoke(
        app,
        [
            "generate-metamorphic-cases",
            str(parking_case),
            "--out",
            str(out_dir),
            "--relations",
            "state_renaming_invariance,event_alias_relation",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert (out_dir / "metamorphic_manifest.json").is_file()
    assert (out_dir / "state_renaming_invariance" / "reference_fsm.json").is_file()


def test_cli_check_metamorphic_holds(parking_case: Path, tmp_path: Path) -> None:
    reference = load_fsm(parking_case / "reference_fsm.json")
    oracle = load_oracle_suite(parking_case / "oracle_suite.json")
    bundle = generate_metamorphic_case(parking_case, relation="event_alias_relation")
    assert bundle is not None

    source_path = tmp_path / "source_score.json"
    followup_path = tmp_path / "followup_score.json"
    write_score_json(source_path, score_oracle_suite(reference, oracle))
    write_score_json(
        followup_path,
        score_oracle_suite(bundle.followup_reference, bundle.followup_oracle),
    )

    result = runner.invoke(
        app,
        [
            "check-metamorphic",
            str(source_path),
            str(followup_path),
            "--relation",
            "event_alias_relation",
        ],
    )

    assert result.exit_code == 0, result.stdout


def test_cli_check_metamorphic_rejects_unknown_relation(tmp_path: Path) -> None:
    source_path = tmp_path / "source.json"
    followup_path = tmp_path / "followup.json"
    score = score_oracle_suite(
        load_fsm(FIXTURES / "simple_fsm.json"),
        load_oracle_suite(FIXTURES / "simple_oracle.json"),
    )
    write_score_json(source_path, score)
    write_score_json(followup_path, score)

    result = runner.invoke(
        app,
        [
            "check-metamorphic",
            str(source_path),
            str(followup_path),
            "--relation",
            "not_a_relation",
        ],
    )

    assert result.exit_code == 1


def test_load_score_result_round_trip(tmp_path: Path) -> None:
    score = score_oracle_suite(
        load_fsm(FIXTURES / "simple_fsm.json"),
        load_oracle_suite(FIXTURES / "simple_oracle.json"),
    )
    path = tmp_path / "score.json"
    write_score_json(path, score)

    loaded = load_score_result(path)
    assert loaded.bpr == score.bpr
    assert loaded.total_steps == score.total_steps


def test_generate_metamorphic_case_missing_files(tmp_path: Path) -> None:
    case_dir = tmp_path / "empty_case"
    case_dir.mkdir()

    with pytest.raises(MetamorphicError, match="Missing required case file"):
        generate_metamorphic_case(case_dir, relation="state_renaming_invariance")
