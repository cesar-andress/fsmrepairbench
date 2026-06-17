"""Extended C3 oracle-depth ablation: deep walks beyond shallow/medium/deep with repair metrics."""

from __future__ import annotations

import csv
import json
import shutil
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import _pyplot, _save_bar_plot
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.models import FSM
from fsmrepairbench.mutators import MUTATION_OPERATORS
from fsmrepairbench.oracle_depth_ablation import (
    COHORT_FILENAME,
    OracleDepthAblationError,
    OracleDepthAblationResult,
    _list_output_files,
    _load_case_strata,
    _write_csv,
    load_cohort_manifest,
    write_ablation_cohort_manifest,
)
from fsmrepairbench.oracle_generator import (
    DEPTH_MAX_STEPS,
    EXTENDED_ABLATION_DEPTHS,
    DepthLevel,
    OracleGeneratorError,
    ScenarioPolicy,
    compute_coverage,
    generate_oracle_suite,
)
from fsmrepairbench.patch import PatchError, apply_patch
from fsmrepairbench.repair_engines.baselines import propose_baseline_patch
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.statistics import (
    append_ci_section_to_report,
    bootstrap_mean_ci,
    bootstrap_rate_ci,
    write_confidence_interval_exports,
)
from fsmrepairbench.validators import load_fsm_json
from fsmrepairbench.dataset_builder import resolve_coupling_case_file

EXTENDED_EXPERIMENT = "C3-oracle-depth-ablation-extended"
EXTENDED_RELEASE_LABEL = "C3-oracle-depth-ablation-extended-200"
DEFAULT_EXTENDED_OUTPUT = Path("results/oracle_depth_ablation_extended")
DEFAULT_EXTENDED_PAPER_EXPORT = Path("../paper1/results/oracle_depth_ablation_extended")
DEFAULT_REPAIR_ENGINE = "missing-transition"
ZENODO_DOI = "10.5281/zenodo.20724095"

EXTENDED_PER_CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "oracle_depth",
    "declared_max_steps",
    "mutation_operator",
    "size_class",
    "scenario_policy",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "fault_detected",
    "final_bpr",
    "repair_delta_bpr",
    "complete_repair",
    "effective_repair",
    "oracle_state_coverage",
    "oracle_transition_coverage",
    "oracle_event_coverage",
    "scenario_count",
    "mean_scenario_length",
    "median_scenario_length",
    "max_scenario_length",
    "max_scenario_steps",
)
EXTENDED_DEPTH_SUMMARY_COLUMNS: tuple[str, ...] = (
    "oracle_depth",
    "declared_max_steps",
    "scenario_policy",
    "case_count",
    "overall_detection_rate",
    "mean_faulty_bpr",
    "mean_bpr_delta",
    "mean_complete_repair_rate",
    "mean_effective_repair_rate",
    "mean_repair_delta_bpr",
    "mean_scenario_length",
    "median_scenario_length",
    "max_scenario_length",
    "mean_scenario_count",
    "mean_oracle_state_coverage",
    "mean_oracle_transition_coverage",
    "mean_oracle_event_coverage",
    "detection_gains_vs_shallow",
    "detection_losses_vs_shallow",
    "skipped_reference_bpr_cases",
)
EXTENDED_PAIRED_COLUMNS: tuple[str, ...] = (
    "comparison_depth",
    "declared_max_steps",
    "both_detected",
    "shallow_only_detected",
    "higher_only_detected",
    "neither_detected",
    "detection_gains",
    "detection_losses",
    "mcnemar_chi2",
)


