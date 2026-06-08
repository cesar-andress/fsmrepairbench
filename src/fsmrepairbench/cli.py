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
from fsmrepairbench.higher_order_mutation import (
    HigherOrderMutationError,
    analyze_dataset_coupling,
    mutate_higher_order,
    write_dataset_coupling_report,
)
from fsmrepairbench.hf_export import HuggingFaceExportError, export_huggingface_dataset
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
from fsmrepairbench.models import BugMetadata
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
        top = report.rankings[0] if report.rankings else None
        if top is None:
            console.print("[green]OK[/green] No ranked elements")
        else:
            console.print(
                f"[green]OK[/green] top={top.element_type}:{top.element_id} "
                f"score={top.score:.4f}"
            )
    else:
        console.print(
            f"[green]OK[/green] Ranked {len(report.rankings)} elements using {method} "
            f"({report.total_failed_scenarios} failed scenarios)"
        )
        console.print(f"Report: {out}")
        for element in report.rankings[:5]:
            console.print(
                f"  {element.element_type}:{element.element_id} "
                f"score={element.score:.4f} "
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

    if quiet:
        console.print(
            f"[green]OK[/green] coupling_effect={report.coupling_effect_estimate:.2%}, "
            f"cases={report.case_count}"
        )
    else:
        console.print(
            f"[green]OK[/green] Analyzed {report.case_count} cases "
            f"({report.first_order_case_count} first-order, "
            f"{report.higher_order_case_count} higher-order)"
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


@app.command("export-hf")
def export_hf_cmd(dataset_dir: Path) -> None:
    """Export a benchmark dataset to HuggingFace JSONL splits."""
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
