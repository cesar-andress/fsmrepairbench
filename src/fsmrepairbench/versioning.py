"""Benchmark versioning, migration, and release manifests."""

from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from fsmrepairbench.difficulty import estimate_difficulty
from fsmrepairbench.validators import load_fsm_json

CASE_ID_PATTERN = re.compile(r"^case_(\d{6})$")
RELEASE_MANIFEST_FILENAME = "release_manifest.json"
MIGRATION_REPORT_FILENAME = "migration_report.json"


class BenchmarkVersion(StrEnum):
    """Supported benchmark dataset versions."""

    V0_1 = "v0.1"
    V1_0 = "v1.0"
    V1_1 = "v1.1"
    V2_0 = "v2.0"


SUPPORTED_VERSIONS: tuple[BenchmarkVersion, ...] = (
    BenchmarkVersion.V0_1,
    BenchmarkVersion.V1_0,
    BenchmarkVersion.V1_1,
    BenchmarkVersion.V2_0,
)


@dataclass(frozen=True)
class VersionSpec:
    """Schema expectations for one benchmark version."""

    version: BenchmarkVersion
    dataset_id: str
    required_case_files: tuple[str, ...]
    optional_case_files: tuple[str, ...]
    metadata_fields: tuple[str, ...]
    compatible_read_versions: tuple[BenchmarkVersion, ...]


VERSION_SPECS: dict[BenchmarkVersion, VersionSpec] = {
    BenchmarkVersion.V0_1: VersionSpec(
        version=BenchmarkVersion.V0_1,
        dataset_id="fsmrepairbench_v0",
        required_case_files=(
            "reference_fsm.json",
            "faulty_fsm.json",
            "bug_metadata.json",
            "oracle_suite.json",
        ),
        optional_case_files=(),
        metadata_fields=("dataset_id", "seed", "cases_dir"),
        compatible_read_versions=(BenchmarkVersion.V0_1,),
    ),
    BenchmarkVersion.V1_0: VersionSpec(
        version=BenchmarkVersion.V1_0,
        dataset_id="fsmrepairbench_v1",
        required_case_files=(
            "reference_fsm.json",
            "faulty_fsm.json",
            "bug_metadata.json",
            "oracle_suite.json",
            "case_metadata.json",
        ),
        optional_case_files=(),
        metadata_fields=(
            "dataset_id",
            "benchmark_version",
            "seed",
            "target_size",
            "completed_cases",
            "cases_dir",
        ),
        compatible_read_versions=(
            BenchmarkVersion.V0_1,
            BenchmarkVersion.V1_0,
        ),
    ),
    BenchmarkVersion.V1_1: VersionSpec(
        version=BenchmarkVersion.V1_1,
        dataset_id="fsmrepairbench_v1",
        required_case_files=(
            "reference_fsm.json",
            "faulty_fsm.json",
            "bug_metadata.json",
            "oracle_suite.json",
            "case_metadata.json",
        ),
        optional_case_files=(),
        metadata_fields=(
            "dataset_id",
            "benchmark_version",
            "seed",
            "target_size",
            "completed_cases",
            "cases_dir",
            "statistics",
        ),
        compatible_read_versions=(
            BenchmarkVersion.V0_1,
            BenchmarkVersion.V1_0,
            BenchmarkVersion.V1_1,
        ),
    ),
    BenchmarkVersion.V2_0: VersionSpec(
        version=BenchmarkVersion.V2_0,
        dataset_id="fsmrepairbench_v2",
        required_case_files=(
            "reference_fsm.json",
            "faulty_fsm.json",
            "bug_metadata.json",
            "oracle_suite.json",
            "case_metadata.json",
        ),
        optional_case_files=("requirements.json",),
        metadata_fields=(
            "dataset_id",
            "benchmark_version",
            "schema_version",
            "seed",
            "target_size",
            "completed_cases",
            "cases_dir",
            "statistics",
        ),
        compatible_read_versions=tuple(SUPPORTED_VERSIONS),
    ),
}


class VersioningError(ValueError):
    """Raised when version detection or migration fails."""


DEFAULT_BENCHMARK_VERSION = BenchmarkVersion.V1_0


