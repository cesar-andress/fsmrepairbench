"""Machine-readable FSM literature knowledge base."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

LITERATURE_TAXONOMY_FILENAME = "literature_taxonomy.yaml"


class GenerationSupport(StrEnum):
    """How fully FSMRepairBench can generate instances of a literature family."""

    FULL = "full"
    PARTIAL = "partial"
    PLANNED = "planned"
    REFERENCE_ONLY = "reference_only"
    NONE = "none"


class LiteratureEntry(BaseModel):
    """One FSM family entry in the literature knowledge base."""

    id: str
    name: str
    category: str
    description: str
    formal_definition: str
    references: list[str]
    features: list[str] = Field(default_factory=list)
    repair_relevance: str
    generation_support: GenerationSupport


class LiteratureTaxonomy(BaseModel):
    """Top-level literature taxonomy document."""

    version: str
    description: str = ""
    entries: list[LiteratureEntry] = Field(min_length=1)


class LiteratureError(ValueError):
    """Raised when literature data cannot be loaded or queried."""


@dataclass(frozen=True)
class LiteratureIndexResult:
    """Resolved literature index for CLI or programmatic use."""

    taxonomy_path: Path
    taxonomy: LiteratureTaxonomy
    entries: tuple[LiteratureEntry, ...]


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def default_literature_taxonomy_path() -> Path:
    """Return the default path to ``literature_taxonomy.yaml``."""
    candidates = (
        _package_root() / "data" / "literature" / LITERATURE_TAXONOMY_FILENAME,
        Path("data") / "literature" / LITERATURE_TAXONOMY_FILENAME,
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return candidates[0].resolve()


def load_literature_taxonomy(path: Path | None = None) -> LiteratureTaxonomy:
    """Load and validate the literature taxonomy from *path*."""
    taxonomy_path = path or default_literature_taxonomy_path()
    if not taxonomy_path.is_file():
        msg = f"Literature taxonomy not found: {taxonomy_path}"
        raise LiteratureError(msg)

    try:
        raw = yaml.safe_load(taxonomy_path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Failed to read literature taxonomy: {exc}"
        raise LiteratureError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in literature taxonomy: {exc}"
        raise LiteratureError(msg) from exc

    if not isinstance(raw, dict):
        msg = "Literature taxonomy must be a YAML mapping"
        raise LiteratureError(msg)

    try:
        return LiteratureTaxonomy.model_validate(raw)
    except Exception as exc:
        msg = f"Invalid literature taxonomy schema: {exc}"
        raise LiteratureError(msg) from exc


def build_literature_index(path: Path | None = None) -> LiteratureIndexResult:
    """Load the literature taxonomy and return an index result."""
    taxonomy_path = path or default_literature_taxonomy_path()
    taxonomy = load_literature_taxonomy(taxonomy_path)
    return LiteratureIndexResult(
        taxonomy_path=taxonomy_path,
        taxonomy=taxonomy,
        entries=tuple(taxonomy.entries),
    )


def get_literature_entry(entry_id: str, path: Path | None = None) -> LiteratureEntry:
    """Return one literature entry by *entry_id*."""
    taxonomy = load_literature_taxonomy(path)
    for entry in taxonomy.entries:
        if entry.id == entry_id:
            return entry
    known = ", ".join(item.id for item in taxonomy.entries)
    msg = f"Unknown literature entry '{entry_id}'. Known: {known}"
    raise LiteratureError(msg)


def filter_literature_entries(
    *,
    category: str | None = None,
    generation_support: GenerationSupport | None = None,
    path: Path | None = None,
) -> list[LiteratureEntry]:
    """Return literature entries matching optional filters."""
    taxonomy = load_literature_taxonomy(path)
    results = list(taxonomy.entries)
    if category is not None:
        normalized = category.strip().lower()
        results = [entry for entry in results if entry.category.lower() == normalized]
    if generation_support is not None:
        results = [entry for entry in results if entry.generation_support is generation_support]
    return results


def literature_index_to_dict(result: LiteratureIndexResult) -> dict[str, Any]:
    """Return a JSON-serialisable index payload."""
    return {
        "version": result.taxonomy.version,
        "description": result.taxonomy.description,
        "taxonomy_path": str(result.taxonomy_path),
        "entry_count": len(result.entries),
        "entries": [entry.model_dump(mode="json") for entry in result.entries],
    }


def write_literature_index_json(path: Path, result: LiteratureIndexResult) -> None:
    """Write a machine-readable literature index to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(literature_index_to_dict(result), indent=2) + "\n", encoding="utf-8")
