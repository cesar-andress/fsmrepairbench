"""Stratified dataset generation specifications."""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator

from fsmrepairbench.taxonomy import (
    ArityClass,
    BugType,
    Completeness,
    Determinism,
    GraphStructure,
    GuardComplexity,
    MachineType,
    OracleDepth,
    SizeClass,
    TimeFeature,
)


class StratifiedSpecError(ValueError):
    """Raised when a dataset plan cannot be loaded or validated."""


class GenerationCell(BaseModel):
    """One stratum in a stratified benchmark generation plan."""

    machine_type: MachineType
    determinism: Determinism
    completeness: Completeness
    arity_class: ArityClass
    size_class: SizeClass
    guard_complexity: GuardComplexity
    time_features: list[TimeFeature]
    graph_structure: list[GraphStructure]
    oracle_depth: OracleDepth
    bug_type: BugType
    count: int = Field(ge=1)

    @field_validator(
        "machine_type",
        "determinism",
        "completeness",
        "arity_class",
        "size_class",
        "guard_complexity",
        "oracle_depth",
        "bug_type",
        mode="before",
    )
    @classmethod
    def _coerce_enum(cls, value: str | object) -> object:
        return value

    @field_validator("time_features", "graph_structure", mode="before")
    @classmethod
    def _coerce_list(cls, value: list[str] | str) -> list[str]:
        if isinstance(value, str):
            return [value]
        return value


class DatasetPlan(BaseModel):
    """Full stratified dataset generation plan."""

    name: str
    version: str
    seed: int
    cells: list[GenerationCell] = Field(min_length=1)


def load_dataset_plan(path: Path) -> DatasetPlan:
    """Load a dataset plan from JSON or YAML."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        msg = f"Failed to read dataset plan: {exc}"
        raise StratifiedSpecError(msg) from exc

    try:
        if path.suffix.lower() in {".yaml", ".yml"}:
            raw = yaml.safe_load(raw_text)
        else:
            raw = json.loads(raw_text)
    except (yaml.YAMLError, json.JSONDecodeError) as exc:
        msg = f"Invalid dataset plan format in '{path}': {exc}"
        raise StratifiedSpecError(msg) from exc

    if not isinstance(raw, dict):
        msg = f"Dataset plan must be a mapping: {path}"
        raise StratifiedSpecError(msg)

    try:
        return DatasetPlan.model_validate(raw)
    except Exception as exc:
        msg = f"Invalid dataset plan schema in '{path}': {exc}"
        raise StratifiedSpecError(msg) from exc


def total_planned_cases(plan: DatasetPlan) -> int:
    """Return the total number of cases requested by *plan*."""
    return sum(cell.count for cell in plan.cells)