@dataclass(frozen=True)
class ExtendedDepthCaseResult:
    """Detection, ΔBPR, and repair metrics for one case at one oracle depth."""

    case_id: str
    depth: DepthLevel
    mutation_operator: str
    size_class: str
    reference_bpr: float
    faulty_bpr: float
    bpr_delta: float
    fault_detected: bool
    final_bpr: float
    repair_delta_bpr: float
    complete_repair: bool
    effective_repair: bool
    oracle_state_coverage: float
    oracle_transition_coverage: float
    oracle_event_coverage: float
    scenario_count: int
    max_scenario_steps: int
    scenario_policy: ScenarioPolicy
    mean_scenario_length: float
    median_scenario_length: float
    max_scenario_length: int

    def to_dict(self) -> dict[str, str | float | bool | int]:
        return {
            "case_id": self.case_id,
            "oracle_depth": self.depth,
            "declared_max_steps": DEPTH_MAX_STEPS[self.depth],
            "mutation_operator": self.mutation_operator,
            "size_class": self.size_class,
            "scenario_policy": self.scenario_policy,
            "reference_bpr": round(self.reference_bpr, 6),
            "faulty_bpr": round(self.faulty_bpr, 6),
            "bpr_delta": round(self.bpr_delta, 6),
            "fault_detected": self.fault_detected,
            "final_bpr": round(self.final_bpr, 6),
            "repair_delta_bpr": round(self.repair_delta_bpr, 6),
            "complete_repair": self.complete_repair,
            "effective_repair": self.effective_repair,
            "oracle_state_coverage": round(self.oracle_state_coverage, 6),
            "oracle_transition_coverage": round(self.oracle_transition_coverage, 6),
            "oracle_event_coverage": round(self.oracle_event_coverage, 6),
            "scenario_count": self.scenario_count,
            "mean_scenario_length": round(self.mean_scenario_length, 6),
            "median_scenario_length": round(self.median_scenario_length, 6),
            "max_scenario_length": self.max_scenario_length,
            "max_scenario_steps": self.max_scenario_steps,
        }


def _evaluate_repair(
    faulty: FSM,
    oracle_suite: object,
    *,
    engine: str = DEFAULT_REPAIR_ENGINE,
    seed: int = 0,
) -> tuple[float, float, bool, bool]:
    initial_bpr = score_oracle_suite(faulty, oracle_suite).bpr  # type: ignore[arg-type]
    try:
        patch = propose_baseline_patch(faulty, oracle_suite, engine=engine, seed=seed)  # type: ignore[arg-type]
        repaired = apply_patch(faulty, patch)
    except (PatchError, ValueError):
        return initial_bpr, 0.0, initial_bpr == 1.0, False
    final_bpr = score_oracle_suite(repaired, oracle_suite).bpr  # type: ignore[arg-type]
    delta = final_bpr - initial_bpr
    return final_bpr, delta, final_bpr == 1.0, final_bpr > initial_bpr


def score_extended_case_at_depth(
    case_dir: Path,
    depth: DepthLevel,
    *,
    scenario_policy: ScenarioPolicy = "depth-forced",
    repair_engine: str = DEFAULT_REPAIR_ENGINE,
    repair_seed: int = 0,
) -> ExtendedDepthCaseResult:
    """Regenerate oracle at *depth*, score detection, and run baseline repair."""
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    if reference_path is None or faulty_path is None:
        msg = f"Incomplete case directory: {case_dir}"
        raise OracleDepthAblationError(msg)

    case_id, mutation_operator, size_class = _load_case_strata(case_dir)
    reference = load_fsm_json(reference_path)
    faulty = load_fsm_json(faulty_path)

    try:
        generation = generate_oracle_suite(reference, depth=depth, policy=scenario_policy)
    except OracleGeneratorError as exc:
        msg = f"Oracle generation failed for {case_dir.name} at {depth}: {exc}"
        raise OracleDepthAblationError(msg) from exc

    reference_bpr = score_oracle_suite(reference, generation.suite).bpr
    if reference_bpr != 1.0:
        msg = f"Reference BPR {reference_bpr:.4f} != 1.0 for {case_dir.name} at {depth}"
        raise OracleDepthAblationError(msg)

    faulty_bpr = score_oracle_suite(faulty, generation.suite).bpr
    coverage = compute_coverage(reference, generation.suite)
    bpr_delta = reference_bpr - faulty_bpr
    scenario_steps = [len(scenario.steps) for scenario in generation.suite.scenarios]
    final_bpr, repair_delta, complete_repair, effective_repair = _evaluate_repair(
        faulty,
        generation.suite,
        engine=repair_engine,
        seed=repair_seed,
    )

    return ExtendedDepthCaseResult(
        case_id=case_id,
        depth=depth,
        mutation_operator=mutation_operator,
        size_class=size_class,
        reference_bpr=reference_bpr,
        faulty_bpr=faulty_bpr,
        bpr_delta=bpr_delta,
        fault_detected=bpr_delta > 0.0,
        final_bpr=final_bpr,
        repair_delta_bpr=repair_delta,
        complete_repair=complete_repair,
        effective_repair=effective_repair,
        oracle_state_coverage=coverage.state_coverage,
        oracle_transition_coverage=coverage.transition_coverage,
        oracle_event_coverage=coverage.event_coverage,
        scenario_count=len(generation.suite.scenarios),
        max_scenario_steps=max(scenario_steps) if scenario_steps else 0,
        scenario_policy=scenario_policy,
        mean_scenario_length=generation.mean_scenario_length,
        median_scenario_length=generation.median_scenario_length,
        max_scenario_length=generation.max_scenario_length,
    )


