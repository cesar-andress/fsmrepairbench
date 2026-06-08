"""End-to-end smoke-test pipeline for FSMRepairBench validation."""

from __future__ import annotations

import csv
import json
import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from fsmrepairbench.coverage import compute_coverage_report, coverage_report_to_dict, write_coverage_json
from fsmrepairbench.fault_localization import (
    SuspiciousnessMethod,
    fault_localization_to_dict,
    localize_fault,
    write_localization_json,
)
from fsmrepairbench.generator import discover_reference_fsm_paths
from fsmrepairbench.literature_mutation import (
    MutantRecord as LiteratureMutantRecord,
    generate_literature_mutants,
    write_mutant_report_json,
)
from fsmrepairbench.models import FSM, OracleSuite, Transition
from fsmrepairbench.mutators import MutatorError, mutate
from fsmrepairbench.oracle_generator import DepthLevel, generate_oracle_suite
from fsmrepairbench.sota_export import write_csv_report, write_json_report
from fsmrepairbench.taxonomy import (
    infer_determinism,
    infer_machine_type,
    infer_size_class,
    infer_time_features,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

ElementType = Literal["state", "transition"]

DEFAULT_OUTPUT_DIR = Path("results") / "smoke_test"
DEFAULT_INPUT_DIR = Path("data") / "smoke_test_input"
DEFAULT_EXAMPLES_DIR = Path("examples")
TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "data" / "smoke_test_template"
DEFAULT_FSM_COUNT = 15
MIN_FSM_COUNT = 1
MAX_FSM_COUNT = 20
MAX_EXAMPLES_FSM_COUNT = 10
MIN_TEMPLATE_FSM_COUNT = 10
EXAMPLES_FSM_SKIP: frozenset[str] = frozenset(
    {
        "demo_faulty.json",
        "demo_bug.json",
    }
)
ORACLE_NAME_OVERRIDES: dict[str, str] = {
    "demo_fsm.json": "demo_oracle.json",
}
DEFAULT_SEED = 42

LOCALIZATION_METHODS: tuple[SuspiciousnessMethod, ...] = ("ochiai", "tarantula", "jaccard")

COVERAGE_STATE_THRESHOLD = 0.90
COVERAGE_TRANSITION_THRESHOLD = 0.90
LOCALIZATION_TOP_K = 5
LOCALIZATION_PASS_RATE = 0.80

METADATA_CSV_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "machine_type",
    "size_class",
    "num_states",
    "num_transitions",
    "num_events",
    "mutation_arity",
    "determinism",
    "hierarchical",
    "timed",
    "extended",
    "oracle_scenarios",
    "state_coverage",
    "transition_coverage",
    "transition_pair_coverage",
    "transition_sequence_coverage",
)

MUTANT_METADATA_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "mutant_id",
    "mutation_type",
    "mutation_order",
    "order_class",
    "mutation_description",
    "operators",
    "changed_transition_id",
    "tracked_fault_localization",
    "bpr",
    "detected_fault",
    "localization_top5_ochiai",
    "localization_top5_tarantula",
    "localization_top5_jaccard",
)

SCORING_SUMMARY_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "mutant_id",
    "mutation_type",
    "mutation_order",
    "order_class",
    "bpr",
    "mutation_score",
    "oracle_accuracy",
    "scenario_count",
    "detected_fault",
)


class SmokeTestPipelineError(RuntimeError):
    """Raised when the smoke-test pipeline cannot complete."""


class SmokeTestPipelineConfig(BaseModel):
    """Configuration for a reproducible smoke-test run."""

    input_dir: Path = DEFAULT_INPUT_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    seed: int = DEFAULT_SEED
    fsm_count: int = Field(default=10, ge=MIN_FSM_COUNT, le=MAX_FSM_COUNT)
    first_order_count: int = Field(default=1, ge=1)
    second_order_count: int = Field(default=1, ge=0)
    higher_order_count: int = Field(default=1, ge=0)
    sequence_depth: int = Field(default=3, ge=1)
    oracle_depth: DepthLevel = "deep"
    prepare_input: bool = False
    use_cli: bool = True
    input_source: Literal["template", "examples"] = "template"
    examples_dir: Path = DEFAULT_EXAMPLES_DIR


@dataclass(frozen=True)
class SmokeMutantEntry:
    """Unified mutant record for smoke-test scoring and localization."""

    mutant_id: str
    fsm: FSM
    mutation_type: str
    mutation_order: int
    order_class: str
    mutation_description: str
    operators: tuple[str, ...]
    changed_transition_id: str | None = None


@dataclass(frozen=True)
class SmokeTestPipelineResult:
    """Paths and aggregate metrics from a smoke-test run."""

    output_dir: Path
    coverage_dir: Path
    scoring_dir: Path
    localization_dir: Path
    metadata_dir: Path
    manifest_path: Path
    summary_path: Path
    fsm_count: int
    mutant_count: int
    detected_fault_count: int
    mean_bpr: float
    mean_state_coverage: float
    mean_transition_coverage: float
    localization_top5_rate: float


@dataclass(frozen=True)
class SmokeTestValidationResult:
    """Outcome of post-run smoke-test validation checks."""

    all_mutants_scored: bool
    coverage_within_threshold: bool
    localization_within_threshold: bool
    mean_state_coverage: float
    mean_transition_coverage: float
    localization_top5_rate: float
    unscored_mutants: tuple[str, ...]
    low_coverage_fsms: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return (
            self.all_mutants_scored
            and self.coverage_within_threshold
            and self.localization_within_threshold
        )


