"""Artifact evaluation and experiment reproduction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator

from fsmrepairbench import __version__
from fsmrepairbench.dataset_builder import build_dataset
from fsmrepairbench.experiments import (
    ExperimentConfig,
    ExperimentResult,
    RepairRunner,
    discover_experiment_cases,
    run_experiment,
)
from fsmrepairbench.freeze import FreezeResult, freeze_release
from fsmrepairbench.leaderboard import LeaderboardResult, generate_leaderboard
from fsmrepairbench.llm.clients.base import ModelBackend
from fsmrepairbench.llm.prompts import (
    reset_active_prompt_template,
    set_active_prompt_template,
)
from fsmrepairbench.versioning import BenchmarkVersion, detect_benchmark_version

REPRODUCTION_REPORT_FILENAME = "reproduction_report.json"


class ArtifactError(ValueError):
    """Raised when an artifact manifest or reproduction step fails."""


class DatasetArtifactSpec(BaseModel):
    """Dataset pinning for an artifact package."""

    benchmark_version: BenchmarkVersion
    size: int = Field(ge=1)
    seed: int
    output_dir: Path
    build_if_missing: bool = True
    cases_subdir: str = "cases"

    @field_validator("benchmark_version", mode="before")
    @classmethod
    def _coerce_benchmark_version(cls, value: str | BenchmarkVersion) -> BenchmarkVersion:
        if isinstance(value, BenchmarkVersion):
            return value
        return BenchmarkVersion(str(value))

    @field_validator("output_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)


class SeedsArtifactSpec(BaseModel):
    """Deterministic seeds used by an artifact package."""

    dataset: int
    mutation: int | None = None
    reference: int | None = None


class ModelsArtifactSpec(BaseModel):
    """Model list and backend defaults for an artifact package."""

    default_backend: ModelBackend = ModelBackend.OLLAMA
    models: list[str | dict[str, Any]]

    @field_validator("default_backend", mode="before")
    @classmethod
    def _coerce_backend(cls, value: str | ModelBackend) -> ModelBackend:
        if isinstance(value, ModelBackend):
            return value
        return ModelBackend(str(value))


class PromptsArtifactSpec(BaseModel):
    """Prompt template metadata for an artifact package."""

    version: str
    template_file: str


class ExperimentArtifactSpec(BaseModel):
    """Experiment execution settings for an artifact package."""

    iterations: int = Field(default=3, ge=1)
    temperature: float = 0.0
    workers: int = Field(default=4, ge=1)
    resume: bool = True
    checkpoint_interval: int = Field(default=100, ge=1)
    output_dir: Path

    @field_validator("output_dir", mode="before")
    @classmethod
    def _coerce_path(cls, value: str | Path) -> Path:
        return Path(value)


class PostprocessArtifactSpec(BaseModel):
    """Optional post-processing steps after experiment execution."""

    freeze: bool = False
    release_dir: Path | None = None
    leaderboard: bool = False

    @field_validator("release_dir", mode="before")
    @classmethod
    def _coerce_release_dir(cls, value: str | Path | None) -> Path | None:
        if value is None:
            return None
        return Path(value)


class ArtifactManifest(BaseModel):
    """Top-level artifact manifest referenced by ``artifact.yaml``."""

    artifact_id: str
    title: str
    fsmrepairbench_version: str = __version__
    dataset: str | Path | dict[str, Any]
    seeds: str | Path | dict[str, Any]
    models: str | Path | dict[str, Any]
    prompts: str | Path | dict[str, Any]
    experiment: str | Path | dict[str, Any]
    postprocess: PostprocessArtifactSpec | None = None


@dataclass(frozen=True)
class ArtifactBundle:
    """Resolved artifact package ready for reproduction."""

    manifest_path: Path
    artifact_root: Path
    manifest: ArtifactManifest
    dataset: DatasetArtifactSpec
    seeds: SeedsArtifactSpec
    models: ModelsArtifactSpec
    prompts: PromptsArtifactSpec
    experiment: ExperimentArtifactSpec
    postprocess: PostprocessArtifactSpec


@dataclass(frozen=True)
class ReproduceResult:
    """Outcome of reproducing one artifact package."""

    artifact_id: str
    artifact_root: Path
    dataset_dir: Path
    cases_dir: Path
    experiment: ExperimentResult
    freeze: FreezeResult | None
    leaderboard: LeaderboardResult | None
    report_path: Path


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        msg = f"Failed to read artifact file '{path}': {exc}"
        raise ArtifactError(msg) from exc
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML in artifact file '{path}': {exc}"
        raise ArtifactError(msg) from exc

    if not isinstance(raw, dict):
        msg = f"Artifact file must contain a YAML mapping: {path}"
        raise ArtifactError(msg)
    return raw


def _resolve_artifact_reference(
    artifact_root: Path,
    reference: str | Path | dict[str, Any],
) -> dict[str, Any]:
    if isinstance(reference, dict):
        return reference

    path = Path(reference)
    if not path.is_absolute():
        path = artifact_root / path
    return _load_yaml_mapping(path)


def _resolve_prompt_template(artifact_root: Path, prompts: PromptsArtifactSpec) -> str:
    template_path = Path(prompts.template_file)
    if not template_path.is_absolute():
        template_path = artifact_root / "prompts" / template_path
        if not template_path.is_file():
            template_path = artifact_root / prompts.template_file
    if not template_path.is_file():
        msg = f"Prompt template not found: {template_path}"
        raise ArtifactError(msg)
    return template_path.read_text(encoding="utf-8")


def _resolve_path(artifact_root: Path, path: Path) -> Path:
    if path.is_absolute():
        return path
    return (artifact_root / path).resolve()


def load_artifact_bundle(artifact_path: Path) -> ArtifactBundle:
    """Load and resolve an artifact package from *artifact_path*."""
    artifact_path = artifact_path.resolve()
    if not artifact_path.is_file():
        msg = f"Artifact manifest not found: {artifact_path}"
        raise ArtifactError(msg)

    artifact_root = artifact_path.parent
    try:
        manifest = ArtifactManifest.model_validate(_load_yaml_mapping(artifact_path))
    except Exception as exc:
        msg = f"Invalid artifact manifest schema in '{artifact_path}': {exc}"
        raise ArtifactError(msg) from exc

    dataset = DatasetArtifactSpec.model_validate(
        _resolve_artifact_reference(artifact_root, manifest.dataset)
    )
    seeds = SeedsArtifactSpec.model_validate(
        _resolve_artifact_reference(artifact_root, manifest.seeds)
    )
    models = ModelsArtifactSpec.model_validate(
        _resolve_artifact_reference(artifact_root, manifest.models)
    )
    prompts = PromptsArtifactSpec.model_validate(
        _resolve_artifact_reference(artifact_root, manifest.prompts)
    )
    experiment = ExperimentArtifactSpec.model_validate(
        _resolve_artifact_reference(artifact_root, manifest.experiment)
    )
    postprocess = manifest.postprocess or PostprocessArtifactSpec()

    if seeds.dataset != dataset.seed:
        msg = (
            f"Seed mismatch: dataset.seed={dataset.seed} "
            f"does not match seeds.dataset={seeds.dataset}"
        )
        raise ArtifactError(msg)

    return ArtifactBundle(
        manifest_path=artifact_path,
        artifact_root=artifact_root,
        manifest=manifest,
        dataset=dataset,
        seeds=seeds,
        models=models,
        prompts=prompts,
        experiment=experiment,
        postprocess=postprocess,
    )


def prepare_artifact_dataset(bundle: ArtifactBundle) -> tuple[Path, Path]:
    """Ensure the artifact dataset exists and matches the pinned version."""
    dataset_dir = _resolve_path(bundle.artifact_root, bundle.dataset.output_dir)
    cases_dir = dataset_dir / bundle.dataset.cases_subdir
    metadata_path = dataset_dir / "metadata.json"

    needs_build = bundle.dataset.build_if_missing and (
        not cases_dir.is_dir() or not metadata_path.is_file()
    )
    if needs_build:
        build_dataset(
            size=bundle.dataset.size,
            seed=bundle.dataset.seed,
            output_dir=dataset_dir,
            workers=1,
            resume=False,
            benchmark_version=bundle.dataset.benchmark_version,
        )

    if not cases_dir.is_dir():
        msg = f"Cases directory not found for artifact dataset: {cases_dir}"
        raise ArtifactError(msg)

    detected = detect_benchmark_version(dataset_dir)
    if detected is not bundle.dataset.benchmark_version:
        msg = (
            f"Dataset version mismatch for {dataset_dir}: "
            f"expected {bundle.dataset.benchmark_version.value}, found {detected.value}"
        )
        raise ArtifactError(msg)

    discover_experiment_cases(cases_dir)
    return dataset_dir, cases_dir


def build_experiment_config(bundle: ArtifactBundle, cases_dir: Path) -> ExperimentConfig:
    """Build an experiment config from a resolved artifact bundle."""
    output_dir = _resolve_path(bundle.artifact_root, bundle.experiment.output_dir)
    return ExperimentConfig(
        models=bundle.models.models,
        cases_dir=cases_dir,
        iterations=bundle.experiment.iterations,
        temperature=bundle.experiment.temperature,
        output_dir=output_dir,
        resume=bundle.experiment.resume,
        workers=bundle.experiment.workers,
        checkpoint_interval=bundle.experiment.checkpoint_interval,
        default_backend=bundle.models.default_backend,
    )


def write_reproduction_report(
    path: Path,
    *,
    bundle: ArtifactBundle,
    dataset_dir: Path,
    cases_dir: Path,
    experiment: ExperimentResult,
    freeze: FreezeResult | None,
    leaderboard: LeaderboardResult | None,
) -> None:
    """Write a JSON report describing a completed reproduction run."""
    payload = {
        "artifact_id": bundle.manifest.artifact_id,
        "title": bundle.manifest.title,
        "reproduced_at": datetime.now(tz=UTC).isoformat(),
        "fsmrepairbench_version": __version__,
        "artifact_fsmrepairbench_version": bundle.manifest.fsmrepairbench_version,
        "dataset": {
            "benchmark_version": bundle.dataset.benchmark_version.value,
            "dataset_dir": str(dataset_dir),
            "cases_dir": str(cases_dir),
            "size": bundle.dataset.size,
            "seed": bundle.dataset.seed,
        },
        "seeds": bundle.seeds.model_dump(),
        "models": bundle.models.model_dump(mode="json"),
        "prompts": bundle.prompts.model_dump(),
        "experiment": {
            "output_dir": str(experiment.output_dir),
            "summary_path": str(experiment.summary_path),
            "progress_path": str(experiment.progress_path),
            "result_count": len(experiment.rows),
        },
        "postprocess": {
            "freeze_release_dir": str(freeze.release_dir) if freeze is not None else None,
            "leaderboard_dir": str(leaderboard.results_dir) if leaderboard is not None else None,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def reproduce_artifact(
    artifact_path: Path,
    *,
    repair_runner: RepairRunner | None = None,
    resume: bool | None = None,
) -> ReproduceResult:
    """Reproduce the experiment defined by an artifact manifest."""
    bundle = load_artifact_bundle(artifact_path)
    if bundle.manifest.fsmrepairbench_version != __version__:
        msg = (
            f"Artifact targets fsmrepairbench {bundle.manifest.fsmrepairbench_version}, "
            f"but {__version__} is installed"
        )
        raise ArtifactError(msg)

    dataset_dir, cases_dir = prepare_artifact_dataset(bundle)
    experiment_config = build_experiment_config(bundle, cases_dir)
    prompt_template = _resolve_prompt_template(bundle.artifact_root, bundle.prompts)
    prompt_token = set_active_prompt_template(prompt_template)

    try:
        experiment_result = run_experiment(
            experiment_config,
            repair_runner=repair_runner,
            resume=resume,
        )
    finally:
        reset_active_prompt_template(prompt_token)

    freeze_result: FreezeResult | None = None
    if bundle.postprocess.freeze:
        release_dir = bundle.postprocess.release_dir
        if release_dir is None:
            release_dir = Path("releases") / bundle.manifest.artifact_id
        release_path = _resolve_path(bundle.artifact_root, release_dir)
        freeze_result = freeze_release(experiment_result.output_dir, release_path)

    leaderboard_result: LeaderboardResult | None = None
    if bundle.postprocess.leaderboard:
        leaderboard_result = generate_leaderboard(experiment_result.output_dir)

    report_path = bundle.artifact_root / REPRODUCTION_REPORT_FILENAME
    write_reproduction_report(
        report_path,
        bundle=bundle,
        dataset_dir=dataset_dir,
        cases_dir=cases_dir,
        experiment=experiment_result,
        freeze=freeze_result,
        leaderboard=leaderboard_result,
    )

    return ReproduceResult(
        artifact_id=bundle.manifest.artifact_id,
        artifact_root=bundle.artifact_root,
        dataset_dir=dataset_dir,
        cases_dir=cases_dir,
        experiment=experiment_result,
        freeze=freeze_result,
        leaderboard=leaderboard_result,
        report_path=report_path,
    )