@dataclass(frozen=True)
class MigrationCaseReport:
    """Migration outcome for one benchmark case."""

    case_id: str
    status: str
    changes: tuple[str, ...]


@dataclass(frozen=True)
class MigrationReport:
    """Summary of a benchmark migration or compatibility analysis."""

    source_version: BenchmarkVersion
    target_version: BenchmarkVersion
    source_dir: Path
    output_dir: Path | None
    case_count: int
    stable_case_ids_preserved: bool
    added_fields: tuple[str, ...]
    warnings: tuple[str, ...]
    cases: tuple[MigrationCaseReport, ...]
    added_cases: tuple[str, ...] = ()
    removed_cases: tuple[str, ...] = ()
    modified_cases: tuple[Any, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        from fsmrepairbench.benchmark_evolution import evolution_release_for_version

        return {
            "source_version": self.source_version.value,
            "target_version": self.target_version.value,
            "source_release": evolution_release_for_version(self.source_version).value,
            "target_release": evolution_release_for_version(self.target_version).value,
            "source_dir": str(self.source_dir),
            "output_dir": str(self.output_dir) if self.output_dir is not None else None,
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "case_count": self.case_count,
            "stable_case_ids_preserved": self.stable_case_ids_preserved,
            "added_fields": list(self.added_fields),
            "warnings": list(self.warnings),
            "added_cases": list(self.added_cases),
            "removed_cases": list(self.removed_cases),
            "modified_cases": [
                {
                    "case_id": case.case_id,
                    "changes": list(case.changes),
                }
                for case in self.modified_cases
            ],
            "cases": [
                {
                    "case_id": case.case_id,
                    "status": case.status,
                    "changes": list(case.changes),
                }
                for case in self.cases
            ],
        }


@dataclass(frozen=True)
class ReleaseManifest:
    """Release manifest for a versioned benchmark dataset."""

    benchmark_version: BenchmarkVersion
    dataset_id: str
    dataset_dir: Path
    case_count: int
    stable_case_id_format: str
    compatible_versions: tuple[str, ...]
    required_case_files: tuple[str, ...]
    metadata_path: str
    index_path: str

    def to_dict(self) -> dict[str, Any]:
        from fsmrepairbench.benchmark_evolution import evolution_release_for_version

        return {
            "benchmark_version": self.benchmark_version.value,
            "evolution_release": evolution_release_for_version(self.benchmark_version).value,
            "dataset_id": self.dataset_id,
            "dataset_dir": str(self.dataset_dir),
            "generated_at": datetime.now(tz=UTC).isoformat(),
            "case_count": self.case_count,
            "stable_case_id_format": self.stable_case_id_format,
            "compatible_versions": list(self.compatible_versions),
            "required_case_files": list(self.required_case_files),
            "metadata_path": self.metadata_path,
            "index_path": self.index_path,
            "schema_version": _schema_version_for(self.benchmark_version),
        }


def format_case_id(case_number: int) -> str:
    """Return the stable benchmark case identifier for *case_number*."""
    if case_number <= 0:
        msg = "case_number must be positive"
        raise VersioningError(msg)
    return f"case_{case_number:06d}"


def parse_case_number(case_id: str) -> int:
    """Parse the numeric index from a stable case identifier."""
    match = CASE_ID_PATTERN.match(case_id)
    if match is None:
        msg = f"Invalid stable case id: {case_id}"
        raise VersioningError(msg)
    return int(match.group(1))


def is_stable_case_id(case_id: str) -> bool:
    """Return whether *case_id* follows the stable benchmark format."""
    return CASE_ID_PATTERN.match(case_id) is not None


def version_spec(version: BenchmarkVersion) -> VersionSpec:
    """Return the specification for *version*."""
    return VERSION_SPECS[version]


def _schema_version_for(version: BenchmarkVersion) -> int:
    mapping = {
        BenchmarkVersion.V0_1: 0,
        BenchmarkVersion.V1_0: 1,
        BenchmarkVersion.V1_1: 1,
        BenchmarkVersion.V2_0: 2,
    }
    return mapping[version]


def _parse_version_value(raw: str | None) -> BenchmarkVersion | None:
    if raw is None:
        return None
    normalized = raw.strip().lower()
    aliases = {
        "0.1": BenchmarkVersion.V0_1,
        "v0.1": BenchmarkVersion.V0_1,
        "0.1.0": BenchmarkVersion.V0_1,
        "1.0": BenchmarkVersion.V1_0,
        "v1.0": BenchmarkVersion.V1_0,
        "1.0.0": BenchmarkVersion.V1_0,
        "1.1": BenchmarkVersion.V1_1,
        "v1.1": BenchmarkVersion.V1_1,
        "1.1.0": BenchmarkVersion.V1_1,
        "2.0": BenchmarkVersion.V2_0,
        "v2.0": BenchmarkVersion.V2_0,
        "2.0.0": BenchmarkVersion.V2_0,
    }
    return aliases.get(normalized)


def detect_benchmark_version(dataset_dir: Path) -> BenchmarkVersion:
    """Detect the benchmark version for *dataset_dir*."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise VersioningError(msg)

    metadata_path = dataset_dir / "metadata.json"
    if metadata_path.is_file():
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        for key in ("benchmark_version", "version"):
            detected = _parse_version_value(str(payload.get(key)) if payload.get(key) else None)
            if detected is not None:
                return detected
        dataset_id = str(payload.get("dataset_id", ""))
        if dataset_id == "fsmrepairbench_v0":
            return BenchmarkVersion.V0_1
        if dataset_id == "fsmrepairbench_v2":
            return BenchmarkVersion.V2_0

    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"Could not detect benchmark version for {dataset_dir}"
        raise VersioningError(msg)

    sample_dirs = sorted(path for path in cases_root.iterdir() if path.is_dir())
    if not sample_dirs:
        msg = f"No cases found under {cases_root}"
        raise VersioningError(msg)

    sample = sample_dirs[0]
    if (sample / "case_metadata.json").is_file():
        metadata = json.loads((sample / "case_metadata.json").read_text(encoding="utf-8"))
        if isinstance(metadata.get("difficulty"), dict):
            if metadata.get("schema_version") == 2:
                return BenchmarkVersion.V2_0
            return BenchmarkVersion.V1_1
        return BenchmarkVersion.V1_0
    return BenchmarkVersion.V0_1


def discover_case_directories(dataset_dir: Path) -> list[Path]:
    """Return sorted case directories under *dataset_dir*."""
    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"Cases directory not found: {cases_root}"
        raise VersioningError(msg)
    return sorted(path for path in cases_root.iterdir() if path.is_dir() and is_stable_case_id(path.name))


def collect_case_requirements(reference_path: Path) -> list[str]:
    reference = load_fsm_json(reference_path)
    seen: set[str] = set()
    requirements: list[str] = []
    for transition in reference.transitions:
        for requirement in transition.requirements:
            if requirement in seen:
                continue
            seen.add(requirement)
            requirements.append(requirement)
    return sorted(requirements)


def normalize_case_metadata(
    payload: dict[str, Any],
    *,
    case_dir: Path,
    source_version: BenchmarkVersion,
    target_version: BenchmarkVersion,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    """Upgrade case metadata for backward-compatible reads."""
    changes: list[str] = []
    normalized = dict(payload)

    if "case_id" not in normalized:
        normalized["case_id"] = case_dir.name
        changes.append("added case_id")

    if target_version in {BenchmarkVersion.V1_0, BenchmarkVersion.V1_1, BenchmarkVersion.V2_0}:
        if "difficulty_score" not in normalized and (case_dir / "reference_fsm.json").is_file():
            estimate = estimate_difficulty(load_fsm_json(case_dir / "reference_fsm.json"))
            normalized["difficulty_score"] = estimate.difficulty_score
            normalized["difficulty_category"] = estimate.category
            changes.append("computed difficulty_score")

    if target_version in {BenchmarkVersion.V1_1, BenchmarkVersion.V2_0}:
        if "difficulty" not in normalized and "difficulty_score" in normalized:
            normalized["difficulty"] = {
                "difficulty_score": normalized["difficulty_score"],
                "category": normalized.get("difficulty_category", "medium"),
            }
            changes.append("added difficulty block")

    if target_version is BenchmarkVersion.V2_0:
        normalized["schema_version"] = 2
        normalized["benchmark_version"] = BenchmarkVersion.V2_0.value
        if "requirements" not in normalized and (case_dir / "reference_fsm.json").is_file():
            normalized["requirements"] = collect_case_requirements(case_dir / "reference_fsm.json")
            changes.append("added requirements")
        changes.append("set schema_version=2")

    if source_version is BenchmarkVersion.V0_1 and "mutation_operator" not in normalized:
        bug_metadata_path = case_dir / "bug_metadata.json"
        if bug_metadata_path.is_file():
            bug_metadata = json.loads(bug_metadata_path.read_text(encoding="utf-8"))
            normalized["mutation_operator"] = bug_metadata.get("mutation_operator", "unknown")
            changes.append("backfilled mutation_operator")

    return normalized, tuple(changes)


def analyze_migration(dataset_dir: Path, target_version: BenchmarkVersion) -> MigrationReport:
    """Analyze migration from *dataset_dir* to *target_version* without writing files."""
    source_version = detect_benchmark_version(dataset_dir)
    case_dirs = discover_case_directories(dataset_dir)
    case_reports: list[MigrationCaseReport] = []
    warnings: list[str] = []
    added_fields: set[str] = set()

    for case_dir in case_dirs:
        metadata_path = case_dir / "case_metadata.json"
        if metadata_path.is_file():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        else:
            payload = {"case_id": case_dir.name}
        _, changes = normalize_case_metadata(
            payload,
            case_dir=case_dir,
            source_version=source_version,
            target_version=target_version,
        )
        for change in changes:
            added_fields.add(change)
        case_reports.append(
            MigrationCaseReport(
                case_id=case_dir.name,
                status="would_migrate" if changes else "unchanged",
                changes=changes,
            )
        )

    if source_version is BenchmarkVersion.V0_1 and target_version is not BenchmarkVersion.V0_1:
        warnings.append("Legacy v0.1 cases will gain case_metadata.json during migration")

    report = MigrationReport(
        source_version=source_version,
        target_version=target_version,
        source_dir=dataset_dir,
        output_dir=None,
        case_count=len(case_reports),
        stable_case_ids_preserved=True,
        added_fields=tuple(sorted(added_fields)),
        warnings=tuple(warnings),
        cases=tuple(case_reports),
    )
    from fsmrepairbench.benchmark_evolution import attach_evolution_to_migration_report

    return attach_evolution_to_migration_report(
        report,
        source_dir=dataset_dir,
        target_dir=None,
    )


def _version_order(version: BenchmarkVersion) -> int:
    return SUPPORTED_VERSIONS.index(version)


def migrate_benchmark(
    source_dir: Path,
    output_dir: Path,
    target_version: BenchmarkVersion,
) -> MigrationReport:
    """Migrate a benchmark dataset to *target_version* preserving stable case IDs."""
    source_version = detect_benchmark_version(source_dir)
    if _version_order(target_version) < _version_order(source_version):
        msg = f"Downgrade from {source_version.value} to {target_version.value} is not supported"
        raise VersioningError(msg)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True)

    for name in ("index.csv", "progress.csv"):
        source_file = source_dir / name
        if source_file.is_file():
            shutil.copy2(source_file, output_dir / name)

    case_reports: list[MigrationCaseReport] = []
    added_fields: set[str] = set()
    warnings: list[str] = []

    for case_dir in discover_case_directories(source_dir):
        destination = output_dir / "cases" / case_dir.name
        destination.mkdir(parents=True, exist_ok=True)

        for source_file in case_dir.iterdir():
            if not source_file.is_file():
                continue
            if source_file.name in {"case_metadata.json", "requirements.json"}:
                continue
            shutil.copy2(source_file, destination / source_file.name)

        metadata_path = case_dir / "case_metadata.json"
        if metadata_path.is_file():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        else:
            payload = {"case_id": case_dir.name}

        normalized, changes = normalize_case_metadata(
            payload,
            case_dir=destination,
            source_version=source_version,
            target_version=target_version,
        )
        normalized["benchmark_version"] = target_version.value
        (destination / "case_metadata.json").write_text(
            json.dumps(normalized, indent=2) + "\n",
            encoding="utf-8",
        )

        if target_version is BenchmarkVersion.V2_0:
            requirements = normalized.get("requirements", [])
            if isinstance(requirements, list):
                (destination / "requirements.json").write_text(
                    json.dumps({"requirements": requirements}, indent=2) + "\n",
                    encoding="utf-8",
                )

        for change in changes:
            added_fields.add(change)
        case_reports.append(
            MigrationCaseReport(
                case_id=case_dir.name,
                status="migrated" if changes else "copied",
                changes=changes,
            )
        )

    metadata_source = source_dir / "metadata.json"
    if metadata_source.is_file():
        metadata_payload = json.loads(metadata_source.read_text(encoding="utf-8"))
    else:
        metadata_payload = {}
    metadata_payload["benchmark_version"] = target_version.value
    metadata_payload["dataset_id"] = version_spec(target_version).dataset_id
    metadata_payload["schema_version"] = _schema_version_for(target_version)
    metadata_payload["migrated_from"] = source_version.value
    metadata_payload["migrated_at"] = datetime.now(tz=UTC).isoformat()
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata_payload, indent=2) + "\n",
        encoding="utf-8",
    )

    report = MigrationReport(
        source_version=source_version,
        target_version=target_version,
        source_dir=source_dir,
        output_dir=output_dir,
        case_count=len(case_reports),
        stable_case_ids_preserved=all(
            is_stable_case_id(case.case_id) for case in case_reports
        ),
        added_fields=tuple(sorted(added_fields)),
        warnings=tuple(warnings),
        cases=tuple(case_reports),
    )
    from fsmrepairbench.benchmark_evolution import attach_evolution_to_migration_report

    report = attach_evolution_to_migration_report(
        report,
        source_dir=source_dir,
        target_dir=output_dir,
    )
    write_migration_report(output_dir / MIGRATION_REPORT_FILENAME, report)
    write_release_manifest(output_dir)
    return report


def write_migration_report(path: Path, report: MigrationReport) -> None:
    """Write a migration report JSON file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2) + "\n", encoding="utf-8")


