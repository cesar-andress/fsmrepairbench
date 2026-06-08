"""Benchmark evolution across major releases v0, v1, and v2."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from fsmrepairbench.versioning import (
    BenchmarkVersion,
    VersioningError,
    detect_benchmark_version,
    discover_case_directories,
)

CASE_FINGERPRINT_FILES: tuple[str, ...] = (
    "reference_fsm.json",
    "faulty_fsm.json",
    "bug_metadata.json",
    "oracle_suite.json",
    "case_metadata.json",
    "requirements.json",
)

EVOLUTION_REPORT_FILENAME = "evolution_report.json"


class EvolutionRelease(StrEnum):
    """Major benchmark evolution releases."""

    V0 = "v0"
    V1 = "v1"
    V2 = "v2"


EVOLUTION_RELEASES: tuple[EvolutionRelease, ...] = (
    EvolutionRelease.V0,
    EvolutionRelease.V1,
    EvolutionRelease.V2,
)

EVOLUTION_PREDECESSORS: dict[EvolutionRelease, EvolutionRelease | None] = {
    EvolutionRelease.V0: None,
    EvolutionRelease.V1: EvolutionRelease.V0,
    EvolutionRelease.V2: EvolutionRelease.V1,
}

EVOLUTION_SUCCESSORS: dict[EvolutionRelease, EvolutionRelease | None] = {
    EvolutionRelease.V0: EvolutionRelease.V1,
    EvolutionRelease.V1: EvolutionRelease.V2,
    EvolutionRelease.V2: None,
}


class BenchmarkEvolutionError(ValueError):
    """Raised when benchmark evolution analysis fails."""


@dataclass(frozen=True)
class ModifiedCaseReport:
    """One benchmark case that changed between releases."""

    case_id: str
    changes: tuple[str, ...]


@dataclass(frozen=True)
class ReleaseTrace:
    """Traceability metadata for one benchmark release."""

    evolution_release: EvolutionRelease
    benchmark_version: BenchmarkVersion
    dataset_id: str
    dataset_dir: Path
    case_ids: tuple[str, ...]
    predecessor_release: EvolutionRelease | None
    successor_release: EvolutionRelease | None


@dataclass(frozen=True)
class EvolutionReport:
    """Case-level diff between two benchmark releases."""

    source_release: EvolutionRelease
    target_release: EvolutionRelease
    source_version: BenchmarkVersion
    target_version: BenchmarkVersion
    source_dir: Path
    target_dir: Path
    added_cases: tuple[str, ...]
    removed_cases: tuple[str, ...]
    modified_cases: tuple[ModifiedCaseReport, ...]
    unchanged_cases: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "source_release": self.source_release.value,
            "target_release": self.target_release.value,
            "source_version": self.source_version.value,
            "target_version": self.target_version.value,
            "source_dir": str(self.source_dir),
            "target_dir": str(self.target_dir),
            "added_cases": list(self.added_cases),
            "removed_cases": list(self.removed_cases),
            "modified_cases": [
                {"case_id": case.case_id, "changes": list(case.changes)}
                for case in self.modified_cases
            ],
            "unchanged_cases": list(self.unchanged_cases),
            "source_case_count": len(self.unchanged_cases)
            + len(self.removed_cases)
            + len(self.modified_cases),
            "target_case_count": len(self.unchanged_cases)
            + len(self.added_cases)
            + len(self.modified_cases),
        }


def evolution_release_for_version(version: BenchmarkVersion) -> EvolutionRelease:
    """Map a schema version to a major evolution release."""
    if version is BenchmarkVersion.V0_1:
        return EvolutionRelease.V0
    if version in {BenchmarkVersion.V1_0, BenchmarkVersion.V1_1}:
        return EvolutionRelease.V1
    return EvolutionRelease.V2


def parse_evolution_release(raw: str) -> EvolutionRelease:
    """Parse a major release identifier."""
    normalized = raw.strip().lower()
    aliases = {
        "v0": EvolutionRelease.V0,
        "0": EvolutionRelease.V0,
        "v1": EvolutionRelease.V1,
        "1": EvolutionRelease.V1,
        "v2": EvolutionRelease.V2,
        "2": EvolutionRelease.V2,
    }
    release = aliases.get(normalized)
    if release is None:
        msg = f"Unsupported evolution release: {raw}"
        raise BenchmarkEvolutionError(msg)
    return release


def _dataset_id_for_release(release: EvolutionRelease) -> str:
    mapping = {
        EvolutionRelease.V0: "fsmrepairbench_v0",
        EvolutionRelease.V1: "fsmrepairbench_v1",
        EvolutionRelease.V2: "fsmrepairbench_v2",
    }
    return mapping[release]


def discover_case_ids(dataset_dir: Path) -> tuple[str, ...]:
    """Return stable case identifiers under *dataset_dir*."""
    return tuple(case_dir.name for case_dir in discover_case_directories(dataset_dir))


def compute_case_fingerprint(case_dir: Path) -> str:
    """Return a stable fingerprint for one benchmark case directory."""
    digest = hashlib.sha256()
    for filename in CASE_FINGERPRINT_FILES:
        path = case_dir / filename
        if not path.is_file():
            continue
        digest.update(filename.encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def diff_case_files(source_dir: Path, target_dir: Path) -> tuple[str, ...]:
    """Return human-readable file-level changes for one case."""
    changes: list[str] = []
    filenames = sorted(set(CASE_FINGERPRINT_FILES) | {
        path.name for path in source_dir.iterdir() if path.is_file()
    } | {path.name for path in target_dir.iterdir() if path.is_file()})

    for filename in filenames:
        source_path = source_dir / filename
        target_path = target_dir / filename
        if source_path.is_file() and not target_path.is_file():
            changes.append(f"removed file {filename}")
        elif target_path.is_file() and not source_path.is_file():
            changes.append(f"added file {filename}")
        elif (
            source_path.is_file()
            and target_path.is_file()
            and source_path.read_bytes() != target_path.read_bytes()
        ):
            changes.append(f"modified file {filename}")
    return tuple(changes)


def compare_case_inventories(
    source_dir: Path,
    target_dir: Path,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[ModifiedCaseReport, ...], tuple[str, ...]]:
    """Compare case inventories between two benchmark directories."""
    source_cases = {path.name: path for path in discover_case_directories(source_dir)}
    target_cases = {path.name: path for path in discover_case_directories(target_dir)}

    source_ids = set(source_cases)
    target_ids = set(target_cases)

    added_cases = tuple(sorted(target_ids - source_ids))
    removed_cases = tuple(sorted(source_ids - target_ids))
    modified_cases: list[ModifiedCaseReport] = []
    unchanged_cases: list[str] = []

    for case_id in sorted(source_ids & target_ids):
        source_fingerprint = compute_case_fingerprint(source_cases[case_id])
        target_fingerprint = compute_case_fingerprint(target_cases[case_id])
        if source_fingerprint == target_fingerprint:
            unchanged_cases.append(case_id)
            continue
        changes = diff_case_files(source_cases[case_id], target_cases[case_id])
        modified_cases.append(ModifiedCaseReport(case_id=case_id, changes=changes))

    return added_cases, removed_cases, tuple(modified_cases), tuple(unchanged_cases)


def build_release_trace(dataset_dir: Path) -> ReleaseTrace:
    """Build traceability metadata for a benchmark release."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise BenchmarkEvolutionError(msg)

    benchmark_version = detect_benchmark_version(dataset_dir)
    evolution_release = evolution_release_for_version(benchmark_version)
    metadata_path = dataset_dir / "metadata.json"
    dataset_id = _dataset_id_for_release(evolution_release)
    if metadata_path.is_file():
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        dataset_id = str(payload.get("dataset_id", dataset_id))

    return ReleaseTrace(
        evolution_release=evolution_release,
        benchmark_version=benchmark_version,
        dataset_id=dataset_id,
        dataset_dir=dataset_dir,
        case_ids=discover_case_ids(dataset_dir),
        predecessor_release=EVOLUTION_PREDECESSORS[evolution_release],
        successor_release=EVOLUTION_SUCCESSORS[evolution_release],
    )