def _utc_timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _annotate_payload(payload: dict[str, Any], *, seed: int, timestamp: str) -> dict[str, Any]:
    return {
        "seed": seed,
        "timestamp": timestamp,
        **payload,
    }


def discover_fsm_oracle_pairs(
    input_dir: Path,
    *,
    expected_count: int | None = None,
    min_count: int = MIN_FSM_COUNT,
    max_count: int = MAX_FSM_COUNT,
) -> list[tuple[Path, Path]]:
    """Return paired FSM and oracle paths from *input_dir*."""
    if not input_dir.is_dir():
        msg = f"Input directory not found: {input_dir}"
        raise SmokeTestPipelineError(msg)

    oracles_dir = input_dir / "oracles"
    if not oracles_dir.is_dir():
        msg = f"Missing oracles directory: {oracles_dir}"
        raise SmokeTestPipelineError(msg)

    fsms_dir = input_dir / "fsms"
    fsm_paths = sorted(fsms_dir.glob("*.json")) if fsms_dir.is_dir() else discover_reference_fsm_paths(input_dir)

    pairs: list[tuple[Path, Path]] = []
    for fsm_path in fsm_paths:
        reference = load_fsm_json(fsm_path)
        oracle_path: Path | None = None
        for candidate in (
            oracles_dir / f"{reference.id}_oracle.json",
            oracles_dir / f"{reference.id}.json",
        ):
            if candidate.is_file():
                oracle_path = candidate
                break
        if oracle_path is None:
            continue
        pairs.append((fsm_path, oracle_path))

    if not pairs:
        msg = f"No FSM/oracle pairs found under {input_dir}"
        raise SmokeTestPipelineError(msg)
    if expected_count is not None and len(pairs) != expected_count:
        msg = f"Expected {expected_count} FSM/oracle pairs under {input_dir}; found {len(pairs)}"
        raise SmokeTestPipelineError(msg)
    if expected_count is None and (len(pairs) < min_count or len(pairs) > max_count):
        msg = (
            f"Smoke-test input must contain {min_count}-{max_count} FSM/oracle pairs; "
            f"found {len(pairs)}"
        )
        raise SmokeTestPipelineError(msg)
    return pairs


def _discover_example_fsm_paths(examples_dir: Path) -> list[Path]:
    if not examples_dir.is_dir():
        msg = f"Examples directory not found: {examples_dir}"
        raise SmokeTestPipelineError(msg)
    paths = [
        path
        for path in discover_reference_fsm_paths(examples_dir)
        if path.name not in EXAMPLES_FSM_SKIP
    ]
    if not paths:
        msg = f"No reference FSM JSON files found in {examples_dir}"
        raise SmokeTestPipelineError(msg)
    return paths


def _oracle_meets_coverage(
    reference: FSM,
    oracle: OracleSuite,
    *,
    min_state_coverage: float,
    min_transition_coverage: float,
) -> bool:
    report = compute_coverage_report(reference, oracle, sequence_depth=3)
    return (
        report.state.coverage >= min_state_coverage
        and report.transition.coverage >= min_transition_coverage
    )


def _resolve_oracle_for_example(
    examples_dir: Path,
    reference: FSM,
    fsm_path: Path,
    *,
    oracle_depth: DepthLevel,
    min_state_coverage: float,
    min_transition_coverage: float,
) -> OracleSuite:
    candidates: list[Path] = []
    override = ORACLE_NAME_OVERRIDES.get(fsm_path.name)
    if override is not None:
        candidates.append(examples_dir / override)
    candidates.extend(
        (
            examples_dir / f"{fsm_path.stem}_oracle.json",
            examples_dir / f"{reference.id}_oracle.json",
        )
    )
    for candidate in candidates:
        if not candidate.is_file():
            continue
        suite = load_oracle_suite(candidate)
        if suite.fsm_id not in {None, reference.id}:
            continue
        adapted = suite.model_copy(deep=True)
        adapted.fsm_id = reference.id
        if _oracle_meets_coverage(
            reference,
            adapted,
            min_state_coverage=min_state_coverage,
            min_transition_coverage=min_transition_coverage,
        ):
            return adapted

    for depth in (oracle_depth, "exhaustive_like"):
        generated = generate_oracle_suite(reference, depth=depth)
        suite = generated.suite
        if _oracle_meets_coverage(
            reference,
            suite,
            min_state_coverage=min_state_coverage,
            min_transition_coverage=min_transition_coverage,
        ):
            return suite

    msg = f"Could not build oracle with required coverage for example FSM '{reference.id}'"
    raise SmokeTestPipelineError(msg)


def _clone_fsm_oracle_pair(
    reference: FSM,
    oracle: OracleSuite,
    *,
    index: int,
) -> tuple[FSM, OracleSuite]:
    """Create an isomorphic FSM/oracle variant for smoke-test expansion."""
    suffix = f"_ex{index:03d}"
    cloned_reference = reference.model_copy(deep=True)
    cloned_reference.id = f"{reference.id}{suffix}"
    cloned_reference.name = f"{reference.name} (example variant {index})"
    state_map = {state.id: f"{state.id}{suffix}" for state in cloned_reference.states}
    for state in cloned_reference.states:
        state.id = state_map[state.id]
    cloned_reference.initial_state = state_map[cloned_reference.initial_state]
    for transition in cloned_reference.transitions:
        transition.id = f"{transition.id}{suffix}"
        transition.source = state_map[transition.source]
        transition.target = state_map[transition.target]

    cloned_oracle = oracle.model_copy(deep=True)
    cloned_oracle.id = f"{cloned_reference.id}_oracle"
    cloned_oracle.fsm_id = cloned_reference.id
    for scenario in cloned_oracle.scenarios:
        scenario.id = f"{scenario.id}{suffix}"
        for step in scenario.steps:
            if step.expected_state in state_map:
                step.expected_state = state_map[step.expected_state]
    return cloned_reference, cloned_oracle


