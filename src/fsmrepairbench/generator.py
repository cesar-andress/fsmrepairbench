"""Benchmark case generation from reference FSMs."""

from __future__ import annotations

import csv
import json
import shutil
from dataclasses import dataclass
from pathlib import Path

from pydantic import ValidationError

from fsmrepairbench.models import FSM, BugMetadata, OracleSuite
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import is_valid_fsm, load_fsm_json, load_oracle_suite, validate_fsm

SUMMARY_COLUMNS: tuple[str, ...] = (
    "case_id",
    "reference_fsm_id",
    "faulty_fsm_id",
    "mutation_operator",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "valid_reference",
    "valid_faulty",
)

REQUIRED_FSM_KEYS: tuple[str, ...] = (
    "id",
    "states",
    "initial_state",
    "events",
    "transitions",
)

MAX_MUTATION_RETRIES = 32


class BenchmarkGenerationError(RuntimeError):
    """Raised when benchmark generation cannot complete."""


@dataclass(frozen=True)
class BenchmarkCaseSummary:
    """One row in the generated benchmark summary."""

    case_id: str
    reference_fsm_id: str
    faulty_fsm_id: str
    mutation_operator: str
    reference_bpr: float | None
    faulty_bpr: float | None
    bpr_delta: float | None
    valid_reference: bool
    valid_faulty: bool


@dataclass(frozen=True)
class BenchmarkGenerationResult:
    """Result of a benchmark generation run."""

    output_dir: Path
    summary_path: Path
    cases: tuple[BenchmarkCaseSummary, ...]
    skipped_input_files: tuple[tuple[Path, str], ...] = ()


@dataclass(frozen=True)
class ReferenceFsmDiscovery:
    """Reference FSM discovery outcome for one input directory."""

    reference_paths: tuple[Path, ...]
    skipped_files: tuple[tuple[Path, str], ...]


