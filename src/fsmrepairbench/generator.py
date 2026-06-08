"""Benchmark case generation from reference FSMs."""

from __future__ import annotations

import csv
import shutil
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.models import FSM, BugMetadata, OracleSuite
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import is_valid_fsm, load_fsm_json, load_oracle_suite

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


def discover_reference_fsm_paths(input_dir: Path) -> list[Path]:
    """Return reference FSM JSON paths directly under *input_dir*."""
    return sorted(path for path in input_dir.glob("*.json") if path.is_file())


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

    reference_paths = discover_reference_fsm_paths(input_dir)
    if not reference_paths:
        raise BenchmarkGenerationError(f"No reference FSM JSON files found in {input_dir}")

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
    )