def compare_benchmark_evolution(source_dir: Path, target_dir: Path) -> EvolutionReport:
    """Compare two benchmark releases and classify case changes."""
    try:
        source_version = detect_benchmark_version(source_dir)
        target_version = detect_benchmark_version(target_dir)
    except VersioningError as exc:
        raise BenchmarkEvolutionError(str(exc)) from exc

    added, removed, modified, unchanged = compare_case_inventories(source_dir, target_dir)
    return EvolutionReport(
        source_release=evolution_release_for_version(source_version),
        target_release=evolution_release_for_version(target_version),
        source_version=source_version,
        target_version=target_version,
        source_dir=source_dir,
        target_dir=target_dir,
        added_cases=added,
        removed_cases=removed,
        modified_cases=modified,
        unchanged_cases=unchanged,
    )


def attach_evolution_to_migration_report(
    report: Any,
    *,
    source_dir: Path,
    target_dir: Path | None,
) -> Any:
    """Attach added/removed/modified case summaries to a migration report."""
    from fsmrepairbench.versioning import MigrationReport

    if not isinstance(report, MigrationReport):
        msg = "Expected a MigrationReport instance"
        raise BenchmarkEvolutionError(msg)

    if target_dir is not None and target_dir.is_dir():
        added, removed, modified, _ = compare_case_inventories(source_dir, target_dir)
        return MigrationReport(
            source_version=report.source_version,
            target_version=report.target_version,
            source_dir=report.source_dir,
            output_dir=report.output_dir,
            case_count=report.case_count,
            stable_case_ids_preserved=report.stable_case_ids_preserved,
            added_fields=report.added_fields,
            warnings=report.warnings,
            cases=report.cases,
            added_cases=added,
            removed_cases=removed,
            modified_cases=modified,
        )

    modified = tuple(
        ModifiedCaseReport(case_id=case.case_id, changes=case.changes)
        for case in report.cases
        if case.changes
    )
    return MigrationReport(
        source_version=report.source_version,
        target_version=report.target_version,
        source_dir=report.source_dir,
        output_dir=report.output_dir,
        case_count=report.case_count,
        stable_case_ids_preserved=report.stable_case_ids_preserved,
        added_fields=report.added_fields,
        warnings=report.warnings,
        cases=report.cases,
        added_cases=(),
        removed_cases=(),
        modified_cases=modified,
    )


def write_evolution_report(path: Path, report: EvolutionReport) -> None:
    """Write an evolution comparison report JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")