def _looks_like_fsm_document(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    return all(key in payload for key in REQUIRED_FSM_KEYS)


def discover_reference_fsm_files(input_dir: Path) -> ReferenceFsmDiscovery:
    """Scan *input_dir* for valid reference FSM JSON files and skipped entries."""
    if not input_dir.is_dir():
        msg = f"Input directory not found: {input_dir}"
        raise BenchmarkGenerationError(msg)

    reference_paths: list[Path] = []
    skipped_files: list[tuple[Path, str]] = []

    for path in sorted(input_dir.glob("*.json")):
        if not path.is_file():
            continue

        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            skipped_files.append((path, f"invalid JSON: {exc}"))
            continue

        if not _looks_like_fsm_document(payload):
            skipped_files.append((path, "missing required FSM fields"))
            continue

        try:
            fsm = load_fsm_json(path)
        except ValidationError as exc:
            skipped_files.append((path, f"invalid FSM schema: {exc}"))
            continue

        validation_errors = validate_fsm(fsm)
        if validation_errors:
            skipped_files.append((path, validation_errors[0]))
            continue

        reference_paths.append(path)

    return ReferenceFsmDiscovery(
        reference_paths=tuple(reference_paths),
        skipped_files=tuple(skipped_files),
    )


def discover_reference_fsms(input_dir: Path) -> list[Path]:
    """Return valid reference FSM JSON paths directly under *input_dir*."""
    discovery = discover_reference_fsm_files(input_dir)
    if not discovery.reference_paths:
        skipped_count = len(discovery.skipped_files)
        suffix = f" ({skipped_count} file(s) skipped)" if skipped_count else ""
        msg = f"No reference FSM JSON files found in {input_dir}{suffix}"
        raise BenchmarkGenerationError(msg)
    return list(discovery.reference_paths)


def discover_reference_fsm_paths(input_dir: Path) -> list[Path]:
    """Return reference FSM JSON paths directly under *input_dir*."""
    return discover_reference_fsms(input_dir)


def discover_oracle_suites(input_dir: Path) -> dict[str, OracleSuite]:
    """Load oracle suites from ``input_dir/oracles`` indexed by ``fsm_id``."""
    oracles_dir = input_dir / "oracles"
    if not oracles_dir.is_dir():
        return {}

    suites: dict[str, OracleSuite] = {}
    for path in sorted(oracles_dir.glob("*.json")):
        suite = load_oracle_suite(path)
        if suite.fsm_id is None:
            continue
        suites[suite.fsm_id] = suite
    return suites


def resolve_oracle_for_fsm(fsm: FSM, oracle_suites: dict[str, OracleSuite]) -> OracleSuite | None:
    """Return the oracle suite associated with *fsm*, if available."""
    return oracle_suites.get(fsm.id)


def _mutation_seed(base_seed: int, case_number: int, attempt: int) -> int:
    return base_seed + case_number * 1000 + attempt


def _operator_for_variant(variant_index: int) -> str:
    return MUTATION_OPERATORS[variant_index % len(MUTATION_OPERATORS)]


def _format_optional_float(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6f}"


def _write_json(path: Path, payload: FSM | OracleSuite | BugMetadata) -> None:
    path.write_text(payload.model_dump_json(indent=2) + "\n", encoding="utf-8")


def _score_bpr(fsm: FSM, oracle: OracleSuite | None) -> float | None:
    if oracle is None:
        return None
    return score_oracle_suite(fsm, oracle).bpr


def _try_mutate(
    reference: FSM,
    operator: str,
    base_seed: int,
    case_number: int,
) -> tuple[FSM, BugMetadata]:
    last_error: MutatorError | None = None
    for attempt in range(MAX_MUTATION_RETRIES):
        try:
            return mutate(reference, operator, _mutation_seed(base_seed, case_number, attempt))
        except MutatorError as exc:
            last_error = exc
    msg = f"Could not apply operator '{operator}' for case {case_number}: {last_error}"
    raise BenchmarkGenerationError(msg)


def _write_case(
    *,
    case_dir: Path,
    reference: FSM,
    faulty_fsm: FSM,
    bug_metadata: BugMetadata,
    oracle: OracleSuite | None,
) -> None:
    case_dir.mkdir(parents=True, exist_ok=True)
    _write_json(case_dir / "reference_fsm.json", reference)
    _write_json(case_dir / "faulty_fsm.json", faulty_fsm)
    _write_json(case_dir / "bug_metadata.json", bug_metadata)
    if oracle is not None:
        _write_json(case_dir / "oracle_suite.json", oracle)


def write_benchmark_case(
    *,
    case_dir: Path,
    reference: FSM,
    faulty_fsm: FSM,
    bug_metadata: BugMetadata,
    oracle: OracleSuite | None,
) -> None:
    """Write one benchmark case directory."""
    _write_case(
        case_dir=case_dir,
        reference=reference,
        faulty_fsm=faulty_fsm,
        bug_metadata=bug_metadata,
        oracle=oracle,
    )


def generate_benchmark(
    input_dir: Path,
    output_dir: Path,
    *,
    bugs_per_fsm: int = 10,
    seed: int = 123,
) -> BenchmarkGenerationResult:
    """Generate benchmark cases under *output_dir* from reference FSMs in *input_dir*."""
    if bugs_per_fsm <= 0:
        raise BenchmarkGenerationError("bugs_per_fsm must be greater than zero")

    discovery = discover_reference_fsm_files(input_dir)
    reference_paths = list(discovery.reference_paths)
    if not reference_paths:
        skipped_count = len(discovery.skipped_files)
        suffix = f" ({skipped_count} file(s) skipped)" if skipped_count else ""
        raise BenchmarkGenerationError(f"No reference FSM JSON files found in {input_dir}{suffix}")

    oracle_suites = discover_oracle_suites(input_dir)
    cases_root = output_dir / "cases"
    if cases_root.exists():
        shutil.rmtree(cases_root)
    cases_root.mkdir(parents=True, exist_ok=True)

    summaries: list[BenchmarkCaseSummary] = []
    case_number = 0

    for reference_path in reference_paths:
        reference = load_fsm_json(reference_path)
        valid_reference = is_valid_fsm(reference)
        oracle = resolve_oracle_for_fsm(reference, oracle_suites)
        reference_bpr = _score_bpr(reference, oracle) if valid_reference else None

        for variant_index in range(bugs_per_fsm):
            operator = _operator_for_variant(variant_index)
            case_number += 1
            case_id = f"case_{case_number:06d}"
            faulty_fsm, bug_metadata = _try_mutate(reference, operator, seed, case_number)
            valid_faulty = is_valid_fsm(faulty_fsm)
            faulty_bpr = _score_bpr(faulty_fsm, oracle) if oracle is not None else None
            bpr_delta = (
                reference_bpr - faulty_bpr
                if reference_bpr is not None and faulty_bpr is not None
                else None
            )

            case_dir = cases_root / case_id
            _write_case(
                case_dir=case_dir,
                reference=reference,
                faulty_fsm=faulty_fsm,
                bug_metadata=bug_metadata,
                oracle=oracle,
            )

            summaries.append(
                BenchmarkCaseSummary(
                    case_id=case_id,
                    reference_fsm_id=reference.id,
                    faulty_fsm_id=faulty_fsm.id,
                    mutation_operator=operator,
                    reference_bpr=reference_bpr,
                    faulty_bpr=faulty_bpr,
                    bpr_delta=bpr_delta,
                    valid_reference=valid_reference,
                    valid_faulty=valid_faulty,
                )
            )

    summary_path = output_dir / "summary.csv"
    output_dir.mkdir(parents=True, exist_ok=True)
    with summary_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(SUMMARY_COLUMNS))
        writer.writeheader()
        for row in summaries:
            writer.writerow(
                {
                    "case_id": row.case_id,
                    "reference_fsm_id": row.reference_fsm_id,
                    "faulty_fsm_id": row.faulty_fsm_id,
                    "mutation_operator": row.mutation_operator,
                    "reference_bpr": _format_optional_float(row.reference_bpr),
                    "faulty_bpr": _format_optional_float(row.faulty_bpr),
                    "bpr_delta": _format_optional_float(row.bpr_delta),
                    "valid_reference": row.valid_reference,
                    "valid_faulty": row.valid_faulty,
                }
            )

    return BenchmarkGenerationResult(
        output_dir=output_dir,
        summary_path=summary_path,
        cases=tuple(summaries),
        skipped_input_files=discovery.skipped_files,
    )
