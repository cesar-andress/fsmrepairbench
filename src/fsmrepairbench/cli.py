"""Command-line interface for FSMRepairBench."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from fsmrepairbench.analytics import AnalyticsError, generate_benchmark_report
from fsmrepairbench.dataset_builder import (
    DEFAULT_OUTPUT_DIR,
    DatasetBuilderError,
    build_dataset,
)
from fsmrepairbench.difficulty import (
    DifficultyError,
    estimate_difficulty_from_path,
    export_difficulty_metadata,
)
from fsmrepairbench.experiments import (
    ExperimentConfigError,
    load_experiment_config,
    run_experiment,
)
from fsmrepairbench.freeze import FreezeError, freeze_release
from fsmrepairbench.generator import BenchmarkGenerationError, generate_benchmark
from fsmrepairbench.generators.synthetic_factory import (
    ComplexityLevel,
    SyntheticFactoryError,
    SyntheticGenerationParams,
    export_fsm_json,
    generate_synthetic_fsm,
    params_from_complexity,
)
from fsmrepairbench.llm.ollama import OllamaError, run_llm_repair_case
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.oracle_generator import (
    DepthLevel,
    OracleGeneratorError,
    export_oracle_json,
    generate_oracle_suite,
)
from fsmrepairbench.patch import PatchError, apply_patch, load_patch_json, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    BASELINE_ENGINE_NAMES,
    BaselineEngineError,
    propose_baseline_patch,
)
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import (
    load_fsm_json,
    load_oracle_suite,
    validate_fsm,
    validate_fsm_document,
    validate_oracle_document,
)

app = typer.Typer(
    name="fsmrepairbench",
    help="Benchmark toolkit for LLM-based repair of behavioural FSMs.",
    no_args_is_help=True,
)
console = Console()


@app.command("validate-fsm")
def validate_fsm_cmd(path: Path) -> None:
    """Validate an FSM JSON document."""
    ok, message, _ = validate_fsm_document(path)
    if ok:
        console.print(f"[green]OK[/green] {message}")
        raise typer.Exit(code=0)

    console.print(f"[red]ERROR[/red] {message}")
    raise typer.Exit(code=1)


@app.command("validate-oracle")
def validate_oracle(path: Path) -> None:
    """Validate an oracle suite JSON document."""
    ok, message, _ = validate_oracle_document(path)
    if ok:
        console.print(f"[green]OK[/green] {message}")
        raise typer.Exit(code=0)

    console.print(f"[red]ERROR[/red] {message}")
    raise typer.Exit(code=1)


@app.command("score")
def score(fsm_path: Path, oracle_path: Path) -> None:
    """Score an FSM against an oracle suite."""
    fsm_errors = []
    try:
        fsm = load_fsm_json(fsm_path)
        fsm_errors = validate_fsm(fsm)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load FSM: {exc}")
        raise typer.Exit(code=1) from exc

    if fsm_errors:
        console.print(f"[red]ERROR[/red] {fsm_errors[0]}")
        raise typer.Exit(code=1)

    try:
        suite = load_oracle_suite(oracle_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load oracle: {exc}")
        raise typer.Exit(code=1) from exc

    if suite.fsm_id is not None and suite.fsm_id != fsm.id:
        console.print(
            "[red]ERROR[/red] Oracle fsm_id "
            f"'{suite.fsm_id}' does not match FSM id '{fsm.id}'"
        )
        raise typer.Exit(code=1)

    result = score_oracle_suite(fsm, suite)

    console.print(f"[bold]BPR[/bold]: {result.bpr:.2%}")
    console.print(
        f"Steps: {result.passed_steps}/{result.total_steps} | "
        f"Scenarios: {result.passed_scenarios}/{result.total_scenarios}"
    )

    table = Table(title="Scenario Results")
    table.add_column("Scenario")
    table.add_column("Passed")
    table.add_column("Steps")
    for scenario in result.scenarios:
        table.add_row(
            scenario.scenario_id,
            "yes" if scenario.passed else "no",
            f"{scenario.passed_steps}/{scenario.total_steps}",
        )
    console.print(table)

    raise typer.Exit(code=0 if result.bpr == 1.0 else 1)


@app.command("mutate")
def mutate_cmd(
    ref_fsm_path: Path,
    operator: str = typer.Option(..., "--operator", help="Mutation operator name."),
    seed: int = typer.Option(..., "--seed", help="Deterministic seed."),
    out: Path = typer.Option(..., "--out", help="Output path for faulty FSM JSON."),
    meta: Path = typer.Option(..., "--meta", help="Output path for bug metadata JSON."),
) -> None:
    """Generate a faulty FSM from a reference FSM."""
    if operator not in MUTATION_OPERATORS:
        console.print(
            f"[red]ERROR[/red] Unknown operator '{operator}'. "
            f"Known: {', '.join(MUTATION_OPERATORS)}"
        )
        raise typer.Exit(code=1)

    try:
        reference = load_fsm_json(ref_fsm_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load reference FSM: {exc}")
        raise typer.Exit(code=1) from exc

    reference_errors = validate_fsm(reference)
    if reference_errors:
        console.print(f"[red]ERROR[/red] Invalid reference FSM: {reference_errors[0]}")
        raise typer.Exit(code=1)

    try:
        faulty_fsm, bug_metadata = mutate(reference, operator, seed)
    except MutatorError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    out.write_text(
        faulty_fsm.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )
    meta.write_text(
        bug_metadata.model_dump_json(indent=2) + "\n",
        encoding="utf-8",
    )

    console.print(
        f"[green]OK[/green] Wrote faulty FSM '{faulty_fsm.id}' to {out} "
        f"and metadata '{bug_metadata.bug_id}' to {meta}"
    )
    raise typer.Exit(code=0)


@app.command("generate-benchmark")
def generate_benchmark_cmd(
    input_dir: Path,
    output_dir: Path,
    bugs_per_fsm: int = typer.Option(10, "--bugs-per-fsm", min=1),
    seed: int = typer.Option(123, "--seed"),
) -> None:
    """Generate benchmark cases from reference FSMs."""
    if not input_dir.is_dir():
        console.print(f"[red]ERROR[/red] Input directory not found: {input_dir}")
        raise typer.Exit(code=1)

    try:
        result = generate_benchmark(
            input_dir,
            output_dir,
            bugs_per_fsm=bugs_per_fsm,
            seed=seed,
        )
    except BenchmarkGenerationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Generated {len(result.cases)} cases in {result.output_dir}"
    )
    console.print(f"Summary written to {result.summary_path}")
    raise typer.Exit(code=0)


@app.command("apply-patch")
def apply_patch_cmd(
    fsm_path: Path,
    patch_path: Path,
    out: Path = typer.Option(..., "--out", help="Output path for patched FSM JSON."),
    allow_nondeterminism: bool = typer.Option(
        False,
        "--allow-nondeterminism",
        help="Allow non-deterministic resulting FSMs.",
    ),
) -> None:
    """Apply a repair patch to an FSM."""
    try:
        fsm = load_fsm_json(fsm_path)
        patch = load_patch_json(patch_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    errors = validate_patch(fsm, patch, allow_nondeterminism=allow_nondeterminism)
    if errors:
        console.print(f"[red]ERROR[/red] {errors[0]}")
        raise typer.Exit(code=1)

    try:
        repaired = apply_patch(fsm, patch)
    except PatchError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    out.write_text(repaired.model_dump_json(indent=2) + "\n", encoding="utf-8")
    console.print(f"[green]OK[/green] Wrote patched FSM to {out}")
    raise typer.Exit(code=0)


@app.command("baseline-repair")
def baseline_repair_cmd(
    fsm_path: Path,
    oracle_path: Path,
    engine: str = typer.Option(..., "--engine", help="Baseline repair engine name."),
    out: Path = typer.Option(..., "--out", help="Output path for proposed patch JSON."),
    seed: int = typer.Option(0, "--seed", help="Seed for random baseline repair."),
) -> None:
    """Propose a baseline repair patch for an FSM using oracle guidance."""
    if engine not in BASELINE_ENGINE_NAMES:
        console.print(
            f"[red]ERROR[/red] Unknown engine '{engine}'. "
            f"Known: {', '.join(BASELINE_ENGINE_NAMES)}"
        )
        raise typer.Exit(code=1)

    try:
        fsm = load_fsm_json(fsm_path)
        oracle_suite = load_oracle_suite(oracle_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if oracle_suite.fsm_id is not None and oracle_suite.fsm_id != fsm.id:
        console.print(
            "[red]ERROR[/red] Oracle fsm_id "
            f"'{oracle_suite.fsm_id}' does not match FSM id '{fsm.id}'"
        )
        raise typer.Exit(code=1)

    try:
        patch = propose_baseline_patch(fsm, oracle_suite, engine=engine, seed=seed)
    except BaselineEngineError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    out.write_text(patch.model_dump_json(indent=2) + "\n", encoding="utf-8")
    console.print(
        f"[green]OK[/green] Wrote baseline patch '{patch.patch_id}' "
        f"with {len(patch.operations)} operations to {out}"
    )
    raise typer.Exit(code=0)


@app.command("llm-repair")
def llm_repair_cmd(
    fsm_path: Path,
    oracle_path: Path,
    model: str = typer.Option(..., "--model", help="Ollama model name."),
    out: Path = typer.Option(..., "--out", help="Output path for repair result JSON."),
    iterations: int = typer.Option(3, "--iterations", min=1),
    temperature: float = typer.Option(0.0, "--temperature"),
) -> None:
    """Run an iterative Ollama repair loop against an oracle suite."""
    try:
        fsm = load_fsm_json(fsm_path)
        oracle_suite = load_oracle_suite(oracle_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if oracle_suite.fsm_id is not None and oracle_suite.fsm_id != fsm.id:
        console.print(
            "[red]ERROR[/red] Oracle fsm_id "
            f"'{oracle_suite.fsm_id}' does not match FSM id '{fsm.id}'"
        )
        raise typer.Exit(code=1)

    try:
        result = run_llm_repair_case(
            fsm,
            oracle_suite,
            model=model,
            max_iterations=iterations,
            temperature=temperature,
        )
    except (OllamaError, ValueError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    out.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
    console.print(
        f"[green]OK[/green] LLM repair finished with BPR {result.score:.2%}. "
        f"Wrote result to {out}"
    )
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("run-experiment")
def run_experiment_cmd(
    config_path: Path,
    resume: bool = typer.Option(True, "--resume/--no-resume"),
) -> None:
    """Run a batch repair experiment from a YAML config file."""
    try:
        config = load_experiment_config(config_path)
    except ExperimentConfigError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        result = run_experiment(config, resume=resume)
    except ExperimentConfigError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Experiment finished with {len(result.rows)} case/model results"
    )
    console.print(f"Progress: {result.progress_path}")
    console.print(f"Summary: {result.summary_path}")
    raise typer.Exit(code=0)


@app.command("freeze")
def freeze_cmd(results_dir: Path, release_dir: Path) -> None:
    """Freeze experiment results into an auditable release directory."""
    try:
        result = freeze_release(results_dir, release_dir)
    except FreezeError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]OK[/green] Frozen release written to {result.release_dir}")
    console.print(f"Manifest: {result.manifest_path}")
    console.print(f"Files checksummed: {len(result.files)}")
    raise typer.Exit(code=0)


@app.command("generate-fsm")
def generate_fsm_cmd(
    out: Path = typer.Option(..., "--out", help="Output path for generated FSM JSON."),
    states: int | None = typer.Option(None, "--states", min=1),
    events: int | None = typer.Option(None, "--events", min=1),
    branching_factor: int | None = typer.Option(None, "--branching-factor", min=1),
    seed: int = typer.Option(0, "--seed"),
    deterministic: bool = typer.Option(True, "--deterministic/--nondeterministic"),
    allow_dead_states: bool = typer.Option(False, "--allow-dead-states"),
    complexity: ComplexityLevel | None = typer.Option(
        None,
        "--complexity",
        help="Optional preset: small, medium, large, very_large",
    ),
) -> None:
    """Generate a synthetic FSM and export it as benchmark JSON."""
    try:
        if complexity is not None:
            params = params_from_complexity(
                complexity,
                seed=seed,
                deterministic=deterministic,
                allow_dead_states=allow_dead_states,
                branching_factor=branching_factor,
                num_states=states,
                num_events=events,
            )
        else:
            params = SyntheticGenerationParams(
                num_states=states or 10,
                num_events=events or 5,
                branching_factor=branching_factor or 2,
                deterministic=deterministic,
                allow_dead_states=allow_dead_states,
                seed=seed,
            )
        fsm = generate_synthetic_fsm(params)
        export_fsm_json(fsm, out)
    except SyntheticFactoryError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Generated FSM '{fsm.id}' with "
        f"{len(fsm.states)} states and {len(fsm.transitions)} transitions at {out}"
    )
    raise typer.Exit(code=0)


@app.command("generate-oracles")
def generate_oracles_cmd(
    fsm_path: Path,
    out: Path = typer.Option(..., "--out", help="Output path for oracle suite JSON."),
    depth: DepthLevel = typer.Option("medium", "--depth"),
) -> None:
    """Generate behavioural oracle scenarios from a reference FSM."""
    try:
        fsm = load_fsm_json(fsm_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load FSM: {exc}")
        raise typer.Exit(code=1) from exc

    fsm_errors = validate_fsm(fsm)
    if fsm_errors:
        console.print(f"[red]ERROR[/red] Invalid FSM: {fsm_errors[0]}")
        raise typer.Exit(code=1)

    try:
        result = generate_oracle_suite(fsm, depth=depth)
        export_oracle_json(result.suite, out)
    except OracleGeneratorError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    coverage = result.coverage
    console.print(
        f"[green]OK[/green] Generated oracle suite '{result.suite.id}' with "
        f"{len(result.suite.scenarios)} scenarios at {out}"
    )
    console.print(
        "Coverage: "
        f"states={coverage.state_coverage:.2%}, "
        f"transitions={coverage.transition_coverage:.2%}, "
        f"events={coverage.event_coverage:.2%}"
    )
    raise typer.Exit(code=0)


@app.command("build-dataset")
def build_dataset_cmd(
    size: int = typer.Option(..., "--size", min=1),
    seed: int = typer.Option(42, "--seed"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output"),
    workers: int | None = typer.Option(None, "--workers", min=1),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
) -> None:
    """Build a large-scale benchmark dataset automatically."""
    try:
        result = build_dataset(
            size=size,
            seed=seed,
            output_dir=output_dir,
            workers=workers,
            resume=resume,
        )
    except DatasetBuilderError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    completed = len(
        [row for row in result.rows if row.status in {"completed", "skipped"}]
    )
    console.print(
        f"[green]OK[/green] Built dataset with {completed} cases in {result.output_dir}"
    )
    console.print(f"Metadata: {result.metadata_path}")
    console.print(f"Index: {result.index_path}")
    console.print(f"Progress: {result.progress_path}")
    raise typer.Exit(code=0)


@app.command("estimate-difficulty")
def estimate_difficulty_cmd(
    case_path: Path,
    out: Path | None = typer.Option(None, "--out", help="Optional metadata JSON output path."),
) -> None:
    """Estimate difficulty for a benchmark case or FSM JSON file."""
    try:
        estimate = estimate_difficulty_from_path(case_path)
    except (DifficultyError, OSError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if out is not None:
        export_difficulty_metadata(estimate, out)

    table = Table(title="FSM Difficulty Estimate")
    table.add_column("Field")
    table.add_column("Value")
    table.add_row("difficulty_score", f"{estimate.difficulty_score:.2f}")
    table.add_row("category", estimate.category)
    metrics = estimate.metrics
    table.add_row("state_count", str(metrics.state_count))
    table.add_row("transition_count", str(metrics.transition_count))
    table.add_row("branching_factor", f"{metrics.branching_factor:.4f}")
    table.add_row("average_path_length", f"{metrics.average_path_length:.4f}")
    table.add_row("cycles", str(metrics.cycles))
    table.add_row("strongly_connected_components", str(metrics.strongly_connected_components))
    console.print(table)

    if out is not None:
        console.print(f"[green]OK[/green] Wrote difficulty metadata to {out}")
    raise typer.Exit(code=0)


@app.command("benchmark-report")
def benchmark_report_cmd(dataset_dir: Path) -> None:
    """Generate diversity analytics for a benchmark dataset."""
    try:
        result = generate_benchmark_report(dataset_dir)
    except AnalyticsError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    analytics = result.analytics
    console.print(
        f"[green]OK[/green] Generated analytics for {analytics.case_count} cases in "
        f"{result.analytics_dir}"
    )
    console.print(f"Summary: {result.summary_path}")
    console.print(f"Report: {result.report_path}")
    console.print(f"Plots: {result.plots_dir}")
    raise typer.Exit(code=0)


def main() -> None:
    """Entry point for the console script."""
    app()


if __name__ == "__main__":
    main()