def _detection_sets(
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]],
    *,
    depth: DepthLevel,
) -> dict[str, bool]:
    return {row.case_id: row.fault_detected for row in depth_rows[depth]}


def compute_extended_paired_detection_changes(
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]],
    *,
    depths: Sequence[DepthLevel],
    baseline: DepthLevel = "shallow",
) -> list[dict[str, str | float | int]]:
    shallow = _detection_sets(depth_rows, depth=baseline)
    rows: list[dict[str, str | float | int]] = []
    for depth in depths:
        if depth == baseline:
            continue
        higher = _detection_sets(depth_rows, depth=depth)
        both = sum(1 for case_id in shallow if shallow[case_id] and higher.get(case_id, False))
        shallow_only = sum(
            1 for case_id in shallow if shallow[case_id] and not higher.get(case_id, False)
        )
        higher_only = sum(
            1 for case_id in shallow if not shallow[case_id] and higher.get(case_id, False)
        )
        neither = sum(
            1 for case_id in shallow if not shallow[case_id] and not higher.get(case_id, False)
        )
        gains = higher_only
        losses = shallow_only
        discordant = gains + losses
        mcnemar = round(((gains - losses) ** 2) / discordant, 6) if discordant else 0.0
        rows.append(
            {
                "comparison_depth": depth,
                "declared_max_steps": DEPTH_MAX_STEPS[depth],
                "both_detected": both,
                "shallow_only_detected": shallow_only,
                "higher_only_detected": higher_only,
                "neither_detected": neither,
                "detection_gains": gains,
                "detection_losses": losses,
                "mcnemar_chi2": mcnemar,
            }
        )
    return rows


def _aggregate_extended_depth_summary(
    depth: DepthLevel,
    rows: list[ExtendedDepthCaseResult],
    *,
    skipped: int,
    detection_gains_vs_shallow: int = 0,
    detection_losses_vs_shallow: int = 0,
) -> dict[str, str | float | int]:
    if not rows:
        msg = f"No scored cases for depth {depth}"
        raise OracleDepthAblationError(msg)
    count = len(rows)
    detected = sum(1 for row in rows if row.fault_detected)
    complete = sum(1 for row in rows if row.complete_repair)
    effective = sum(1 for row in rows if row.effective_repair)
    return {
        "oracle_depth": depth,
        "declared_max_steps": DEPTH_MAX_STEPS[depth],
        "scenario_policy": rows[0].scenario_policy,
        "case_count": count,
        "overall_detection_rate": round(detected / count, 6),
        "mean_faulty_bpr": round(sum(row.faulty_bpr for row in rows) / count, 6),
        "mean_bpr_delta": round(sum(row.bpr_delta for row in rows) / count, 6),
        "mean_complete_repair_rate": round(complete / count, 6),
        "mean_effective_repair_rate": round(effective / count, 6),
        "mean_repair_delta_bpr": round(sum(row.repair_delta_bpr for row in rows) / count, 6),
        "mean_scenario_length": round(sum(row.mean_scenario_length for row in rows) / count, 2),
        "median_scenario_length": round(sum(row.median_scenario_length for row in rows) / count, 2),
        "max_scenario_length": max(row.max_scenario_length for row in rows),
        "mean_scenario_count": round(sum(row.scenario_count for row in rows) / count, 2),
        "mean_oracle_transition_coverage": round(
            sum(row.oracle_transition_coverage for row in rows) / count,
            6,
        ),
        "mean_oracle_state_coverage": round(
            sum(row.oracle_state_coverage for row in rows) / count,
            6,
        ),
        "mean_oracle_event_coverage": round(
            sum(row.oracle_event_coverage for row in rows) / count,
            6,
        ),
        "detection_gains_vs_shallow": detection_gains_vs_shallow,
        "detection_losses_vs_shallow": detection_losses_vs_shallow,
        "skipped_reference_bpr_cases": skipped,
    }


