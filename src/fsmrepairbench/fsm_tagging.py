"""Structural tagging and metadata export for finite-state machines."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field

from fsmrepairbench.difficulty import (
    compute_average_path_length,
    compute_cycle_count,
    compute_difficulty_metrics,
    compute_strongly_connected_components,
    reachable_state_ids,
)
from fsmrepairbench.hierarchical_fsm import HierarchicalFSM, flatten_hierarchical_fsm
from fsmrepairbench.models import FSM
from fsmrepairbench.taxonomy import (
    GraphStructure,
    infer_determinism,
    infer_graph_structure,
    infer_guard_complexity,
    infer_machine_type,
    infer_size_class,
    infer_time_features,
)
from fsmrepairbench.validators import load_fsm_json, validate_fsm

SizeTag = Literal["small", "medium", "large"]
DeterminismTag = Literal["deterministic", "non_deterministic"]
GraphTag = Literal["acyclic", "cyclic"]

SUPPORTED_FSM_TAGS: tuple[str, ...] = (
    "small",
    "medium",
    "large",
    "deterministic",
    "non_deterministic",
    "acyclic",
    "cyclic",
    "hierarchical",
    "timed",
    "extended",
    "high_branching",
    "deep_paths",
    "high_mutation_resistance",
)

METADATA_CSV_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "filename",
    "source_kind",
    "num_states",
    "num_transitions",
    "num_events",
    "reachable_states",
    "avg_branching",
    "max_out_degree",
    "avg_path_length",
    "cycle_count",
    "mutation_score",
    "size_tag",
    "determinism_tag",
    "graph_tag",
    "tags",
    *SUPPORTED_FSM_TAGS,
)

HIGH_BRANCHING_AVG_THRESHOLD = 3.0
HIGH_BRANCHING_MAX_THRESHOLD = 5
DEEP_PATH_THRESHOLD = 4.0
HIGH_MUTATION_RESISTANCE_THRESHOLD = 0.35


class FSMTaggingError(ValueError):
    """Raised when FSM tagging fails."""


class FSMTagRecord(BaseModel):
    """Tag metadata for one analyzed FSM."""

    fsm_id: str
    filename: str
    source_kind: Literal["fsm", "hierarchical_fsm"] = "fsm"
    num_states: int = Field(ge=0)
    num_transitions: int = Field(ge=0)
    num_events: int = Field(ge=0)
    reachable_states: int = Field(ge=0)
    avg_branching: float = Field(ge=0.0)
    max_out_degree: int = Field(ge=0)
    avg_path_length: float = Field(ge=0.0)
    cycle_count: int = Field(ge=0)
    mutation_score: float | None = Field(default=None, ge=0.0, le=1.0)
    size_tag: SizeTag
    determinism_tag: DeterminismTag
    graph_tag: GraphTag
    tags: list[str] = Field(default_factory=list)
    tag_flags: dict[str, bool] = Field(default_factory=dict)

    def to_csv_row(self) -> dict[str, object]:
        row: dict[str, object] = {
            "fsm_id": self.fsm_id,
            "filename": self.filename,
            "source_kind": self.source_kind,
            "num_states": self.num_states,
            "num_transitions": self.num_transitions,
            "num_events": self.num_events,
            "reachable_states": self.reachable_states,
            "avg_branching": round(self.avg_branching, 4),
            "max_out_degree": self.max_out_degree,
            "avg_path_length": round(self.avg_path_length, 4),
            "cycle_count": self.cycle_count,
            "mutation_score": "" if self.mutation_score is None else round(self.mutation_score, 4),
            "size_tag": self.size_tag,
            "determinism_tag": self.determinism_tag,
            "graph_tag": self.graph_tag,
            "tags": "|".join(self.tags),
        }
        for tag in SUPPORTED_FSM_TAGS:
            row[tag] = int(self.tag_flags.get(tag, False))
        return row


@dataclass(frozen=True)
class FSMTaggingResult:
    """Paths written by an FSM tagging run."""

    source_root: Path
    metadata_csv_path: Path
    records: tuple[FSMTagRecord, ...]
    skipped_files: tuple[str, ...]


def _max_out_degree(fsm: FSM, reachable: set[str]) -> int:
    counts: dict[str, int] = dict.fromkeys(reachable, 0)
    for transition in fsm.transitions:
        if transition.source in reachable:
            counts[transition.source] += 1
    return max(counts.values()) if counts else 0


def _size_tag_from_state_count(state_count: int) -> SizeTag:
    size_class = infer_size_class(state_count)
    if size_class.value in {"tiny", "small"}:
        return "small"
    if size_class.value == "medium":
        return "medium"
    return "large"


def _is_extended_fsm(fsm: FSM) -> bool:
    machine_type = infer_machine_type(fsm)
    if machine_type.value in {"efsm", "timed_efsm", "mealy", "moore", "probabilistic_fsm"}:
        return True
    if fsm.variables:
        return True
    guard_complexity = infer_guard_complexity(fsm)
    return guard_complexity.value in {"compound", "nested"}


def _is_timed_fsm(fsm: FSM) -> bool:
    time_features = infer_time_features(fsm)
    if any(feature.value != "none" for feature in time_features):
        return True
    if fsm.semantics_mode == "timed_discrete":
        return True
    return any(transition.discrete_time is not None for transition in fsm.transitions)


def _estimate_mutation_score(fsm: FSM, *, seed: int) -> float | None:
    try:
        from fsmrepairbench.literature_mutation import generate_literature_mutants
        from fsmrepairbench.oracle_generator import generate_oracle_suite
        from fsmrepairbench.oracle_selection import (
            MutantRecord,
            build_scenario_profiles,
            compute_mutation_score,
        )

        mutant_report = generate_literature_mutants(
            fsm,
            seed=seed,
            first_order_count=5,
            second_order_count=0,
            higher_order_count=0,
            include_fsm=True,
        )
        mutants = tuple(
            MutantRecord(mutant_id=record.mutant_id, fsm=record.fsm)
            for record in mutant_report.mutants
            if record.fsm is not None
        )
        if not mutants:
            return None
        oracle = generate_oracle_suite(fsm, depth="shallow").suite
        profiles = build_scenario_profiles(fsm, oracle, mutants)
        return round(compute_mutation_score(profiles), 6)
    except (ValueError, OSError):
        return None


def analyze_fsm_tags(
    fsm: FSM,
    *,
    filename: str,
    source_kind: Literal["fsm", "hierarchical_fsm"] = "fsm",
    is_hierarchical: bool = False,
    compute_mutation_score: bool = True,
    seed: int = 0,
) -> FSMTagRecord:
    """Analyze one FSM and assign structural tags."""
    reachable = reachable_state_ids(fsm)
    metrics = compute_difficulty_metrics(fsm)
    graph_tags = infer_graph_structure(fsm)
    avg_branching = metrics.branching_factor
    max_out_degree = _max_out_degree(fsm, reachable)
    avg_path_length = compute_average_path_length(fsm, reachable)
    components = compute_strongly_connected_components(fsm, reachable)
    cycle_count = compute_cycle_count(fsm, reachable, components)

    size_tag = _size_tag_from_state_count(len(reachable))
    determinism_tag: DeterminismTag = (
        "non_deterministic"
        if infer_determinism(fsm).value == "nondeterministic"
        else "deterministic"
    )
    graph_tag: GraphTag = (
        "acyclic" if GraphStructure.ACYCLIC in graph_tags else "cyclic"
    )

    mutation_score = _estimate_mutation_score(fsm, seed=seed) if compute_mutation_score else None
    high_mutation_resistance = (
        mutation_score is not None and mutation_score <= HIGH_MUTATION_RESISTANCE_THRESHOLD
    )

    active_tags: list[str] = [
        size_tag,
        determinism_tag,
        graph_tag,
    ]
    tag_flags = dict.fromkeys(SUPPORTED_FSM_TAGS, False)
    tag_flags[size_tag] = True
    tag_flags[determinism_tag] = True
    tag_flags[graph_tag] = True

    if is_hierarchical or source_kind == "hierarchical_fsm":
        active_tags.append("hierarchical")
        tag_flags["hierarchical"] = True
    if _is_timed_fsm(fsm):
        active_tags.append("timed")
        tag_flags["timed"] = True
    if _is_extended_fsm(fsm):
        active_tags.append("extended")
        tag_flags["extended"] = True
    if avg_branching >= HIGH_BRANCHING_AVG_THRESHOLD or max_out_degree >= HIGH_BRANCHING_MAX_THRESHOLD:
        active_tags.append("high_branching")
        tag_flags["high_branching"] = True
    if avg_path_length >= DEEP_PATH_THRESHOLD:
        active_tags.append("deep_paths")
        tag_flags["deep_paths"] = True
    if high_mutation_resistance:
        active_tags.append("high_mutation_resistance")
        tag_flags["high_mutation_resistance"] = True

    return FSMTagRecord(
        fsm_id=fsm.id,
        filename=filename,
        source_kind=source_kind,
        num_states=len(fsm.states),
        num_transitions=len(fsm.transitions),
        num_events=len(fsm.events),
        reachable_states=len(reachable),
        avg_branching=avg_branching,
        max_out_degree=max_out_degree,
        avg_path_length=avg_path_length,
        cycle_count=cycle_count,
        mutation_score=mutation_score,
        size_tag=size_tag,
        determinism_tag=determinism_tag,
        graph_tag=graph_tag,
        tags=active_tags,
        tag_flags=tag_flags,
    )


def _load_fsm_document(path: Path) -> tuple[FSM, Literal["fsm", "hierarchical_fsm"], bool]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict) and "root" in payload and "subsystems" in payload:
        hierarchical = HierarchicalFSM.model_validate(payload)
        flattened = flatten_hierarchical_fsm(hierarchical)
        return flattened, "hierarchical_fsm", True
    fsm = load_fsm_json(path)
    return fsm, "fsm", False


def discover_fsm_json_paths(root: Path) -> list[Path]:
    """Discover analyzable FSM JSON files under *root*."""
    if root.is_file():
        if root.suffix.lower() != ".json":
            msg = f"Unsupported FSM path: {root}"
            raise FSMTaggingError(msg)
        return [root]

    if not root.is_dir():
        msg = f"FSM source path not found: {root}"
        raise FSMTaggingError(msg)

    cases_root = root / "cases"
    if cases_root.is_dir():
        case_paths = sorted(
            case_dir / "reference_fsm.json"
            for case_dir in cases_root.iterdir()
            if case_dir.is_dir() and (case_dir / "reference_fsm.json").is_file()
        )
        if case_paths:
            return case_paths

    excluded_names = {
        "metadata.json",
        "case_metadata.json",
        "bug_metadata.json",
        "oracle_suite.json",
        "requirements.json",
        "faulty_fsm.json",
        "metamorphic_metadata.json",
        "metamorphic_manifest.json",
        "dataset_manifest.json",
        "tagging_manifest.json",
    }

    paths: list[Path] = []
    for path in sorted(root.glob("*.json")):
        if path.name in excluded_names:
            continue
        if path.name.endswith("_metadata.json"):
            continue
        paths.append(path)
    if paths:
        return paths

    for path in sorted(root.rglob("*.json")):
        if path.name in excluded_names:
            continue
        if path.name.endswith("_metadata.json"):
            continue
        if "cases/" in str(path) and path.name != "reference_fsm.json":
            continue
        paths.append(path)

    if not paths:
        msg = f"No FSM JSON files found under {root}"
        raise FSMTaggingError(msg)
    return paths


def tag_fsm_paths(
    paths: Sequence[Path],
    *,
    compute_mutation_score: bool = True,
    seed: int = 42,
) -> tuple[FSMTagRecord, ...]:
    """Analyze and tag FSMs from explicit JSON paths."""
    records: list[FSMTagRecord] = []
    for index, path in enumerate(paths):
        try:
            fsm, source_kind, is_hierarchical = _load_fsm_document(path)
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            msg = f"Failed to load FSM from {path}: {exc}"
            raise FSMTaggingError(msg) from exc

        errors = validate_fsm(fsm, allow_nondeterminism=True)
        if errors:
            continue

        records.append(
            analyze_fsm_tags(
                fsm,
                filename=path.name,
                source_kind=source_kind,
                is_hierarchical=is_hierarchical,
                compute_mutation_score=compute_mutation_score,
                seed=seed + index * 101,
            )
        )

    if not records:
        msg = "No valid FSM documents could be tagged"
        raise FSMTaggingError(msg)
    return tuple(records)


def write_fsm_tags_csv(path: Path, records: Sequence[FSMTagRecord]) -> None:
    """Write tag metadata for *records* to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(METADATA_CSV_COLUMNS))
        writer.writeheader()
        for record in records:
            writer.writerow(record.to_csv_row())


