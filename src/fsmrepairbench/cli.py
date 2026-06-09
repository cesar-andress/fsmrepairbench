"""Command-line interface for FSMRepairBench."""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import typer
from pydantic import ValidationError
from rich.console import Console
from rich.table import Table

from fsmrepairbench.artifact import ArtifactError, load_artifact_bundle, reproduce_artifact
from fsmrepairbench.case_filter import (
    CaseFilterError,
    compute_subset_overlap,
    filter_cases,
    normalize_filter_key,
    parse_predicate_string,
    write_filter_csv,
    write_overlap_json,
)
from fsmrepairbench.coverage_optimizer import CoverageOptimizerError, generate_coverage_report
from fsmrepairbench.gap_detection import GapDetectionError, detect_benchmark_gaps
from fsmrepairbench.failure_pattern_mining import (
    FailurePatternMiningError,
    mine_failure_patterns,
)
from fsmrepairbench.dataset_builder import (
    DEFAULT_OUTPUT_DIR,
    DatasetBuilderError,
    build_dataset,
)
from fsmrepairbench.dataset_quality import DatasetQualityError, validate_dataset
from fsmrepairbench.novelty_analysis import NoveltyAnalysisError, analyze_novelty
from fsmrepairbench.difficulty import (
    DifficultyError,
    estimate_difficulty_from_path,
    export_difficulty_metadata,
)
from fsmrepairbench.difficulty_calibration import (
    DifficultyCalibrationError,
    calibrate_benchmark_difficulty,
)
from fsmrepairbench.semantics import (
    SUPPORTED_SEMANTICS_MODES,
    SemanticsError,
    validate_semantics,
    write_semantics_report_json,
)
from fsmrepairbench.tool_runner import ToolRunnerError, load_tool_configs, run_tools
from fsmrepairbench.experiments import (
    ExperimentConfigError,
    load_experiment_config,
    run_experiment,
)
from fsmrepairbench.experiment_pipeline import (
    ExperimentPipelineConfig,
    ExperimentPipelineError,
    run_experiment_pipeline,
)
from fsmrepairbench.smoke_test_pipeline import (
    SmokeTestPipelineConfig,
    SmokeTestPipelineError,
    prepare_smoke_test_input,
    prepare_smoke_test_input_from_examples,
    run_smoke_test_pipeline,
    validate_smoke_test_outputs,
)
from fsmrepairbench.freeze import FreezeError, freeze_release
from fsmrepairbench.generator import BenchmarkGenerationError, generate_benchmark
from fsmrepairbench.generators.fsm_benchmark_dataset import (
    FSMBenchmarkDatasetError,
    FSMBenchmarkGenerationConfig,
    SUPPORTED_FSM_TYPES,
    dataset_type_distribution,
    generate_fsm_benchmark_dataset,
)
from fsmrepairbench.generators.synthetic_factory import (
    ComplexityLevel,
    SyntheticFactoryError,
    SyntheticGenerationParams,
    export_fsm_json,
    generate_synthetic_fsm,
    params_from_complexity,
)
from fsmrepairbench.bpr_engine import (
    BPREngineError,
    BPRScoreInput,
    CandidatePrediction,
    load_candidate_prediction,
    load_mutants_from_directory,
    load_mutants_from_json,
    score_bpr_benchmark,
    write_bpr_csv_summaries,
    write_bpr_score_json,
)
from fsmrepairbench.coverage_oracle_generator import (
    CoverageOracleGeneratorError,
    SUPPORTED_COVERAGE_SUITE_TYPES,
    export_coverage_oracles_directory,
    export_coverage_oracles_json,
    generate_all_coverage_oracle_suites,
    generate_coverage_oracles_for_directory,
)
from fsmrepairbench.literature_mutation import (
    LITERATURE_MUTATION_OPERATORS,
    LiteratureMutationError,
    generate_literature_mutants,
    generate_literature_mutants_for_directory,
    generate_literature_mutants_for_path,
    write_mutant_report_json,
)
from fsmrepairbench.higher_order_mutation import (
    HigherOrderMutationError,
    analyze_dataset_coupling,
    mutate_higher_order,
    write_dataset_coupling_report,
)
from fsmrepairbench.leaderboard import LeaderboardError, generate_leaderboard
from fsmrepairbench.literature import (
    GenerationSupport,
    LiteratureError,
    build_literature_index,
    filter_literature_entries,
    get_literature_entry,
    literature_index_to_dict,
)
from fsmrepairbench.llm.ollama import OllamaError, run_llm_repair_case
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.models import BugMetadata, OracleSemanticsMode
from fsmrepairbench.oracle_generator import (
    DepthLevel,
    OracleGeneratorError,
    export_oracle_json,
    generate_oracle_suite,
)
from fsmrepairbench.requirement_generation import (
    RequirementGenerationError,
    RequirementStyle,
    export_requirements_txt,
    generate_requirements,
)
from fsmrepairbench.ambiguity_injection import (
    AmbiguityInjectionError,
    export_ambiguity_metadata,
    export_injected_requirements_txt,
    inject_requirement_ambiguity,
)
from fsmrepairbench.patch import PatchError, apply_patch, load_patch_json, validate_patch
from fsmrepairbench.repair_engines.baselines import (
    BASELINE_ENGINE_NAMES,
    BaselineEngineError,
    propose_baseline_patch,
)
from fsmrepairbench.metamorphic import (
    CORE_METAMORPHIC_RELATIONS,
    SUPPORTED_RELATIONS,
    MetamorphicError,
    MetamorphicRelationId,
    check_metamorphic_relation,
    export_metamorphic_verification_report,
    generate_metamorphic_cases,
    generate_metamorphic_relation_catalog,
    load_score_result,
    verify_metamorphic_case,
    verify_metamorphic_relations,
    write_metamorphic_check_json,
    write_metamorphic_relation_catalog,
)
from fsmrepairbench.error_propagation import (
    ErrorPropagationError,
    analyze_error_propagation,
    write_error_propagation_report_json,
)
from fsmrepairbench.oracle_selection import (
    SUPPORTED_ORACLE_SELECTION_STRATEGIES,
    OracleSelectionError,
    OracleSelectionStrategy,
    load_mutant_pool,
    select_oracle_suite,
    write_oracle_selection_report_json,
    write_selected_oracle_json,
)
from fsmrepairbench.fsm_tagging import (
    FSMTaggingError,
    SUPPORTED_FSM_TAGS,
    tag_fsm_directory,
)
from fsmrepairbench.adversarial_fsm import (
    AdversarialFSMError,
    SUPPORTED_ADVERSARIAL_PATTERNS,
    AdversarialPattern,
    generate_adversarial_dataset,
    generate_adversarial_fsm,
    write_adversarial_fsm,
    build_metadata_record,
)
from fsmrepairbench.llm_evaluation_tasks import (
    LLMEvaluationTaskError,
    SUPPORTED_LLM_TASK_TYPES,
    TASK_TYPE_NAMES,
    LLMTaskType,
    write_llm_evaluation_tasks,
)
from fsmrepairbench.oracle_generator import DepthLevel
from fsmrepairbench.test_suite_optimizer import (
    SUPPORTED_OPTIMIZER_ALGORITHMS,
    TestSuiteOptimizerError,
    OptimizerAlgorithm,
    optimize_test_suites,
    visualize_pareto_results,
    write_optimization_report_json,
)
from fsmrepairbench.selective_mutation import (
    SUPPORTED_STRATEGIES,
    MutationStrategy,
    SelectiveMutationError,
    plan_mutations,
    write_mutation_plan_json,
)
from fsmrepairbench.scorer import score_oracle_suite, write_score_csv, write_score_json
from fsmrepairbench.constrained_input import (
    CONSTRAINED_INPUT_CSV_COLUMNS,
    constrained_plan_to_csv_rows,
    constrained_plan_to_json_dict,
    generate_constrained_inputs,
)
from fsmrepairbench.coupling_tracker import (
    COUPLING_CSV_COLUMNS,
    coupling_report_to_csv_rows,
    coupling_report_to_json_dict,
    track_coupling_effect,
)
from fsmrepairbench.hierarchical_fsm import (
    HIERARCHICAL_CSV_COLUMNS,
    HierarchicalFSM,
    flatten_hierarchical_fsm,
    generate_hierarchical_oracle,
    hierarchical_oracle_to_csv_rows,
)
from fsmrepairbench.coverage import compute_coverage_report, write_coverage_json
from fsmrepairbench.fault_localization import (
    SuspiciousnessMethod,
    localize_fault,
    write_localization_json,
)
from fsmrepairbench.spec_coverage import (
    SPEC_COVERAGE_CSV_COLUMNS,
    compute_spec_coverage,
    spec_coverage_to_csv_rows,
    spec_coverage_to_json_dict,
)
from fsmrepairbench.sota_export import write_csv_report, write_json_report
from fsmrepairbench.stratified_builder import StratifiedBuilderError, build_stratified_dataset
from fsmrepairbench.validators import (
    is_oracle_compatible,
    load_fsm_json,
    load_oracle_suite,
    oracle_incompatibility_message,
    validate_fsm,
    validate_fsm_document,
    validate_oracle_document,
)
from fsmrepairbench.benchmark_evolution import (
    EVOLUTION_REPORT_FILENAME,
    BenchmarkEvolutionError,
    build_release_trace,
    compare_benchmark_evolution,
    write_evolution_report,
)
from fsmrepairbench.versioning import (
    MIGRATION_REPORT_FILENAME,
    RELEASE_MANIFEST_FILENAME,
    BenchmarkVersion,
    VersioningError,
    analyze_migration,
    detect_benchmark_version,
    migrate_benchmark,
    write_migration_report,
    write_release_manifest,
)

app = typer.Typer(
    name="fsmrepairbench",
    help="Benchmark toolkit for LLM-based repair of behavioural FSMs.",
    no_args_is_help=True,
)
evolution_app = typer.Typer(help="Trace and compare benchmark evolution releases v0, v1, and v2.")
app.add_typer(evolution_app, name="benchmark-evolution")
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


