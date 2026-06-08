"""Tests for natural-language requirement generation."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.models import FSM, State, Transition
from fsmrepairbench.requirement_generation import (
    export_requirements_txt,
    generate_requirements,
    generate_requirements_from_path,
)
from fsmrepairbench.validators import load_fsm

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


def test_generate_requirements_links_fsm_id() -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    result = generate_requirements(fsm, style="concise")

    assert result.fsm_id == "toggle_001"
    assert result.fsm_name == "Toggle"
    assert len(result.items) == 3
    assert result.items[0].requirement_id == "R1"
    assert "off" in result.items[0].text.lower()


def test_all_styles_preserve_core_semantics() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    styles = ("concise", "verbose", "ambiguous", "industrial")

    for style in styles:
        result = generate_requirements(fsm, style=style)
        combined = "\n".join(result.lines).lower()
        assert result.fsm_id == "parking_gate_001"
        assert len(result.items) == 4
        assert "closed" in combined
        assert "car arrives" in combined or "car_arrives" in combined
        assert "open" in combined


def test_self_loop_with_guard_describes_rejection() -> None:
    fsm = load_fsm(FIXTURES / "valid_fsm.json")
    result = generate_requirements(fsm, style="verbose")
    rejection = next(item for item in result.items if item.transition_id == "t1")

    assert "remain" in rejection.text.lower() or "closed" in rejection.text.lower()
    assert "ticket invalid" in rejection.text.lower() or "ticket_invalid" in rejection.text.lower()


def test_export_requirements_txt_includes_header(tmp_path: Path) -> None:
    fsm = load_fsm(FIXTURES / "simple_fsm.json")
    result = generate_requirements(fsm, style="industrial")
    output = tmp_path / "requirements.txt"
    export_requirements_txt(result, output)

    text = output.read_text(encoding="utf-8")
    assert "FSM-ID: toggle_001" in text
    assert "Style: industrial" in text
    assert "R1:" in text
    assert text.endswith("\n")


def test_honours_existing_transition_requirement_ids() -> None:
    fsm = FSM(
        id="custom_001",
        name="Custom",
        states=[State(id="a"), State(id="b")],
        initial_state="a",
        events=["go"],
        transitions=[
            Transition(
                id="t1",
                source="a",
                event="go",
                target="b",
                requirements=["R9"],
            )
        ],
    )
    result = generate_requirements(fsm, style="concise")

    ids = {item.requirement_id for item in result.items}
    assert "R9" in ids
    assert len(result.items) == 2


def test_generate_requirements_from_path() -> None:
    result = generate_requirements_from_path(FIXTURES / "simple_fsm.json", style="verbose")
    assert result.fsm_id == "toggle_001"
    assert "shall begin" in result.items[0].text.lower()


def test_fsm_without_reachable_transitions_still_describes_initial_state() -> None:
    fsm = FSM(
        id="idle",
        name="Idle",
        states=[State(id="a"), State(id="b")],
        initial_state="a",
        events=["go"],
        transitions=[
            Transition(id="t1", source="b", event="go", target="a"),
        ],
    )
    result = generate_requirements(fsm, style="concise")

    assert len(result.items) == 1
    assert result.items[0].requirement_id == "R1"
    assert "idle" in result.items[0].text.lower()


def test_cli_generate_requirements(tmp_path: Path) -> None:
    output = tmp_path / "requirements.txt"
    result = runner.invoke(
        app,
        [
            "generate-requirements",
            str(FIXTURES / "simple_fsm.json"),
            "--out",
            str(output),
            "--style",
            "concise",
        ],
    )

    assert result.exit_code == 0
    text = output.read_text(encoding="utf-8")
    assert "FSM-ID: toggle_001" in text
    assert "Generated 3 requirements" in result.stdout
