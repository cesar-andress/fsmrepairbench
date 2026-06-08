"""Release freezing for reproducible benchmark artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench import __version__
from fsmrepairbench.models import RepairResult

RESULT_FILE_PATTERN = "case_*__*.json"
HASH_COLUMNS: tuple[str, ...] = ("path", "sha256", "size_bytes")
CASES_INDEX_COLUMNS: tuple[str, ...] = (
    "case_id",
    "model",
    "mutation_operator",
    "result_file",
    "initial_bpr",
    "final_bpr",
    "delta_bpr",
    "complete_repair",
    "effective_repair",
    "regression",
    "iterations_completed",
)

REQUIRED_RESULT_FIELDS: tuple[str, ...] = (
    "case_id",
    "model",
    "mutation_operator",
    "initial_bpr",
    "final_bpr",
    "delta_bpr",
    "complete_repair",
    "effective_repair",
    "regression",
    "patch_parse_failures",
    "patch_validation_failures",
    "patch_application_failures",
    "iterations_completed",
    "repair_result",
)


class FreezeError(ValueError):
    """Raised when a release cannot be frozen."""


@dataclass(frozen=True)
class FrozenFileRecord:
    """Metadata for one frozen artifact."""

    path: str
    sha256: str
    size_bytes: int


@dataclass(frozen=True)
class FreezeResult:
    """Result of freezing a results directory."""

    release_dir: Path
    manifest_path: Path
    summary_path: Path
    cases_index_path: Path
    environment_path: Path
    hashes_path: Path
    readme_path: Path
    files: tuple[FrozenFileRecord, ...]


def sha256_file(path: Path) -> str:
    """Compute the SHA256 hex digest of *path*."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_git_commit() -> str | None:
    """Return the current git commit hash when available."""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    commit = completed.stdout.strip()
    return commit or None


def collect_environment_info() -> dict[str, Any]:
    """Collect runtime environment metadata."""
    return {
        "fsmrepairbench_version": __version__,
        "python_version": sys.version,
        "platform": platform.platform(),
        "git_commit": get_git_commit(),
    }


def discover_result_files(results_dir: Path) -> list[Path]:
    """Return sorted experiment result JSON files under *results_dir*."""
    return sorted(results_dir.glob(RESULT_FILE_PATTERN))


