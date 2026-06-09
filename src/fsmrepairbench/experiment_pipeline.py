"""End-to-end experiment pipeline for FSMRepairBench."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from fsmrepairbench.bpr_engine import BPRScoreInput, CandidatePrediction, score_bpr_benchmark
from fsmrepairbench.experiment_statistics import (
    StatisticalTestResult,
    compare_independent_groups,
    compare_paired_groups,
)
from fsmrepairbench.generators.synthetic_factory import (
    SyntheticGenerationParams,
    export_fsm_json,
    generate_synthetic_fsm,
)
from fsmrepairbench.literature_mutation import (
    generate_literature_mutants,
    write_mutant_report_json,
)
from fsmrepairbench.models import FSM, OracleSuite
from fsmrepairbench.mutators import mutate
from fsmrepairbench.oracle_generator import generate_oracle_suite
from fsmrepairbench.oracle_selection import MutantRecord
from fsmrepairbench.patch import apply_patch
from fsmrepairbench.repair_engines.baselines import BASELINE_ENGINE_NAMES, propose_baseline_patch
from fsmrepairbench.sota_export import write_csv_report, write_json_report
from fsmrepairbench.test_suite_optimizer import (
    SUPPORTED_OPTIMIZER_ALGORITHMS,
    OptimizerAlgorithm,
    optimize_test_suites,
    visualize_pareto_results,
    write_optimization_report_json,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

RESULTS_DIR = "results"
FIGURES_DIR = "figures"
TABLES_DIR = "tables"
REPORTS_DIR = "reports"

METRICS_CSV_COLUMNS: tuple[str, ...] = (
    "fsm_id",
    "model",
    "bpr",
    "mutation_score",
    "transition_coverage",
    "oracle_scenarios",
    "optimized_scenarios",
    "pareto_front_size",
    "execution_cost",
)

STATISTICS_CSV_COLUMNS: tuple[str, ...] = (
    "test",
    "group_a",
    "group_b",
    "metric",
    "statistic",
    "p_value",
    "effect_size",
    "effect_label",
    "n_a",
    "n_b",
    "significant",
    "notes",
)


class ExperimentPipelineError(RuntimeError):
    """Raised when the experiment pipeline fails."""


class PipelineInstanceMetrics(BaseModel):
    """Metrics collected for one FSM and one evaluated model."""

    fsm_id: str
    model: str
    bpr: float = Field(ge=0.0, le=1.0)
    mutation_score: float = Field(ge=0.0, le=1.0)
    transition_coverage: float = Field(ge=0.0, le=1.0)
    oracle_scenarios: int = Field(ge=0)
    optimized_scenarios: int = Field(ge=0)
    pareto_front_size: int = Field(ge=0)
    execution_cost: int = Field(ge=0)


class ExperimentPipelineConfig(BaseModel):
    """Configuration for a reproducible experiment pipeline run."""

    output_root: Path = Path("experiment_output")
    seed: int = 42
    fsm_count: int = Field(default=6, ge=1)
    num_states: int = Field(default=8, ge=2)
    num_events: int = Field(default=4, ge=1)
    mutants_per_fsm: int = Field(default=5, ge=1)
    optimizers: tuple[OptimizerAlgorithm, ...] = ("random_search", "nsga2")
    models: tuple[str, ...] = ("reference", *BASELINE_ENGINE_NAMES)
    optimizer_iterations: int = Field(default=40, ge=1)
    optimizer_population_size: int = Field(default=12, ge=2)
    optimizer_generations: int = Field(default=8, ge=1)
    generate_plots: bool = True
    alpha: float = Field(default=0.05, gt=0.0, lt=1.0)


@dataclass(frozen=True)
class ExperimentPipelineResult:
    """Paths produced by a full pipeline run."""

    output_root: Path
    results_dir: Path
    figures_dir: Path
    tables_dir: Path
    reports_dir: Path
    metrics_csv: Path
    model_summary_csv: Path
    statistics_csv: Path
    model_summary_tex: Path
    statistics_tex: Path
    pipeline_report_json: Path
    pipeline_report_md: Path
    instance_count: int


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        msg = (
            "Plotting dependencies are missing. "
            f"Install them with: pip install -e '.[analytics]' ({exc})"
        )
        raise ExperimentPipelineError(msg) from exc
    return plt


def _write_latex_table(
    path: Path,
    *,
    columns: tuple[str, ...],
    rows: list[list[str]],
    caption: str,
    label: str,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    alignment = "l" + "r" * (len(columns) - 1)
    header = " & ".join(_latex_escape(column) for column in columns) + r" \\"
    body_lines = [" & ".join(_latex_escape(cell) for cell in row) + r" \\" for row in rows]
    content = "\n".join(
        [
            r"\begin{table}[t]",
            r"\centering",
            rf"\caption{{{_latex_escape(caption)}}}",
            rf"\label{{{label}}}",
            rf"\begin{{tabular}}{{{alignment}}}",
            r"\toprule",
            header,
            r"\midrule",
            *body_lines,
            r"\bottomrule",
            r"\end{tabular}",
            r"\end{table}",
        ]
    )
    path.write_text(content + "\n", encoding="utf-8")


def _latex_escape(value: str) -> str:
    return (
        value.replace("\\", r"\textbackslash{}")
        .replace("_", r"\_")
        .replace("%", r"\%")
        .replace("&", r"\&")
    )


def _step_generate_fsms(config: ExperimentPipelineConfig, results_dir: Path) -> list[Path]:
    fsm_dir = results_dir / "fsms"
    fsm_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for index in range(config.fsm_count):
        params = SyntheticGenerationParams(
            num_states=config.num_states,
            num_events=config.num_events,
            branching_factor=2,
            seed=config.seed + index * 17,
        )
        fsm = generate_synthetic_fsm(params)
        path = fsm_dir / f"fsm_{index + 1:04d}.json"
        export_fsm_json(fsm, path)
        paths.append(path)
    return paths


def _step_generate_mutants(fsm_paths: Sequence[Path], config: ExperimentPipelineConfig, results_dir: Path) -> dict[str, Path]:
    mutant_roots: dict[str, Path] = {}
    mutants_dir = results_dir / "mutants"
    mutants_dir.mkdir(parents=True, exist_ok=True)
    for index, fsm_path in enumerate(fsm_paths):
        reference = load_fsm_json(fsm_path)
        out_dir = mutants_dir / reference.id
        report = generate_literature_mutants(
            reference,
            seed=config.seed + index * 101,
            first_order_count=config.mutants_per_fsm,
            second_order_count=0,
            higher_order_count=0,
            include_fsm=True,
        )
        write_mutant_report_json(out_dir / "mutants.json", report, include_fsm=True)
        mutant_roots[reference.id] = out_dir
    return mutant_roots


def _load_mutants(mutants_dir: Path) -> tuple[MutantRecord, ...]:
    payload = json.loads((mutants_dir / "mutants.json").read_text(encoding="utf-8"))
    records: list[MutantRecord] = []
    for item in payload.get("mutants", []):
        fsm_payload = item.get("fsm")
        if fsm_payload is None:
            continue
        records.append(
            MutantRecord(
                mutant_id=str(item["mutant_id"]),
                fsm=FSM.model_validate(fsm_payload),
            )
        )
    return tuple(records)


def _step_generate_oracles(fsm_paths: Sequence[Path], results_dir: Path) -> dict[str, Path]:
    oracle_paths: dict[str, Path] = {}
    oracle_dir = results_dir / "oracles"
    oracle_dir.mkdir(parents=True, exist_ok=True)
    for fsm_path in fsm_paths:
        reference = load_fsm_json(fsm_path)
        generated = generate_oracle_suite(reference, depth="medium")
        path = oracle_dir / f"{reference.id}_oracle.json"
        path.write_text(generated.suite.model_dump_json(indent=2) + "\n", encoding="utf-8")
        oracle_paths[reference.id] = path
    return oracle_paths


def _step_optimize_suites(
    fsm_paths: Sequence[Path],
    oracle_paths: dict[str, Path],
    mutant_roots: dict[str, Path],
    config: ExperimentPipelineConfig,
    results_dir: Path,
) -> dict[str, Path]:
    optimization_paths: dict[str, Path] = {}
    optimize_dir = results_dir / "optimized_suites"
    optimize_dir.mkdir(parents=True, exist_ok=True)
    for index, fsm_path in enumerate(fsm_paths):
        reference = load_fsm_json(fsm_path)
        oracle = load_oracle_suite(oracle_paths[reference.id])
        mutants = _load_mutants(mutant_roots[reference.id])
        report = optimize_test_suites(
            reference,
            oracle,
            mutants,
            algorithms=config.optimizers,
            seed=config.seed + index * 1000,
            iterations=config.optimizer_iterations,
            population_size=config.optimizer_population_size,
            generations=config.optimizer_generations,
        )
        path = optimize_dir / f"{reference.id}_optimization.json"
        write_optimization_report_json(path, report)
        optimization_paths[reference.id] = path
    return optimization_paths


def _evaluate_model(
    *,
    model: str,
    reference: FSM,
    faulty: FSM,
    oracle: OracleSuite,
    mutants: tuple[MutantRecord, ...],
) -> PipelineInstanceMetrics:
    if model == "reference":
        candidate = reference.model_copy(deep=True)
    else:
        patch = propose_baseline_patch(faulty, oracle, engine=model)
        candidate = apply_patch(faulty, patch)

    report = score_bpr_benchmark(
        BPRScoreInput(
            reference=reference,
            oracle=oracle,
            candidate=CandidatePrediction(candidate_fsm=candidate),
            mutants=mutants,
        )
    )
    return PipelineInstanceMetrics(
        fsm_id=reference.id,
        model=model,
        bpr=round(report.bpr, 6),
        mutation_score=round(report.mutation_score, 6),
        transition_coverage=round(report.coverage.transition, 6),
        oracle_scenarios=len(oracle.scenarios),
        optimized_scenarios=0,
        pareto_front_size=0,
        execution_cost=report.execution_cost,
    )


def _step_evaluate_models(
    fsm_paths: Sequence[Path],
    oracle_paths: dict[str, Path],
    mutant_roots: dict[str, Path],
    optimization_paths: dict[str, Path],
    config: ExperimentPipelineConfig,
    results_dir: Path,
) -> list[PipelineInstanceMetrics]:
    metrics: list[PipelineInstanceMetrics] = []
    eval_dir = results_dir / "model_eval"
    eval_dir.mkdir(parents=True, exist_ok=True)

    for index, fsm_path in enumerate(fsm_paths):
        reference = load_fsm_json(fsm_path)
        oracle = load_oracle_suite(oracle_paths[reference.id])
        mutants = _load_mutants(mutant_roots[reference.id])
        faulty, _ = mutate(reference, "wrong_target", config.seed + index * 13)
        optimization = json.loads(optimization_paths[reference.id].read_text(encoding="utf-8"))
        optimized_scenarios = min(
            (
                len(solution["scenario_ids"])
                for algorithm in optimization["algorithms"].values()
                for solution in algorithm["pareto_front"]
            ),
            default=len(oracle.scenarios),
        )
        pareto_front_size = len(optimization.get("combined_pareto_front", []))

        for model in config.models:
            item = _evaluate_model(
                model=model,
                reference=reference,
                faulty=faulty,
                oracle=oracle,
                mutants=mutants,
            )
            item = item.model_copy(
                update={
                    "optimized_scenarios": optimized_scenarios,
                    "pareto_front_size": pareto_front_size,
                }
            )
            metrics.append(item)

        eval_payload = {
            "fsm_id": reference.id,
            "models": [item.model_dump() for item in metrics if item.fsm_id == reference.id],
        }
        (eval_dir / f"{reference.id}_eval.json").write_text(
            json.dumps(eval_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return metrics


def _summarize_models(metrics: list[PipelineInstanceMetrics]) -> list[dict[str, object]]:
    grouped: dict[str, list[PipelineInstanceMetrics]] = defaultdict(list)
    for item in metrics:
        grouped[item.model].append(item)

    rows: list[dict[str, object]] = []
    for model, items in sorted(grouped.items()):
        rows.append(
            {
                "model": model,
                "instances": len(items),
                "mean_bpr": round(sum(item.bpr for item in items) / len(items), 4),
                "mean_mutation_score": round(
                    sum(item.mutation_score for item in items) / len(items),
                    4,
                ),
                "mean_transition_coverage": round(
                    sum(item.transition_coverage for item in items) / len(items),
                    4,
                ),
                "mean_execution_cost": round(
                    sum(item.execution_cost for item in items) / len(items),
                    2,
                ),
            }
        )
    return rows


def _compute_statistics(
    metrics: list[PipelineInstanceMetrics],
    *,
    alpha: float,
) -> list[StatisticalTestResult]:
    grouped: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for item in metrics:
        grouped[item.model]["bpr"].append(item.bpr)
        grouped[item.model]["mutation_score"].append(item.mutation_score)
        grouped[item.model]["transition_coverage"].append(item.transition_coverage)

    results: list[StatisticalTestResult] = []
    models = sorted(grouped)
    if len(models) >= 2:
        reference = "reference"
        for model in models:
            if model == reference:
                continue
            for metric in ("bpr", "mutation_score", "transition_coverage"):
                mw, wil, cliffs, cohens = compare_independent_groups(
                    group_a=reference,
                    group_b=model,
                    metric=metric,
                    values_a=grouped[reference][metric],
                    values_b=grouped[model][metric],
                    alpha=alpha,
                )
                results.extend([mw, wil, cliffs, cohens])

    if "reference" in grouped and "missing-transition" in grouped:
        for metric in ("bpr", "mutation_score", "transition_coverage"):
            values_a = grouped["reference"][metric]
            values_b = grouped["missing-transition"][metric]
            if len(values_a) == len(values_b) and len(values_a) >= 2:
                mw, wil, cliffs, cohens = compare_paired_groups(
                    group_a="reference",
                    group_b="missing-transition",
                    metric=metric,
                    values_a=values_a,
                    values_b=values_b,
                    alpha=alpha,
                )
                results.extend([mw, wil, cliffs, cohens])
    return results


def _write_plots(
    metrics: list[PipelineInstanceMetrics],
    model_summary: list[dict[str, object]],
    figures_dir: Path,
) -> list[Path]:
    plt = _pyplot()
    figures_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    fig, axis = plt.subplots(figsize=(8, 5))
    models = [row["model"] for row in model_summary]
    means = [float(row["mean_bpr"]) for row in model_summary]
    axis.bar(models, means, color="#4C72B0")
    axis.set_ylabel("Mean BPR")
    axis.set_title("Model repair performance")
    axis.set_ylim(0.0, 1.0)
    axis.tick_params(axis="x", rotation=20)
    path = figures_dir / "model_bpr_comparison.png"
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)
    written.append(path)

    grouped: dict[str, list[float]] = defaultdict(list)
    for item in metrics:
        grouped[item.model].append(item.bpr)
    fig, axis = plt.subplots(figsize=(8, 5))
    axis.boxplot([grouped[model] for model in models], tick_labels=models)
    axis.set_ylabel("BPR")
    axis.set_title("BPR distribution by model")
    axis.tick_params(axis="x", rotation=20)
    path = figures_dir / "model_bpr_distribution.png"
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)
    written.append(path)

    fig, axis = plt.subplots(figsize=(8, 5))
    axis.bar(
        models,
        [float(row["mean_mutation_score"]) for row in model_summary],
        color="#55A868",
    )
    axis.set_ylabel("Mean mutation score")
    axis.set_title("Mutation score by model")
    axis.set_ylim(0.0, 1.0)
    axis.tick_params(axis="x", rotation=20)
    path = figures_dir / "mutation_score_by_model.png"
    fig.tight_layout()
    fig.savefig(path, dpi=300)
    plt.close(fig)
    written.append(path)

    return written


def run_experiment_pipeline(config: ExperimentPipelineConfig) -> ExperimentPipelineResult:
    """Execute the full seven-step experiment pipeline."""
    output_root = config.output_root
    results_dir = output_root / RESULTS_DIR
    figures_dir = output_root / FIGURES_DIR
    tables_dir = output_root / TABLES_DIR
    reports_dir = output_root / REPORTS_DIR
    for directory in (results_dir, figures_dir, tables_dir, reports_dir):
        directory.mkdir(parents=True, exist_ok=True)

    fsm_paths = _step_generate_fsms(config, results_dir)
    mutant_roots = _step_generate_mutants(fsm_paths, config, results_dir)
    oracle_paths = _step_generate_oracles(fsm_paths, results_dir)
    optimization_paths = _step_optimize_suites(
        fsm_paths,
        oracle_paths,
        mutant_roots,
        config,
        results_dir,
    )
    metrics = _step_evaluate_models(
        fsm_paths,
        oracle_paths,
        mutant_roots,
        optimization_paths,
        config,
        results_dir,
    )

    metrics_csv = tables_dir / "instance_metrics.csv"
    write_csv_report(
        metrics_csv,
        columns=METRICS_CSV_COLUMNS,
        rows=[item.model_dump() for item in metrics],
    )

    model_summary = _summarize_models(metrics)
    model_summary_csv = tables_dir / "model_summary.csv"
    write_csv_report(
        model_summary_csv,
        columns=("model", "instances", "mean_bpr", "mean_mutation_score", "mean_transition_coverage", "mean_execution_cost"),
        rows=model_summary,
    )

    statistics = _compute_statistics(metrics, alpha=config.alpha)
    statistics_csv = tables_dir / "statistical_tests.csv"
    write_csv_report(
        statistics_csv,
        columns=STATISTICS_CSV_COLUMNS,
        rows=[item.to_csv_row() for item in statistics],
    )

    model_summary_tex = tables_dir / "model_summary.tex"
    _write_latex_table(
        model_summary_tex,
        columns=("Model", "Instances", "Mean BPR", "Mean Mutation", "Mean Coverage"),
        rows=[
            [
                str(row["model"]),
                str(row["instances"]),
                f"{float(row['mean_bpr']):.3f}",
                f"{float(row['mean_mutation_score']):.3f}",
                f"{float(row['mean_transition_coverage']):.3f}",
            ]
            for row in model_summary
        ],
        caption="Summary of benchmark model performance across generated FSM instances.",
        label="tab:model_summary",
    )

    statistics_tex = tables_dir / "statistical_tests.tex"
    _write_latex_table(
        statistics_tex,
        columns=("Test", "Group A", "Group B", "Metric", "Effect", "p-value", "Significant"),
        rows=[
            [
                item.test,
                item.group_a,
                item.group_b,
                item.metric,
                f"{item.effect_size:.3f} ({item.effect_label})",
                "" if item.p_value is None else f"{item.p_value:.4f}",
                "yes" if item.significant else "no",
            ]
            for item in statistics
        ],
        caption="Statistical comparisons between benchmark models and suites.",
        label="tab:statistical_tests",
    )

    figure_paths: list[str] = []
    if config.generate_plots:
        written = _write_plots(metrics, model_summary, figures_dir)
        figure_paths = [str(path) for path in written]

        for fsm_path in fsm_paths:
            reference = load_fsm_json(fsm_path)
            oracle = load_oracle_suite(oracle_paths[reference.id])
            mutants = _load_mutants(mutant_roots[reference.id])
            report = optimize_test_suites(
                reference,
                oracle,
                mutants,
                algorithms=config.optimizers,
                seed=config.seed,
                iterations=config.optimizer_iterations,
                population_size=config.optimizer_population_size,
                generations=config.optimizer_generations,
            )
            plot_dir = figures_dir / reference.id
            visualize_pareto_results(report, plot_dir)
            figure_paths.extend(str(path) for path in plot_dir.glob("*.png"))

    pipeline_report = {
        "pipeline_steps": [
            "generate_fsms",
            "generate_mutants",
            "generate_oracle_suites",
            "optimize_test_suites",
            "evaluate_benchmark_models",
            "compute_metrics",
            "generate_plots",
        ],
        "config": config.model_dump(mode="json"),
        "instance_count": len(fsm_paths),
        "metrics_count": len(metrics),
        "statistics_count": len(statistics),
        "figure_paths": figure_paths,
        "output_dirs": {
            "results": str(results_dir),
            "figures": str(figures_dir),
            "tables": str(tables_dir),
            "reports": str(reports_dir),
        },
    }
    pipeline_report_json = reports_dir / "pipeline_report.json"
    write_json_report(pipeline_report_json, pipeline_report)

    pipeline_report_md = reports_dir / "pipeline_report.md"
    pipeline_report_md.write_text(
        "\n".join(
            [
                "# Experiment Pipeline Report",
                "",
                f"- FSM instances: {len(fsm_paths)}",
                f"- Metrics rows: {len(metrics)}",
                f"- Statistical tests: {len(statistics)}",
                f"- Figures: {len(figure_paths)}",
                "",
                "## Outputs",
                "",
                f"- Metrics CSV: `{metrics_csv}`",
                f"- Model summary CSV: `{model_summary_csv}`",
                f"- Statistical tests CSV: `{statistics_csv}`",
                f"- Model summary LaTeX: `{model_summary_tex}`",
                f"- Statistical tests LaTeX: `{statistics_tex}`",
                "",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    manifest_path = output_root / "pipeline_manifest.json"
    write_json_report(manifest_path, pipeline_report)

    return ExperimentPipelineResult(
        output_root=output_root,
        results_dir=results_dir,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        reports_dir=reports_dir,
        metrics_csv=metrics_csv,
        model_summary_csv=model_summary_csv,
        statistics_csv=statistics_csv,
        model_summary_tex=model_summary_tex,
        statistics_tex=statistics_tex,
        pipeline_report_json=pipeline_report_json,
        pipeline_report_md=pipeline_report_md,
        instance_count=len(fsm_paths),
    )