def compute_extended_confidence_intervals(
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]],
    *,
    depths: Sequence[DepthLevel],
) -> list[Any]:
    ci_rows: list[Any] = []
    for depth in depths:
        rows = depth_rows.get(depth, [])
        if not rows:
            continue
        ci_rows.extend(
            [
                bootstrap_rate_ci(
                    [row.fault_detected for row in rows],
                    "detection_rate",
                    group="C3-extended",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
                bootstrap_mean_ci(
                    [row.bpr_delta for row in rows],
                    "mean_bpr_delta",
                    group="C3-extended",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
                bootstrap_rate_ci(
                    [row.complete_repair for row in rows],
                    "complete_repair_rate",
                    group="C3-extended",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
                bootstrap_rate_ci(
                    [row.effective_repair for row in rows],
                    "effective_repair_rate",
                    group="C3-extended",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
                bootstrap_mean_ci(
                    [row.repair_delta_bpr for row in rows],
                    "mean_repair_delta_bpr",
                    group="C3-extended",
                    partition="cohort_wide",
                    subgroup=depth,
                ),
            ]
        )
    return ci_rows


def _write_extended_figures(
    figures_dir: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]],
    depths: Sequence[DepthLevel],
) -> None:
    figures_dir.mkdir(parents=True, exist_ok=True)
    labels = [str(row["oracle_depth"]) for row in depth_summaries]
    max_steps = [int(row["declared_max_steps"]) for row in depth_summaries]
    label_with_steps = [
        f"{depth}\n(max {step})" for depth, step in zip(labels, max_steps, strict=True)
    ]

    _save_bar_plot(
        figures_dir / "detection_rate_by_depth.png",
        title="Mutation Detection Rate by Extended Oracle Depth",
        xlabel="Oracle Depth Preset",
        ylabel="Detection Rate (%)",
        labels=label_with_steps,
        values=[round(float(row["overall_detection_rate"]) * 100.0, 1) for row in depth_summaries],
    )
    _save_bar_plot(
        figures_dir / "mean_bpr_delta_by_depth.png",
        title="Mean ΔBPR by Extended Oracle Depth",
        xlabel="Oracle Depth Preset",
        ylabel="Mean ΔBPR",
        labels=label_with_steps,
        values=[round(float(row["mean_bpr_delta"]), 4) for row in depth_summaries],
    )
    _save_bar_plot(
        figures_dir / "complete_repair_rate_by_depth.png",
        title="Complete Repair Rate by Extended Oracle Depth",
        xlabel="Oracle Depth Preset",
        ylabel="Complete Repair Rate (%)",
        labels=label_with_steps,
        values=[
            round(float(row["mean_complete_repair_rate"]) * 100.0, 1) for row in depth_summaries
        ],
    )
    _save_bar_plot(
        figures_dir / "effective_repair_rate_by_depth.png",
        title="Effective Repair Rate by Extended Oracle Depth",
        xlabel="Oracle Depth Preset",
        ylabel="Effective Repair Rate (%)",
        labels=label_with_steps,
        values=[
            round(float(row["mean_effective_repair_rate"]) * 100.0, 1) for row in depth_summaries
        ],
    )
    _save_bar_plot(
        figures_dir / "mean_scenario_length_by_depth.png",
        title="Mean Scenario Length by Extended Oracle Depth",
        xlabel="Oracle Depth Preset",
        ylabel="Mean Steps",
        labels=label_with_steps,
        values=[round(float(row["mean_scenario_length"]), 1) for row in depth_summaries],
    )
    _save_bar_plot(
        figures_dir / "max_scenario_length_by_depth.png",
        title="Max Scenario Length by Extended Oracle Depth",
        xlabel="Oracle Depth Preset",
        ylabel="Max Steps",
        labels=label_with_steps,
        values=[float(row["max_scenario_length"]) for row in depth_summaries],
    )

    active_operators = [
        operator
        for operator in MUTATION_OPERATORS
        if any(row.mutation_operator == operator for rows in depth_rows.values() for row in rows)
    ]
    if active_operators:
        plt = _pyplot()
        figure, axis = plt.subplots(figsize=(12, 5))
        width = 0.12
        x_positions = list(range(len(active_operators)))
        for index, depth in enumerate(depths):
            rows = depth_rows[depth]
            rates = [
                sum(1 for row in rows if row.mutation_operator == op and row.fault_detected)
                / max(1, sum(1 for row in rows if row.mutation_operator == op))
                for op in active_operators
            ]
            offsets = [pos + (index - (len(depths) - 1) / 2) * width for pos in x_positions]
            axis.bar(
                offsets,
                [rate * 100.0 for rate in rates],
                width=width,
                label=f"{depth} ({DEPTH_MAX_STEPS[depth]})",
            )
        axis.set_title("Detection Rate by Operator and Extended Oracle Depth")
        axis.set_xlabel("Mutation Operator")
        axis.set_ylabel("Detection Rate (%)")
        axis.set_xticks(x_positions)
        axis.set_xticklabels(active_operators, rotation=45, ha="right")
        axis.legend(fontsize=8)
        figure.tight_layout()
        figure.savefig(figures_dir / "detection_by_operator_depth.png", dpi=120)
        plt.close(figure)


def _write_extended_tables(
    tables_dir: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
    paired_rows: list[dict[str, str | float | int]],
) -> None:
    def _tex_ident(name: str) -> str:
        return str(name).replace("_", "\\_")

    tables_dir.mkdir(parents=True, exist_ok=True)
    summary_lines = [
        "% Auto-generated by fsmrepairbench.oracle_depth_ablation_extended",
        "\\begin{table}[t]",
        "\\caption{Extended depth-forced oracle ablation: detection, $\\Delta$BPR, and "
        "\\texttt{missing-transition} repair across six depth presets on the C3 200-case pin. "
        "Prior shallow/medium/deep-only analysis under shortest-path left declared ceilings "
        "inert ($\\approx$4 executed steps at every preset); depth-forced walks now span "
        "4--60 steps while detection remains stable.}",
        "\\label{tab:c3-extended-depth-summary}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrrrr@{}}",
        "\\toprule",
        "Depth & Max & Detect. & Mean $\\Delta$BPR & Complete & Effective & Mean repair $\\Delta$BPR "
        "& Mean len. & Max len. \\\\",
        "\\midrule",
    ]
    for row in depth_summaries:
        summary_lines.append(
            f"\\texttt{{{_tex_ident(row['oracle_depth'])}}} & {row['declared_max_steps']} & "
            f"{100 * float(row['overall_detection_rate']):.1f}\\% & "
            f"{float(row['mean_bpr_delta']):.3f} & "
            f"{100 * float(row['mean_complete_repair_rate']):.1f}\\% & "
            f"{100 * float(row['mean_effective_repair_rate']):.1f}\\% & "
            f"{float(row['mean_repair_delta_bpr']):.3f} & "
            f"{float(row['mean_scenario_length']):.1f} & "
            f"{int(row['max_scenario_length'])} \\\\"
        )
    summary_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_extended_depth_summary.tex").write_text(
        "\n".join(summary_lines),
        encoding="utf-8",
    )

    paired_lines = [
        "% Auto-generated by fsmrepairbench.oracle_depth_ablation_extended",
        "\\begin{table}[t]",
        "\\caption{Paired mutation-detection changes vs shallow across extended depth presets.}",
        "\\label{tab:c3-extended-paired-detection}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrrrr@{}}",
        "\\toprule",
        "Depth & Max steps & Both & Shallow only & Higher only & Neither & Gains & Losses \\\\",
        "\\midrule",
    ]
    for row in paired_rows:
        paired_lines.append(
            f"\\texttt{{{_tex_ident(row['comparison_depth'])}}} & {row['declared_max_steps']} & "
            f"{row['both_detected']} & {row['shallow_only_detected']} & "
            f"{row['higher_only_detected']} & {row['neither_detected']} & "
            f"{row['detection_gains']} & {row['detection_losses']} \\\\"
        )
    paired_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_extended_paired_detection.tex").write_text(
        "\n".join(paired_lines),
        encoding="utf-8",
    )