@app.command("validate-semantics")
def validate_semantics_cmd(
    fsm_path: Path,
    mode: str = typer.Option(..., "--mode", help="Oracle semantics mode to validate."),
    oracle_path: Path | None = typer.Option(
        None,
        "--oracle",
        help="Optional oracle suite used to validate mode-specific step requirements.",
    ),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Optional path to write the semantics validation report JSON.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Validate FSM and optional oracle semantics for advanced system families."""
    if mode not in SUPPORTED_SEMANTICS_MODES:
        console.print(
            f"[red]ERROR[/red] Unknown mode '{mode}'. "
            f"Supported: {', '.join(SUPPORTED_SEMANTICS_MODES)}"
        )
        raise typer.Exit(code=1)

    try:
        fsm = load_fsm_json(fsm_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load FSM: {exc}")
        raise typer.Exit(code=1) from exc

    oracle_suite = None
    if oracle_path is not None:
        try:
            oracle_suite = load_oracle_suite(oracle_path)
        except (OSError, json.JSONDecodeError, ValidationError) as exc:
            console.print(f"[red]ERROR[/red] Failed to load oracle: {exc}")
            raise typer.Exit(code=1) from exc

    try:
        report = validate_semantics(
            fsm,
            mode=cast(OracleSemanticsMode, mode),
            oracle_suite=oracle_suite,
        )
    except SemanticsError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if out is not None:
        write_semantics_report_json(out, report)

    if quiet:
        status = "valid" if report.valid else "invalid"
        console.print(f"[green]OK[/green] mode={mode} status={status} fsm={fsm.id}")
    else:
        features = report.structural_features
        console.print(
            f"FSM '{fsm.id}' semantics mode '{mode}': "
            f"{'valid' if report.valid else 'invalid'}"
        )
        console.print(
            "Features: "
            f"nondeterminism={features.has_nondeterminism}, "
            f"probabilities={features.has_probabilities}, "
            f"cycles={features.has_cycles}, "
            f"refusals={features.has_refusals}, "
            f"discrete_time={features.has_discrete_time}"
        )
        if report.issues:
            for issue in report.issues[:5]:
                prefix = "WARN" if issue.severity == "warning" else "ERR"
                console.print(f"  [{prefix}] {issue.message}")
        if out is not None:
            console.print(f"Report: {out}")

    raise typer.Exit(code=0 if report.valid else 1)


@app.command("score")
def score(
    fsm_path: Path,
    oracle_path: Path,
    out_json: Path | None = typer.Option(
        None,
        "--out-json",
        help="Write the full ScoreResult as JSON to this path.",
    ),
    out_csv: Path | None = typer.Option(
        None,
        "--out-csv",
        help="Write scenario-level score rows as CSV to this path.",
    ),
    quiet: bool = typer.Option(
        False,
        "--quiet",
        help="Suppress detailed table output; print a short summary only.",
    ),
) -> None:
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

    if not is_oracle_compatible(fsm, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(fsm, suite)}")
        raise typer.Exit(code=1)

    result = score_oracle_suite(fsm, suite)

    if out_json is not None:
        write_score_json(out_json, result)
    if out_csv is not None:
        write_score_csv(
            out_csv,
            fsm_id=fsm.id,
            oracle_suite_id=suite.id,
            result=result,
        )

    if quiet:
        console.print(f"[green]OK[/green] BPR: {result.bpr:.2%}")
    else:
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


@app.command("score-bpr")
def score_bpr_cmd(
    reference_path: Path,
    oracle_path: Path,
    candidate_path: Path,
    out: Path = typer.Option(..., "--out", help="Output JSON file or directory for CSV summaries."),
    mutants_path: Path | None = typer.Option(
        None,
        "--mutants",
        help="Mutants JSON file or directory (optional).",
    ),
    path_length: int = typer.Option(3, "--path-length", min=1),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Score candidate predictions with BPR, coverage, mutation score, and oracle accuracy."""
    try:
        reference = load_fsm_json(reference_path)
        oracle = load_oracle_suite(oracle_path)
        candidate = load_candidate_prediction(candidate_path)
    except (OSError, json.JSONDecodeError, ValidationError, BPREngineError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(reference, oracle):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(reference, oracle)}")
        raise typer.Exit(code=1)

    mutants = ()
    if mutants_path is not None:
        try:
            mutants = (
                load_mutants_from_directory(mutants_path)
                if mutants_path.is_dir()
                else load_mutants_from_json(mutants_path)
            )
        except (OSError, json.JSONDecodeError, BPREngineError) as exc:
            console.print(f"[red]ERROR[/red] Failed to load mutants: {exc}")
            raise typer.Exit(code=1) from exc

    try:
        report = score_bpr_benchmark(
            BPRScoreInput(
                reference=reference,
                oracle=oracle,
                candidate=candidate,
                mutants=mutants,
                path_length=path_length,
            )
        )
    except BPREngineError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if out.suffix == ".json":
        write_bpr_score_json(out, report)
        target = out
    else:
        write_bpr_score_json(out / "bpr_score.json", report)
        write_bpr_csv_summaries(out, report)
        target = out / "bpr_summary.csv"

    if quiet:
        console.print(f"[green]OK[/green] BPR={report.bpr:.2%} -> {target}")
    else:
        console.print(f"[green]OK[/green] BPR={report.bpr:.2%}")
        console.print(
            f"Coverage state={report.coverage.state:.2%}, "
            f"transition={report.coverage.transition:.2%}, "
            f"path={report.coverage.path:.2%}"
        )
        console.print(
            f"Mutation score={report.mutation_score:.2%}, "
            f"oracle accuracy={report.oracle_accuracy:.2%}, "
            f"execution cost={report.execution_cost}"
        )
        console.print(f"Output: {target}")

    raise typer.Exit(code=0)


@app.command("plan-mutations")
def plan_mutations_cmd(
    fsm_path: Path,
    strategy: str = typer.Option(
        "coverage_aware",
        "--strategy",
        help="Selection strategy for mutation planning.",
    ),
    budget: int = typer.Option(100, "--budget", min=1),
    out: Path = typer.Option(..., "--out", help="Write mutation plan JSON to this path."),
    seed: int = typer.Option(42, "--seed", help="Seed for random_sample strategy."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Plan selective first-order mutations without generating every possible mutant."""
    if strategy not in SUPPORTED_STRATEGIES:
        console.print(
            f"[red]ERROR[/red] Unknown strategy '{strategy}'. "
            f"Supported: {', '.join(SUPPORTED_STRATEGIES)}"
        )
        raise typer.Exit(code=1)

    try:
        fsm = load_fsm_json(fsm_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load FSM: {exc}")
        raise typer.Exit(code=1) from exc

    reference_errors = validate_fsm(fsm)
    if reference_errors:
        console.print(f"[red]ERROR[/red] Invalid FSM: {reference_errors[0]}")
        raise typer.Exit(code=1)

    try:
        plan = plan_mutations(fsm, strategy=cast(MutationStrategy, strategy), budget=budget, seed=seed)
    except SelectiveMutationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_mutation_plan_json(out, plan)

    if quiet:
        console.print(
            f"[green]OK[/green] planned={len(plan.planned_mutations)}, "
            f"cost={plan.expected_cost:.1f}, diversity={plan.expected_diversity:.2f}"
        )
    else:
        console.print(
            f"[green]OK[/green] Planned {len(plan.planned_mutations)} mutations "
            f"for '{fsm.id}' using {strategy}"
        )
        console.print(
            f"Expected cost={plan.expected_cost:.1f}, "
            f"diversity={plan.expected_diversity:.2f}"
        )
        console.print(f"Plan: {out}")

    raise typer.Exit(code=0)


@app.command("select-oracles")
def select_oracles_cmd(
    fsm_path: Path,
    oracle_path: Path,
    mutants_dir: Path,
    strategy: str = typer.Option(
        "mutual_information",
        "--strategy",
        help="Oracle selection strategy.",
    ),
    budget: int = typer.Option(50, "--budget", min=1),
    out: Path = typer.Option(..., "--out", help="Write selected oracle suite JSON here."),
    report: Path = typer.Option(
        ...,
        "--report",
        help="Write oracle selection report JSON here.",
    ),
    seed: int = typer.Option(42, "--seed", help="Seed for random strategy."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Select a compact oracle suite using information-theoretic criteria."""
    if strategy not in SUPPORTED_ORACLE_SELECTION_STRATEGIES:
        console.print(
            f"[red]ERROR[/red] Unknown strategy '{strategy}'. "
            f"Supported: {', '.join(SUPPORTED_ORACLE_SELECTION_STRATEGIES)}"
        )
        raise typer.Exit(code=1)

    try:
        reference = load_fsm_json(fsm_path)
        suite = load_oracle_suite(oracle_path)
        mutants = load_mutant_pool(mutants_dir)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc
    except OracleSelectionError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(reference, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(reference, suite)}")
        raise typer.Exit(code=1)

    try:
        selection = select_oracle_suite(
            reference,
            suite,
            mutants,
            strategy=cast(OracleSelectionStrategy, strategy),
            budget=budget,
            seed=seed,
        )
    except OracleSelectionError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_selected_oracle_json(out, selection)
    write_oracle_selection_report_json(report, selection)

    if quiet:
        console.print(
            f"[green]OK[/green] selected={len(selection.selected_scenarios)}, "
            f"mutation_retained={selection.mutation_score_retained:.2f}"
        )
    else:
        console.print(
            f"[green]OK[/green] Selected {len(selection.selected_scenarios)} of "
            f"{len(suite.scenarios)} scenarios using {strategy}"
        )
        console.print(
            f"Coverage retained={selection.coverage_retained:.2%}, "
            f"mutation score retained={selection.mutation_score_retained:.2%}"
        )
        console.print(f"Selected oracle: {out}")
        console.print(f"Report: {report}")

    raise typer.Exit(code=0)


@app.command("optimize-test-suite")
def optimize_test_suite_cmd(
    fsm_path: Path,
    oracle_path: Path,
    mutants_path: Path,
    out: Path = typer.Option(..., "--out", help="Write optimization report JSON here."),
    plots_dir: Path | None = typer.Option(
        None,
        "--plots-dir",
        help="Optional directory for Pareto front plots.",
    ),
    algorithm: list[str] | None = typer.Option(
        None,
        "--algorithm",
        help=(
            "Optimizer to run (repeatable). "
            f"Supported: {', '.join(SUPPORTED_OPTIMIZER_ALGORITHMS)}"
        ),
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for search algorithms."),
    iterations: int = typer.Option(200, "--iterations", min=1, help="Iterations for local/random search."),
    population_size: int = typer.Option(
        40,
        "--population-size",
        min=2,
        help="Population size for GA and NSGA-II.",
    ),
    generations: int = typer.Option(
        30,
        "--generations",
        min=1,
        help="Generations for GA and NSGA-II.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Optimize test suites with multi-objective search and Pareto fronts."""
    selected = tuple(algorithm or SUPPORTED_OPTIMIZER_ALGORITHMS)
    unknown = [item for item in selected if item not in SUPPORTED_OPTIMIZER_ALGORITHMS]
    if unknown:
        console.print(
            f"[red]ERROR[/red] Unknown algorithm(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(SUPPORTED_OPTIMIZER_ALGORITHMS)}"
        )
        raise typer.Exit(code=1)

    try:
        reference = load_fsm_json(fsm_path)
        suite = load_oracle_suite(oracle_path)
        mutants = (
            load_mutant_pool(mutants_path)
            if mutants_path.is_dir()
            else load_mutants_from_json(mutants_path)
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc
    except (OracleSelectionError, BPREngineError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(reference, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(reference, suite)}")
        raise typer.Exit(code=1)

    try:
        report = optimize_test_suites(
            reference,
            suite,
            mutants,
            algorithms=cast(tuple[OptimizerAlgorithm, ...], selected),
            seed=seed,
            iterations=iterations,
            population_size=population_size,
            generations=generations,
        )
    except TestSuiteOptimizerError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_optimization_report_json(out, report)
    plot_paths: list[Path] = []
    if plots_dir is not None:
        try:
            plot_paths = visualize_pareto_results(report, plots_dir)
        except TestSuiteOptimizerError as exc:
            console.print(f"[red]ERROR[/red] {exc}")
            raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] pareto={len(report.combined_pareto_front)}, "
            f"algorithms={len(report.algorithms)} -> {out}"
        )
    else:
        console.print(
            f"[green]OK[/green] Optimized '{suite.id}' with {len(selected)} algorithm(s)"
        )
        console.print(
            f"Scenarios={report.scenario_count}, mutants={report.mutant_count}, "
            f"combined Pareto size={len(report.combined_pareto_front)}"
        )
        for name, result in report.algorithms.items():
            console.print(
                f"  {name}: evaluations={result.evaluations}, "
                f"pareto_front={len(result.pareto_front)}"
            )
        console.print(f"Report: {out}")
        if plot_paths:
            console.print(f"Plots: {plots_dir} ({len(plot_paths)} files)")

    raise typer.Exit(code=0)


@app.command("generate-llm-tasks")
def generate_llm_tasks_cmd(
    source_path: Path,
    out: Path = typer.Option(..., "--out", help="Write LLM evaluation tasks JSONL here."),
    task_type: list[str] | None = typer.Option(
        None,
        "--task-type",
        help=(
            "Task type letter to include (repeatable: A-G). "
            f"Supported: {', '.join(SUPPORTED_LLM_TASK_TYPES)}"
        ),
    ),
    seed: int = typer.Option(42, "--seed", help="Seed for synthetic repair tasks."),
    oracle_depth: str = typer.Option(
        "medium",
        "--oracle-depth",
        help="Oracle depth for generated test tasks (shallow, medium, deep, exhaustive_like).",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate LLM evaluation tasks (A-G) for every FSM and write JSONL."""
    selected = tuple(task_type or SUPPORTED_LLM_TASK_TYPES)
    unknown = [item for item in selected if item not in SUPPORTED_LLM_TASK_TYPES]
    if unknown:
        console.print(
            f"[red]ERROR[/red] Unknown task type(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(SUPPORTED_LLM_TASK_TYPES)}"
        )
        raise typer.Exit(code=1)

    if oracle_depth not in {"shallow", "medium", "deep", "exhaustive_like"}:
        console.print(
            "[red]ERROR[/red] Invalid --oracle-depth. "
            "Use shallow, medium, deep, or exhaustive_like."
        )
        raise typer.Exit(code=1)

    try:
        result = write_llm_evaluation_tasks(
            source_path,
            out,
            task_types=cast(tuple[LLMTaskType, ...], selected),
            seed=seed,
            oracle_depth=cast(DepthLevel, oracle_depth),
        )
    except LLMEvaluationTaskError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] tasks={result.task_count}, "
            f"sources={result.source_count} -> {out}"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated {result.task_count} tasks "
            f"from {result.source_count} FSM source(s)"
        )
        for letter in SUPPORTED_LLM_TASK_TYPES:
            count = result.task_counts_by_type.get(letter, 0)
            if count:
                console.print(f"  {letter} ({TASK_TYPE_NAMES.get(letter, letter)}): {count}")
        console.print(f"Tasks: {out}")
        console.print(f"Manifest: {out.with_name(out.stem + '_manifest.json')}")

    raise typer.Exit(code=0)


@app.command("analyze-error-propagation")
def analyze_error_propagation_cmd(
    case_dir: Path,
    out: Path = typer.Option(..., "--out", help="Write propagation report JSON to this path."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Analyze fault activation, propagation, and masking for a benchmark case."""
    try:
        report = analyze_error_propagation(case_dir)
    except ErrorPropagationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_error_propagation_report_json(out, report)

    if quiet:
        console.print(
            f"[green]OK[/green] detected={report.summary.detected_count}, "
            f"masked={report.summary.masked_count}"
        )
    else:
        console.print(
            f"[green]OK[/green] Analyzed {report.summary.scenarios_analyzed} scenarios "
            f"for '{report.case_id}'"
        )
        console.print(
            "Classification: "
            f"easy={report.summary.easy_mutant}, "
            f"hard_to_kill={report.summary.hard_to_kill_mutant}, "
            f"masked={report.summary.masked_mutant}, "
            f"equivalent={report.summary.equivalent_or_near_equivalent}"
        )
        console.print(f"Report: {out}")

    raise typer.Exit(code=0)


@app.command("generate-metamorphic-cases")
def generate_metamorphic_cases_cmd(
    case_dir: Path,
    out: Path = typer.Option(..., "--out", help="Write metamorphic follow-up cases here."),
    relations: str | None = typer.Option(
        None,
        "--relations",
        help="Comma-separated metamorphic relations (default: all supported).",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate metamorphic follow-up benchmark cases from a source case directory."""
    selected: tuple[MetamorphicRelationId, ...] | None = None
    if relations is not None:
        selected_tuple = tuple(item.strip() for item in relations.split(",") if item.strip())
        unknown = [item for item in selected_tuple if item not in SUPPORTED_RELATIONS]
        if unknown:
            console.print(
                f"[red]ERROR[/red] Unknown relation(s): {', '.join(unknown)}. "
                f"Supported: {', '.join(SUPPORTED_RELATIONS)}"
            )
            raise typer.Exit(code=1)
        selected = cast(tuple[MetamorphicRelationId, ...], selected_tuple)

    try:
        report = generate_metamorphic_cases(case_dir, out, relations=selected)
    except MetamorphicError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] generated={len(report.generated)}, "
            f"skipped={len(report.skipped)}"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated {len(report.generated)} metamorphic follow-up cases "
            f"from '{case_dir.name}'"
        )
        for bundle in report.generated:
            console.print(
                f"  - {bundle.relation_id}: {bundle.followup_case_dir} "
                f"({bundle.expected_relation.kind})"
            )
        if report.skipped:
            console.print(f"Skipped {len(report.skipped)} relation(s)")
        console.print(f"Manifest: {out / 'metamorphic_manifest.json'}")

    raise typer.Exit(code=0)


@app.command("check-metamorphic")
def check_metamorphic_cmd(
    source_result: Path,
    followup_result: Path,
    relation: str = typer.Option(..., "--relation", help="Metamorphic relation identifier."),
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Optional path to write the metamorphic check report JSON.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Check whether two score results satisfy a metamorphic relation."""
    if relation not in SUPPORTED_RELATIONS:
        console.print(
            f"[red]ERROR[/red] Unknown relation '{relation}'. "
            f"Supported: {', '.join(SUPPORTED_RELATIONS)}"
        )
        raise typer.Exit(code=1)

    try:
        source_score = load_score_result(source_result)
        followup_score = load_score_result(followup_result)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load score result: {exc}")
        raise typer.Exit(code=1) from exc

    try:
        report = check_metamorphic_relation(
            source_score,
            followup_score,
            relation=cast(MetamorphicRelationId, relation),
        )
    except MetamorphicError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if out is not None:
        write_metamorphic_check_json(out, report)

    if quiet:
        status = "holds" if report.holds else "violated"
        console.print(
            f"[green]OK[/green] relation={relation} status={status} "
            f"source_bpr={report.source_score.bpr:.4f} "
            f"followup_bpr={report.followup_score.bpr:.4f}"
        )
    else:
        if report.holds:
            console.print(
                f"[green]OK[/green] Metamorphic relation '{relation}' holds "
                f"(source_bpr={report.source_score.bpr:.4f}, "
                f"followup_bpr={report.followup_score.bpr:.4f})"
            )
        else:
            console.print(
                f"[red]VIOLATION[/red] Metamorphic relation '{relation}' violated "
                f"(source_bpr={report.source_score.bpr:.4f}, "
                f"followup_bpr={report.followup_score.bpr:.4f})"
            )
            for violation in report.violations[:3]:
                console.print(f"  - {violation.message}")
        if out is not None:
            console.print(f"Report: {out}")

    raise typer.Exit(code=0 if report.holds else 1)


@app.command("verify-metamorphic-relations")
def verify_metamorphic_relations_cmd(
    source_path: Path,
    out: Path = typer.Option(..., "--out", help="Directory for pass/fail verification reports."),
    oracle_path: Path | None = typer.Option(
        None,
        "--oracle",
        help="Oracle suite JSON when *source_path* is an FSM file rather than a case directory.",
    ),
    relations: str | None = typer.Option(
        None,
        "--relations",
        help="Comma-separated relation ids (default: all supported relations).",
    ),
    core_only: bool = typer.Option(
        False,
        "--core-only",
        help="Verify only core MR1-MR4 relations.",
    ),
    catalog: Path | None = typer.Option(
        None,
        "--catalog",
        help="Optional path to write the metamorphic relation catalog JSON.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Verify all metamorphic relations and export pass/fail reports."""
    selected: tuple[MetamorphicRelationId, ...] | None
    if core_only:
        selected = CORE_METAMORPHIC_RELATIONS
    elif relations is not None:
        selected_tuple = tuple(item.strip() for item in relations.split(",") if item.strip())
        unknown = [item for item in selected_tuple if item not in SUPPORTED_RELATIONS]
        if unknown:
            console.print(
                f"[red]ERROR[/red] Unknown relation(s): {', '.join(unknown)}. "
                f"Supported: {', '.join(SUPPORTED_RELATIONS)}"
            )
            raise typer.Exit(code=1)
        selected = cast(tuple[MetamorphicRelationId, ...], selected_tuple)
    else:
        selected = None

    try:
        if source_path.is_dir() and (source_path / "reference_fsm.json").is_file():
            report = verify_metamorphic_case(source_path, relations=selected)
        else:
            if oracle_path is None:
                console.print(
                    "[red]ERROR[/red] --oracle is required when SOURCE is an FSM JSON file"
                )
                raise typer.Exit(code=1)
            reference = load_fsm_json(source_path)
            oracle = load_oracle_suite(oracle_path)
            if not is_oracle_compatible(reference, oracle):
                console.print(
                    f"[red]ERROR[/red] {oracle_incompatibility_message(reference, oracle)}"
                )
                raise typer.Exit(code=1)
            report = verify_metamorphic_relations(
                reference,
                oracle,
                relations=selected,
                source_path=str(source_path),
            )
    except MetamorphicError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    json_path, csv_path = export_metamorphic_verification_report(out, report)
    if catalog is not None:
        write_metamorphic_relation_catalog(catalog)

    if quiet:
        console.print(
            f"[green]OK[/green] status={report.overall_status} "
            f"pass={report.passed} fail={report.failed} skip={report.skipped}"
        )
    else:
        status_color = "green" if report.overall_status == "pass" else "red"
        console.print(
            f"[{status_color}]"
            f"{report.overall_status.upper()}[/{status_color}] "
            f"Verified {len(report.verifications)} relation(s) for '{report.fsm_id}'"
        )
        console.print(
            f"Passed={report.passed}, failed={report.failed}, skipped={report.skipped}"
        )
        for item in report.verifications:
            if item.status == "pass":
                label = f"{item.mr_label} " if item.mr_label else ""
                console.print(
                    f"  [green]PASS[/green] {label}{item.relation_id} "
                    f"(bpr={item.source_bpr:.4f})"
                )
            elif item.status == "fail":
                label = f"{item.mr_label} " if item.mr_label else ""
                console.print(
                    f"  [red]FAIL[/red] {label}{item.relation_id}: {item.rationale}"
                )
            else:
                console.print(f"  [yellow]SKIP[/yellow] {item.relation_id}: {item.skip_reason}")
        console.print(f"Report: {json_path}")
        console.print(f"CSV: {csv_path}")
        if catalog is not None:
            console.print(f"Catalog: {catalog}")

    raise typer.Exit(code=0 if report.overall_status == "pass" else 1)


@app.command("coverage")
def coverage_cmd(
    fsm_path: Path,
    oracle_path: Path,
    out: Path = typer.Option(..., "--out", help="Write coverage report JSON to this path."),
    sequence_depth: int = typer.Option(
        3,
        "--sequence-depth",
        min=1,
        help="Maximum transition-sequence length for sequence coverage.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Compute specification-based coverage criteria for an FSM and oracle suite."""
    try:
        fsm = load_fsm_json(fsm_path)
        suite = load_oracle_suite(oracle_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(fsm, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(fsm, suite)}")
        raise typer.Exit(code=1)

    report = compute_coverage_report(fsm, suite, sequence_depth=sequence_depth)
    write_coverage_json(out, report)

    if quiet:
        console.print(
            f"[green]OK[/green] state={report.state.coverage:.2%}, "
            f"transition={report.transition.coverage:.2%}, "
            f"pairs={report.transition_pair.coverage:.2%}, "
            f"sequences={report.transition_sequence.coverage:.2%}"
        )
    else:
        console.print(f"[green]OK[/green] Wrote coverage report for '{fsm.id}' to {out}")
        console.print(f"State coverage: {report.state.coverage:.2%}")
        console.print(f"Transition coverage: {report.transition.coverage:.2%}")
        console.print(f"Transition-pair coverage: {report.transition_pair.coverage:.2%}")
        console.print(
            "Transition-sequence coverage "
            f"(depth<={sequence_depth}): {report.transition_sequence.coverage:.2%}"
        )
        if report.guard is not None:
            console.print(f"Guard coverage: {report.guard.coverage:.2%}")
        if report.timeout is not None:
            console.print(f"Timeout coverage: {report.timeout.coverage:.2%}")

    raise typer.Exit(code=0)


@app.command("localize-fault")
def localize_fault_cmd(
    fsm_path: Path,
    oracle_path: Path,
    out: Path = typer.Option(..., "--out", help="Write localization report JSON to this path."),
    method: str = typer.Option(
        "ochiai",
        "--method",
        help="Suspiciousness coefficient: ochiai, tarantula, or jaccard.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Rank suspicious FSM elements using spectrum-based fault localization."""
    if method not in {"ochiai", "tarantula", "jaccard"}:
        console.print(f"[red]ERROR[/red] Unknown method '{method}'")
        raise typer.Exit(code=1)

    try:
        fsm = load_fsm_json(fsm_path)
        suite = load_oracle_suite(oracle_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(fsm, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(fsm, suite)}")
        raise typer.Exit(code=1)

    try:
        report = localize_fault(fsm, suite, method=cast(SuspiciousnessMethod, method))
    except ValueError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_localization_json(out, report)

    if quiet:
        top = report.ranked_elements[0] if report.ranked_elements else None
        if top is None:
            console.print("[green]OK[/green] No ranked elements")
        else:
            console.print(
                f"[green]OK[/green] top={top.element_type}:{top.element_id} "
                f"suspiciousness={top.suspiciousness:.4f}"
            )
    else:
        console.print(
            f"[green]OK[/green] Ranked {len(report.ranked_elements)} elements using {method}"
        )
        console.print(f"Report: {out}")
        for element in report.ranked_elements[:5]:
            console.print(
                f"  {element.element_type}:{element.element_id} "
                f"suspiciousness={element.suspiciousness:.4f} "
                f"(failed={element.failed_cover_count}, passed={element.passed_cover_count})"
            )

    raise typer.Exit(code=0)


@app.command("spec-coverage")
def spec_coverage_cmd(
    fsm_path: Path,
    oracle_path: Path,
    out_json: Path | None = typer.Option(None, "--out-json"),
    out_csv: Path | None = typer.Option(None, "--out-csv"),
    max_sequence_length: int = typer.Option(3, "--max-sequence-length", min=1),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Compute specification-based transition, pair, and sequence coverage."""
    try:
        fsm = load_fsm_json(fsm_path)
        suite = load_oracle_suite(oracle_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(fsm, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(fsm, suite)}")
        raise typer.Exit(code=1)

    report = compute_spec_coverage(fsm, suite, max_sequence_length=max_sequence_length)
    if out_json is not None:
        write_json_report(out_json, spec_coverage_to_json_dict(report))
    if out_csv is not None:
        write_csv_report(
            out_csv,
            columns=SPEC_COVERAGE_CSV_COLUMNS,
            rows=spec_coverage_to_csv_rows(report),
        )

    if quiet:
        console.print(
            f"[green]OK[/green] transition={report.transition_coverage:.2%}, "
            f"pairs={report.transition_pair_coverage:.2%}, "
            f"sequences={report.sequence_coverage:.2%}"
        )
    else:
        console.print(f"[bold]Machine type[/bold]: {report.machine_type.value}")
        console.print(f"Transition coverage: {report.transition_coverage:.2%}")
        console.print(f"Transition pair coverage: {report.transition_pair_coverage:.2%}")
        console.print(f"Sequence coverage (len<={max_sequence_length}): {report.sequence_coverage:.2%}")
        if report.efsm_guard_transition_coverage is not None:
            console.print(f"EFSM guard coverage: {report.efsm_guard_transition_coverage:.2%}")
        if report.timed_transition_coverage is not None:
            console.print(f"Timed transition coverage: {report.timed_transition_coverage:.2%}")

    raise typer.Exit(code=0)


@app.command("coupling-report")
def coupling_report_cmd(
    reference_path: Path,
    faulty_path: Path,
    oracle_path: Path,
    metadata_path: Path,
    out_json: Path | None = typer.Option(None, "--out-json"),
    out_csv: Path | None = typer.Option(None, "--out-csv"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Track coupling between mutation complexity and oracle fault detection."""
    try:
        reference = load_fsm_json(reference_path)
        faulty = load_fsm_json(faulty_path)
        suite = load_oracle_suite(oracle_path)
        metadata = BugMetadata.model_validate(json.loads(metadata_path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load input: {exc}")
        raise typer.Exit(code=1) from exc

    if not is_oracle_compatible(faulty, suite):
        console.print(f"[red]ERROR[/red] {oracle_incompatibility_message(faulty, suite)}")
        raise typer.Exit(code=1)

    report = track_coupling_effect(reference, faulty, suite, metadata)
    if out_json is not None:
        write_json_report(out_json, coupling_report_to_json_dict(report))
    if out_csv is not None:
        write_csv_report(
            out_csv,
            columns=COUPLING_CSV_COLUMNS,
            rows=coupling_report_to_csv_rows(report),
        )

    if quiet:
        console.print(
            f"[green]OK[/green] complexity={report.mutation_complexity}, "
            f"fault_detectable={report.fault_detectable}"
        )
    else:
        console.print(f"Operator: {report.mutation_operator} ({report.mutation_complexity})")
        console.print(f"Reference BPR: {report.reference_bpr:.2%}")
        console.print(f"Faulty BPR: {report.faulty_bpr:.2%}")
        console.print(f"Complex fault coverage: {report.complex_fault_coverage:.2%}")
        console.print(f"Simple proxy coverage: {report.simple_fault_proxy_coverage:.2%}")

    raise typer.Exit(code=0)


@app.command("flatten-hierarchical")
def flatten_hierarchical_cmd(
    hierarchical_path: Path,
    out: Path = typer.Option(..., "--out"),
) -> None:
    """Flatten a hierarchical FSM JSON document to a flat FSM."""
    try:
        hierarchical = HierarchicalFSM.model_validate(
            json.loads(hierarchical_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load hierarchical FSM: {exc}")
        raise typer.Exit(code=1) from exc

    flat = flatten_hierarchical_fsm(hierarchical)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(flat.model_dump_json(indent=2) + "\n", encoding="utf-8")
    console.print(f"[green]OK[/green] Flattened '{hierarchical.id}' to {out}")
    raise typer.Exit(code=0)


@app.command("generate-hierarchical-oracle")
def generate_hierarchical_oracle_cmd(
    hierarchical_path: Path,
    out_json: Path = typer.Option(..., "--out-json"),
    out_csv: Path | None = typer.Option(None, "--out-csv"),
    depth: str = typer.Option("medium", "--depth"),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Generate multi-level oracles for a hierarchical FSM."""
    if depth not in {"shallow", "medium", "deep", "exhaustive_like"}:
        console.print(f"[red]ERROR[/red] Unknown depth '{depth}'")
        raise typer.Exit(code=1)

    try:
        hierarchical = HierarchicalFSM.model_validate(
            json.loads(hierarchical_path.read_text(encoding="utf-8"))
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load hierarchical FSM: {exc}")
        raise typer.Exit(code=1) from exc

    suite = generate_hierarchical_oracle(hierarchical, depth=cast(DepthLevel, depth))
    write_json_report(out_json, suite.model_dump())
    if out_csv is not None:
        write_csv_report(
            out_csv,
            columns=HIERARCHICAL_CSV_COLUMNS,
            rows=hierarchical_oracle_to_csv_rows(suite),
        )

    if quiet:
        console.print(f"[green]OK[/green] {len(suite.scenarios)} hierarchical scenarios")
    else:
        console.print(
            f"[green]OK[/green] Generated hierarchical oracle '{suite.id}' "
            f"with {len(suite.scenarios)} scenarios"
        )
        console.print(f"Oracle JSON: {out_json}")
        if out_csv is not None:
            console.print(f"Oracle CSV: {out_csv}")

    raise typer.Exit(code=0)


@app.command("generate-constrained-inputs")
def generate_constrained_inputs_cmd(
    fsm_path: Path,
    out_json: Path = typer.Option(..., "--out-json"),
    out_csv: Path | None = typer.Option(None, "--out-csv"),
    target_coverage: float = typer.Option(1.0, "--target-coverage"),
    max_path_length: int = typer.Option(8, "--max-path-length", min=1),
    quiet: bool = typer.Option(False, "--quiet"),
) -> None:
    """Generate constraint-based input sequences for FSM path coverage."""
    try:
        fsm = load_fsm_json(fsm_path)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load FSM: {exc}")
        raise typer.Exit(code=1) from exc

    plan = generate_constrained_inputs(
        fsm,
        target_transition_coverage=target_coverage,
        max_path_length=max_path_length,
    )
    write_json_report(out_json, constrained_plan_to_json_dict(plan))
    if out_csv is not None:
        write_csv_report(
            out_csv,
            columns=CONSTRAINED_INPUT_CSV_COLUMNS,
            rows=constrained_plan_to_csv_rows(plan),
        )

    if quiet:
        console.print(
            f"[green]OK[/green] coverage={plan.achieved_transition_coverage:.2%}, "
            f"sequences={len(plan.sequences)}"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated {len(plan.sequences)} constrained sequences "
            f"({plan.achieved_transition_coverage:.2%} transition coverage)"
        )
        console.print(f"Plan JSON: {out_json}")
        if out_csv is not None:
            console.print(f"Plan CSV: {out_csv}")

    raise typer.Exit(code=0)


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
    if result.skipped_input_files:
        console.print(
            f"Skipped {len(result.skipped_input_files)} non-FSM input file(s): "
            + ", ".join(path.name for path, _ in result.skipped_input_files)
        )
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

    if not is_oracle_compatible(fsm, oracle_suite):
        console.print(
            f"[red]ERROR[/red] {oracle_incompatibility_message(fsm, oracle_suite)}"
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

    if not is_oracle_compatible(fsm, oracle_suite):
        console.print(
            f"[red]ERROR[/red] {oracle_incompatibility_message(fsm, oracle_suite)}"
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

    from fsmrepairbench.repair_trajectory import export_repair_trace, repair_trace_path_for_result

    trace_path = repair_trace_path_for_result(out, single_repair=True)
    export_repair_trace(result, trace_path)
    console.print(
        f"[green]OK[/green] LLM repair finished with BPR {result.score:.2%}. "
        f"Wrote result to {out}"
    )
    console.print(f"Repair trace: {trace_path}")
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


@app.command("run-experiment-pipeline")
def run_experiment_pipeline_cmd(
    output_root: Path = typer.Option(
        Path("experiment_output"),
        "--output-root",
        help="Root directory for results/, figures/, tables/, and reports/.",
    ),
    seed: int = typer.Option(42, "--seed", help="Random seed for generation and search."),
    fsm_count: int = typer.Option(6, "--fsm-count", min=1, help="Number of synthetic FSMs."),
    num_states: int = typer.Option(8, "--num-states", min=2, help="States per synthetic FSM."),
    num_events: int = typer.Option(4, "--num-events", min=1, help="Events per synthetic FSM."),
    mutants_per_fsm: int = typer.Option(5, "--mutants-per-fsm", min=1, help="First-order mutants per FSM."),
    optimizer: list[str] | None = typer.Option(
        None,
        "--optimizer",
        help="Optimizer algorithms to run (repeatable).",
    ),
    optimizer_iterations: int = typer.Option(40, "--optimizer-iterations", min=1),
    optimizer_population_size: int = typer.Option(12, "--optimizer-population-size", min=2),
    optimizer_generations: int = typer.Option(8, "--optimizer-generations", min=1),
    alpha: float = typer.Option(0.05, "--alpha", help="Significance level for statistical tests."),
    skip_plots: bool = typer.Option(False, "--skip-plots", help="Skip matplotlib figure generation."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Run the full seven-step FSMRepairBench experiment pipeline."""
    from fsmrepairbench.test_suite_optimizer import SUPPORTED_OPTIMIZER_ALGORITHMS

    selected_optimizers = tuple(optimizer or ("random_search", "nsga2"))
    unknown = [item for item in selected_optimizers if item not in SUPPORTED_OPTIMIZER_ALGORITHMS]
    if unknown:
        console.print(
            f"[red]ERROR[/red] Unknown optimizer(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(SUPPORTED_OPTIMIZER_ALGORITHMS)}"
        )
        raise typer.Exit(code=1)

    config = ExperimentPipelineConfig(
        output_root=output_root,
        seed=seed,
        fsm_count=fsm_count,
        num_states=num_states,
        num_events=num_events,
        mutants_per_fsm=mutants_per_fsm,
        optimizers=cast(tuple[str, ...], selected_optimizers),
        optimizer_iterations=optimizer_iterations,
        optimizer_population_size=optimizer_population_size,
        optimizer_generations=optimizer_generations,
        generate_plots=not skip_plots,
        alpha=alpha,
    )
    try:
        result = run_experiment_pipeline(config)
    except ExperimentPipelineError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] instances={result.instance_count} "
            f"tables={result.tables_dir.name} figures={result.figures_dir.name}"
        )
    else:
        console.print(
            f"[green]OK[/green] Experiment pipeline finished with "
            f"{result.instance_count} FSM instances"
        )
        console.print(f"Results: {result.results_dir}")
        console.print(f"Tables: {result.tables_dir}")
        console.print(f"Figures: {result.figures_dir}")
        console.print(f"Reports: {result.reports_dir}")
        console.print(f"Metrics CSV: {result.metrics_csv}")
        console.print(f"Statistical tests CSV: {result.statistics_csv}")
    raise typer.Exit(code=0)


@app.command("run-smoke-test")
def run_smoke_test_cmd(
    input_dir: Path = typer.Option(
        Path("data/smoke_test_input"),
        "--input-dir",
        help="Directory with fsms/ and oracles/ subdirectories.",
    ),
    output_dir: Path = typer.Option(
        Path("results/smoke_test"),
        "--output-dir",
        help="Consolidated smoke-test output directory.",
    ),
    seed: int = typer.Option(42, "--seed", help="Fixed random seed for reproducibility."),
    fsm_count: int = typer.Option(10, "--fsm-count", min=1, max=20),
    examples_dir: Path = typer.Option(
        Path("examples"),
        "--examples-dir",
        help="Directory containing example FSM JSON files.",
    ),
    from_examples: bool = typer.Option(
        False,
        "--from-examples",
        help="Build smoke-test input from examples/ FSMs and oracles.",
    ),
    prepare_input: bool = typer.Option(
        False,
        "--prepare-input",
        help="Generate a deterministic input dataset before running the pipeline.",
    ),
    use_cli: bool = typer.Option(
        True,
        "--use-cli/--no-use-cli",
        help="Invoke existing CLI commands for scoring, coverage, and localization.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress per-FSM progress logging."),
) -> None:
    """Run the end-to-end smoke-test validation pipeline."""
    if from_examples and fsm_count > 10:
        console.print("[red]ERROR[/red] Examples smoke test supports at most 10 FSMs")
        raise typer.Exit(code=1)
    if not from_examples and fsm_count < 10:
        console.print("[red]ERROR[/red] Template smoke test requires at least 10 FSMs")
        raise typer.Exit(code=1)

    if prepare_input or not input_dir.is_dir():
        try:
            if from_examples:
                prepare_smoke_test_input_from_examples(
                    examples_dir,
                    input_dir,
                    seed=seed,
                    max_fsm_count=fsm_count,
                )
            else:
                prepare_smoke_test_input(input_dir, seed=seed, fsm_count=fsm_count)
        except SmokeTestPipelineError as exc:
            console.print(f"[red]ERROR[/red] {exc}")
            raise typer.Exit(code=1) from exc

    config = SmokeTestPipelineConfig(
        input_dir=input_dir,
        output_dir=output_dir,
        seed=seed,
        fsm_count=fsm_count,
        prepare_input=False,
        use_cli=use_cli,
        input_source="examples" if from_examples else "template",
        examples_dir=examples_dir,
    )
    try:
        if quiet:
            import io
            import contextlib

            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                result = run_smoke_test_pipeline(config)
        else:
            result = run_smoke_test_pipeline(config)
        validation = validate_smoke_test_outputs(result.output_dir)
    except SmokeTestPipelineError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Smoke test finished: "
        f"{result.fsm_count} FSMs, {result.mutant_count} mutants, "
        f"mean BPR={result.mean_bpr:.2%}, "
        f"mean state coverage={result.mean_state_coverage:.2%}, "
        f"mean transition coverage={result.mean_transition_coverage:.2%}, "
        f"detected faults={result.detected_fault_count}"
    )
    console.print(f"Output: {result.output_dir}")
    console.print(f"Summary: {result.summary_path}")
    if not validation.passed:
        console.print("[yellow]WARN[/yellow] Post-run validation thresholds were not all met")
        if validation.unscored_mutants:
            console.print(f"  Unscored mutants: {len(validation.unscored_mutants)}")
        if validation.low_coverage_fsms:
            console.print(f"  Low coverage FSMs: {', '.join(validation.low_coverage_fsms)}")
        console.print(
            f"  Localization top-5 rate: {validation.localization_top5_rate:.2%} "
            f"(required >= 80%)"
        )
    raise typer.Exit(code=0 if validation.passed else 1)


@app.command("prepare-smoke-test-input")
def prepare_smoke_test_input_cmd(
    output_dir: Path = typer.Option(
        Path("data/smoke_test_input"),
        "--output-dir",
        help="Directory for generated FSM and oracle inputs.",
    ),
    seed: int = typer.Option(42, "--seed"),
    fsm_count: int = typer.Option(10, "--fsm-count", min=1, max=20),
    examples_dir: Path = typer.Option(
        Path("examples"),
        "--examples-dir",
        help="Directory containing example FSM JSON files.",
    ),
    from_examples: bool = typer.Option(
        False,
        "--from-examples",
        help="Build input from examples/ instead of the parking-gate template.",
    ),
) -> None:
    """Generate a deterministic smoke-test input dataset with high oracle coverage."""
    try:
        if from_examples:
            if fsm_count > 10:
                console.print("[red]ERROR[/red] Examples smoke test supports at most 10 FSMs")
                raise typer.Exit(code=1)
            path = prepare_smoke_test_input_from_examples(
                examples_dir,
                output_dir,
                seed=seed,
                max_fsm_count=fsm_count,
            )
        else:
            if fsm_count < 10:
                console.print("[red]ERROR[/red] Template smoke test requires at least 10 FSMs")
                raise typer.Exit(code=1)
            path = prepare_smoke_test_input(output_dir, seed=seed, fsm_count=fsm_count)
    except SmokeTestPipelineError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]OK[/green] Prepared {fsm_count} FSM/oracle pairs in {path}")
    raise typer.Exit(code=0)


@app.command("run-tools")
def run_tools_cmd(
    dataset_dir: Path,
    tools_dir: Path,
    out: Path = typer.Option(..., "--out", help="Write tool run results to this directory."),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
    workers: int = typer.Option(1, "--workers", min=1),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Run multiple repair tools reproducibly on an FSMRepairBench dataset."""
    try:
        load_tool_configs(tools_dir)
    except ToolRunnerError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    try:
        result = run_tools(
            dataset_dir,
            tools_dir,
            out,
            resume=resume,
            workers=workers,
        )
    except ToolRunnerError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] runs={len(result.rows)} summary={result.summary_path.name}"
        )
    else:
        console.print(
            f"[green]OK[/green] Completed {len(result.rows)} case/tool runs "
            f"from '{dataset_dir}'"
        )
        console.print(f"Summary: {result.summary_path}")
        console.print(f"Leaderboard: {result.leaderboard_path}")
        console.print(f"Manifest: {result.output_dir / 'tool_run_manifest.json'}")

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


@app.command("mutate-higher-order")
def mutate_higher_order_cmd(
    ref_fsm_path: Path,
    operators: str = typer.Option(
        ...,
        "--operators",
        help="Comma-separated mutation operators to apply in order.",
    ),
    seed: int = typer.Option(..., "--seed", help="Deterministic seed."),
    out: Path = typer.Option(..., "--out", help="Output path for faulty FSM JSON."),
    meta: Path = typer.Option(..., "--meta", help="Output path for bug metadata JSON."),
) -> None:
    """Generate a first- or higher-order faulty FSM by chaining mutation operators."""
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
        faulty_fsm, bug_metadata = mutate_higher_order(reference, operators, seed)
    except HigherOrderMutationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    out.write_text(faulty_fsm.model_dump_json(indent=2) + "\n", encoding="utf-8")
    meta.write_text(bug_metadata.model_dump_json(indent=2) + "\n", encoding="utf-8")

    order_label = "higher-order" if bug_metadata.is_higher_order else "first-order"
    console.print(
        f"[green]OK[/green] Wrote {order_label} faulty FSM '{faulty_fsm.id}' "
        f"(mutation_order={bug_metadata.mutation_order}) to {out}"
    )
    console.print(f"Metadata: {meta}")
    raise typer.Exit(code=0)


@app.command("generate-literature-mutants")
def generate_literature_mutants_cmd(
    fsm_path: Path,
    out: Path = typer.Option(..., "--out", help="Write mutant report JSON to this path."),
    seed: int = typer.Option(42, "--seed", help="Deterministic generation seed."),
    include_fsm: bool = typer.Option(
        True,
        "--include-fsm/--no-include-fsm",
        help="Embed full mutant FSM JSON in the report.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate literature-inspired first-, second-, and higher-order FSM mutants."""
    try:
        report = generate_literature_mutants_for_path(
            fsm_path,
            seed=seed,
            include_fsm=include_fsm,
        )
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] Failed to load FSM: {exc}")
        raise typer.Exit(code=1) from exc
    except LiteratureMutationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_mutant_report_json(out, report, include_fsm=include_fsm)

    if quiet:
        console.print(
            f"[green]OK[/green] {report.statistics.total_mutants} mutants -> {out}"
        )
    else:
        stats = report.statistics
        console.print(
            f"[green]OK[/green] Generated {stats.total_mutants} mutants for "
            f"'{report.parent_fsm_id}'"
        )
        console.print(
            f"  first-order={stats.first_order_count}, "
            f"second-order={stats.second_order_count}, "
            f"higher-order={stats.higher_order_count}"
        )
        console.print(f"Report: {out}")

    raise typer.Exit(code=0)


@app.command("generate-literature-mutants-dir")
def generate_literature_mutants_dir_cmd(
    input_dir: Path,
    out: Path = typer.Option(..., "--out", help="Output directory for mutant reports."),
    seed: int = typer.Option(42, "--seed", help="Deterministic generation seed."),
    include_fsm: bool = typer.Option(
        True,
        "--include-fsm/--no-include-fsm",
        help="Embed full mutant FSM JSON in each report.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate literature mutants for every fsm_*.json file in a dataset directory."""
    try:
        summary = generate_literature_mutants_for_directory(
            input_dir,
            out,
            seed=seed,
            include_fsm=include_fsm,
        )
    except LiteratureMutationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] {summary.total_mutants} mutants for "
            f"{summary.fsm_count} FSMs -> {out}"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated {summary.total_mutants} mutants "
            f"for {summary.fsm_count} FSMs"
        )
        console.print(
            f"  first-order={summary.first_order_count}, "
            f"second-order={summary.second_order_count}, "
            f"higher-order={summary.higher_order_count}"
        )
        console.print(f"Statistics: {out / 'statistics.json'}")

    raise typer.Exit(code=0)


@app.command("coupling-analysis")
def coupling_analysis_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(..., "--out", help="Write coupling analysis JSON to this path."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Estimate whether oracles detecting first-order faults also detect higher-order faults."""
    try:
        report = analyze_dataset_coupling(dataset_dir)
    except HigherOrderMutationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    write_dataset_coupling_report(out, report)

    if report.discovery.skipped:
        console.print("[yellow]WARN[/yellow] Skipped incomplete case directories:")
        for inspection in report.discovery.skipped:
            console.print(f"  - {inspection.skip_reason}")

    if quiet:
        console.print(
            f"[green]OK[/green] coupling_effect={report.coupling_effect_estimate:.2%}, "
            f"cases={report.case_count}"
        )
    else:
        console.print(
            f"[green]OK[/green] Analyzed {report.case_count} cases "
            f"({report.first_order_case_count} first-order, "
            f"{report.higher_order_case_count} higher-order) "
            f"from {report.discovery.total_directories} directories"
        )
        console.print(
            f"First-order detection rate: {report.first_order_detection_rate:.2%}"
        )
        console.print(
            f"Higher-order detection rate: {report.higher_order_detection_rate:.2%}"
        )
        console.print(f"Coupling effect estimate: {report.coupling_effect_estimate:.2%}")
        console.print(f"Report: {out}")

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


@app.command("generate-adversarial-fsm")
def generate_adversarial_fsm_cmd(
    out: Path = typer.Option(..., "--out", help="Output path for adversarial FSM JSON."),
    metadata: Path = typer.Option(
        ...,
        "--metadata",
        help="Output path for difficulty metadata JSON.",
    ),
    pattern: str = typer.Option(
        "highly_symmetric",
        "--pattern",
        help=f"Adversarial pattern. Supported: {', '.join(SUPPORTED_ADVERSARIAL_PATTERNS)}",
    ),
    seed: int = typer.Option(42, "--seed", help="Deterministic generation seed."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate one adversarial FSM designed to challenge LLM reasoning."""
    if pattern not in SUPPORTED_ADVERSARIAL_PATTERNS:
        console.print(
            f"[red]ERROR[/red] Unknown pattern '{pattern}'. "
            f"Supported: {', '.join(SUPPORTED_ADVERSARIAL_PATTERNS)}"
        )
        raise typer.Exit(code=1)

    try:
        fsm, difficulty = generate_adversarial_fsm(
            cast(AdversarialPattern, pattern),
            seed=seed,
        )
        record = build_metadata_record(
            fsm,
            difficulty,
            pattern=cast(AdversarialPattern, pattern),
            seed=seed,
            filename=out.name,
            metadata_filename=metadata.name,
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        metadata.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(fsm.model_dump_json(indent=2, exclude_none=True) + "\n", encoding="utf-8")
        metadata.write_text(record.model_dump_json(indent=2) + "\n", encoding="utf-8")
    except AdversarialFSMError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(
            f"[green]OK[/green] rank={difficulty.rank}/10 pattern={pattern} -> {out}"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated adversarial FSM '{fsm.id}' "
            f"(pattern={pattern}, rank={difficulty.rank}/10, label={difficulty.label})"
        )
        console.print(f"FSM: {out}")
        console.print(f"Metadata: {metadata}")

    raise typer.Exit(code=0)


@app.command("generate-adversarial-fsms")
def generate_adversarial_fsms_cmd(
    out: Path = typer.Option(Path("adversarial_dataset"), "--out", help="Output dataset directory."),
    count: int | None = typer.Option(
        None,
        "--count",
        min=1,
        help="Number of adversarial FSMs (defaults to one per selected pattern).",
    ),
    seed: int = typer.Option(42, "--seed", help="Global random seed."),
    pattern: list[str] | None = typer.Option(
        None,
        "--pattern",
        help="Adversarial pattern to include (repeatable). Defaults to all patterns.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate a dataset of adversarial FSMs with difficulty metadata."""
    selected = tuple(pattern or SUPPORTED_ADVERSARIAL_PATTERNS)
    unknown = [item for item in selected if item not in SUPPORTED_ADVERSARIAL_PATTERNS]
    if unknown:
        console.print(
            f"[red]ERROR[/red] Unknown pattern(s): {', '.join(unknown)}. "
            f"Supported: {', '.join(SUPPORTED_ADVERSARIAL_PATTERNS)}"
        )
        raise typer.Exit(code=1)

    try:
        result = generate_adversarial_dataset(
            output_dir=out,
            count=count,
            seed=seed,
            patterns=cast(tuple[AdversarialPattern, ...], selected),
        )
    except AdversarialFSMError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    ranks = [record.difficulty.rank for record in result.records]
    if quiet:
        console.print(
            f"[green]OK[/green] fsms={len(result.records)} "
            f"rank={min(ranks)}-{max(ranks)} -> {out}"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated {len(result.records)} adversarial FSMs under {out}"
        )
        console.print(
            f"Difficulty ranks: min={min(ranks)}, max={max(ranks)}, "
            f"mean={sum(ranks) / len(ranks):.1f}"
        )
        console.print(f"Metadata CSV: {result.metadata_csv_path}")
        console.print(f"Manifest: {out / 'dataset_manifest.json'}")

    raise typer.Exit(code=0)


@app.command("tag-fsms")
def tag_fsms_cmd(
    source_path: Path,
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Output metadata.csv path (defaults to SOURCE/metadata.csv).",
    ),
    seed: int = typer.Option(42, "--seed", help="Seed for mutation-resistance sampling."),
    skip_mutation_score: bool = typer.Option(
        False,
        "--skip-mutation-score",
        help="Skip mutation-score analysis for faster tagging.",
    ),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Analyze every FSM and assign structural tags into metadata.csv."""
    try:
        result = tag_fsm_directory(
            source_path,
            output_path=out,
            compute_mutation_score=not skip_mutation_score,
            seed=seed,
        )
    except FSMTaggingError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    tag_counts: dict[str, int] = dict.fromkeys(SUPPORTED_FSM_TAGS, 0)
    for record in result.records:
        for tag, enabled in record.tag_flags.items():
            if enabled:
                tag_counts[tag] += 1

    if quiet:
        console.print(
            f"[green]OK[/green] tagged={len(result.records)} -> {result.metadata_csv_path}"
        )
    else:
        console.print(
            f"[green]OK[/green] Tagged {len(result.records)} FSM(s) from '{source_path}'"
        )
        if result.skipped_files:
            console.print(f"Skipped {len(result.skipped_files)} invalid or unreadable file(s)")
        for tag in SUPPORTED_FSM_TAGS:
            if tag_counts[tag]:
                console.print(f"  {tag}: {tag_counts[tag]}")
        console.print(f"Metadata CSV: {result.metadata_csv_path}")
        manifest = result.metadata_csv_path.with_name("tagging_manifest.json")
        console.print(f"Manifest: {manifest}")

    raise typer.Exit(code=0)


@app.command("generate-fsm-dataset")
def generate_fsm_dataset_cmd(
    out: Path = typer.Option(Path("dataset"), "--out", help="Output dataset directory."),
    count: int = typer.Option(10_000, "--count", min=1, help="Number of FSMs to generate."),
    seed: int = typer.Option(42, "--seed", help="Global random seed for reproducible generation."),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate a reproducible FSM benchmark dataset (DFA, NFA, Mealy, Moore, EFSM, timed)."""
    try:
        records = generate_fsm_benchmark_dataset(
            FSMBenchmarkGenerationConfig(count=count, seed=seed, output_dir=out)
        )
    except FSMBenchmarkDatasetError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    distribution = dataset_type_distribution(records)
    if quiet:
        console.print(
            f"[green]OK[/green] Generated {len(records)} FSMs in {out} "
            f"(seed={seed}, types={len(SUPPORTED_FSM_TYPES)})"
        )
    else:
        console.print(
            f"[green]OK[/green] Generated {len(records)} FSMs under {out} "
            f"with seed={seed}"
        )
        console.print(f"Metadata: {out / 'metadata.csv'}")
        table = Table(title="Machine type distribution")
        table.add_column("Type")
        table.add_column("Count", justify="right")
        for fsm_type in SUPPORTED_FSM_TYPES:
            table.add_row(fsm_type, str(distribution[fsm_type]))
        console.print(table)

    raise typer.Exit(code=0)


@app.command("generate-coverage-oracles")
def generate_coverage_oracles_cmd(
    fsm_path: Path,
    out: Path = typer.Option(..., "--out", help="Output JSON file or directory."),
    seed: int = typer.Option(42, "--seed", help="Deterministic generation seed."),
    max_depth: int = typer.Option(25, "--max-depth", min=1),
    path_length: int = typer.Option(3, "--path-length", min=1),
    mutant_count: int = typer.Option(10, "--mutant-count", min=1),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate minimized transition/state/path/boundary/mutation-killing oracle suites."""
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
        export = generate_all_coverage_oracle_suites(
            fsm,
            seed=seed,
            max_depth=max_depth,
            path_length=path_length,
            mutant_count=mutant_count,
        )
    except CoverageOracleGeneratorError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if out.suffix == ".json":
        export_coverage_oracles_json(out, export)
        target = out
    else:
        export_coverage_oracles_directory(out, export)
        target = out / "manifest.json"

    if quiet:
        total_sequences = sum(suite.sequence_count for suite in export.suites.values())
        console.print(
            f"[green]OK[/green] {total_sequences} sequences across "
            f"{len(SUPPORTED_COVERAGE_SUITE_TYPES)} suites -> {target}"
        )
    else:
        table = Table(title=f"Coverage oracle suites for '{fsm.id}'")
        table.add_column("Suite")
        table.add_column("Sequences", justify="right")
        table.add_column("Coverage", justify="right")
        for suite_type in SUPPORTED_COVERAGE_SUITE_TYPES:
            suite = export.suites[suite_type]
            table.add_row(
                suite_type,
                str(suite.sequence_count),
                f"{suite.coverage_ratio:.2%}",
            )
        console.print(table)
        console.print(f"Export: {target}")

    raise typer.Exit(code=0)


@app.command("generate-coverage-oracles-dir")
def generate_coverage_oracles_dir_cmd(
    input_dir: Path,
    out: Path = typer.Option(..., "--out", help="Output directory for oracle suites."),
    seed: int = typer.Option(42, "--seed", help="Deterministic generation seed."),
    max_depth: int = typer.Option(25, "--max-depth", min=1),
    path_length: int = typer.Option(3, "--path-length", min=1),
    quiet: bool = typer.Option(False, "--quiet", help="Print a short summary only."),
) -> None:
    """Generate coverage oracle suites for every FSM JSON file in a dataset directory."""
    try:
        manifests = generate_coverage_oracles_for_directory(
            input_dir,
            out,
            seed=seed,
            max_depth=max_depth,
            path_length=path_length,
        )
    except CoverageOracleGeneratorError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    if quiet:
        console.print(f"[green]OK[/green] {len(manifests)} FSM oracle bundles -> {out}")
    else:
        console.print(
            f"[green]OK[/green] Generated coverage oracle suites for {len(manifests)} FSMs"
        )
        console.print(f"Output root: {out}")

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


@app.command("generate-requirements")
def generate_requirements_cmd(
    fsm_path: Path,
    out: Path = typer.Option(..., "--out", help="Output path for requirements.txt."),
    style: RequirementStyle = typer.Option(
        "concise",
        "--style",
        help="Requirement wording style: concise, verbose, ambiguous, or industrial.",
    ),
) -> None:
    """Generate natural-language requirements from a reference FSM."""
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
        result = generate_requirements(fsm, style=style)
        export_requirements_txt(result, out)
    except RequirementGenerationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Generated {len(result.items)} requirements for FSM "
        f"'{result.fsm_id}' ({result.style}) at {out}"
    )
    raise typer.Exit(code=0)


@app.command("inject-ambiguity")
def inject_ambiguity_cmd(
    fsm_path: Path,
    out: Path = typer.Option(..., "--out", help="Output path for ambiguous requirements.txt."),
    metadata_out: Path | None = typer.Option(
        None,
        "--metadata-out",
        help="Output path for ambiguity metadata JSON.",
    ),
    clear_style: RequirementStyle = typer.Option(
        "concise",
        "--clear-style",
        help="Style used to generate the clear baseline requirements.",
    ),
) -> None:
    """Inject controlled ambiguity into clear natural-language requirements."""
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
        result = inject_requirement_ambiguity(fsm, clear_style=clear_style)
        export_injected_requirements_txt(result, out)
        metadata_path = metadata_out or out.with_name("ambiguity_metadata.json")
        export_ambiguity_metadata(result, metadata_path)
    except (AmbiguityInjectionError, RequirementGenerationError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    classes = sorted({injection.ambiguity_class for injection in result.injections})
    console.print(
        f"[green]OK[/green] Injected ambiguity into {len(result.injections)} requirements "
        f"for FSM '{result.fsm_id}' at {out}"
    )
    console.print(f"Ambiguity metadata: {metadata_path}")
    console.print(f"Classes used: {', '.join(classes)}")
    raise typer.Exit(code=0)


@app.command("build-dataset")
def build_dataset_cmd(
    size: int = typer.Option(..., "--size", min=1),
    seed: int = typer.Option(42, "--seed"),
    output_dir: Path = typer.Option(DEFAULT_OUTPUT_DIR, "--output"),
    workers: int | None = typer.Option(None, "--workers", min=1),
    resume: bool = typer.Option(True, "--resume/--no-resume"),
    benchmark_version: BenchmarkVersion = typer.Option(
        BenchmarkVersion.V1_0,
        "--benchmark-version",
        help="Benchmark schema version for the generated dataset.",
    ),
) -> None:
    """Build a large-scale benchmark dataset automatically."""
    try:
        result = build_dataset(
            size=size,
            seed=seed,
            output_dir=output_dir,
            workers=workers,
            resume=resume,
            benchmark_version=benchmark_version,
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


@app.command("calibrate-difficulty")
def calibrate_difficulty_cmd(
    dataset_dir: Path,
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Directory for difficulty_calibration.csv and report JSON.",
    ),
    bucket_method: str = typer.Option(
        "quantile",
        "--bucket-method",
        help="Bucket assignment strategy: quantile (dataset-calibrated) or fixed.",
    ),
) -> None:
    """Calibrate benchmark difficulty and write difficulty_calibration.csv."""
    if bucket_method not in {"quantile", "fixed"}:
        console.print(f"[red]ERROR[/red] Unsupported bucket method: {bucket_method}")
        raise typer.Exit(code=1)

    try:
        result = calibrate_benchmark_difficulty(
            dataset_dir,
            bucket_method=bucket_method,  # type: ignore[arg-type]
            output_dir=output_dir,
        )
    except (DifficultyCalibrationError, CoverageOptimizerError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    report = result.report
    distribution = report["bucket_distribution"]
    console.print(
        f"[green]OK[/green] Calibrated difficulty for {report['case_count']} cases"
    )
    console.print(f"Calibration CSV: {result.calibration_path}")
    console.print(f"Report: {result.report_path}")
    console.print(
        "Buckets: "
        + ", ".join(f"{bucket}={count}" for bucket, count in sorted(distribution.items()))
    )
    raise typer.Exit(code=0)


@app.command("benchmark-report")
def benchmark_report_cmd(dataset_dir: Path) -> None:
    """Generate diversity analytics for a benchmark dataset."""
    from fsmrepairbench.analytics import AnalyticsError, generate_benchmark_report

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


@app.command("analyze-benchmark")
def analyze_benchmark_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(
        Path("results/analysis"),
        "--out",
        help="Directory for analysis CSVs, figures, and Markdown report.",
    ),
    max_cases: int | None = typer.Option(
        None,
        "--max-cases",
        min=1,
        help="Analyze at most this many cases from the dataset (in index order).",
    ),
) -> None:
    """Generate publication-oriented analysis for an existing benchmark dataset."""
    from fsmrepairbench.analytics import AnalyticsError, generate_analysis_report

    try:
        result = generate_analysis_report(dataset_dir, output_dir=out, max_cases=max_cases)
    except AnalyticsError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Analyzed {result.case_count} cases from {dataset_dir}"
    )
    console.print(f"Summary: {result.summary_path}")
    console.print(f"Distributions: {result.distributions_path}")
    console.print(f"Correlations: {result.correlations_path}")
    console.print(f"Figures: {result.figures_dir}")
    console.print(f"Report: {result.markdown_path}")
    raise typer.Exit(code=0)


@app.command("run-oracle-depth-ablation")
def run_oracle_depth_ablation_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(
        Path("results/oracle_depth_ablation"),
        "--out",
        help="Directory for ablation CSVs, figures, tables, and report.",
    ),
    cohort_size: int = typer.Option(
        200,
        "--cohort-size",
        min=1,
        help="Number of stratified cases from the analysis cohort.",
    ),
    cohort_file: Path | None = typer.Option(
        None,
        "--cohort-file",
        help="Use an existing pinned cohort manifest (one case ID per line).",
    ),
    cohort_manifest: Path | None = typer.Option(
        None,
        "--cohort-manifest",
        help="Source cohort for selection (default: analysis_cohort_1k.txt).",
    ),
    no_write_cohort: bool = typer.Option(
        False,
        "--no-write-cohort",
        help="Do not write oracle_depth_ablation_200.txt under the dataset.",
    ),
) -> None:
    """Run oracle depth ablation (shallow/medium/deep) on a pinned case sample."""
    from fsmrepairbench.oracle_depth_ablation import (
        OracleDepthAblationError,
        run_oracle_depth_ablation,
    )

    try:
        result = run_oracle_depth_ablation(
            dataset_dir,
            output_dir=out,
            cohort_size=cohort_size,
            cohort_manifest=cohort_manifest,
            cohort_path=cohort_file,
            write_cohort=not no_write_cohort,
        )
    except OracleDepthAblationError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Oracle depth ablation on {result.case_count} cases "
        f"from {dataset_dir}"
    )
    console.print(f"Cohort: {result.cohort_path}")
    console.print(f"Depth summary: {result.depth_summary_path}")
    console.print(f"Summary: {result.summary_path}")
    console.print(f"Distributions: {result.distributions_path}")
    console.print(f"Per-case: {result.per_case_path}")
    console.print(f"Figures: {result.figures_dir}")
    console.print(f"Tables: {result.tables_dir}")
    console.print(f"Report: {result.report_path}")
    raise typer.Exit(code=0)


@app.command("run-localization-campaign")
def run_localization_campaign_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(
        Path("results/rq3_localization_1k"),
        "--out",
        help="Directory for localization CSVs, figures, tables, and report.",
    ),
    cohort_file: Path | None = typer.Option(
        None,
        "--cohort-file",
        help="Pinned cohort manifest (one case ID per line).",
    ),
    method: str = typer.Option(
        "ochiai",
        "--method",
        help="Suspiciousness coefficient (ochiai, tarantula, jaccard).",
    ),
) -> None:
    """Run transition-level Ochiai localization on a pinned cohort."""
    from fsmrepairbench.fault_localization import SuspiciousnessMethod
    from fsmrepairbench.localization_campaign import (
        LocalizationCampaignError,
        run_localization_campaign,
    )

    try:
        result = run_localization_campaign(
            dataset_dir,
            output_dir=out,
            cohort_path=cohort_file,
            method=cast(SuspiciousnessMethod, method),
        )
    except LocalizationCampaignError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Localization campaign on {result.case_count} cases "
        f"({result.localized_cases} localized) from {dataset_dir}"
    )
    console.print(f"Cohort: {result.cohort_path}")
    console.print(f"Summary: {result.summary_path}")
    console.print(f"Metrics: {result.localization_metrics_path}")
    console.print(f"Per-case: {result.per_case_path}")
    console.print(f"Figures: {result.figures_dir}")
    console.print(f"Tables: {result.tables_dir}")
    console.print(f"Report: {result.report_path}")
    raise typer.Exit(code=0)


@app.command("generate-taxonomy-coverage")
def generate_taxonomy_coverage_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(
        Path("results/taxonomy_coverage"),
        "--out",
        help="Directory for taxonomy coverage CSVs, figures, tables, and report.",
    ),
    cohort_file: Path | None = typer.Option(
        None,
        "--cohort-file",
        help="Optional cohort manifest (one case ID per line).",
    ),
) -> None:
    """Report empirical taxonomy coverage for an existing benchmark dataset."""
    from fsmrepairbench.taxonomy_coverage import (
        TaxonomyCoverageError,
        generate_taxonomy_coverage_report,
    )

    try:
        result = generate_taxonomy_coverage_report(
            dataset_dir,
            output_dir=out,
            cohort_path=cohort_file,
        )
    except TaxonomyCoverageError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Taxonomy coverage report for {result.case_count} cases "
        f"from {dataset_dir}"
    )
    console.print(f"Report: {result.report_path}")
    console.print(f"Summary: {result.summary_path}")
    console.print(f"Dimension summary: {result.dimension_summary_path}")
    console.print(f"FSM families: {result.fsm_family_path}")
    console.print(f"Mutation operators: {result.mutation_operator_path}")
    console.print(f"Complexity tiers: {result.complexity_tier_path}")
    console.print(f"Figures: {result.figures_dir}")
    console.print(f"Tables: {result.tables_dir}")
    raise typer.Exit(code=0)


@app.command("run-benchmark-campaign")
def run_benchmark_campaign_cmd(
    plan_path: Path,
    dataset_dir: Path,
    out: Path = typer.Option(
        Path("results/v0_2_campaign"),
        "--out",
        help="Campaign report output directory.",
    ),
    skip_build: bool = typer.Option(
        False,
        "--skip-build",
        help="Reuse an existing dataset in DATASET_DIR and only run analyses.",
    ),
) -> None:
    """Build and analyze the FSMRepairBench v0.2 benchmark campaign."""
    from fsmrepairbench.benchmark_campaign import BenchmarkCampaignError, run_benchmark_campaign

    try:
        result = run_benchmark_campaign(
            plan_path,
            dataset_dir,
            output_dir=out,
            skip_build=skip_build,
        )
    except BenchmarkCampaignError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Completed v0.2 campaign for {result.case_count} cases"
    )
    console.print(f"Dataset: {result.dataset_dir}")
    console.print(f"Mutation summary: {result.mutation_summary_path}")
    console.print(f"Coverage report: {result.coverage_report_path}")
    console.print(f"Coupling report: {result.coupling_report_path}")
    console.print(f"Campaign summary: {result.summary_json_path}")
    console.print(f"Benchmark report: {result.benchmark_report_path}")
    raise typer.Exit(code=0)


@app.command("export-hf")
def export_hf_cmd(dataset_dir: Path) -> None:
    """Export a benchmark dataset to HuggingFace JSONL splits."""
    from fsmrepairbench.hf_export import HuggingFaceExportError, export_huggingface_dataset

    try:
        result = export_huggingface_dataset(dataset_dir)
    except HuggingFaceExportError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Exported HuggingFace dataset to {result.output_dir} "
        f"(train={result.split_counts['train']}, "
        f"validation={result.split_counts['validation']}, "
        f"test={result.split_counts['test']})"
    )
    console.print(f"Dataset card: {result.dataset_card_path}")
    raise typer.Exit(code=0)


@app.command("leaderboard")
def leaderboard_cmd(results_dir: Path) -> None:
    """Generate leaderboard CSV and Markdown from experiment results."""
    try:
        result = generate_leaderboard(results_dir)
    except LeaderboardError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Generated leaderboard for {len(result.entries)} models in "
        f"{result.results_dir}"
    )
    console.print(f"CSV: {result.csv_path}")
    console.print(f"Markdown: {result.markdown_path}")

    table = Table(title="Leaderboard")
    table.add_column("Rank")
    table.add_column("Model")
    table.add_column("Complete Repair")
    table.add_column("Repair Success")
    table.add_column("Avg BPR Δ")
    for entry in result.entries:
        table.add_row(
            str(entry.rank),
            entry.model,
            f"{entry.complete_repair_rate:.2%}",
            f"{entry.repair_success_rate:.2%}",
            f"{entry.avg_bpr_improvement:.4f}",
        )
    console.print(table)
    raise typer.Exit(code=0)


@app.command("benchmark-version")
def benchmark_version_cmd(dataset_dir: Path) -> None:
    """Detect and display the benchmark version for a dataset."""
    try:
        version = detect_benchmark_version(dataset_dir)
    except VersioningError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]OK[/green] Benchmark version: {version.value}")
    manifest_path = dataset_dir / RELEASE_MANIFEST_FILENAME
    if manifest_path.is_file():
        console.print(f"Release manifest: {manifest_path}")
    raise typer.Exit(code=0)


@evolution_app.command("compare")
def benchmark_evolution_compare_cmd(
    source_dir: Path,
    target_dir: Path,
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Output path for the evolution comparison report JSON.",
    ),
) -> None:
    """Compare two benchmark releases and report added, removed, and modified cases."""
    try:
        report = compare_benchmark_evolution(source_dir, target_dir)
        report_path = out or source_dir / EVOLUTION_REPORT_FILENAME
        write_evolution_report(report_path, report)
    except (BenchmarkEvolutionError, VersioningError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Compared {report.source_release.value} -> "
        f"{report.target_release.value} releases"
    )
    console.print(f"Added cases: {len(report.added_cases)}")
    console.print(f"Removed cases: {len(report.removed_cases)}")
    console.print(f"Modified cases: {len(report.modified_cases)}")
    console.print(f"Evolution report: {report_path}")
    raise typer.Exit(code=0)


@evolution_app.command("trace")
def benchmark_evolution_trace_cmd(dataset_dir: Path) -> None:
    """Show traceability metadata for a benchmark release."""
    try:
        trace = build_release_trace(dataset_dir)
    except (BenchmarkEvolutionError, VersioningError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]OK[/green] Evolution release: {trace.evolution_release.value}")
    console.print(f"Benchmark version: {trace.benchmark_version.value}")
    console.print(f"Dataset ID: {trace.dataset_id}")
    console.print(f"Cases: {len(trace.case_ids)}")
    if trace.predecessor_release is not None:
        console.print(f"Predecessor release: {trace.predecessor_release.value}")
    if trace.successor_release is not None:
        console.print(f"Successor release: {trace.successor_release.value}")
    raise typer.Exit(code=0)


@app.command("migrate-benchmark")
def migrate_benchmark_cmd(
    source_dir: Path,
    target_version: BenchmarkVersion = typer.Option(..., "--target-version"),
    output_dir: Path = typer.Option(..., "--output"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Analyze migration without writing files."),
) -> None:
    """Migrate a benchmark dataset to a newer schema version."""
    try:
        if dry_run:
            report = analyze_migration(source_dir, target_version)
            report_path = source_dir / f"dry_run_{MIGRATION_REPORT_FILENAME}"
            write_migration_report(report_path, report)
            console.print(
                f"[green]OK[/green] Dry-run migration {report.source_version.value} -> "
                f"{report.target_version.value} for {report.case_count} cases"
            )
            console.print(
                "Modified cases: "
                f"{len(report.modified_cases)} "
                f"(added={len(report.added_cases)}, removed={len(report.removed_cases)})"
            )
            console.print(f"Report: {report_path}")
            raise typer.Exit(code=0)

        report = migrate_benchmark(source_dir, output_dir, target_version)
    except VersioningError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Migrated {report.case_count} cases from "
        f"{report.source_version.value} to {report.target_version.value}"
    )
    console.print(
        "Evolution changes: "
        f"added={len(report.added_cases)}, "
        f"removed={len(report.removed_cases)}, "
        f"modified={len(report.modified_cases)}"
    )
    console.print(f"Output: {output_dir}")
    console.print(f"Migration report: {output_dir / MIGRATION_REPORT_FILENAME}")
    console.print(f"Release manifest: {output_dir / RELEASE_MANIFEST_FILENAME}")
    raise typer.Exit(code=0)


@app.command("build-stratified-dataset")
def build_stratified_dataset_cmd(plan_path: Path, output_dir: Path) -> None:
    """Build a taxonomy-stratified benchmark dataset from a plan file."""
    try:
        result = build_stratified_dataset(plan_path, output_dir)
    except (StratifiedBuilderError, ValidationError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Built stratified dataset '{plan_path.name}' with "
        f"{len(result.cases)} cases in {result.output_dir}"
    )
    console.print(f"Case index: {result.case_index_path}")
    console.print(f"Feature matrix: {result.feature_matrix_path}")
    console.print(f"Plan copy: {result.dataset_plan_path}")
    raise typer.Exit(code=0)


@app.command("filter-cases")
def filter_cases_cmd(
    dataset_dir: Path,
    out: Path = typer.Option(..., "--out", help="CSV output path for the filtered subset."),
    determinism: str | None = typer.Option(None, "--determinism"),
    machine_type: str | None = typer.Option(None, "--machine-type"),
    arity: str | None = typer.Option(None, "--arity", help="Filter by arity_class."),
    bug_type: str | None = typer.Option(None, "--bug-type"),
    completeness: str | None = typer.Option(None, "--completeness"),
    size_class: str | None = typer.Option(None, "--size-class"),
    guard_complexity: str | None = typer.Option(None, "--guard-complexity"),
    oracle_depth: str | None = typer.Option(None, "--oracle-depth"),
) -> None:
    """Filter stratified dataset cases by taxonomy features."""
    raw_filters = {
        "determinism": determinism,
        "machine_type": machine_type,
        "arity_class": arity,
        "bug_type": bug_type,
        "completeness": completeness,
        "size_class": size_class,
        "guard_complexity": guard_complexity,
        "oracle_depth": oracle_depth,
    }
    filters = {
        normalize_filter_key(key): value
        for key, value in raw_filters.items()
        if value is not None
    }
    if not filters:
        console.print("[red]ERROR[/red] At least one feature filter must be provided")
        raise typer.Exit(code=1)

    try:
        cases = filter_cases(dataset_dir, filters)
        write_filter_csv(out, cases)
    except CaseFilterError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]OK[/green] Wrote {len(cases)} matching cases to {out}")
    raise typer.Exit(code=0)


@app.command("subset-overlap")
def subset_overlap_cmd(
    dataset_dir: Path,
    a: str = typer.Option(..., "--a", help="Comma-separated predicate, e.g. determinism=deterministic"),
    b: str = typer.Option(..., "--b", help="Comma-separated predicate for subset B."),
    out: Path = typer.Option(..., "--out", help="JSON output path."),
) -> None:
    """Compute overlap statistics between two feature-defined subsets."""
    try:
        overlap = compute_subset_overlap(
            dataset_dir,
            parse_predicate_string(a),
            parse_predicate_string(b),
        )
        write_overlap_json(out, overlap)
    except CaseFilterError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Overlap A={overlap.count_a}, B={overlap.count_b}, "
        f"intersection={overlap.count_intersection}, jaccard={overlap.jaccard:.4f}"
    )
    console.print(f"Report: {out}")
    raise typer.Exit(code=0)


@app.command("coverage-optimizer")
def coverage_optimizer_cmd(
    dataset_dir: Path,
    out: Path | None = typer.Option(
        None,
        "--out",
        help="Optional output path for coverage_report.json.",
    ),
    suggest_count: int = typer.Option(
        200,
        "--suggest-count",
        min=1,
        help="Target number of additional cases to recommend.",
    ),
) -> None:
    """Analyze benchmark diversity from feature_matrix.csv and suggest gap-filling regions."""
    try:
        result = generate_coverage_report(
            dataset_dir,
            output_path=out,
            suggestion_count=suggest_count,
        )
    except CoverageOptimizerError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    report = result.report
    unique = report["unique_feature_combinations"]
    suggestions = report["suggestions"]
    console.print(
        f"[green]OK[/green] Coverage report for {report['case_count']} cases written to "
        f"{result.report_path}"
    )
    console.print(
        f"Unique combinations: {unique['unique_count']} "
        f"(duplicates={unique['duplicate_combinations']})"
    )
    console.print(f"Missing core combinations: {report['missing_combinations']['missing_count']}")
    console.print(f"Suggestion: {suggestions['message']}")
    console.print(f"Recommended regions: {len(suggestions['regions'])}")
    raise typer.Exit(code=0)


@app.command("detect-gaps")
def detect_gaps_cmd(
    dataset_dir: Path,
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Directory for missing_cells.csv and gap_fill_plan.yaml.",
    ),
    expected_count: int | None = typer.Option(
        None,
        "--expected-count",
        min=1,
        help="Target cases per feature-space cell.",
    ),
    max_plan_cells: int = typer.Option(
        200,
        "--max-plan-cells",
        min=1,
        help="Maximum generation cells in the automatic gap-fill plan.",
    ),
) -> None:
    """Detect underrepresented benchmark regions and write gap-fill artifacts."""
    try:
        result = detect_benchmark_gaps(
            dataset_dir,
            expected_count=expected_count,
            max_plan_cells=max_plan_cells,
            output_dir=output_dir,
        )
    except (GapDetectionError, CoverageOptimizerError) as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    report = result.report
    console.print(
        f"[green]OK[/green] Detected {report['total_gaps']} low-density cells "
        f"({report['missing_cells']} missing, {report['underrepresented_cells']} underrepresented)"
    )
    console.print(f"Missing cells CSV: {result.missing_cells_path}")
    console.print(f"Gap-fill plan: {result.gap_fill_plan_path}")
    console.print(f"Report: {result.report_path}")
    console.print(
        f"Suggested additional cases: {report['suggested_additional_cases']} "
        f"(plan covers {report['generation_plan_cases']} cases in "
        f"{report['generation_plan_cells']} cells)"
    )
    raise typer.Exit(code=0)


@app.command("validate-dataset")
def validate_dataset_cmd(
    dataset_dir: Path,
    output_path: Path | None = typer.Option(
        None,
        "--output",
        help="Path for quality_report.json (defaults to DATASET_DIR/quality_report.json).",
    ),
) -> None:
    """Validate benchmark dataset quality and write quality_report.json."""
    try:
        result = validate_dataset(dataset_dir, output_path=output_path)
    except DatasetQualityError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    report = result.report
    status = report["overall_status"]
    summary = report["summary"]
    status_color = {"pass": "green", "warn": "yellow", "fail": "red"}.get(status, "white")
    console.print(
        f"[{status_color}]Quality report[/{status_color}] "
        f"({status.upper()}) for {report['case_count']} cases"
    )
    console.print(f"Report: {result.report_path}")
    console.print(
        "Findings: "
        f"errors={summary['errors']}, "
        f"warnings={summary['warnings']}, "
        f"info={summary['info']}"
    )
    failed_checks = [
        name
        for name, check in report["checks"].items()
        if check["status"] != "pass"
    ]
    if failed_checks:
        console.print(f"Checks with findings: {', '.join(sorted(failed_checks))}")
    raise typer.Exit(code=0 if result.passed else 1)


@app.command("analyze-novelty")
def analyze_novelty_cmd(
    dataset_dir: Path,
    output_path: Path | None = typer.Option(
        None,
        "--output",
        help="Path for novelty_report.json (defaults to DATASET_DIR/novelty_report.json).",
    ),
    cluster_threshold: float = typer.Option(
        0.85,
        "--cluster-threshold",
        min=0.0,
        max=1.0,
        help="Combined similarity threshold for high-similarity clusters.",
    ),
) -> None:
    """Analyze benchmark novelty and detect synthetic dataset collapse."""
    try:
        result = analyze_novelty(
            dataset_dir,
            output_path=output_path,
            cluster_threshold=cluster_threshold,
        )
    except NoveltyAnalysisError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    summary = result.report["novelty_summary"]
    risk = summary["collapse_risk"]
    risk_color = {"low": "green", "medium": "yellow", "high": "red"}.get(risk, "white")
    console.print(
        f"[{risk_color}]Novelty report[/{risk_color}] "
        f"(collapse risk: {risk.upper()}) for {result.report['case_count']} cases"
    )
    console.print(f"Report: {result.report_path}")
    console.print(
        "Summary: "
        f"novelty_score={summary['novelty_score']:.4f}, "
        f"clusters={summary['high_similarity_cluster_count']}, "
        f"largest_cluster={summary['largest_cluster_size']}"
    )
    if result.report["high_similarity_clusters"]:
        largest = result.report["high_similarity_clusters"][0]
        console.print(
            "Largest cluster: "
            f"{largest['size']} cases "
            f"(mean similarity={largest['mean_combined_similarity']:.4f})"
        )
    raise typer.Exit(code=0 if not result.collapsed else 1)


@app.command("mine-failure-patterns")
def mine_failure_patterns_cmd(
    input_dir: Path,
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Directory for failure_patterns.csv (defaults to input_dir).",
    ),
) -> None:
    """Mine recurring repair failure patterns from repair_trace.json files."""
    try:
        result = mine_failure_patterns(input_dir, output_dir=output_dir)
    except FailurePatternMiningError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    report = result.report
    console.print(
        f"[green]OK[/green] Discovered {report['occurrence_count']} failure pattern "
        f"occurrences across {report['trace_count']} repair traces"
    )
    console.print(f"Failure patterns CSV: {result.patterns_path}")
    console.print(f"Report: {result.report_path}")
    if report["top_patterns"]:
        top = ", ".join(
            f"{item['pattern']}={item['occurrences']}" for item in report["top_patterns"][:5]
        )
        console.print(f"Top patterns: {top}")
    raise typer.Exit(code=0)


@app.command("literature-index")
def literature_index_cmd(
    taxonomy_path: Path | None = typer.Argument(
        None,
        help="Optional path to literature_taxonomy.yaml (defaults to bundled data).",
    ),
    entry_id: str | None = typer.Option(None, "--id", help="Show one literature entry."),
    category: str | None = typer.Option(None, "--category", help="Filter by category."),
    generation_support: GenerationSupport | None = typer.Option(
        None,
        "--generation-support",
        help="Filter by FSMRepairBench generation support level.",
    ),
    as_json: bool = typer.Option(False, "--json", help="Print machine-readable JSON."),
    out: Path | None = typer.Option(None, "--out", help="Write JSON index to this path."),
) -> None:
    """Index the FSM literature knowledge base."""
    try:
        if entry_id is not None:
            entry = get_literature_entry(entry_id, taxonomy_path)
            if as_json or out is not None:
                payload = entry.model_dump(mode="json")
                if out is not None:
                    out.parent.mkdir(parents=True, exist_ok=True)
                    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                    console.print(f"[green]OK[/green] Wrote literature entry to {out}")
                else:
                    console.print(json.dumps(payload, indent=2))
                raise typer.Exit(code=0)

            console.print(f"[bold]{entry.name}[/bold] ({entry.id})")
            console.print(f"Category: {entry.category}")
            console.print(f"Generation support: {entry.generation_support.value}")
            console.print(entry.description.strip())
            console.print(f"Repair relevance: {entry.repair_relevance.strip()}")
            raise typer.Exit(code=0)

        result = build_literature_index(taxonomy_path)
        entries = list(result.entries)
        if category is not None or generation_support is not None:
            entries = filter_literature_entries(
                category=category,
                generation_support=generation_support,
                path=result.taxonomy_path,
            )

        if as_json or out is not None:
            if entries != list(result.entries):
                payload = {
                    "version": result.taxonomy.version,
                    "description": result.taxonomy.description,
                    "taxonomy_path": str(result.taxonomy_path),
                    "entry_count": len(entries),
                    "entries": [entry.model_dump(mode="json") for entry in entries],
                }
            else:
                payload = literature_index_to_dict(result)

            if out is not None:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
                console.print(f"[green]OK[/green] Wrote literature index to {out}")
            else:
                console.print(json.dumps(payload, indent=2))
            raise typer.Exit(code=0)

        table = Table(title="FSM Literature Taxonomy")
        table.add_column("ID")
        table.add_column("Name")
        table.add_column("Category")
        table.add_column("Generation")
        table.add_column("Features")
        for entry in entries:
            table.add_row(
                entry.id,
                entry.name,
                entry.category,
                entry.generation_support.value,
                ", ".join(entry.features[:3]),
            )
        console.print(table)
        console.print(f"Source: {result.taxonomy_path}")
        console.print(f"Entries: {len(entries)}")
    except LiteratureError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    raise typer.Exit(code=0)


@app.command("release-manifest")
def release_manifest_cmd(dataset_dir: Path) -> None:
    """Generate or refresh the release manifest for a benchmark dataset."""
    try:
        manifest_path = write_release_manifest(dataset_dir)
    except VersioningError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]OK[/green] Wrote release manifest to {manifest_path}")
    raise typer.Exit(code=0)


@app.command("reproduce")
def reproduce_cmd(
    artifact_path: Path,
    resume: bool = typer.Option(True, "--resume/--no-resume"),
) -> None:
    """Reproduce a published experiment from an artifact manifest."""
    try:
        bundle = load_artifact_bundle(artifact_path)
    except ArtifactError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"Reproducing artifact [bold]{bundle.manifest.artifact_id}[/bold]: "
        f"{bundle.manifest.title}"
    )
    console.print(
        f"Dataset {bundle.dataset.benchmark_version.value} "
        f"(size={bundle.dataset.size}, seed={bundle.dataset.seed})"
    )
    console.print(f"Models: {', '.join(str(model) for model in bundle.models.models)}")

    try:
        result = reproduce_artifact(artifact_path, resume=resume)
    except ArtifactError as exc:
        console.print(f"[red]ERROR[/red] {exc}")
        raise typer.Exit(code=1) from exc

    console.print(
        f"[green]OK[/green] Reproduced {result.artifact_id} with "
        f"{len(result.experiment.rows)} case/model results"
    )
    console.print(f"Dataset: {result.dataset_dir}")
    console.print(f"Results: {result.experiment.output_dir}")
    console.print(f"Report: {result.report_path}")
    if result.freeze is not None:
        console.print(f"Frozen release: {result.freeze.release_dir}")
    if result.leaderboard is not None:
        console.print(f"Leaderboard: {result.leaderboard.markdown_path}")
    raise typer.Exit(code=0)


def main() -> None:
    """Entry point for the console script."""
    app()


if __name__ == "__main__":
    main()
