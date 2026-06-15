"""Enhanced C3 oracle-depth ablation: 500-case depth-forced shallow/medium/deep with repair metrics."""

from __future__ import annotations

import json
import shutil
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.oracle_depth_ablation import (
    ABLATION_DEPTHS,
    COHORT_JSON_FILENAME_500,
    COHORT_FILENAME_500,
    DEFAULT_ENHANCED_OUTPUT,
    DEFAULT_ENHANCED_PAPER_EXPORT,
    ENHANCED_COHORT_SIZE,
    ENHANCED_EXPERIMENT,
    ENHANCED_RELEASE_LABEL,
    OracleDepthAblationError,
    OracleDepthAblationResult,
    ZENODO_DOI,
    _list_output_files,
    load_cohort_manifest,
    select_ablation_cohort,
    write_ablation_cohort_manifest,
)
from fsmrepairbench.oracle_depth_ablation_extended import (
    DEFAULT_REPAIR_ENGINE,
    EXTENDED_DEPTH_SUMMARY_COLUMNS,
    EXTENDED_PAIRED_COLUMNS,
    EXTENDED_PER_CASE_COLUMNS,
    ExtendedDepthCaseResult,
    _aggregate_extended_depth_summary,
    _detection_sets,
    _write_csv,
    _write_extended_distributions_csv,
    _write_extended_figures,
    _write_extended_summary_csv,
    _write_extended_tables,
    compute_extended_confidence_intervals,
    compute_extended_paired_detection_changes,
    score_extended_case_at_depth,
    write_extended_ablation_report,
)
from fsmrepairbench.oracle_generator import DEPTH_MAX_STEPS, DepthLevel, ScenarioPolicy
from fsmrepairbench.statistics import append_ci_section_to_report, write_confidence_interval_exports


def _copy_enhanced_paper_exports(*, output_dir: Path, paper_export_dir: Path) -> None:
    paper_export_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "depth_summary.csv",
        "per_case_results.csv",
        "paired_detection_changes.csv",
        "coverage_by_depth.csv",
        "summary.csv",
        "distributions.csv",
        "confidence_intervals.csv",
        "confidence_intervals.json",
        "report.md",
        "manifest.json",
    ):
        source = output_dir / name
        if source.is_file():
            (paper_export_dir / name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    for subdir in ("figures", "tables"):
        src_dir = output_dir / subdir
        if src_dir.is_dir():
            dest = paper_export_dir / subdir
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src_dir, dest)


def _build_enhanced_manifest(
    *,
    dataset_dir: Path,
    out: Path,
    cohort_path: Path,
    cohort_json: Path | None,
    case_count: int,
    depth_summaries: list[dict[str, object]],
    paired_rows: list[dict[str, object]],
    depth_summary_path: Path,
    repair_engine: str,
) -> dict[str, object]:
    cohort_sha256 = sha256_file(cohort_path) if cohort_path.is_file() else ""
    timestamp_utc = datetime.now(UTC).isoformat()
    git_commit_hash = get_git_commit()
    manifest: dict[str, object] = {
        "release_label": ENHANCED_RELEASE_LABEL,
        "experiment": ENHANCED_EXPERIMENT,
        "zenodo_doi": ZENODO_DOI,
        "dataset_path": str(dataset_dir),
        "dataset_dir": str(dataset_dir),
        "output_dir": str(out),
        "cohort_file": str(cohort_path),
        "cohort_path": str(cohort_path),
        "cohort_manifest_path": str(cohort_json or cohort_path.with_suffix(".json")),
        "cohort_sha256": cohort_sha256,
        "case_count": case_count,
        "cohort_size": case_count,
        "oracle_depths": list(ABLATION_DEPTHS),
        "depth_presets": {depth: DEPTH_MAX_STEPS[depth] for depth in ABLATION_DEPTHS},
        "scenario_policy": "depth-forced",
        "repair_engine": repair_engine,
        "depth_summaries": depth_summaries,
        "paired_detection_changes": paired_rows,
        "depth_summary_sha256": sha256_file(depth_summary_path),
        "timestamp_utc": timestamp_utc,
        "generated_at": timestamp_utc,
        "git_commit_hash": git_commit_hash,
        "output_files": sorted(set(_list_output_files(out) + ["manifest.json"])),
        "regeneration_commands": [
            (
                "fsmrepairbench run-oracle-depth-ablation-enhanced data/fsmrepairbench_1k "
                f"--out {out} --cohort-file {cohort_path} --no-write-cohort"
            ),
            "python ../paper1/scripts/generate_oracle_depth_ablation_outputs.py",
        ],
        "limitations_note": (
            "Depth-forced oracle generation on a 500-case stratified pin; "
            "repair metrics use missing-transition baseline on cohort-wide partition."
        ),
    }
    return manifest


