"""Tests for benchmark evolution across v0, v1, and v2 releases."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.benchmark_evolution import (
    EVOLUTION_REPORT_FILENAME,
    EvolutionRelease,
    build_release_trace,
    compare_benchmark_evolution,
    evolution_release_for_version,
)
from fsmrepairbench.cli import app
from fsmrepairbench.dataset_builder import build_dataset
from fsmrepairbench.versioning import (
    MIGRATION_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    BenchmarkVersion,
    analyze_migration,
    detect_benchmark_version,
    migrate_benchmark,
)

runner = CliRunner()


def test_evolution_release_mapping() -> None:
    assert evolution_release_for_version(BenchmarkVersion.V0_1) is EvolutionRelease.V0
    assert evolution_release_for_version(BenchmarkVersion.V1_0) is EvolutionRelease.V1
    assert evolution_release_for_version(BenchmarkVersion.V2_0) is EvolutionRelease.V2


def test_build_release_trace_is_traceable(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=2, seed=42, output_dir=output_dir, workers=1, resume=False)

    trace = build_release_trace(output_dir)

    assert trace.evolution_release is EvolutionRelease.V1
    assert trace.benchmark_version is BenchmarkVersion.V1_0
    assert trace.dataset_id == "fsmrepairbench_v1"
    assert trace.predecessor_release is EvolutionRelease.V0
    assert trace.successor_release is EvolutionRelease.V2
    assert len(trace.case_ids) == 2


def test_compare_benchmark_evolution_detects_case_changes(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    build_dataset(size=2, seed=42, output_dir=source_dir, workers=1, resume=False)
    shutil.copytree(source_dir, target_dir)

    removed_case = target_dir / "cases" / "case_000002"
    shutil.rmtree(removed_case)

    added_case = target_dir / "cases" / "case_000003"
    shutil.copytree(target_dir / "cases" / "case_000001", added_case)
    metadata = json.loads((added_case / "case_metadata.json").read_text(encoding="utf-8"))
    metadata["case_id"] = "case_000003"
    (added_case / "case_metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")

    modified_case = target_dir / "cases" / "case_000001" / "case_metadata.json"
    payload = json.loads(modified_case.read_text(encoding="utf-8"))
    payload["notes"] = "modified for evolution test"
    modified_case.write_text(json.dumps(payload, indent=2) + "\n")

    report = compare_benchmark_evolution(source_dir, target_dir)

    assert report.source_release is EvolutionRelease.V1
    assert report.target_release is EvolutionRelease.V1
    assert "case_000003" in report.added_cases
    assert "case_000002" in report.removed_cases
    assert any(case.case_id == "case_000001" for case in report.modified_cases)


def test_migration_report_includes_evolution_case_changes(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    output_dir = tmp_path / "target"
    build_dataset(size=2, seed=42, output_dir=source_dir, workers=1, resume=False)

    report = migrate_benchmark(source_dir, output_dir, BenchmarkVersion.V1_1)
    payload = json.loads((output_dir / MIGRATION_REPORT_FILENAME).read_text(encoding="utf-8"))

    assert payload["source_release"] == "v1"
    assert payload["target_release"] == "v1"
    assert payload["added_cases"] == []
    assert payload["removed_cases"] == []
    assert len(payload["modified_cases"]) == 2
    assert report.modified_cases


def test_analyze_migration_dry_run_reports_modified_cases(tmp_path: Path) -> None:
    source_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=source_dir, workers=1, resume=False)

    report = analyze_migration(source_dir, BenchmarkVersion.V2_0)

    assert len(report.modified_cases) >= 1


def test_release_manifest_includes_evolution_release(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=output_dir, workers=1, resume=False)

    payload = json.loads((output_dir / RELEASE_MANIFEST_FILENAME).read_text(encoding="utf-8"))
    assert payload["evolution_release"] == "v1"


def test_cli_benchmark_evolution_compare(tmp_path: Path) -> None:
    source_dir = tmp_path / "source"
    target_dir = tmp_path / "target"
    build_dataset(size=1, seed=42, output_dir=source_dir, workers=1, resume=False)
    shutil.copytree(source_dir, target_dir)
    report_path = tmp_path / EVOLUTION_REPORT_FILENAME

    result = runner.invoke(
        app,
        [
            "benchmark-evolution",
            "compare",
            str(source_dir),
            str(target_dir),
            "--out",
            str(report_path),
        ],
    )

    assert result.exit_code == 0
    assert report_path.is_file()
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert "added_cases" in payload
    assert "removed_cases" in payload
    assert "modified_cases" in payload


def test_cli_benchmark_evolution_trace(tmp_path: Path) -> None:
    output_dir = tmp_path / "dataset"
    build_dataset(size=1, seed=42, output_dir=output_dir, workers=1, resume=False)

    result = runner.invoke(app, ["benchmark-evolution", "trace", str(output_dir)])
    assert result.exit_code == 0
    assert "Evolution release: v1" in result.stdout
    assert detect_benchmark_version(output_dir) is BenchmarkVersion.V1_0