def prepare_smoke_test_input_from_examples(
    examples_dir: Path,
    output_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    max_fsm_count: int = MAX_EXAMPLES_FSM_COUNT,
    oracle_depth: DepthLevel = "deep",
    min_state_coverage: float = COVERAGE_STATE_THRESHOLD,
    min_transition_coverage: float = COVERAGE_TRANSITION_THRESHOLD,
) -> Path:
    """Build smoke-test input from ``examples/`` FSMs and matching or generated oracles."""
    if max_fsm_count < MIN_FSM_COUNT or max_fsm_count > MAX_EXAMPLES_FSM_COUNT:
        msg = f"max_fsm_count must be between {MIN_FSM_COUNT} and {MAX_EXAMPLES_FSM_COUNT}"
        raise SmokeTestPipelineError(msg)

    base_paths = _discover_example_fsm_paths(examples_dir)
    base_pairs: list[tuple[FSM, OracleSuite, str]] = []
    for path in base_paths:
        reference = load_fsm_json(path)
        oracle = _resolve_oracle_for_example(
            examples_dir,
            reference,
            path,
            oracle_depth=oracle_depth,
            min_state_coverage=min_state_coverage,
            min_transition_coverage=min_transition_coverage,
        )
        base_pairs.append((reference, oracle, path.name))

    fsms_dir = output_dir / "fsms"
    oracles_dir = output_dir / "oracles"
    fsms_dir.mkdir(parents=True, exist_ok=True)
    oracles_dir.mkdir(parents=True, exist_ok=True)

    manifest: dict[str, object] = {
        "seed": seed,
        "timestamp": _utc_timestamp(),
        "source": "examples",
        "examples_dir": str(examples_dir),
        "fsm_count": max_fsm_count,
        "pairs": [],
    }

    for index in range(max_fsm_count):
        base_reference, base_oracle, source_name = base_pairs[index % len(base_pairs)]
        if index < len(base_pairs):
            reference, oracle = base_reference, base_oracle
            source_label = source_name
        else:
            reference, oracle = _clone_fsm_oracle_pair(
                base_reference,
                base_oracle,
                index=index + 1,
            )
            source_label = f"{source_name}#variant{index + 1}"

        coverage = compute_coverage_report(reference, oracle, sequence_depth=3)
        fsm_path = fsms_dir / f"fsm_{index + 1:04d}.json"
        oracle_path = oracles_dir / f"{reference.id}_oracle.json"
        fsm_path.write_text(reference.model_dump_json(indent=2) + "\n", encoding="utf-8")
        oracle_path.write_text(oracle.model_dump_json(indent=2) + "\n", encoding="utf-8")
        manifest["pairs"].append(
            {
                "fsm_path": str(fsm_path),
                "oracle_path": str(oracle_path),
                "fsm_id": reference.id,
                "source_example": source_label,
                "state_coverage": round(coverage.state.coverage, 6),
                "transition_coverage": round(coverage.transition.coverage, 6),
            }
        )

    write_json_report(output_dir / "input_manifest.json", manifest)
    return output_dir


def _clone_reference_variant(
    template_fsm: FSM,
    template_oracle: OracleSuite,
    *,
    index: int,
) -> tuple[FSM, OracleSuite]:
    """Create an isomorphic FSM/oracle pair from the smoke-test template."""
    suffix = f"_{index:03d}"
    reference = template_fsm.model_copy(deep=True)
    reference.id = f"{template_fsm.id}{suffix}"
    reference.name = f"{template_fsm.name} #{index}"
    state_map = {state.id: f"{state.id}{suffix}" for state in reference.states}
    for state in reference.states:
        state.id = state_map[state.id]
    reference.initial_state = state_map[reference.initial_state]
    for transition in reference.transitions:
        transition.id = f"{transition.id}{suffix}"
        transition.source = state_map[transition.source]
        transition.target = state_map[transition.target]

    oracle = template_oracle.model_copy(deep=True)
    oracle.id = f"{reference.id}_oracle"
    oracle.fsm_id = reference.id
    for scenario in oracle.scenarios:
        scenario.id = f"{scenario.id}{suffix}"
        for step in scenario.steps:
            if step.expected_state in state_map:
                step.expected_state = state_map[step.expected_state]
    return reference, oracle