def generate_release_manifest(dataset_dir: Path) -> ReleaseManifest:
    """Build a release manifest for *dataset_dir*."""
    version = detect_benchmark_version(dataset_dir)
    spec = version_spec(version)
    metadata_path = dataset_dir / "metadata.json"
    dataset_id = spec.dataset_id
    if metadata_path.is_file():
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        dataset_id = str(payload.get("dataset_id", dataset_id))

    case_dirs = discover_case_directories(dataset_dir)
    return ReleaseManifest(
        benchmark_version=version,
        dataset_id=dataset_id,
        dataset_dir=dataset_dir,
        case_count=len(case_dirs),
        stable_case_id_format="case_{index:06d}",
        compatible_versions=tuple(item.value for item in spec.compatible_read_versions),
        required_case_files=spec.required_case_files,
        metadata_path="metadata.json",
        index_path="index.csv",
    )


def write_release_manifest(dataset_dir: Path) -> Path:
    """Write ``release_manifest.json`` for *dataset_dir*."""
    manifest = generate_release_manifest(dataset_dir)
    path = dataset_dir / RELEASE_MANIFEST_FILENAME
    path.write_text(json.dumps(manifest.to_dict(), indent=2) + "\n", encoding="utf-8")
    return path


def ensure_backward_compatible_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize dataset metadata for backward-compatible reads."""
    normalized = dict(payload)
    version_raw = normalized.get("benchmark_version", normalized.get("version"))
    detected = _parse_version_value(str(version_raw) if version_raw is not None else None)
    if detected is None:
        detected = DEFAULT_BENCHMARK_VERSION
    normalized["benchmark_version"] = detected.value
    normalized.setdefault("schema_version", _schema_version_for(detected))
    normalized.setdefault("dataset_id", version_spec(detected).dataset_id)
    return normalized