def validate_result_file(path: Path) -> dict[str, Any]:
    """Validate an experiment result JSON file."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"Invalid result JSON '{path}': {exc}"
        raise FreezeError(msg) from exc

    if not isinstance(payload, dict):
        msg = f"Result file must contain a JSON object: {path}"
        raise FreezeError(msg)

    missing = [field for field in REQUIRED_RESULT_FIELDS if field not in payload]
    if missing:
        msg = f"Result file '{path}' missing fields: {', '.join(missing)}"
        raise FreezeError(msg)

    try:
        RepairResult.model_validate(payload["repair_result"])
    except Exception as exc:
        msg = f"Invalid repair_result in '{path}': {exc}"
        raise FreezeError(msg) from exc

    return payload


def _relative_release_path(path: Path, release_dir: Path) -> str:
    return path.relative_to(release_dir).as_posix()


def _copy_file(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _build_cases_index_rows(
    *,
    release_dir: Path,
    result_payloads: list[tuple[Path, dict[str, Any]]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for destination, payload in result_payloads:
        rows.append(
            {
                "case_id": payload["case_id"],
                "model": payload["model"],
                "mutation_operator": payload["mutation_operator"],
                "result_file": _relative_release_path(destination, release_dir),
                "initial_bpr": payload["initial_bpr"],
                "final_bpr": payload["final_bpr"],
                "delta_bpr": payload["delta_bpr"],
                "complete_repair": payload["complete_repair"],
                "effective_repair": payload["effective_repair"],
                "regression": payload["regression"],
                "iterations_completed": payload["iterations_completed"],
            }
        )
    return rows


def _build_readme(
    *,
    dataset_size_bytes: int,
    unique_cases: int,
    models: list[str],
    repair_attempts: int,
    result_count: int,
) -> str:
    model_lines = "\n".join(f"- `{model}`" for model in models) or "- none"
    return (
        "# FSMRepairBench Frozen Release\n\n"
        "This directory contains an auditable frozen snapshot of benchmark results.\n"
        "All artifacts are checksummed in `hashes.csv` and listed in `manifest.json`.\n\n"
        "## Dataset overview\n\n"
        f"- Dataset size: {dataset_size_bytes} bytes\n"
        f"- Unique cases: {unique_cases}\n"
        f"- Result files: {result_count}\n"
        f"- Models evaluated:\n{model_lines}\n"
        f"- Total repair attempts: {repair_attempts}\n\n"
        "## Metrics definitions\n\n"
        "- `initial_bpr`: Behavioural Pass Rate before repair.\n"
        "- `final_bpr`: Behavioural Pass Rate after repair.\n"
        "- `delta_bpr`: `final_bpr - initial_bpr`.\n"
        "- `complete_repair`: `True` when `final_bpr == 1.0`.\n"
        "- `effective_repair`: `True` when `final_bpr > initial_bpr`.\n"
        "- `regression`: `True` when `final_bpr < initial_bpr`.\n"
        "- `patch_parse_failures`: Iterations where patch JSON could not be parsed.\n"
        "- `patch_validation_failures`: Iterations where patch validation failed.\n"
        "- `patch_application_failures`: Iterations where patch application failed.\n"
        "- `iterations_completed`: Number of recorded repair iterations.\n\n"
        "## Files\n\n"
        "- `summary.csv`: Frozen experiment summary.\n"
        "- `cases_index.csv`: Index of frozen per-case/per-model result files.\n"
        "- `results/`: Frozen JSON result payloads.\n"
        "- `environment.json`: Toolchain and runtime metadata.\n"
        "- `hashes.csv`: SHA256 checksums for all frozen JSON/CSV files.\n"
        "- `manifest.json`: Release metadata and file inventory.\n"
    )


def _hash_tracked_files(release_dir: Path) -> list[FrozenFileRecord]:
    records: list[FrozenFileRecord] = []
    for path in sorted(release_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in {".json", ".csv"}:
            continue
        if path.name == "manifest.json":
            continue
        records.append(
            FrozenFileRecord(
                path=_relative_release_path(path, release_dir),
                sha256=sha256_file(path),
                size_bytes=path.stat().st_size,
            )
        )
    return records


def freeze_release(results_dir: Path, release_dir: Path) -> FreezeResult:
    """Validate, copy, and checksum experiment results into *release_dir*."""
    if not results_dir.is_dir():
        msg = f"Results directory not found: {results_dir}"
        raise FreezeError(msg)

    summary_source = results_dir / "summary.csv"
    if not summary_source.is_file():
        msg = f"Missing summary.csv in results directory: {results_dir}"
        raise FreezeError(msg)

    result_sources = discover_result_files(results_dir)
    if not result_sources:
        msg = f"No result JSON files matching '{RESULT_FILE_PATTERN}' in {results_dir}"
        raise FreezeError(msg)

    validated_payloads: list[tuple[Path, dict[str, Any]]] = []
    for source in result_sources:
        payload = validate_result_file(source)
        validated_payloads.append((source, payload))

    if release_dir.exists():
        shutil.rmtree(release_dir)
    release_dir.mkdir(parents=True)

    summary_destination = release_dir / "summary.csv"
    _copy_file(summary_source, summary_destination)

    copied_payloads: list[tuple[Path, dict[str, Any]]] = []
    for source, payload in validated_payloads:
        destination = release_dir / "results" / source.name
        _copy_file(source, destination)
        copied_payloads.append((destination, payload))

    cases_index_path = release_dir / "cases_index.csv"
    cases_rows = _build_cases_index_rows(
        release_dir=release_dir,
        result_payloads=copied_payloads,
    )
    _write_csv(cases_index_path, CASES_INDEX_COLUMNS, cases_rows)

    environment_path = release_dir / "environment.json"
    environment = collect_environment_info()
    environment_path.write_text(
        json.dumps(environment, indent=2) + "\n",
        encoding="utf-8",
    )

    hash_records = _hash_tracked_files(release_dir)
    hashes_path = release_dir / "hashes.csv"
    _write_csv(
        hashes_path,
        HASH_COLUMNS,
        [
            {
                "path": record.path,
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
            }
            for record in hash_records
        ],
    )

    models = sorted({str(row["model"]) for row in cases_rows})
    unique_cases = len({str(row["case_id"]) for row in cases_rows})
    repair_attempts = sum(int(row["iterations_completed"]) for row in cases_rows)
    dataset_size_bytes = sum(record.size_bytes for record in hash_records)

    manifest_path = release_dir / "manifest.json"
    manifest = {
        "fsmrepairbench_version": __version__,
        "frozen_at": datetime.now(tz=UTC).isoformat(),
        "source_results_dir": str(results_dir.resolve()),
        "release_dir": str(release_dir.resolve()),
        "dataset_size_bytes": dataset_size_bytes,
        "unique_cases": unique_cases,
        "result_files": len(copied_payloads),
        "models": models,
        "repair_attempts": repair_attempts,
        "files": [
            {
                "path": record.path,
                "sha256": record.sha256,
                "size_bytes": record.size_bytes,
            }
            for record in hash_records
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    readme_path = release_dir / "README.md"
    readme_path.write_text(
        _build_readme(
            dataset_size_bytes=dataset_size_bytes,
            unique_cases=unique_cases,
            models=models,
            repair_attempts=repair_attempts,
            result_count=len(copied_payloads),
        ),
        encoding="utf-8",
    )

    all_records = hash_records + [
        FrozenFileRecord(
            path="manifest.json",
            sha256=sha256_file(manifest_path),
            size_bytes=manifest_path.stat().st_size,
        )
    ]

    return FreezeResult(
        release_dir=release_dir,
        manifest_path=manifest_path,
        summary_path=summary_destination,
        cases_index_path=cases_index_path,
        environment_path=environment_path,
        hashes_path=hashes_path,
        readme_path=readme_path,
        files=tuple(all_records),
    )