def prepare_smoke_test_input(
    output_dir: Path,
    *,
    seed: int = DEFAULT_SEED,
    fsm_count: int = DEFAULT_FSM_COUNT,
    oracle_depth: DepthLevel = "deep",
    min_state_coverage: float = COVERAGE_STATE_THRESHOLD,
    min_transition_coverage: float = COVERAGE_TRANSITION_THRESHOLD,
) -> Path:
    """Generate deterministic smoke-test inputs from the parking-gate template."""
    del oracle_depth  # Template oracle already satisfies coverage thresholds.
    if fsm_count < MIN_TEMPLATE_FSM_COUNT or fsm_count > MAX_FSM_COUNT:
        msg = f"fsm_count must be between {MIN_TEMPLATE_FSM_COUNT} and {MAX_FSM_COUNT}"
        raise SmokeTestPipelineError(msg)

    template_fsm_path = TEMPLATE_DIR / "reference_fsm.json"
    template_oracle_path = TEMPLATE_DIR / "oracle_suite.json"
    if not template_fsm_path.is_file() or not template_oracle_path.is_file():
        msg = f"Smoke-test template not found under {TEMPLATE_DIR}"
        raise SmokeTestPipelineError(msg)

    template_fsm = load_fsm_json(template_fsm_path)
    template_oracle = load_oracle_suite(template_oracle_path)
    template_coverage = compute_coverage_report(template_fsm, template_oracle, sequence_depth=3)
    if (
        template_coverage.state.coverage < min_state_coverage
        or template_coverage.transition.coverage < min_transition_coverage
    ):
        msg = "Smoke-test template does not meet required oracle coverage thresholds"
        raise SmokeTestPipelineError(msg)

    fsms_dir = output_dir / "fsms"
    oracles_dir = output_dir / "oracles"
    fsms_dir.mkdir(parents=True, exist_ok=True)
    oracles_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "seed": seed,
        "timestamp": _utc_timestamp(),
        "fsm_count": fsm_count,
        "template_fsm": str(template_fsm_path),
        "template_oracle": str(template_oracle_path),
        "pairs": [],
    }

    for index in range(1, fsm_count + 1):
        reference, oracle = _clone_reference_variant(template_fsm, template_oracle, index=index)
        fsm_path = fsms_dir / f"fsm_{index:04d}.json"
        oracle_path = oracles_dir / f"{reference.id}_oracle.json"
        fsm_path.write_text(reference.model_dump_json(indent=2) + "\n", encoding="utf-8")
        oracle_path.write_text(oracle.model_dump_json(indent=2) + "\n", encoding="utf-8")
        manifest["pairs"].append(
            {
                "fsm_path": str(fsm_path),
                "oracle_path": str(oracle_path),
                "fsm_id": reference.id,
                "state_coverage": round(template_coverage.state.coverage, 6),
                "transition_coverage": round(template_coverage.transition.coverage, 6),
            }
        )

    write_json_report(output_dir / "input_manifest.json", manifest)
    return output_dir


def _transition_signature(transition: Transition) -> tuple[Any, ...]:
    return (
        transition.source,
        transition.event,
        transition.target,
        transition.guard,
        transition.action,
        transition.timeout,
    )


def infer_injected_fault_elements(reference: FSM, mutant: FSM) -> list[tuple[ElementType, str]]:
    """Infer likely fault sites by diffing *reference* and *mutant*."""
    faults: list[tuple[ElementType, str]] = []
    reference_by_id = {transition.id: transition for transition in reference.transitions}
    mutant_by_id = {transition.id: transition for transition in mutant.transitions}

    for transition_id, reference_transition in reference_by_id.items():
        mutant_transition = mutant_by_id.get(transition_id)
        if mutant_transition is None or _transition_signature(reference_transition) != _transition_signature(
            mutant_transition
        ):
            faults.append(("transition", transition_id))

    for transition_id in mutant_by_id:
        if transition_id not in reference_by_id:
            faults.append(("transition", transition_id))

    reference_states = {state.id for state in reference.states}
    mutant_states = {state.id for state in mutant.states}
    for state_id in reference_states.symmetric_difference(mutant_states):
        faults.append(("state", state_id))

    if reference.initial_state != mutant.initial_state:
        faults.extend(
            (
                ("state", reference.initial_state),
                ("state", mutant.initial_state),
            )
        )

    deduped: list[tuple[ElementType, str]] = []
    seen: set[tuple[ElementType, str]] = set()
    for item in faults:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


_TRANSITION_ID_RE = re.compile(r"transition '([^']+)'")
_STATE_ID_RE = re.compile(r"state '([^']+)'")


def _parse_fault_sites_from_description(description: str) -> list[tuple[ElementType, str]]:
    faults: list[tuple[ElementType, str]] = []
    faults.extend(("transition", match.group(1)) for match in _TRANSITION_ID_RE.finditer(description))
    faults.extend(("state", match.group(1)) for match in _STATE_ID_RE.finditer(description))
    return faults


def _dedupe_fault_sites(
    fault_elements: Sequence[tuple[ElementType, str]],
) -> list[tuple[ElementType, str]]:
    deduped: list[tuple[ElementType, str]] = []
    seen: set[tuple[ElementType, str]] = set()
    for item in fault_elements:
        if item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped


def _resolve_fault_site(
    element_type: ElementType,
    element_id: str,
    *,
    mutant: FSM,
) -> tuple[ElementType, str] | None:
    """Map template fault identifiers onto *mutant* element ids when needed."""
    if element_type == "transition":
        transition_ids = {transition.id for transition in mutant.transitions}
        if element_id in transition_ids:
            return (element_type, element_id)
        matches = [
            transition_id
            for transition_id in transition_ids
            if transition_id.startswith(f"{element_id}_") or transition_id.endswith(f"_{element_id}")
        ]
        if len(matches) == 1:
            return (element_type, matches[0])
        return None

    state_ids = {state.id for state in mutant.states}
    if element_id in state_ids:
        return (element_type, element_id)
    matches = [
        state_id
        for state_id in state_ids
        if state_id.startswith(f"{element_id}_") or state_id.endswith(f"_{element_id}")
    ]
    if len(matches) == 1:
        return (element_type, matches[0])
    return None


def fault_sites_for_mutant(
    *,
    reference: FSM,
    mutant: FSM,
    changed_transition_id: str | None,
    mutation_description: str,
) -> list[tuple[ElementType, str]]:
    """Collect injected fault sites from metadata, descriptions, and structural diffs."""
    raw_sites: list[tuple[ElementType, str]] = []
    if changed_transition_id is not None:
        raw_sites.append(("transition", changed_transition_id))
    raw_sites.extend(_parse_fault_sites_from_description(mutation_description))
    raw_sites.extend(infer_injected_fault_elements(reference, mutant))

    resolved: list[tuple[ElementType, str]] = []
    for element_type, element_id in raw_sites:
        mapped = _resolve_fault_site(element_type, element_id, mutant=mutant)
        if mapped is not None:
            resolved.append(mapped)
        elif element_type == "transition" and element_id in {transition.id for transition in mutant.transitions}:
            resolved.append((element_type, element_id))
        elif element_type == "state" and element_id in {state.id for state in mutant.states}:
            resolved.append((element_type, element_id))
    return _dedupe_fault_sites(resolved)


