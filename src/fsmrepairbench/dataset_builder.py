"""Large-scale benchmark dataset builder."""

from __future__ import annotations

import csv
import json
import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock
from typing import Any, cast

from fsmrepairbench.difficulty import estimate_difficulty
from fsmrepairbench.generator import MAX_MUTATION_RETRIES, write_benchmark_case
from fsmrepairbench.generators.synthetic_factory import (
    ComplexityLevel,
    SyntheticFactoryError,
    generate_synthetic_fsm,
    params_from_complexity,
)
from fsmrepairbench.models import FSM, BugMetadata
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.oracle_generator import (
    DepthLevel,
    OracleGeneratorError,
    generate_oracle_suite,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import is_valid_fsm
from fsmrepairbench.versioning import (
    DEFAULT_BENCHMARK_VERSION,
    BenchmarkVersion,
    collect_case_requirements,
    format_case_id,
    version_spec,
    write_release_manifest,
)

DATASET_ID = version_spec(DEFAULT_BENCHMARK_VERSION).dataset_id
DEFAULT_OUTPUT_DIR = Path("data") / DATASET_ID

COMPLEXITY_LEVELS: tuple[ComplexityLevel, ...] = ("small", "medium", "large", "very_large")
ORACLE_DEPTH_BY_COMPLEXITY: dict[ComplexityLevel, DepthLevel] = {
    "small": "shallow",
    "medium": "medium",
    "large": "medium",
    "very_large": "deep",
}

INDEX_COLUMNS: tuple[str, ...] = (
    "case_id",
    "reference_fsm_id",
    "faulty_fsm_id",
    "complexity",
    "state_count",
    "transition_count",
    "event_count",
    "mutation_operator",
    "difficulty_score",
    "oracle_state_coverage",
    "oracle_transition_coverage",
    "oracle_event_coverage",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "valid_reference",
    "valid_faulty",
)
PROGRESS_COLUMNS: tuple[str, ...] = INDEX_COLUMNS + ("status",)
REQUIRED_CASE_FILES: tuple[str, ...] = (
    "reference_fsm.json",
    "faulty_fsm.json",
    "bug_metadata.json",
    "oracle_suite.json",
    "case_metadata.json",
)


class DatasetBuilderError(RuntimeError):
    """Raised when dataset construction cannot complete."""


@dataclass(frozen=True)
class CaseBuildSpec:
    """Deterministic specification for one benchmark case."""

    case_number: int
    base_seed: int
    benchmark_version: BenchmarkVersion = DEFAULT_BENCHMARK_VERSION

    @property
    def case_id(self) -> str:
        return format_case_id(self.case_number)

    @property
    def complexity(self) -> ComplexityLevel:
        return COMPLEXITY_LEVELS[(self.case_number - 1) % len(COMPLEXITY_LEVELS)]

    @property
    def mutation_operator(self) -> str:
        return MUTATION_OPERATORS[(self.case_number - 1) % len(MUTATION_OPERATORS)]

    @property
    def reference_seed(self) -> int:
        return self.base_seed + self.case_number


@dataclass(frozen=True)
class DatasetCaseRow:
    """One row in the dataset index."""

    case_id: str
    reference_fsm_id: str
    faulty_fsm_id: str
    complexity: ComplexityLevel
    state_count: int
    transition_count: int
    event_count: int
    mutation_operator: str
    difficulty_score: float
    oracle_state_coverage: float
    oracle_transition_coverage: float
    oracle_event_coverage: float
    reference_bpr: float
    faulty_bpr: float
    bpr_delta: float
    valid_reference: bool
    valid_faulty: bool
    status: str = "completed"

    def to_index_dict(self) -> dict[str, str | float | bool | int]:
        return {
            "case_id": self.case_id,
            "reference_fsm_id": self.reference_fsm_id,
            "faulty_fsm_id": self.faulty_fsm_id,
            "complexity": self.complexity,
            "state_count": self.state_count,
            "transition_count": self.transition_count,
            "event_count": self.event_count,
            "mutation_operator": self.mutation_operator,
            "difficulty_score": self.difficulty_score,
            "oracle_state_coverage": self.oracle_state_coverage,
            "oracle_transition_coverage": self.oracle_transition_coverage,
            "oracle_event_coverage": self.oracle_event_coverage,
            "reference_bpr": self.reference_bpr,
            "faulty_bpr": self.faulty_bpr,
            "bpr_delta": self.bpr_delta,
            "valid_reference": self.valid_reference,
            "valid_faulty": self.valid_faulty,
        }

    def to_progress_dict(self) -> dict[str, str | float | bool | int]:
        row = self.to_index_dict()
        row["status"] = self.status
        return row


@dataclass(frozen=True)
class DatasetBuildResult:
    """Result of a dataset build run."""

    output_dir: Path
    metadata_path: Path
    index_path: Path
    progress_path: Path
    rows: tuple[DatasetCaseRow, ...]


def case_dir_for(output_dir: Path, case_id: str) -> Path:
    """Return the directory path for *case_id*."""
    return output_dir / "cases" / case_id


def is_case_complete(case_dir: Path) -> bool:
    """Return whether *case_dir* contains a fully packaged benchmark case."""
    return case_dir.is_dir() and all((case_dir / name).is_file() for name in REQUIRED_CASE_FILES)


def load_case_row(case_dir: Path) -> DatasetCaseRow:
    """Load an index row from a packaged case directory."""
    metadata_path = case_dir / "case_metadata.json"
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    coverage = payload["oracle_coverage"]
    return DatasetCaseRow(
        case_id=str(payload["case_id"]),
        reference_fsm_id=str(payload["reference_fsm_id"]),
        faulty_fsm_id=str(payload["faulty_fsm_id"]),
        complexity=cast(ComplexityLevel, payload["complexity"]),
        state_count=int(payload["state_count"]),
        transition_count=int(payload["transition_count"]),
        event_count=int(payload["event_count"]),
        mutation_operator=str(payload["mutation_operator"]),
        difficulty_score=float(payload["difficulty_score"]),
        oracle_state_coverage=float(coverage["state_coverage"]),
        oracle_transition_coverage=float(coverage["transition_coverage"]),
        oracle_event_coverage=float(coverage["event_coverage"]),
        reference_bpr=float(payload["reference_bpr"]),
        faulty_bpr=float(payload["faulty_bpr"]),
        bpr_delta=float(payload["bpr_delta"]),
        valid_reference=bool(payload["valid_reference"]),
        valid_faulty=bool(payload["valid_faulty"]),
        status="skipped",
    )


def _parse_index_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes"}


def load_dataset_cases(dataset_dir: Path) -> list[DatasetCaseRow]:
    """Load benchmark cases from *dataset_dir* index or case metadata."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise DatasetBuilderError(msg)

    index_path = dataset_dir / "index.csv"
    if index_path.is_file():
        return _load_cases_from_index(index_path)

    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"No index.csv or cases/ directory found in {dataset_dir}"
        raise DatasetBuilderError(msg)

    rows: list[DatasetCaseRow] = []
    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        if is_case_complete(case_dir):
            rows.append(load_case_row(case_dir))

    if not rows:
        msg = f"No complete benchmark cases found under {cases_root}"
        raise DatasetBuilderError(msg)

    return rows


def _load_cases_from_index(index_path: Path) -> list[DatasetCaseRow]:
    rows: list[DatasetCaseRow] = []
    with index_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"Index CSV has no header: {index_path}"
            raise DatasetBuilderError(msg)

        for record in reader:
            rows.append(
                DatasetCaseRow(
                    case_id=str(record["case_id"]),
                    reference_fsm_id=str(record["reference_fsm_id"]),
                    faulty_fsm_id=str(record["faulty_fsm_id"]),
                    complexity=cast(ComplexityLevel, str(record["complexity"])),
                    state_count=int(record["state_count"]),
                    transition_count=int(record["transition_count"]),
                    event_count=int(record["event_count"]),
                    mutation_operator=str(record["mutation_operator"]),
                    difficulty_score=float(record["difficulty_score"]),
                    oracle_state_coverage=float(record["oracle_state_coverage"]),
                    oracle_transition_coverage=float(record["oracle_transition_coverage"]),
                    oracle_event_coverage=float(record["oracle_event_coverage"]),
                    reference_bpr=float(record["reference_bpr"]),
                    faulty_bpr=float(record["faulty_bpr"]),
                    bpr_delta=float(record["bpr_delta"]),
                    valid_reference=_parse_index_bool(record["valid_reference"]),
                    valid_faulty=_parse_index_bool(record["valid_faulty"]),
                )
            )
    return rows


def _format_csv_value(key: str, value: str | float | bool | int) -> str | float | bool | int:
    float_columns = {
        "difficulty_score",
        "oracle_state_coverage",
        "oracle_transition_coverage",
        "oracle_event_coverage",
        "reference_bpr",
        "faulty_bpr",
        "bpr_delta",
    }
    if key in float_columns and isinstance(value, float):
        return f"{value:.6f}"
    return value


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _write_index_csv(path: Path, rows: list[DatasetCaseRow]) -> None:
    _write_csv(
        path,
        INDEX_COLUMNS,
        [
            {
                key: _format_csv_value(key, value)
                for key, value in row.to_index_dict().items()
            }
            for row in sorted(rows, key=lambda item: item.case_id)
        ],
    )


def _write_progress_csv(path: Path, rows: list[DatasetCaseRow]) -> None:
    formatted_rows: list[dict[str, Any]] = []
    for row in sorted(rows, key=lambda item: item.case_id):
        progress_row = row.to_progress_dict()
        formatted_rows.append(
            {
                key: _format_csv_value(key, value) if key != "status" else value
                for key, value in progress_row.items()
            }
        )
    _write_csv(path, PROGRESS_COLUMNS, formatted_rows)


def _write_case_metadata(
    case_dir: Path,
    row: DatasetCaseRow,
    difficulty_metadata: dict[str, object],
    *,
    benchmark_version: BenchmarkVersion = DEFAULT_BENCHMARK_VERSION,
) -> None:
    payload = {
        "case_id": row.case_id,
        "benchmark_version": benchmark_version.value,
        "reference_fsm_id": row.reference_fsm_id,
        "faulty_fsm_id": row.faulty_fsm_id,
        "complexity": row.complexity,
        "state_count": row.state_count,
        "transition_count": row.transition_count,
        "event_count": row.event_count,
        "mutation_operator": row.mutation_operator,
        "difficulty_score": row.difficulty_score,
        "difficulty_category": difficulty_metadata["category"],
        "difficulty": difficulty_metadata,
        "oracle_coverage": {
            "state_coverage": row.oracle_state_coverage,
            "transition_coverage": row.oracle_transition_coverage,
            "event_coverage": row.oracle_event_coverage,
        },
        "reference_bpr": row.reference_bpr,
        "faulty_bpr": row.faulty_bpr,
        "bpr_delta": row.bpr_delta,
        "valid_reference": row.valid_reference,
        "valid_faulty": row.valid_faulty,
    }
    if benchmark_version is BenchmarkVersion.V2_0:
        payload["schema_version"] = 2
        requirements = collect_case_requirements(case_dir / "reference_fsm.json")
        payload["requirements"] = requirements
        (case_dir / "requirements.json").write_text(
            json.dumps({"requirements": requirements}, indent=2) + "\n",
            encoding="utf-8",
        )
    (case_dir / "case_metadata.json").write_text(
        json.dumps(payload, indent=2) + "\n",
        encoding="utf-8",
    )


def _mutation_seed(base_seed: int, case_number: int, attempt: int) -> int:
    return base_seed + case_number * 1000 + attempt


def _try_mutate_case(
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
    raise DatasetBuilderError(msg)


def build_single_case(spec: CaseBuildSpec, output_dir: Path) -> DatasetCaseRow:
    """Build and package one benchmark case."""
    case_dir = case_dir_for(output_dir, spec.case_id)
    params = params_from_complexity(spec.complexity, seed=spec.reference_seed)
    reference = generate_synthetic_fsm(params)
    valid_reference = is_valid_fsm(reference)

    depth = ORACLE_DEPTH_BY_COMPLEXITY[spec.complexity]
    oracle_result = generate_oracle_suite(reference, depth=depth)
    oracle = oracle_result.suite
    coverage = oracle_result.coverage

    reference_bpr = score_oracle_suite(reference, oracle).bpr
    if reference_bpr != 1.0:
        msg = f"Reference FSM for {spec.case_id} did not achieve BPR=1.0"
        raise DatasetBuilderError(msg)

    faulty_fsm, bug_metadata = _try_mutate_case(
        reference,
        spec.mutation_operator,
        spec.base_seed,
        spec.case_number,
    )
    valid_faulty = is_valid_fsm(faulty_fsm)
    faulty_bpr = score_oracle_suite(faulty_fsm, oracle).bpr
    difficulty = estimate_difficulty(reference)

    row = DatasetCaseRow(
        case_id=spec.case_id,
        reference_fsm_id=reference.id,
        faulty_fsm_id=faulty_fsm.id,
        complexity=spec.complexity,
        state_count=len(reference.states),
        transition_count=len(reference.transitions),
        event_count=len(reference.events),
        mutation_operator=spec.mutation_operator,
        difficulty_score=difficulty.difficulty_score,
        oracle_state_coverage=coverage.state_coverage,
        oracle_transition_coverage=coverage.transition_coverage,
        oracle_event_coverage=coverage.event_coverage,
        reference_bpr=reference_bpr,
        faulty_bpr=faulty_bpr,
        bpr_delta=reference_bpr - faulty_bpr,
        valid_reference=valid_reference,
        valid_faulty=valid_faulty,
    )

    write_benchmark_case(
        case_dir=case_dir,
        reference=reference,
        faulty_fsm=faulty_fsm,
        bug_metadata=bug_metadata,
        oracle=oracle,
    )
    _write_case_metadata(
        case_dir,
        row,
        difficulty.to_metadata(),
        benchmark_version=spec.benchmark_version,
    )
    return row


def _build_case_worker(payload: tuple[CaseBuildSpec, str]) -> DatasetCaseRow:
    spec, output_dir_str = payload
    try:
        return build_single_case(spec, Path(output_dir_str))
    except (DatasetBuilderError, SyntheticFactoryError, OracleGeneratorError) as exc:
        return DatasetCaseRow(
            case_id=spec.case_id,
            reference_fsm_id="",
            faulty_fsm_id="",
            complexity=spec.complexity,
            state_count=0,
            transition_count=0,
            event_count=0,
            mutation_operator=spec.mutation_operator,
            difficulty_score=0.0,
            oracle_state_coverage=0.0,
            oracle_transition_coverage=0.0,
            oracle_event_coverage=0.0,
            reference_bpr=0.0,
            faulty_bpr=0.0,
            bpr_delta=0.0,
            valid_reference=False,
            valid_faulty=False,
            status=f"failed: {exc}",
        )


def discover_completed_rows(output_dir: Path) -> list[DatasetCaseRow]:
    """Load completed case rows from an existing dataset directory."""
    cases_root = output_dir / "cases"
    if not cases_root.is_dir():
        return []

    rows: list[DatasetCaseRow] = []
    for case_path in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        if is_case_complete(case_path):
            rows.append(load_case_row(case_path))
    return rows


def write_dataset_metadata(
    path: Path,
    *,
    seed: int,
    target_size: int,
    completed_cases: int,
    workers: int,
    rows: list[DatasetCaseRow],
    benchmark_version: BenchmarkVersion = DEFAULT_BENCHMARK_VERSION,
) -> None:
    """Write dataset-level JSON metadata."""
    complexity_counts: dict[str, int] = {}
    operator_counts: dict[str, int] = {}
    for row in rows:
        if row.status != "completed":
            continue
        complexity_counts[row.complexity] = complexity_counts.get(row.complexity, 0) + 1
        operator_counts[row.mutation_operator] = operator_counts.get(row.mutation_operator, 0) + 1

    completed_rows = [row for row in rows if row.status == "completed"]
    avg_difficulty = (
        sum(row.difficulty_score for row in completed_rows) / len(completed_rows)
        if completed_rows
        else 0.0
    )

    payload = {
        "dataset_id": version_spec(benchmark_version).dataset_id,
        "benchmark_version": benchmark_version.value,
        "version": benchmark_version.value,
        "schema_version": 2 if benchmark_version is BenchmarkVersion.V2_0 else 1,
        "seed": seed,
        "target_size": target_size,
        "completed_cases": completed_cases,
        "failed_cases": len([row for row in rows if row.status.startswith("failed")]),
        "workers": workers,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "index_path": "index.csv",
        "progress_path": "progress.csv",
        "cases_dir": "cases",
        "statistics": {
            "average_difficulty_score": round(avg_difficulty, 4),
            "complexity_counts": complexity_counts,
            "mutation_operator_counts": operator_counts,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _row_is_complete(row: DatasetCaseRow) -> bool:
    return row.status in {"completed", "skipped"}


def build_dataset(
    *,
    size: int,
    seed: int = 42,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    workers: int | None = None,
    resume: bool = True,
    benchmark_version: BenchmarkVersion = DEFAULT_BENCHMARK_VERSION,
) -> DatasetBuildResult:
    """Build a large-scale benchmark dataset with parallel execution and resume."""
    if size <= 0:
        raise DatasetBuilderError("size must be greater than zero")

    worker_count = workers or min(8, os.cpu_count() or 1)
    output_dir.mkdir(parents=True, exist_ok=True)
    cases_root = output_dir / "cases"
    cases_root.mkdir(parents=True, exist_ok=True)

    progress_path = output_dir / "progress.csv"
    index_path = output_dir / "index.csv"
    metadata_path = output_dir / "metadata.json"

    rows_by_case: dict[str, DatasetCaseRow] = {}
    if resume:
        for row in discover_completed_rows(output_dir):
            rows_by_case[row.case_id] = row
        if rows_by_case:
            _write_progress_csv(progress_path, list(rows_by_case.values()))

    pending_specs: list[CaseBuildSpec] = []
    for case_number in range(1, size + 1):
        spec = CaseBuildSpec(
            case_number=case_number,
            base_seed=seed,
            benchmark_version=benchmark_version,
        )
        if resume and spec.case_id in rows_by_case:
            continue
        pending_specs.append(spec)

    progress_lock = Lock()

    def record_row(row: DatasetCaseRow) -> None:
        with progress_lock:
            rows_by_case[row.case_id] = row
            _write_progress_csv(progress_path, list(rows_by_case.values()))

    if pending_specs:
        with ProcessPoolExecutor(max_workers=worker_count) as executor:
            futures = {
                executor.submit(_build_case_worker, (spec, str(output_dir))): spec
                for spec in pending_specs
            }
            for future in as_completed(futures):
                row = future.result()
                record_row(row)

    all_rows = [rows_by_case[format_case_id(case_number)] for case_number in range(1, size + 1)]
    completed_rows = [row for row in all_rows if _row_is_complete(row)]
    if len(completed_rows) != size:
        failed = [row.case_id for row in all_rows if not _row_is_complete(row)]
        msg = (
            f"Dataset build incomplete: {len(completed_rows)}/{size} cases completed; "
            f"failed={failed[:5]}"
        )
        raise DatasetBuilderError(msg)

    _write_index_csv(index_path, completed_rows)
    write_dataset_metadata(
        metadata_path,
        seed=seed,
        target_size=size,
        completed_cases=len(completed_rows),
        workers=worker_count,
        rows=all_rows,
        benchmark_version=benchmark_version,
    )
    write_release_manifest(output_dir)

    return DatasetBuildResult(
        output_dir=output_dir,
        metadata_path=metadata_path,
        index_path=index_path,
        progress_path=progress_path,
        rows=tuple(all_rows),
    )
