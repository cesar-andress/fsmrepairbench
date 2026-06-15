"""Integration tests for regenerating frozen paper exports from repo campaign outputs."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PAPER1 = Path(__file__).resolve().parents[2].parent / "paper1"
REPO = Path(__file__).resolve().parents[2]
PAPER_RESULTS = PAPER1 / "results"

pytestmark = pytest.mark.integration


def _load_generate_module(script_name: str):
    script_path = PAPER1 / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(script_name.replace(".py", ""), script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _require_repo_campaign(src: Path) -> None:
    if not src.is_dir():
        pytest.skip(f"Missing repo campaign output: {src}")


@pytest.fixture()
def isolated_paper_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Copy paper results to a temp tree so generate scripts do not mutate the checkout."""
    out_root = tmp_path / "paper_results"
    if PAPER_RESULTS.is_dir():
        shutil.copytree(PAPER_RESULTS, out_root)
    else:
        out_root.mkdir()
    monkeypatch.setenv("FSMREPAIRBENCH_GOLDEN_RESULTS_DIR", str(out_root))
    return out_root


def test_generate_baseline_repair_c1_export_only(isolated_paper_results: Path) -> None:
    raw_runs = REPO / "results" / "repair_baseline_1k_c1"
    if not (raw_runs / "per_case_results.csv").is_file() and not (raw_runs / "summary.csv").is_file():
        legacy = REPO / "results" / "baseline_repair_C1"
        if (legacy / "per_case_results.csv").is_file():
            raw_runs = legacy
    if not raw_runs.is_dir():
        pytest.skip("C1 raw runs not present")

    out = isolated_paper_results / "baseline_repair_C1"
    out.mkdir(parents=True, exist_ok=True)

    completed = subprocess.run(
        [
            sys.executable,
            str(PAPER1 / "scripts" / "generate_baseline_repair_C1_outputs.py"),
            "--skip-multi-seed",
            "--no-per-seed-runs",
        ],
        cwd=str(REPO),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr

    manifest = PAPER_RESULTS / "baseline_repair_C1" / "manifest.json"
    if manifest.is_file():
        assert "cohort_sha256" in manifest.read_text(encoding="utf-8")


def test_generate_rq3_localization_outputs(
    isolated_paper_results: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = REPO / "results" / "rq3_localization_1k"
    _require_repo_campaign(src)

    module = _load_generate_module("generate_rq3_localization_outputs.py")
    out = tmp_path / "rq3_out"
    monkeypatch.setattr(module, "SRC", src)
    monkeypatch.setattr(module, "OUT", out)
    module.main()

    assert (out / "manifest.json").is_file()
    assert (out / "per_case_results.csv").is_file()
    assert (out / "tables").is_dir()


def test_generate_rq4_coupling_outputs_regenerate_derived(
    isolated_paper_results: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = REPO / "results" / "rq4_coupling_250"
    _require_repo_campaign(src)
    subset = REPO / "results" / "rq4_coupling_subset"
    if not subset.is_dir():
        pytest.skip("Missing rq4_coupling_subset workspace")

    module = _load_generate_module("generate_rq4_coupling_outputs.py")
    out = tmp_path / "rq4_out"
    monkeypatch.setattr(module, "SRC", src)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "RANDOM_SRC", REPO / "results" / "rq4_coupling_250_random_secondary")
    monkeypatch.setattr(
        sys,
        "argv",
        ["generate_rq4_coupling_outputs.py", "--skip-random-secondary", "--regenerate-derived"],
    )
    module.main()

    assert (out / "manifest.json").is_file()
    assert (out / "coupling_metrics.csv").is_file()
    assert (out / "fo_ho_metrics_by_order.csv").is_file()
    assert "complete_repair_rate_detectable" in (out / "coupling_metrics.csv").read_text(encoding="utf-8")


def test_generate_oracle_depth_ablation_outputs(
    isolated_paper_results: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    src = REPO / "results" / "oracle_depth_ablation"
    _require_repo_campaign(src)

    module = _load_generate_module("generate_oracle_depth_ablation_outputs.py")
    out = tmp_path / "c3_out"
    tables = tmp_path / "tables"
    figures = tmp_path / "figures"
    monkeypatch.setattr(module, "SRC", src)
    monkeypatch.setattr(module, "OUT", out)
    monkeypatch.setattr(module, "TABLES", tables)
    monkeypatch.setattr(module, "FIGURES", figures)
    module.main()

    assert (out / "manifest.json").is_file()
    assert (out / "depth_summary.csv").is_file()
    assert tables.is_dir()


def test_verify_cohort_manifests_script_passes() -> None:
    script = PAPER1 / "scripts" / "verify_cohort_manifests.py"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(REPO),
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "OK verified" in completed.stdout