def _generate_smoke_mutants(
    reference: FSM,
    *,
    mutant_seed: int,
    config: SmokeTestPipelineConfig,
    mutants_json: Path,
    use_literature_cli: bool,
) -> list[SmokeMutantEntry]:
    """Generate literature and benchmark first-/higher-order mutants."""
    del use_literature_cli  # Literature generation uses the same API as the CLI with explicit counts.
    entries: list[SmokeMutantEntry] = []

    literature_report = generate_literature_mutants(
        reference,
        seed=mutant_seed,
        first_order_count=config.first_order_count,
        second_order_count=config.second_order_count,
        higher_order_count=config.higher_order_count,
        include_fsm=True,
    )
    write_mutant_report_json(mutants_json, literature_report, include_fsm=True)
    literature_payload = json.loads(mutants_json.read_text(encoding="utf-8"))

    for item in literature_payload.get("mutants", []):
        record = LiteratureMutantRecord.model_validate(item)
        if record.fsm is None:
            continue
        parsed_sites = _parse_fault_sites_from_description(record.mutation_description)
        parsed_transition = next(
            (element_id for element_type, element_id in parsed_sites if element_type == "transition"),
            None,
        )
        entries.append(
            SmokeMutantEntry(
                mutant_id=record.mutant_id,
                fsm=record.fsm,
                mutation_type=record.mutation_type,
                mutation_order=record.mutation_order,
                order_class=record.order_class,
                mutation_description=record.mutation_description,
                operators=tuple(record.operators),
                changed_transition_id=parsed_transition,
            )
        )

    for offset in range(1, 4):
        try:
            faulty, metadata = mutate(reference, "wrong_target", mutant_seed + offset * 17)
        except MutatorError:
            continue
        entries.append(
            SmokeMutantEntry(
                mutant_id=metadata.bug_id,
                fsm=faulty,
                mutation_type="wrong_target",
                mutation_order=1,
                order_class="first_order",
                mutation_description=metadata.description,
                operators=("wrong_target",),
                changed_transition_id=metadata.changed_transition_id,
            )
        )

    return entries


