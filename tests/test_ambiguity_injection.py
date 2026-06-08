"""Tests for requirement ambiguity injection."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.ambiguity_injection import (
    AMBIGUITY_CLASSES,
    AMBIGUITY_METADATA_FILENAME,
    inject_requirement_ambiguity,
)
from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def _composite_fsm() -> FSM:
    return FSM(
        id="ambiguity_demo",
        name="Ambiguity Demo",
        description="FSM covering all ambiguity injection classes.",
        states=[State(id="idle"), State(id="busy"), State(id="done")],
        initial_state="idle",
        events=["start", "finish", "retry"],
        transitions=[
            Transition(
                id="t_guard_loop",
                source="busy",
                event="retry",
                target="busy",
                guard="queue_full",
                action="log_retry",
            ),
            Transition(
                id="t_guard_move",
                source="idle",
                event="start",
                target="busy",
                guard="resources_available",
                action="allocate",
            ),
            Transition(
                id="t_timed",
                source="busy",
                event="finish",
                target="done",
                timeout=30.0,
                action="complete_job",
            ),
            Transition(
                id="t_plain",
                source="done",
                event="start",
                target="idle",
            ),
        ],
    )


def test_inject_requirement_ambiguity_assigns_classes() -> None:
    result = inject_requirement_ambiguity(_composite_fsm(), clear_style="concise")

    classes = {injection.ambiguity_class for injection in result.injections}
    assert classes == set(AMBIGUITY_CLASSES)
    assert result.fsm_id == "ambiguity_demo"
    assert all(
        injection.original_text != injection.ambiguous_text for injection in result.injections
    )


def test_missing_condition_drops_guard_from_clear_requirement() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    result = inject_requirement_ambiguity(fsm, clear_style="verbose")

    guarded = next(
        injection
        for injection in result.injections
        if injection.transition_id == "t2" and injection.ambiguity_class == "missing_condition"
    )
    assert "ticket_valid" in guarded.dropped_elements
    assert "ticket valid" not in guarded.ambiguous_text.lower()


def test_incomplete_exception_covers_self_loop() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    result = inject_requirement_ambiguity(fsm, clear_style="concise")

    rejection = next(
        injection
        for injection in result.injections
        if injection.transition_id == "t1"
    )
    assert rejection.ambiguity_class == "incomplete_exception"
    assert "handles the event" in rejection.ambiguous_text.lower()


def test_temporal_ambiguity_softens_timeout() -> None:
    result = inject_requirement_ambiguity(_composite_fsm(), clear_style="concise")
    timed = next(
        injection
        for injection in result.injections
        if injection.transition_id == "t_timed"
    )

    assert timed.ambiguity_class == "temporal_ambiguity"
    assert "timeout=30.0" in timed.dropped_elements
    assert "eventually" in timed.ambiguous_text.lower()


def test_cli_inject_ambiguity_writes_outputs(tmp_path: Path) -> None:
    requirements_out = tmp_path / "requirements_ambiguous.txt"
    metadata_out = tmp_path / AMBIGUITY_METADATA_FILENAME

    result = runner.invoke(
        app,
        [
            "inject-ambiguity",
            str(FIXTURES / "simple_fsm.json"),
            "--out",
            str(requirements_out),
            "--metadata-out",
            str(metadata_out),
            "--clear-style",
            "concise",
        ],
    )

    assert result.exit_code == 0
    assert requirements_out.is_file()
    assert metadata_out.is_file()

    requirements_text = requirements_out.read_text(encoding="utf-8")
    metadata = json.loads(metadata_out.read_text(encoding="utf-8"))

    assert "FSM-ID: toggle_001" in requirements_text
    assert metadata["fsm_id"] == "toggle_001"
    assert len(metadata["injections"]) == 3
    assert metadata["injections"][0]["original_text"]
    assert metadata["injections"][0]["ambiguous_text"]
    assert "Injected ambiguity into 3 requirements" in result.stdout
