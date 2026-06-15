"""Unified CLI smoke tests for benchmark campaign commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.manifest_integrity import verify_campaign_manifest
from tests.helpers import FIXTURES, setup_cases_root

runner = CliRunner()
FIXTURE_DATASET = FIXTURES / "stratified_coupling_dataset"
TOOLS_DIR = Path(__file__).resolve().parents[1] / "tools" / "baselines_c1"


@pytest.mark.parametrize(
    ("command", "args_factory"),
    [
        pytest.param(
            "run-tools",
            lambda tmp: _run_tools_args(tmp),
            id="run-tools",
        ),
        pytest.param(
            "run-localization-campaign",
            lambda tmp: _run_localization_args(tmp),
            id="run-localization-campaign",
        ),
        pytest.param(
            "run-coupling-campaign",
            lambda tmp: _run_coupling_args(tmp),
            id="run-coupling-campaign",
        ),
        pytest.param(
            "run-oracle-depth-ablation",
            lambda tmp: _run_oracle_depth_args(tmp),
            id="run-oracle-depth-ablation",
        ),
    ],
)
def test_campaign_cli_writes_manifest_and_core_exports(
    tmp_path: Path,
    command: str,
    args_factory,
) -> None:
    args = args_factory(tmp_path)
    result = runner.invoke(app, [command, *args])
    assert result.exit_code == 0, result.stdout

    out_dir = tmp_path / "out"
    if command == "run-tools":
        assert (out_dir / "summary.csv").is_file()
        assert (out_dir / "leaderboard.csv").is_file()
        assert (out_dir / "tool_run_manifest.json").is_file()
        return

    manifest_path = out_dir / "manifest.json"
    assert manifest_path.is_file(), f"stdout:\n{result.stdout}"

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest.get("zenodo_doi") == "10.5281/zenodo.20602528"
    assert manifest.get("release_label")
    assert manifest.get("regeneration_commands")

    integrity = verify_campaign_manifest(
        manifest_path,
        required_fields=("release_label", "zenodo_doi", "regeneration_commands", "output_files"),
        verify_output_files=True,
        verify_csv_sha256=False,
    )
    assert integrity.passed, "\n".join(integrity.errors)


def _write_cohort(tmp_path: Path, case_id: str = "case_000002") -> Path:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text(f"{case_id}\n", encoding="utf-8")
    return cohort_path


def _run_tools_args(tmp_path: Path) -> list[str]:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "baseline_missing_transition.yaml").write_text(
        (TOOLS_DIR / "baseline_missing_transition.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return [
        str(cases_root),
        str(tools_dir),
        "--out",
        str(tmp_path / "out"),
        "--workers",
        "1",
    ]


def _run_localization_args(tmp_path: Path) -> list[str]:
    cohort_path = _write_cohort(tmp_path)
    return [
        str(FIXTURE_DATASET),
        "--out",
        str(tmp_path / "out"),
        "--cohort-file",
        str(cohort_path),
    ]


def _run_coupling_args(tmp_path: Path) -> list[str]:
    cohort_path = _write_cohort(tmp_path)
    return [
        str(FIXTURE_DATASET),
        "--out",
        str(tmp_path / "out"),
        "--subset-dir",
        str(tmp_path / "subset"),
        "--cohort-file",
        str(cohort_path),
        "--seed",
        "44",
        "--copy-cases",
    ]


def _run_oracle_depth_args(tmp_path: Path) -> list[str]:
    cohort_path = _write_cohort(tmp_path)
    return [
        str(FIXTURE_DATASET),
        "--out",
        str(tmp_path / "out"),
        "--cohort-file",
        str(cohort_path),
        "--no-write-cohort",
    ]


def test_run_tools_cli_produces_leaderboard(tmp_path: Path) -> None:
    args = _run_tools_args(tmp_path)
    result = runner.invoke(app, ["run-tools", *args])
    assert result.exit_code == 0, result.stdout
    out_dir = tmp_path / "out"
    assert (out_dir / "summary.csv").is_file()
    assert (out_dir / "leaderboard.csv").is_file()