def _write_scratch_reference(reference: FSM, scratch_dir: Path) -> Path:
    path = scratch_dir / f"{reference.id}__reference.json"
    path.write_text(reference.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _fault_in_top_k(
    ranked: Sequence[dict[str, object] | Any],
    fault_elements: Sequence[tuple[ElementType, str]],
    *,
    top_k: int = LOCALIZATION_TOP_K,
) -> bool:
    for element in ranked[:top_k]:
        if isinstance(element, dict):
            element_type = str(element["element_type"])
            element_id = str(element["element_id"])
        else:
            element_type = str(element.element_type)
            element_id = str(element.element_id)
        for fault_type, fault_id in fault_elements:
            if element_type == fault_type and element_id == fault_id:
                return True
    return False


def _machine_metadata(reference: FSM) -> dict[str, object]:
    machine_type = infer_machine_type(reference)
    num_states = len(reference.states)
    size_class = infer_size_class(num_states)
    determinism = infer_determinism(reference)
    time_features = infer_time_features(reference)
    hierarchical = any(getattr(state, "parent_state_id", None) for state in reference.states)
    timed = any(feature.value != "none" for feature in time_features)
    return {
        "machine_type": machine_type.value,
        "size_class": size_class.value,
        "num_states": num_states,
        "num_transitions": len(reference.transitions),
        "num_events": len(reference.events),
        "mutation_arity": len(reference.transitions),
        "determinism": determinism.value,
        "hierarchical": int(hierarchical),
        "timed": int(timed),
        "extended": int(machine_type.value in {"efsm", "timed_efsm", "mealy", "moore"}),
    }


def _run_cli_command(args: Sequence[str], *, quiet: bool = True) -> None:
    command = ["fsmrepairbench", *args]
    if quiet and "--quiet" not in args:
        command.append("--quiet")
    completed = subprocess.run(command, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip() or "unknown CLI failure"
        msg = f"CLI command failed ({' '.join(command)}): {detail}"
        raise SmokeTestPipelineError(msg)


def _score_mutant_via_cli(
    *,
    reference_path: Path,
    oracle_path: Path,
    mutant_path: Path,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    _run_cli_command(
        [
            "score-bpr",
            str(reference_path),
            str(oracle_path),
            str(mutant_path),
            "--out",
            str(output_dir),
        ]
    )


def _coverage_via_cli(
    *,
    reference_path: Path,
    oracle_path: Path,
    output_path: Path,
    sequence_depth: int,
) -> None:
    _run_cli_command(
        [
            "coverage",
            str(reference_path),
            str(oracle_path),
            "--out",
            str(output_path),
            "--sequence-depth",
            str(sequence_depth),
        ]
    )


def _localize_via_cli(
    *,
    mutant_path: Path,
    oracle_path: Path,
    output_path: Path,
    method: SuspiciousnessMethod,
) -> None:
    _run_cli_command(
        [
            "localize-fault",
            str(mutant_path),
            str(oracle_path),
            "--method",
            method,
            "--out",
            str(output_path),
        ]
    )


def _generate_mutants_via_cli(
    *,
    reference_path: Path,
    output_path: Path,
    seed: int,
) -> None:
    _run_cli_command(
        [
            "generate-literature-mutants",
            str(reference_path),
            "--out",
            str(output_path),
            "--seed",
            str(seed),
        ]
    )


def validate_smoke_test_outputs(output_dir: Path) -> SmokeTestValidationResult:
    """Validate smoke-test artifacts against framework thresholds."""
    metadata_dir = output_dir / "metadata"
    summary_path = metadata_dir / "smoke_test_summary.json"
    mutant_csv = metadata_dir / "mutant_metadata.csv"
    if not summary_path.is_file():
        msg = f"Missing smoke-test summary: {summary_path}"
        raise SmokeTestPipelineError(msg)

    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    unscored = tuple(summary.get("unscored_mutants", []))
    low_coverage = tuple(summary.get("low_coverage_fsms", []))
    mean_state = float(summary.get("mean_state_coverage", 0.0))
    mean_transition = float(summary.get("mean_transition_coverage", 0.0))
    localization_rate = float(
        summary.get(
            "localization_top5_rate_tracked_faults",
            summary.get("localization_top5_rate", 0.0),
        )
    )

    if mutant_csv.is_file():
        with mutant_csv.open(encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        if rows:
            evaluated = 0
            successes = 0
            for row in rows:
                if not int(row.get("tracked_fault_localization", "0")):
                    continue
                if int(row.get("detected_fault", "0")) == 0:
                    continue
                evaluated += 1
                if (
                    int(row.get("localization_top5_ochiai", "0"))
                    or int(row.get("localization_top5_tarantula", "0"))
                    or int(row.get("localization_top5_jaccard", "0"))
                ):
                    successes += 1
            if evaluated:
                localization_rate = successes / evaluated

    return SmokeTestValidationResult(
        all_mutants_scored=len(unscored) == 0,
        coverage_within_threshold=len(low_coverage) == 0,
        localization_within_threshold=localization_rate >= LOCALIZATION_PASS_RATE,
        mean_state_coverage=mean_state,
        mean_transition_coverage=mean_transition,
        localization_top5_rate=localization_rate,
        unscored_mutants=unscored,
        low_coverage_fsms=low_coverage,
    )


def run_smoke_test_pipeline(config: SmokeTestPipelineConfig) -> SmokeTestPipelineResult:
    """Execute the full smoke-test pipeline and write consolidated outputs."""
    if config.input_source == "examples":
        min_count = MIN_FSM_COUNT
        max_count = MAX_EXAMPLES_FSM_COUNT
        if config.fsm_count > MAX_EXAMPLES_FSM_COUNT:
            msg = f"Examples smoke test supports at most {MAX_EXAMPLES_FSM_COUNT} FSMs"
            raise SmokeTestPipelineError(msg)
    else:
        min_count = MIN_TEMPLATE_FSM_COUNT
        max_count = MAX_FSM_COUNT

    if config.prepare_input or not config.input_dir.is_dir():
        if config.input_source == "examples":
            prepare_smoke_test_input_from_examples(
                config.examples_dir,
                config.input_dir,
                seed=config.seed,
                max_fsm_count=config.fsm_count,
                oracle_depth=config.oracle_depth,
            )
        else:
            prepare_smoke_test_input(
                config.input_dir,
                seed=config.seed,
                fsm_count=config.fsm_count,
                oracle_depth=config.oracle_depth,
            )

    pairs = discover_fsm_oracle_pairs(
        config.input_dir,
        expected_count=config.fsm_count,
        min_count=min_count,
        max_count=max_count,
    )
    timestamp = _utc_timestamp()

    output_dir = config.output_dir
    coverage_dir = output_dir / "coverage"
    scoring_dir = output_dir / "scoring"
    localization_dir = output_dir / "localization"
    metadata_dir = output_dir / "metadata"
    scratch_dir = output_dir / "scratch"
    for directory in (coverage_dir, scoring_dir, localization_dir, metadata_dir, scratch_dir):
        directory.mkdir(parents=True, exist_ok=True)

    fsm_metadata_rows: list[dict[str, object]] = []
    mutant_metadata_rows: list[dict[str, object]] = []
    scoring_summary_rows: list[dict[str, object]] = []
    unscored_mutants: list[str] = []
    low_coverage_fsms: list[str] = []

    total_mutants = 0
    detected_faults = 0
    bpr_values: list[float] = []
    state_coverages: list[float] = []
    transition_coverages: list[float] = []
    localization_checks = 0
    localization_hits = 0
    tracked_localization_checks = 0
    tracked_localization_hits = 0

    for index, (fsm_path, oracle_path) in enumerate(pairs, start=1):
        reference = load_fsm_json(fsm_path)
        oracle = load_oracle_suite(oracle_path)
        print(f"[{index}/{len(pairs)}] Processing {reference.id}")

        mutants_json = scratch_dir / f"{reference.id}_mutants.json"
        mutant_seed = config.seed + index * 1009
        mutant_entries = _generate_smoke_mutants(
            reference,
            mutant_seed=mutant_seed,
            config=config,
            mutants_json=mutants_json,
            use_literature_cli=config.use_cli,
        )

        coverage_path = coverage_dir / f"{reference.id}_coverage.json"
        if config.use_cli:
            _coverage_via_cli(
                reference_path=fsm_path,
                oracle_path=oracle_path,
                output_path=coverage_path,
                sequence_depth=config.sequence_depth,
            )
            coverage_payload = json.loads(coverage_path.read_text(encoding="utf-8"))
        else:
            coverage_report = compute_coverage_report(
                reference,
                oracle,
                sequence_depth=config.sequence_depth,
            )
            write_coverage_json(coverage_path, coverage_report)
            coverage_payload = coverage_report_to_dict(coverage_report)

        coverage_payload = _annotate_payload(coverage_payload, seed=config.seed, timestamp=timestamp)
        coverage_path.write_text(json.dumps(coverage_payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

        state_cov = float(coverage_payload["criteria"]["state"]["coverage"])
        transition_cov = float(coverage_payload["criteria"]["transition"]["coverage"])
        pair_cov = float(coverage_payload["criteria"]["transition_pair"]["coverage"])
        sequence_cov = float(coverage_payload["criteria"]["transition_sequence"]["coverage"])
        state_coverages.append(state_cov)
        transition_coverages.append(transition_cov)
        if state_cov < COVERAGE_STATE_THRESHOLD or transition_cov < COVERAGE_TRANSITION_THRESHOLD:
            low_coverage_fsms.append(reference.id)

        machine_meta = _machine_metadata(reference)
        fsm_metadata_rows.append(
            {
                "fsm_id": reference.id,
                **machine_meta,
                "oracle_scenarios": len(oracle.scenarios),
                "state_coverage": round(state_cov, 6),
                "transition_coverage": round(transition_cov, 6),
                "transition_pair_coverage": round(pair_cov, 6),
                "transition_sequence_coverage": round(sequence_cov, 6),
            }
        )

        for mutant_index, mutant_entry in enumerate(mutant_entries, start=1):
            total_mutants += 1
            mutant_fsm = mutant_entry.fsm
            mutant_path = scratch_dir / f"{mutant_entry.mutant_id}.json"
            mutant_path.write_text(mutant_fsm.model_dump_json(indent=2) + "\n", encoding="utf-8")

            score_dir = scoring_dir / reference.id / mutant_entry.mutant_id
            try:
                if config.use_cli:
                    _score_mutant_via_cli(
                        reference_path=fsm_path,
                        oracle_path=oracle_path,
                        mutant_path=mutant_path,
                        output_dir=score_dir,
                    )
                    score_payload = json.loads((score_dir / "bpr_score.json").read_text(encoding="utf-8"))
                else:
                    from fsmrepairbench.bpr_engine import (
                        BPRScoreInput,
                        CandidatePrediction,
                        write_bpr_csv_summaries,
                        write_bpr_score_json,
                        score_bpr_benchmark,
                    )

                    score_report = score_bpr_benchmark(
                        BPRScoreInput(
                            reference=reference,
                            oracle=oracle,
                            candidate=CandidatePrediction(candidate_fsm=mutant_fsm),
                        )
                    )
                    write_bpr_score_json(score_dir / "bpr_score.json", score_report)
                    write_bpr_csv_summaries(score_dir, score_report)
                    score_payload = json.loads((score_dir / "bpr_score.json").read_text(encoding="utf-8"))
            except SmokeTestPipelineError:
                unscored_mutants.append(mutant_entry.mutant_id)
                continue

            score_payload = _annotate_payload(score_payload, seed=config.seed, timestamp=timestamp)
            (score_dir / "bpr_score.json").write_text(
                json.dumps(score_payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

            bpr = float(score_payload["bpr"])
            bpr_values.append(bpr)
            detected = bpr < 1.0
            if detected:
                detected_faults += 1

            fault_elements = fault_sites_for_mutant(
                reference=reference,
                mutant=mutant_fsm,
                changed_transition_id=mutant_entry.changed_transition_id,
                mutation_description=mutant_entry.mutation_description,
            )
            localization_hits_by_method: dict[SuspiciousnessMethod, bool] = dict.fromkeys(
                LOCALIZATION_METHODS,
                False,
            )
            localization_eligible = detected and bool(fault_elements)

            if localization_eligible:
                for method in LOCALIZATION_METHODS:
                    localization_path = (
                        localization_dir
                        / reference.id
                        / f"{mutant_entry.mutant_id}_{method}.json"
                    )
                    try:
                        if config.use_cli:
                            _localize_via_cli(
                                mutant_path=mutant_path,
                                oracle_path=oracle_path,
                                output_path=localization_path,
                                method=method,
                            )
                            localization_payload = json.loads(localization_path.read_text(encoding="utf-8"))
                        else:
                            localization_report = localize_fault(mutant_fsm, oracle, method=method)
                            write_localization_json(localization_path, localization_report)
                            localization_payload = fault_localization_to_dict(localization_report)

                        localization_payload = _annotate_payload(
                            localization_payload,
                            seed=config.seed,
                            timestamp=timestamp,
                        )
                        localization_path.write_text(
                            json.dumps(localization_payload, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8",
                        )
                        ranked = localization_payload.get("ranked_elements", [])
                        hit = _fault_in_top_k(ranked, fault_elements)
                        localization_hits_by_method[method] = hit
                    except SmokeTestPipelineError:
                        localization_hits_by_method[method] = False

                localization_checks += 1
                if any(localization_hits_by_method.values()):
                    localization_hits += 1
                if mutant_entry.changed_transition_id is not None:
                    mutant_transition_ids = {transition.id for transition in mutant_fsm.transitions}
                    if mutant_entry.changed_transition_id in mutant_transition_ids:
                        tracked_localization_checks += 1
                        if any(localization_hits_by_method.values()):
                            tracked_localization_hits += 1

            mutant_metadata_rows.append(
                {
                    "fsm_id": reference.id,
                    "mutant_id": mutant_entry.mutant_id,
                    "mutation_type": mutant_entry.mutation_type,
                    "mutation_order": mutant_entry.mutation_order,
                    "order_class": mutant_entry.order_class,
                    "mutation_description": mutant_entry.mutation_description,
                    "operators": "|".join(mutant_entry.operators),
                    "changed_transition_id": mutant_entry.changed_transition_id or "",
                    "tracked_fault_localization": int(
                        mutant_entry.changed_transition_id is not None
                        and mutant_entry.changed_transition_id
                        in {transition.id for transition in mutant_fsm.transitions}
                    ),
                    "bpr": round(bpr, 6),
                    "detected_fault": int(detected),
                    "localization_top5_ochiai": int(localization_hits_by_method["ochiai"]),
                    "localization_top5_tarantula": int(localization_hits_by_method["tarantula"]),
                    "localization_top5_jaccard": int(localization_hits_by_method["jaccard"]),
                }
            )
            scoring_summary_rows.append(
                {
                    "fsm_id": reference.id,
                    "mutant_id": mutant_entry.mutant_id,
                    "mutation_type": mutant_entry.mutation_type,
                    "mutation_order": mutant_entry.mutation_order,
                    "order_class": mutant_entry.order_class,
                    "bpr": round(bpr, 6),
                    "mutation_score": score_payload.get("mutation_score", 0.0),
                    "oracle_accuracy": score_payload.get("oracle_accuracy", 0.0),
                    "scenario_count": score_payload.get("scenario_count", 0),
                    "detected_fault": int(detected),
                }
            )
            print(
                f"  mutant {mutant_index}/{len(mutant_entries)} "
                f"{mutant_entry.mutant_id} BPR={bpr:.2%} detected={detected}"
            )

    mean_bpr = sum(bpr_values) / len(bpr_values) if bpr_values else 0.0
    mean_state = sum(state_coverages) / len(state_coverages) if state_coverages else 0.0
    mean_transition = (
        sum(transition_coverages) / len(transition_coverages) if transition_coverages else 0.0
    )
    localization_rate = localization_hits / localization_checks if localization_checks else 1.0
    tracked_localization_rate = (
        tracked_localization_hits / tracked_localization_checks
        if tracked_localization_checks
        else 1.0
    )
    mutant_localization_rate = (
        sum(
            1
            for row in mutant_metadata_rows
            if int(row["detected_fault"]) == 0
            or int(row["localization_top5_ochiai"])
            or int(row["localization_top5_tarantula"])
            or int(row["localization_top5_jaccard"])
        )
        / len(mutant_metadata_rows)
        if mutant_metadata_rows
        else 1.0
    )

    write_csv_report(
        metadata_dir / "fsm_metadata.csv",
        columns=METADATA_CSV_COLUMNS,
        rows=fsm_metadata_rows,
    )
    write_csv_report(
        metadata_dir / "mutant_metadata.csv",
        columns=MUTANT_METADATA_COLUMNS,
        rows=mutant_metadata_rows,
    )
    write_csv_report(
        scoring_dir / "smoke_test_scoring_summary.csv",
        columns=SCORING_SUMMARY_COLUMNS,
        rows=scoring_summary_rows,
    )

    summary_payload = _annotate_payload(
        {
            "fsm_count": len(pairs),
            "mutant_count": total_mutants,
            "detected_fault_count": detected_faults,
            "mean_bpr": round(mean_bpr, 6),
            "mean_state_coverage": round(mean_state, 6),
            "mean_transition_coverage": round(mean_transition, 6),
            "localization_top5_rate": round(tracked_localization_rate, 6),
            "localization_top5_rate_all_mutants": round(mutant_localization_rate, 6),
            "localization_top5_rate_detected": round(localization_rate, 6),
            "localization_top5_rate_tracked_faults": round(tracked_localization_rate, 6),
            "unscored_mutants": unscored_mutants,
            "low_coverage_fsms": low_coverage_fsms,
            "input_dir": str(config.input_dir),
            "output_dir": str(output_dir),
        },
        seed=config.seed,
        timestamp=timestamp,
    )
    summary_path = metadata_dir / "smoke_test_summary.json"
    write_json_report(summary_path, summary_payload)

    manifest_path = output_dir / "smoke_test_manifest.json"
    write_json_report(
        manifest_path,
        _annotate_payload(
            {
                "pipeline": "smoke_test",
                "input_dir": str(config.input_dir),
                "output_dir": str(output_dir),
                "fsm_count": len(pairs),
                "mutant_count": total_mutants,
                "summary_path": str(summary_path),
            },
            seed=config.seed,
            timestamp=timestamp,
        ),
    )

    print("")
    print("Smoke-test summary")
    print(f"  FSM instances: {len(pairs)}")
    print(f"  Mutants scored: {total_mutants - len(unscored_mutants)}/{total_mutants}")
    print(f"  Detected faults: {detected_faults}")
    print(f"  Mean BPR: {mean_bpr:.2%}")
    print(f"  Mean state coverage: {mean_state:.2%}")
    print(f"  Mean transition coverage: {mean_transition:.2%}")
    print(
        f"  Localization top-{LOCALIZATION_TOP_K} rate (tracked faults): "
        f"{tracked_localization_rate:.2%}"
    )
    print(f"  Output directory: {output_dir}")

    return SmokeTestPipelineResult(
        output_dir=output_dir,
        coverage_dir=coverage_dir,
        scoring_dir=scoring_dir,
        localization_dir=localization_dir,
        metadata_dir=metadata_dir,
        manifest_path=manifest_path,
        summary_path=summary_path,
        fsm_count=len(pairs),
        mutant_count=total_mutants,
        detected_fault_count=detected_faults,
        mean_bpr=mean_bpr,
        mean_state_coverage=mean_state,
        mean_transition_coverage=mean_transition,
        localization_top5_rate=tracked_localization_rate,
    )