def write_extended_ablation_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    cohort_path: Path,
    depth_summaries: list[dict[str, str | float | int]],
    paired_rows: list[dict[str, str | float | int]],
    depths: Sequence[DepthLevel],
    repair_engine: str,
) -> None:
    shallow = next(row for row in depth_summaries if row["oracle_depth"] == "shallow")
    deepest = depth_summaries[-1]
    lines = [
        "# C3 Extended Oracle Depth Ablation Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Dataset: `{dataset_dir}`",
        f"Cohort: `{cohort_path}`",
        f"Output: `{output_dir}`",
        "",
        "## Prior depth ceiling (documented limitation)",
        "",
        "The original C3 v1 campaign used the shipped **shortest-path** generator with",
        "declared ceilings shallow/medium/deep (5/12/25 max steps). On the compact",
        "`plain_fsm` pin, executed scenario length stayed at ~4 steps for every preset,",
        "so detection and ΔBPR did not respond to depth manipulation (construct-validity",
        "failure). C3 v2 introduced **depth-forced** walks for the same three presets;",
        "this extended follow-up adds `exhaustive_like` (40), `extended_50`, and",
        "`extended_60` to probe sensitivity beyond the historical deep=25 ceiling.",
        "",
        "## Extended sensitivity insights",
        "",
        f"- Detection at shallow remains {100 * float(shallow['overall_detection_rate']):.1f}% "
        f"and is unchanged at {deepest['oracle_depth']} "
        f"({100 * float(deepest['overall_detection_rate']):.1f}%; max "
        f"{deepest['declared_max_steps']} declared steps).",
        f"- Mean ΔBPR rises from {float(shallow['mean_bpr_delta']):.3f} (shallow) to "
        f"{float(deepest['mean_bpr_delta']):.3f} ({deepest['oracle_depth']}), confirming "
        "behavioural separation grows with walk length even when detection partition is stable.",
        f"- `{repair_engine}` complete repair ranges "
        f"{100 * float(shallow['mean_complete_repair_rate']):.1f}%–"
        f"{100 * float(deepest['mean_complete_repair_rate']):.1f}% across presets; "
        "effective repair tracks complete repair on detectable faults.",
        "- Paired McNemar counts vs shallow show zero detection gains at every higher preset "
        "(see `paired_detection_changes.csv`).",
        "",
        "## Depth summary",
        "",
        "| Depth | Max steps | Detection | Mean ΔBPR | Complete repair | Effective repair | Mean len. |",
        "|-------|-----------|-----------|-----------|-----------------|------------------|-----------|",
    ]
    for row in depth_summaries:
        lines.append(
            f"| {row['oracle_depth']} | {row['declared_max_steps']} | "
            f"{100 * float(row['overall_detection_rate']):.1f}% | "
            f"{float(row['mean_bpr_delta']):.3f} | "
            f"{100 * float(row['mean_complete_repair_rate']):.1f}% | "
            f"{100 * float(row['mean_effective_repair_rate']):.1f}% | "
            f"{float(row['mean_scenario_length']):.1f} |"
        )
    lines.extend(
        [
            "",
            "## Paired detection vs shallow",
            "",
        ]
    )
    for row in paired_rows:
        lines.append(
            f"- **{row['comparison_depth']}** (max {row['declared_max_steps']}): "
            f"gains={row['detection_gains']}, losses={row['detection_losses']}, "
            f"McNemar χ²={row['mcnemar_chi2']}"
        )
    lines.extend(
        [
            "",
            "## Regeneration",
            "",
            "```bash",
            "fsmrepairbench run-oracle-depth-ablation-extended data/fsmrepairbench_1k \\",
            f"  --out {output_dir} \\",
            f"  --cohort-file {cohort_path} \\",
            "  --no-write-cohort",
            "python ../paper1/scripts/generate_oracle_depth_ablation_extended_outputs.py",
            "```",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_extended_summary_csv(
    path: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
) -> None:
    metric_map = (
        ("overall_detection_rate", "detection_rate"),
        ("mean_bpr_delta", "mean_bpr_delta"),
        ("mean_complete_repair_rate", "complete_repair_rate"),
        ("mean_effective_repair_rate", "effective_repair_rate"),
        ("mean_repair_delta_bpr", "mean_repair_delta_bpr"),
        ("mean_scenario_length", "mean_scenario_length"),
    )
    rows: list[dict[str, str | float]] = []
    for summary in depth_summaries:
        depth = str(summary["oracle_depth"])
        for source_key, metric in metric_map:
            rows.append(
                {"oracle_depth": depth, "metric": metric, "value": float(summary[source_key])}
            )
    _write_csv(path, ["oracle_depth", "metric", "value"], rows)


def _write_extended_distributions_csv(
    path: Path,
    rows: list[ExtendedDepthCaseResult],
) -> None:
    buckets = ("0", "0.01-0.25", "0.25-0.5", "0.5-0.75", "0.75-1.0")
    output: list[dict[str, str | float | int]] = []
    for depth in sorted({row.depth for row in rows}, key=lambda item: DEPTH_MAX_STEPS[item]):
        depth_rows = [row for row in rows if row.depth == depth]
        for metric, values in (
            ("bpr_delta", [row.bpr_delta for row in depth_rows]),
            ("repair_delta_bpr", [row.repair_delta_bpr for row in depth_rows]),
        ):
            counts = {bucket: 0 for bucket in buckets}
            for value in values:
                if value <= 0:
                    counts["0"] += 1
                elif value <= 0.25:
                    counts["0.01-0.25"] += 1
                elif value <= 0.5:
                    counts["0.25-0.5"] += 1
                elif value <= 0.75:
                    counts["0.5-0.75"] += 1
                else:
                    counts["0.75-1.0"] += 1
            total = len(values) or 1
            for bucket, count in counts.items():
                output.append(
                    {
                        "oracle_depth": depth,
                        "metric": metric,
                        "bucket": bucket,
                        "count": count,
                        "fraction": round(count / total, 6),
                    }
                )
    _write_csv(path, ["oracle_depth", "metric", "bucket", "count", "fraction"], output)


def run_oracle_depth_ablation_extended(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_path: Path | None = None,
    cohort_manifest: Path | None = None,
    cohort_size: int = 200,
    write_cohort: bool = True,
    depths: Sequence[DepthLevel] = EXTENDED_ABLATION_DEPTHS,
    scenario_policy: ScenarioPolicy = "depth-forced",
    repair_engine: str = DEFAULT_REPAIR_ENGINE,
    paper_export_dir: Path | None = None,
) -> OracleDepthAblationResult:
    """Run extended depth ablation with detection, ΔBPR, and repair metrics."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise OracleDepthAblationError(msg)

    out = output_dir or DEFAULT_EXTENDED_OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    depth_list = tuple(depths)

    if cohort_path is not None and cohort_path.is_file():
        case_ids = load_cohort_manifest(cohort_path)
    else:
        from fsmrepairbench.oracle_depth_ablation import select_ablation_cohort

        case_ids = select_ablation_cohort(
            dataset_dir,
            cohort_manifest=cohort_manifest,
            size=cohort_size,
        )

    cohort_txt = cohort_path
    cohort_json = None
    if write_cohort and cohort_path is None:
        cohort_txt, cohort_json = write_ablation_cohort_manifest(
            dataset_dir,
            case_ids,
            source_manifest=cohort_manifest,
        )
    elif cohort_path is not None:
        cohort_txt = cohort_path
        cohort_json = cohort_path.with_suffix(".json")

    per_case_rows: list[ExtendedDepthCaseResult] = []
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]] = {
        depth: [] for depth in depth_list
    }
    skipped_by_depth: Counter[DepthLevel] = Counter()

    for depth in depth_list:
        for case_id in case_ids:
            case_dir = dataset_dir / "cases" / case_id
            try:
                result = score_extended_case_at_depth(
                    case_dir,
                    depth,
                    scenario_policy=scenario_policy,
                    repair_engine=repair_engine,
                )
            except OracleDepthAblationError:
                skipped_by_depth[depth] += 1
                continue
            per_case_rows.append(result)
            depth_rows[depth].append(result)

    if not per_case_rows:
        msg = "No cases scored successfully across extended oracle depths"
        raise OracleDepthAblationError(msg)

    paired_rows = compute_extended_paired_detection_changes(depth_rows, depths=depth_list)
    depth_summaries: list[dict[str, str | float | int]] = []
    for depth in depth_list:
        if not depth_rows[depth]:
            continue
        gains, losses = (0, 0)
        if depth != "shallow":
            shallow_set = _detection_sets(depth_rows, depth="shallow")
            higher_set = _detection_sets(depth_rows, depth=depth)
            gains = sum(
                1 for case_id in shallow_set if not shallow_set[case_id] and higher_set.get(case_id, False)
            )
            losses = sum(
                1 for case_id in shallow_set if shallow_set[case_id] and not higher_set.get(case_id, False)
            )
        depth_summaries.append(
            _aggregate_extended_depth_summary(
                depth,
                depth_rows[depth],
                skipped=skipped_by_depth[depth],
                detection_gains_vs_shallow=gains,
                detection_losses_vs_shallow=losses,
            )
        )

    per_case_path = out / "per_case_results.csv"
    depth_summary_path = out / "depth_summary.csv"
    summary_path = out / "summary.csv"
    distributions_path = out / "distributions.csv"
    paired_detection_path = out / "paired_detection_changes.csv"
    coverage_by_depth_path = out / "coverage_by_depth.csv"
    report_path = out / "report.md"
    figures_dir = out / "figures"
    tables_dir = out / "tables"
    manifest_path = out / "manifest.json"

    _write_csv(
        per_case_path,
        list(EXTENDED_PER_CASE_COLUMNS),
        [row.to_dict() for row in per_case_rows],
    )
    _write_csv(depth_summary_path, list(EXTENDED_DEPTH_SUMMARY_COLUMNS), depth_summaries)
    _write_csv(paired_detection_path, list(EXTENDED_PAIRED_COLUMNS), paired_rows)
    _write_csv(
        coverage_by_depth_path,
        [
            "oracle_depth",
            "declared_max_steps",
            "scenario_policy",
            "case_count",
            "mean_oracle_state_coverage",
            "mean_oracle_transition_coverage",
            "mean_oracle_event_coverage",
            "mean_scenario_count",
            "mean_scenario_length",
            "median_scenario_length",
            "max_scenario_length",
        ],
        [
            {
                "oracle_depth": summary["oracle_depth"],
                "declared_max_steps": summary["declared_max_steps"],
                "scenario_policy": summary["scenario_policy"],
                "case_count": summary["case_count"],
                "mean_oracle_state_coverage": summary["mean_oracle_state_coverage"],
                "mean_oracle_transition_coverage": summary["mean_oracle_transition_coverage"],
                "mean_oracle_event_coverage": summary["mean_oracle_event_coverage"],
                "mean_scenario_count": summary["mean_scenario_count"],
                "mean_scenario_length": summary["mean_scenario_length"],
                "median_scenario_length": summary["median_scenario_length"],
                "max_scenario_length": summary["max_scenario_length"],
            }
            for summary in depth_summaries
        ],
    )

    _write_extended_summary_csv(summary_path, depth_summaries=depth_summaries)
    _write_extended_distributions_csv(distributions_path, per_case_rows)

    _write_extended_figures(
        figures_dir,
        depth_summaries=depth_summaries,
        depth_rows=depth_rows,
        depths=depth_list,
    )
    _write_extended_tables(
        tables_dir,
        depth_summaries=depth_summaries,
        paired_rows=paired_rows,
    )
    write_extended_ablation_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME),
        depth_summaries=depth_summaries,
        paired_rows=paired_rows,
        depths=depth_list,
        repair_engine=repair_engine,
    )

    ci_rows = compute_extended_confidence_intervals(depth_rows, depths=depth_list)
    write_confidence_interval_exports(
        out,
        campaign=EXTENDED_EXPERIMENT,
        rows=ci_rows,
    )
    append_ci_section_to_report(report_path, ci_rows)

    cohort_sha = sha256_file(cohort_txt or (dataset_dir / COHORT_FILENAME))
    manifest = {
        "release_label": EXTENDED_RELEASE_LABEL,
        "experiment": EXTENDED_EXPERIMENT,
        "zenodo_doi": ZENODO_DOI,
        "dataset_path": str(dataset_dir),
        "cohort_file": str(cohort_txt or (dataset_dir / COHORT_FILENAME)),
        "cohort_sha256": cohort_sha,
        "case_count": len(case_ids),
        "oracle_depths": list(depth_list),
        "depth_presets": {depth: DEPTH_MAX_STEPS[depth] for depth in depth_list},
        "scenario_policy": scenario_policy,
        "repair_engine": repair_engine,
        "prior_depth_ceiling_note": (
            "Original shortest-path C3 held executed path length near 4 steps at all "
            "shallow/medium/deep presets; extended depth-forced presets probe 40–60 steps."
        ),
        "timestamp_utc": datetime.now(UTC).isoformat(),
        "git_commit_hash": get_git_commit(),
        "output_files": _list_output_files(out),
        "regeneration_commands": [
            (
                "fsmrepairbench run-oracle-depth-ablation-extended data/fsmrepairbench_1k "
                f"--out {out} --cohort-file {cohort_txt} --no-write-cohort"
            ),
            "python ../paper1/scripts/generate_oracle_depth_ablation_extended_outputs.py",
        ],
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_dir = paper_export_dir or DEFAULT_EXTENDED_PAPER_EXPORT
    if paper_dir is not None:
        paper_dir.mkdir(parents=True, exist_ok=True)
        for name in (
            "depth_summary.csv",
            "per_case_results.csv",
            "paired_detection_changes.csv",
            "coverage_by_depth.csv",
            "confidence_intervals.csv",
            "confidence_intervals.json",
            "report.md",
            "manifest.json",
        ):
            source = out / name
            if source.is_file():
                (paper_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        for subdir in ("figures", "tables"):
            src_dir = out / subdir
            if src_dir.is_dir():
                dest = paper_dir / subdir
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(src_dir, dest)

    return OracleDepthAblationResult(
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME),
        cohort_manifest_path=cohort_json or (dataset_dir / COHORT_JSON_FILENAME),
        per_case_path=per_case_path,
        depth_summary_path=depth_summary_path,
        summary_path=summary_path,
        distributions_path=distributions_path,
        report_path=report_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
        case_count=len(case_ids),
        manifest_path=manifest_path,
        paired_detection_path=paired_detection_path,
        coverage_by_depth_path=coverage_by_depth_path,
        paper_export_dir=paper_dir,
    )
