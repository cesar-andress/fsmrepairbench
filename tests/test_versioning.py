"""Tests for benchmark versioning, migration, and release manifests."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import build_dataset
from fsmrepairbench.versioning import (
    MIGRATION_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    BenchmarkVersion,
    analyze_migration,
    detect_benchmark_version,
    ensure_backward_compatible_metadata,
    format_case_id,
    is_stable_case_id,
    migrate_benchmark,
    parse_case_number,
    write_release_manifest,
)

runner = CliRunner()


def test_stable_case_id_helpers() -> None:
    assert format_case_id(1) == "case_000001"
    assert parse_case_number("case_000001") == 1
    assert is_stable_case_id("case_000001")
    assert not is_stable_case_id("case_1")


def test_detect_benchmark_version_for_built_dataset(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=2, seed=42, output_dir=output_dir, workers=1, resume=False)

    version = detect_benchmark_version(output_dir)
    assert version is BenchmarkVersion.V1_0

    metadata = json.loads((output_dir / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["benchmark_version"] == "v1.0"
    assert metadata["dataset_id"] == "fsmrepairbench_v1"


def test_release_manifest_is_written_on_build(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=output_dir, workers=1, resume=False)

    manifest_path = output_dir / RELEASE_MANIFEST_FILENAME
    assert manifest_path.is_file()
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert payload["benchmark_version"] == "v1.0"
    assert payload["stable_case_id_format"] == "case_{index:06d}"
    assert payload["case_count"] == 1


def test_migrate_v1_0_to_v1_1_preserves_case_ids(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "target"
    build_dataset(size=2, seed=42, output_dir=source_dir, workers=1, resume=False)

    report = migrate_benchmark(source_dir, output_dir, BenchmarkVersion.V1_1)

    assert report.stable_case_ids_preserved
    assert report.case_count == 2
    assert report.source_version is BenchmarkVersion.V1_0
    assert report.target_version is BenchmarkVersion.V1_1
    assert (output_dir / MIGRATION_REPORT_FILENAME).is_file()
    assert detect_benchmark_version(output_dir) is BenchmarkVersion.V1_1

    for case_id in ("case_000001", "case_000002"):
        case_dir = output_dir / "cases" / case_id
        assert case_dir.is_dir()
        metadata = json.loads((case_dir / "case_metadata.json").read_text(encoding="utf-8"))
        assert metadata["case_id"] == case_id
        assert metadata["benchmark_version"] == "v1.1"
        assert isinstance(metadata.get("difficulty"), dict)


def test_migrate_v0_1_legacy_dataset(tmp_path: Path) -> None:
    source_dir = tmp_path / "legacy"
    modern_dir = tmp_path / "modern"
    build_dataset(size=1, seed=42, output_dir=modern_dir, workers=1, resume=False)

    legacy_case = modern_dir / "cases" / "case_000001"
    legacy_root = source_dir / "cases" / "case_000001"
    legacy_root.mkdir(parents=True)
    for filename in (
        "reference_fsm.json",
        "faulty_fsm.json",
        "bug_metadata.json",
        "oracle_suite.json",
    ):
        shutil.copy2(legacy_case / filename, legacy_root / filename)

    (source_dir / "metadata.json").write_text(
        json.dumps(
            {
                "dataset_id": "fsmrepairbench_v0",
                "version": "0.1.0",
                "seed": 42,
                "cases_dir": "cases",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    assert detect_benchmark_version(source_dir) is BenchmarkVersion.V0_1
    report = migrate_benchmark(source_dir, tmp_path / "migrated", BenchmarkVersion.V1_0)
    assert report.case_count == 1
    assert (tmp_path / "migrated" / "cases" / "case_000001" / "case_metadata.json").is_file()


def test_analyze_migration_dry_run(tmp_path: Path) -> None:
    source_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=source_dir, workers=1, resume=False)

    report = analyze_migration(source_dir, BenchmarkVersion.V2_0)
    assert report.output_dir is None
    assert report.target_version is BenchmarkVersion.V2_0


def test_ensure_backward_compatible_metadata() -> None:
    normalized = ensure_backward_compatible_metadata({"version": "1.0.0"})
    assert normalized["benchmark_version"] == "v1.0"
    assert normalized["dataset_id"] == "fsmrepairbench_v1"


def test_cli_benchmark_version(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=output_dir, workers=1, resume=False)

    result = runner.invoke(app, ["benchmark-version", str(output_dir)])
    assert result.exit_code == 0
    assert "v1.0" in result.stdout


def test_cli_release_manifest(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=output_dir, workers=1, resume=False)
    (output_dir / RELEASE_MANIFEST_FILENAME).unlink()

    result = runner.invoke(app, ["release-manifest", str(output_dir)])
    assert result.exit_code == 0
    assert (output_dir / RELEASE_MANIFEST_FILENAME).is_file()


def test_write_release_manifest_refreshes_existing_file(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=output_dir, workers=1, resume=False)

    path = write_release_manifest(output_dir)
    assert path.is_file()
