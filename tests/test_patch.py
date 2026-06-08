"""Tests for FSM repair patches."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM
from fsmrepairbench.mutators import mutate
from fsmrepairbench.patch import (
    FSMPatch,
    PatchError,
    RemoveTransitionOperation,
    ReplaceInitialStateOperation,
    ReplaceTransitionTargetOperation,
    apply_patch,
    validate_patch,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import is_valid_fsm, load_fsm, load_oracle_suite

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _faulty_wrong_target(reference: FSM) -> tuple[FSM, str, str]:
    faulty, metadata = mutate(reference, "wrong_target", 42)
    transition_id = metadata.changed_transition_id
    assert transition_id is not None
    reference_target = next(
        transition.target
        for transition in reference.transitions
        if transition.id == transition_id
    )
    return faulty, transition_id, reference_target


def test_valid_patch_improves_fsm() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    oracle = load_oracle_suite(FIXTURES / "valid_oracle.json")
    faulty, transition_id, reference_target = _faulty_wrong_target(reference)

    assert score_oracle_suite(faulty, oracle).bpr < 1.0

    patch = FSMPatch(
        patch_id="patch_001",
        target_fsm_id=faulty.id,
        operations=[
            ReplaceTransitionTargetOperation(
                transition_id=transition_id,
                target=reference_target,
            )
        ],
    )

    assert validate_patch(faulty, patch) == []
    repaired = apply_patch(faulty, patch)
    assert is_valid_fsm(repaired)
    assert score_oracle_suite(repaired, oracle).bpr == pytest.approx(1.0)


def test_invalid_patch_rejected() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, _, _ = _faulty_wrong_target(reference)
    patch = FSMPatch(
        patch_id="patch_bad",
        target_fsm_id=faulty.id,
        operations=[
            ReplaceInitialStateOperation(initial_state="missing_state"),
        ],
    )

    errors = validate_patch(faulty, patch)
    assert any("initial_state" in error for error in errors)


def test_remove_unknown_transition_rejected() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    patch = FSMPatch(
        patch_id="patch_remove",
        target_fsm_id=reference.id,
        operations=[RemoveTransitionOperation(transition_id="does_not_exist")],
    )

    errors = validate_patch(reference, patch)
    assert any("Unknown transition id" in error for error in errors)

    with pytest.raises(PatchError, match="Unknown transition id"):
        apply_patch(reference, patch)


def test_patch_target_fsm_id_mismatch() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    patch = FSMPatch(
        patch_id="patch_mismatch",
        target_fsm_id="other_fsm",
        operations=[],
    )

    errors = validate_patch(reference, patch)
    assert any("target_fsm_id" in error for error in errors)


def test_add_transition_validates_references() -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    patch = FSMPatch.model_validate(
        {
            "patch_id": "patch_add",
            "target_fsm_id": reference.id,
            "operations": [
                {
                    "op": "add_transition",
                    "id": "new_t",
                    "source": "closed",
                    "event": "car_arrives",
                    "target": "missing",
                }
            ],
        }
    )

    errors = validate_patch(reference, patch)
    assert any("target 'missing'" in error for error in errors)


def test_cli_apply_patch_writes_repaired_fsm(tmp_path: Path) -> None:
    reference = load_fsm(FIXTURES / "valid_fsm.json")
    faulty, transition_id, reference_target = _faulty_wrong_target(reference)
    faulty_path = tmp_path / "faulty.json"
    faulty_path.write_text(faulty.model_dump_json(indent=2) + "\n", encoding="utf-8")

    patch_path = tmp_path / "patch.json"
    patch_path.write_text(
        json.dumps(
            {
                "patch_id": "patch_001",
                "target_fsm_id": faulty.id,
                "operations": [
                    {
                        "op": "replace_transition_target",
                        "transition_id": transition_id,
                        "target": reference_target,
                    }
                ],
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    out_path = tmp_path / "repaired.json"

    result = runner.invoke(
        app,
        [
            "apply-patch",
            str(faulty_path),
            str(patch_path),
            "--out",
            str(out_path),
        ],
    )

    assert result.exit_code == 0
    assert out_path.exists()
    repaired = load_fsm(out_path)
    assert is_valid_fsm(repaired)