def run_oracle_depth_ablation_enhanced(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
    cohort_path: Path | None = None,
    cohort_manifest: Path | None = None,
    cohort_size: int = ENHANCED_COHORT_SIZE,
    write_cohort: bool = True,
    depths: Sequence[DepthLevel] = ABLATION_DEPTHS,
    scenario_policy: ScenarioPolicy = "depth-forced",
    repair_engine: str = DEFAULT_REPAIR_ENGINE,
    paper_export_dir: Path | None = None,
) -> OracleDepthAblationResult:
    """Run enhanced depth ablation: depth-forced walks, detection, repair, and ΔBPR."""
    if scenario_policy != "depth-forced":
        msg = "Enhanced ablation requires scenario_policy='depth-forced'"
        raise OracleDepthAblationError(msg)
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise OracleDepthAblationError(msg)

    out = output_dir or DEFAULT_ENHANCED_OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    depth_list = tuple(depths)
    paper_dir = paper_export_dir or DEFAULT_ENHANCED_PAPER_EXPORT

    if cohort_path is not None and cohort_path.is_file():
        case_ids = load_cohort_manifest(cohort_path)
    else:
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
            txt_name=COHORT_FILENAME_500,
            json_name=COHORT_JSON_FILENAME_500,
            release_label=ENHANCED_RELEASE_LABEL,
            experiment=ENHANCED_EXPERIMENT,
        )
    elif cohort_path is not None:
        cohort_txt = cohort_path
        cohort_json = cohort_path.with_suffix(".json")

    per_case_rows: list[ExtendedDepthCaseResult] = []
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]] = {depth: [] for depth in depth_list}
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
        msg = "No cases scored successfully across oracle depths"
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

    _verify_scenario_length_variation(depth_summaries)

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
    _write_enhanced_tables(
        tables_dir,
        depth_summaries=depth_summaries,
        paired_rows=paired_rows,
        depth_rows=depth_rows,
        depths=depth_list,
    )
    write_extended_ablation_report(
        report_path,
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME_500),
        depth_summaries=depth_summaries,
        paired_rows=paired_rows,
        depths=depth_list,
        repair_engine=repair_engine,
    )

    ci_rows = compute_extended_confidence_intervals(depth_rows, depths=depth_list)
    write_confidence_interval_exports(
        out,
        campaign=ENHANCED_EXPERIMENT,
        rows=ci_rows,
    )
    append_ci_section_to_report(report_path, ci_rows)

    manifest = _build_enhanced_manifest(
        dataset_dir=dataset_dir,
        out=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME_500),
        cohort_json=cohort_json,
        case_count=len(case_ids),
        depth_summaries=depth_summaries,
        paired_rows=paired_rows,
        depth_summary_path=depth_summary_path,
        repair_engine=repair_engine,
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    _copy_enhanced_paper_exports(output_dir=out, paper_export_dir=paper_dir)

    return OracleDepthAblationResult(
        dataset_dir=dataset_dir,
        output_dir=out,
        cohort_path=cohort_txt or (dataset_dir / COHORT_FILENAME_500),
        cohort_manifest_path=cohort_json or (dataset_dir / COHORT_JSON_FILENAME_500),
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


def _verify_scenario_length_variation(
    depth_summaries: list[dict[str, str | float | int]],
) -> None:
    """Ensure depth-forced presets produce distinct mean scenario lengths."""
    if len(depth_summaries) < 2:
        return
    lengths = [float(row["mean_scenario_length"]) for row in depth_summaries]
    if max(lengths) - min(lengths) < 1.0:
        msg = (
            "Depth-forced ablation did not produce distinct mean scenario lengths "
            f"across presets: {lengths}"
        )
        raise OracleDepthAblationError(msg)


def _write_enhanced_tables(
    tables_dir: Path,
    *,
    depth_summaries: list[dict[str, str | float | int]],
    paired_rows: list[dict[str, str | float | int]],
    depth_rows: dict[DepthLevel, list[ExtendedDepthCaseResult]],
    depths: Sequence[DepthLevel],
) -> None:
    """Write LaTeX tables for the enhanced 500-case ablation."""
    _write_extended_tables(
        tables_dir,
        depth_summaries=depth_summaries,
        paired_rows=paired_rows,
    )
    tables_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by run-oracle-depth-ablation-enhanced",
        "\\begin{table}[t]",
        "\\caption{Enhanced oracle depth ablation summary (C3; $n=500$; depth-forced).}",
        "\\label{tab:oracle-depth-summary}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lrrrrrrrr@{}}",
        "\\toprule",
        "Depth & Steps & Detect. & $\\Delta$BPR & Complete & Effective & Mean len. & Max len. \\\\",
        "\\midrule",
    ]
    for row in depth_summaries:
        depth = str(row["oracle_depth"]).replace("_", r"\_")
        lines.append(
            f"\\texttt{{{depth}}} & {row['declared_max_steps']} & "
            f"{100 * float(row['overall_detection_rate']):.1f}\\% & "
            f"{float(row['mean_bpr_delta']):.3f} & "
            f"{100 * float(row['mean_complete_repair_rate']):.1f}\\% & "
            f"{100 * float(row['mean_effective_repair_rate']):.1f}\\% & "
            f"{float(row['mean_scenario_length']):.1f} & "
            f"{int(row['max_scenario_length'])} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_depth_summary.tex").write_text("\n".join(lines), encoding="utf-8")

    from fsmrepairbench.mutators import MUTATION_OPERATORS

    active_operators = [
        operator
        for operator in MUTATION_OPERATORS
        if any(row.mutation_operator == operator for rows in depth_rows.values() for row in rows)
    ]
    op_lines = [
        "% Auto-generated by run-oracle-depth-ablation-enhanced",
        "\\begin{table}[t]",
        "\\caption{Per-operator detection by oracle depth preset (C3 enhanced; $n=500$).}",
        "\\label{tab:oracle-depth-by-operator}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}l" + "r" * len(depths) + "@{}}",
        "\\toprule",
        "Operator & " + " & ".join(str(depth) for depth in depths) + " \\\\",
        "\\midrule",
    ]
    for operator in active_operators:
        cells = []
        for depth in depths:
            rows = depth_rows[depth]
            subset = [row for row in rows if row.mutation_operator == operator]
            rate = sum(1 for row in subset if row.fault_detected) / max(1, len(subset))
            cells.append(f"{100 * rate:.1f}\\%")
        op_lines.append(f"{operator.replace('_', r'\_')} & " + " & ".join(cells) + " \\\\")
    op_lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_detection_by_operator_depth.tex").write_text(
        "\n".join(op_lines),
        encoding="utf-8",
    )