def tag_fsm_directory(
    source_root: Path,
    *,
    output_path: Path | None = None,
    compute_mutation_score: bool = True,
    seed: int = 42,
) -> FSMTaggingResult:
    """Analyze every FSM under *source_root* and write metadata.csv."""
    paths = discover_fsm_json_paths(source_root)
    records: list[FSMTagRecord] = []
    skipped: list[str] = []

    for index, path in enumerate(paths):
        try:
            fsm, source_kind, is_hierarchical = _load_fsm_document(path)
        except (OSError, json.JSONDecodeError, ValueError):
            skipped.append(str(path))
            continue

        errors = validate_fsm(fsm, allow_nondeterminism=True)
        if errors:
            skipped.append(str(path))
            continue

        records.append(
            analyze_fsm_tags(
                fsm,
                filename=path.name,
                source_kind=source_kind,
                is_hierarchical=is_hierarchical,
                compute_mutation_score=compute_mutation_score,
                seed=seed + index * 101,
            )
        )

    if not records:
        msg = "No valid FSM documents could be tagged"
        raise FSMTaggingError(msg)

    metadata_csv_path = output_path or (source_root / "metadata.csv")
    write_fsm_tags_csv(metadata_csv_path, records)
    manifest_path = metadata_csv_path.with_name("tagging_manifest.json")
    manifest_path.write_text(
        json.dumps(
            {
                "source_root": str(source_root),
                "metadata_csv": str(metadata_csv_path),
                "tagged_count": len(records),
                "skipped_count": len(skipped),
                "tags": list(SUPPORTED_FSM_TAGS),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return FSMTaggingResult(
        source_root=source_root,
        metadata_csv_path=metadata_csv_path,
        records=tuple(records),
        skipped_files=tuple(skipped),
    )
