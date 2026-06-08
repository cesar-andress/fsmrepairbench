"""Tests for the FSM literature knowledge base."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.literature import (
    GenerationSupport,
    LiteratureError,
    build_literature_index,
    filter_literature_entries,
    get_literature_entry,
    load_literature_taxonomy,
    write_literature_index_json,
)

DATA_PATH = Path(__file__).resolve().parents[1] / "data" / "literature" / "literature_taxonomy.yaml"
runner = CliRunner()

EXPECTED_IDS = {
    "dfa",
    "nfa",
    "mealy",
    "moore",
    "efsm",
    "timed_fsm",
    "timed_automata",
    "interface_automata",
    "register_automata",
    "statecharts",
    "hierarchical_fsm",
    "uml_state_machines",
}


def test_literature_taxonomy_loads() -> None:
    taxonomy = load_literature_taxonomy(DATA_PATH)
    assert taxonomy.version == "1.0"
    assert len(taxonomy.entries) == 12
    assert {entry.id for entry in taxonomy.entries} == EXPECTED_IDS


def test_literature_entry_fields_are_populated() -> None:
    entry = get_literature_entry("efsm", DATA_PATH)
    assert entry.name == "EFSM"
    assert entry.category == "extended"
    assert entry.references
    assert entry.features
    assert entry.formal_definition
    assert entry.generation_support is GenerationSupport.FULL


def test_filter_literature_entries_by_category() -> None:
    timed = filter_literature_entries(category="timed", path=DATA_PATH)
    assert {entry.id for entry in timed} == {"timed_fsm", "timed_automata"}


def test_build_literature_index_json(tmp_path: Path) -> None:
    result = build_literature_index(DATA_PATH)
    output = tmp_path / "index.json"
    write_literature_index_json(output, result)
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["entry_count"] == 12
    assert payload["entries"][0]["id"]


def test_get_unknown_entry_raises() -> None:
    try:
        get_literature_entry("unknown", DATA_PATH)
        raised = False
    except LiteratureError:
        raised = True
    assert raised


def test_cli_literature_index_table() -> None:
    result = runner.invoke(app, ["literature-index", str(DATA_PATH)])
    assert result.exit_code == 0
    assert "FSM Literature Taxonomy" in result.stdout
    assert "efsm" in result.stdout


def test_cli_literature_index_single_entry_json(tmp_path: Path) -> None:
    out = tmp_path / "efsm.json"
    result = runner.invoke(
        app,
        ["literature-index", str(DATA_PATH), "--id", "mealy", "--json", "--out", str(out)],
    )
    assert result.exit_code == 0
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["id"] == "mealy"
    assert payload["generation_support"] == "full"


def test_cli_literature_index_filter_category() -> None:
    result = runner.invoke(
        app,
        ["literature-index", str(DATA_PATH), "--category", "hierarchical"],
    )
    assert result.exit_code == 0
    assert "Statecharts" in result.stdout
    assert "Entries: 2" in result.stdout
