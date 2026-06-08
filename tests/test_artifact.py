"""Tests for artifact evaluation and reproduction."""

from __future__ import annotations

import json
import shutil
import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from fsmrepairbench.artifact import ArtifactError, load_artifact_bundle, reproduce_artifact
from fsmrepairbench.cli import app
from fsmrepairbench.experiments import result_path
from fsmrepairbench.llm.prompts import DEFAULT_REPAIR_PROMPT_TEMPLATE
from fsmrepairbench.models import FSM, OracleSuite, RepairResult
from fsmrepairbench.patch import apply_patch, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    OracleGuidedMissingTransitionRepair,
    OracleGuidedWrongTargetRepair,
)
from fsmrepairbench.scorer import score_oracle_suite

ARTIFACTS = Path(__file__).resolve().parents[1] / "artifacts"
runner = CliRunner()


def _fake_repair_runner(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float,
) -> RepairResult:
    _ = model, max_iterations, temperature
    initial_score = score_oracle_suite(faulty_fsm, oracle_suite)
    for engine in (
        OracleGuidedMissingTransitionRepair(),
        OracleGuidedWrongTargetRepair(),
    ):
        patch = engine.propose_patch(faulty_fsm, oracle_suite)
        if validate_patch(faulty_fsm, patch):
            continue
        repaired = apply_patch(faulty_fsm, patch)
        final_score = score_oracle_suite(repaired, oracle_suite)
        if final_score.bpr <= initial_score.bpr:
            continue
        return RepairResult(
            bug_id=faulty_fsm.id,
            passed=final_score.bpr == 1.0,
            score=final_score.bpr,
            details={
                "model": model,
                "temperature": temperature,
                "max_iterations": max_iterations,
                "iterations": [
                    {
                        "iteration": 1,
                        "bpr_before": initial_score.bpr,
                        "bpr_after": final_score.bpr,
                        "patch_valid": True,
                        "patch_applied": True,
                        "validation_errors": [],
                    }
                ],
                "final_fsm": repaired.model_dump(),
                "passed_steps": final_score.passed_steps,
                "total_steps": final_score.total_steps,
                "passed_scenarios": final_score.passed_scenarios,
                "total_scenarios": final_score.total_scenarios,
            },
        )

    return RepairResult(
        bug_id=faulty_fsm.id,
        passed=False,
        score=initial_score.bpr,
        details={
            "model": model,
            "temperature": temperature,
            "max_iterations": max_iterations,
            "iterations": [],
            "final_fsm": faulty_fsm.model_dump(),
            "passed_steps": initial_score.passed_steps,
            "total_steps": initial_score.total_steps,
            "passed_scenarios": initial_score.passed_scenarios,
            "total_scenarios": initial_score.total_scenarios,
        },
    )


def _write_minimal_artifact(root: Path) -> Path:
    (root / "dataset").mkdir(parents=True)
    (root / "seeds").mkdir()
    (root / "models").mkdir()
    (root / "prompts").mkdir()
    (root / "configs").mkdir()

    shutil.copy2(
        ARTIFACTS / "icse2027" / "prompts" / "repair_v1.txt",
        root / "prompts" / "repair_v1.txt",
    )
    (root / "dataset" / "version.yaml").write_text(
        textwrap.dedent(
            """
            benchmark_version: v1.0
            size: 2
            seed: 42
            output_dir: data/test-artifact
            build_if_missing: true
            cases_subdir: cases
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "seeds" / "seeds.yaml").write_text(
        "dataset: 42\nmutation: 42\nreference: 42\n",
        encoding="utf-8",
    )
    (root / "models" / "models.yaml").write_text(
        textwrap.dedent(
            """
            default_backend: ollama
            models:
              - model-a
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (root / "prompts" / "prompts.yaml").write_text(
        "version: repair_v1\ntemplate_file: repair_v1.txt\n",
        encoding="utf-8",
    )
    (root / "configs" / "experiment.yaml").write_text(
        textwrap.dedent(
            """
            iterations: 2
            temperature: 0.0
            workers: 1
            resume: false
            checkpoint_interval: 1
            output_dir: results/test-artifact
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    artifact_path = root / "artifact.yaml"
    artifact_path.write_text(
        textwrap.dedent(
            """
            artifact_id: test-artifact
            title: Test Artifact
            fsmrepairbench_version: "0.1.0"
            dataset: dataset/version.yaml
            seeds: seeds/seeds.yaml
            models: models/models.yaml
            prompts: prompts/prompts.yaml
            experiment: configs/experiment.yaml
            postprocess:
              freeze: true
              release_dir: releases/test-artifact
              leaderboard: true
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return artifact_path


@pytest.mark.parametrize(
    "artifact_name",
    ["icse2027", "emse2027", "tse2028"],
)
def test_bundled_artifacts_load(artifact_name: str) -> None:
    bundle = load_artifact_bundle(ARTIFACTS / artifact_name / "artifact.yaml")
    assert bundle.manifest.artifact_id == artifact_name
    assert bundle.dataset.benchmark_version.value.startswith("v")
    assert bundle.models.models
    assert bundle.prompts.version == "repair_v1"
    assert bundle.seeds.dataset == bundle.dataset.seed


def test_bundled_prompt_template_matches_default() -> None:
    template = (ARTIFACTS / "icse2027" / "prompts" / "repair_v1.txt").read_text(
        encoding="utf-8"
    )
    assert template == DEFAULT_REPAIR_PROMPT_TEMPLATE


def test_reproduce_artifact_end_to_end(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    artifact_path = _write_minimal_artifact(artifact_root)

    result = reproduce_artifact(
        artifact_path,
        repair_runner=_fake_repair_runner,
        resume=False,
    )

    assert result.artifact_id == "test-artifact"
    assert result.experiment.summary_path.is_file()
    assert result.experiment.progress_path.is_file()
    assert len(result.experiment.rows) == 2
    assert result.freeze is not None
    assert (result.freeze.release_dir / "manifest.json").is_file()
    assert result.leaderboard is not None
    assert result.leaderboard.markdown_path.is_file()
    assert result.report_path.is_file()

    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["artifact_id"] == "test-artifact"
    assert report["dataset"]["benchmark_version"] == "v1.0"
    assert report["prompts"]["version"] == "repair_v1"

    result_file = result_path(result.experiment.output_dir, "case_000001", "model-a")
    assert result_file.is_file()


def test_reproduce_rejects_seed_mismatch(tmp_path: Path) -> None:
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    artifact_path = _write_minimal_artifact(artifact_root)
    seeds_path = artifact_root / "seeds" / "seeds.yaml"
    seeds_path.write_text("dataset: 99\nmutation: 99\nreference: 99\n", encoding="utf-8")

    with pytest.raises(ArtifactError, match="Seed mismatch"):
        reproduce_artifact(artifact_path, repair_runner=_fake_repair_runner, resume=False)


def test_cli_reproduce(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    artifact_root = tmp_path / "artifact"
    artifact_root.mkdir()
    artifact_path = _write_minimal_artifact(artifact_root)

    monkeypatch.setattr(
        "fsmrepairbench.cli.reproduce_artifact",
        lambda path, resume=None: reproduce_artifact(
            path,
            repair_runner=_fake_repair_runner,
            resume=resume,
        ),
    )

    result = runner.invoke(app, ["reproduce", str(artifact_path), "--no-resume"])
    assert result.exit_code == 0
    assert "Reproduced test-artifact" in result.stdout
