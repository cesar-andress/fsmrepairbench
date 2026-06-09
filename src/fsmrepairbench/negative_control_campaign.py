"""No-fault negative control cohort generation and evaluation."""

from __future__ import annotations

import csv
import json
import random
import shutil
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.experiments import (
    ExperimentCase,
    discover_experiment_cases,
)
from fsmrepairbench.freeze import get_git_commit, sha256_file
from fsmrepairbench.generator import write_benchmark_case
from fsmrepairbench.localization_campaign import localize_case_transitions
from fsmrepairbench.models import BugMetadata, FSM, RepairResult
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.tool_runner import (
    build_tool_tasks,
    execute_tool_task,
    load_tool_configs,
    tool_result_path,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

NEGATIVE_CONTROL_EXPERIMENT = "negative-control-no-fault"
NO_FAULT_OPERATOR = "no_fault"
DEFAULT_COHORT_SIZE = 100
DEFAULT_COHORT_SEED = 44
DEFAULT_SOURCE_DATASET = Path("data/fsmrepairbench_1k")
DEFAULT_SOURCE_COHORT = Path("data/fsmrepairbench_1k/analysis_cohort_1k.txt")
DEFAULT_DATASET_DIR = Path("data/fsmrepairbench_negative_controls")
DEFAULT_OUTPUT_DIR = Path("results/negative_controls")
DEFAULT_PAPER_EXPORT = Path("../paper1/results/negative_controls")
DEFAULT_TOOLS_DIR = Path("tools/baselines_c1")
COHORT_FILENAME = "negative_control_cohort_100.txt"
COHORT_JSON_FILENAME = "negative_control_cohort_100.json"
SUMMARY_COLUMNS: tuple[str, ...] = ("metric", "tool_id", "value")
PER_CASE_COLUMNS: tuple[str, ...] = (
    "case_id",
    "source_case_id",
    "mutation_operator",
    "is_negative_control",
    "reference_bpr",
    "faulty_bpr",
    "bpr_delta",
    "tool_id",
    "initial_bpr",
    "final_bpr",
    "delta_bpr",
    "patch_applied",
    "false_repair",
    "regression",
    "complete_repair",
    "effective_repair",
    "spurious_repair_improvement",
    "localization_applicable",
    "localization_skipped",
)


class NegativeControlError(RuntimeError):
    """Raised when negative-control workflow cannot be completed."""


@dataclass(frozen=True)
class NegativeControlCampaignResult:
    """Paths written by a negative-control campaign run."""

    dataset_dir: Path
    output_dir: Path
    paper_export_dir: Path
    cohort_path: Path
    summary_path: Path
    per_case_path: Path
    report_path: Path
    manifest_path: Path
    tables_dir: Path
    case_count: int


def load_cohort_manifest(path: Path) -> list[str]:
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise NegativeControlError(msg)
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def select_negative_control_sources(
    source_ids: list[str],
    *,
    size: int = DEFAULT_COHORT_SIZE,
    seed: int = DEFAULT_COHORT_SEED,
) -> list[str]:
    """Select a reproducible pinned subset of source case IDs."""
    if size < 1:
        msg = "Cohort size must be at least 1"
        raise NegativeControlError(msg)
    if len(source_ids) < size:
        msg = f"Need {size} source cases, found {len(source_ids)}"
        raise NegativeControlError(msg)
    rng = random.Random(seed)
    return sorted(rng.sample(sorted(source_ids), size))


def write_negative_control_cohort_manifest(
    dataset_dir: Path,
    *,
    case_ids: list[str],
    source_cases: list[str],
    seed: int,
    source_cohort: Path,
) -> tuple[Path, Path]:
    txt_path = dataset_dir / COHORT_FILENAME
    json_path = dataset_dir / COHORT_JSON_FILENAME
    txt_path.write_text("\n".join(case_ids) + "\n", encoding="utf-8")
    payload = {
        "experiment": NEGATIVE_CONTROL_EXPERIMENT,
        "cohort_size": len(case_ids),
        "case_ids": case_ids,
        "source_case_ids": source_cases,
        "source_cohort": str(source_cohort),
        "selection_seed": seed,
        "sha256": sha256_file(txt_path),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return txt_path, json_path


def _write_case_metadata(
    case_dir: Path,
    *,
    case_id: str,
    source_metadata: dict[str, Any],
    reference: FSM,
) -> None:
    coverage = source_metadata.get("oracle_coverage", {})
    payload = {
        **source_metadata,
        "case_id": case_id,
        "reference_fsm_id": reference.id,
        "faulty_fsm_id": reference.id,
        "mutation_operator": NO_FAULT_OPERATOR,
        "reference_bpr": 1.0,
        "faulty_bpr": 1.0,
        "bpr_delta": 0.0,
        "valid_reference": True,
        "valid_faulty": True,
        "oracle_coverage": coverage,
    }
    (case_dir / "case_metadata.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_negative_control_case(
    *,
    source_case_dir: Path,
    target_case_dir: Path,
    case_id: str,
    source_case_id: str,
    seed: int,
) -> None:
    """Materialize one no-fault control case from a v0.2.0-analysis source case."""
    reference_path = resolve_coupling_case_file(source_case_dir, "reference_fsm.json")
    oracle_path = resolve_coupling_case_file(source_case_dir, "oracle_suite.json")
    if reference_path is None or oracle_path is None:
        msg = f"Incomplete source case: {source_case_dir}"
        raise NegativeControlError(msg)

    reference = load_fsm_json(reference_path)
    oracle = load_oracle_suite(oracle_path)
    reference_bpr = score_oracle_suite(reference, oracle).bpr
    if reference_bpr != 1.0:
        msg = f"Source case {source_case_id} reference BPR {reference_bpr:.4f} != 1.0"
        raise NegativeControlError(msg)

    faulty = reference.model_copy(deep=True)
    bug_metadata = BugMetadata(
        bug_id=case_id,
        reference_fsm_id=reference.id,
        faulty_fsm_id=reference.id,
        mutation_operator=NO_FAULT_OPERATOR,
        changed_transition_id=None,
        description=(
            "Negative control: no injected mutation; faulty FSM identical to reference."
        ),
        seed=seed,
        is_negative_control=True,
    )

    if target_case_dir.exists():
        shutil.rmtree(target_case_dir)
    target_case_dir.mkdir(parents=True)
    write_benchmark_case(
        case_dir=target_case_dir,
        reference=reference,
        faulty_fsm=faulty,
        bug_metadata=bug_metadata,
        oracle=oracle,
    )

    source_metadata_path = source_case_dir / "case_metadata.json"
    if source_metadata_path.is_file():
        source_metadata = json.loads(source_metadata_path.read_text(encoding="utf-8"))
    else:
        source_metadata = {
            "benchmark_version": "v0.2.0-analysis-derived",
            "complexity": "small",
            "state_count": len(reference.states),
            "transition_count": len(reference.transitions),
            "event_count": len(reference.events),
            "mutation_operator": NO_FAULT_OPERATOR,
            "difficulty_score": 0.0,
            "oracle_coverage": {
                "state_coverage": 1.0,
                "transition_coverage": 1.0,
                "event_coverage": 1.0,
            },
        }
    _write_case_metadata(
        target_case_dir,
        case_id=case_id,
        source_metadata=source_metadata,
        reference=reference,
    )
    (target_case_dir / "source_case_id.txt").write_text(source_case_id + "\n", encoding="utf-8")


def validate_negative_control_case(case_dir: Path) -> list[str]:
    """Return validation errors for a no-fault negative control case."""
    errors: list[str] = []
    required = (
        "reference_fsm.json",
        "faulty_fsm.json",
        "oracle_suite.json",
        "bug_metadata.json",
        "case_metadata.json",
    )
    for filename in required:
        if not (case_dir / filename).is_file():
            errors.append(f"Missing required file: {filename}")

    if errors:
        return errors

    metadata = BugMetadata.model_validate(
        json.loads((case_dir / "bug_metadata.json").read_text(encoding="utf-8"))
    )
    if metadata.mutation_operator != NO_FAULT_OPERATOR:
        errors.append(f"Expected mutation_operator='{NO_FAULT_OPERATOR}'")
    if not metadata.is_negative_control:
        errors.append("Expected is_negative_control=true")

    reference = load_fsm_json(case_dir / "reference_fsm.json")
    faulty = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle = load_oracle_suite(case_dir / "oracle_suite.json")
    if reference.model_dump() != faulty.model_dump():
        errors.append("Faulty FSM is not identical to reference FSM")

    reference_bpr = score_oracle_suite(reference, oracle).bpr
    faulty_bpr = score_oracle_suite(faulty, oracle).bpr
    if reference_bpr != 1.0:
        errors.append(f"Reference BPR {reference_bpr:.4f} != 1.0")
    if faulty_bpr != 1.0:
        errors.append(f"Faulty BPR {faulty_bpr:.4f} != 1.0")
    if round(reference_bpr - faulty_bpr, 6) != 0.0:
        errors.append("Reference and faulty BPR differ")

    return errors


def repair_patch_applied(repair_result: RepairResult | None) -> bool:
    if repair_result is None:
        return False
    iterations = repair_result.details.get("iterations", [])
    if not isinstance(iterations, list):
        return False
    return any(isinstance(record, dict) and record.get("patch_applied") for record in iterations)


def spurious_repair_improvement(
    *,
    complete_repair: bool,
    effective_repair: bool,
    regression: bool,
    patch_applied: bool,
) -> bool:
    """True when a repair tool reports improvement on a no-fault case."""
    _ = complete_repair
    return effective_repair or regression or patch_applied


def build_negative_control_dataset(
    source_dataset: Path,
    *,
    output_dir: Path,
    source_cohort: Path | None = None,
    cohort_size: int = DEFAULT_COHORT_SIZE,
    seed: int = DEFAULT_COHORT_SEED,
) -> tuple[Path, Path, list[str]]:
    """Build a pinned no-fault dataset from the v0.2.0-analysis source pool."""
    cohort_file = source_cohort or (source_dataset / "analysis_cohort_1k.txt")
    source_ids = load_cohort_manifest(cohort_file)
    selected_sources = select_negative_control_sources(source_ids, size=cohort_size, seed=seed)

    if output_dir.exists():
        shutil.rmtree(output_dir)
    cases_root = output_dir / "cases"
    cases_root.mkdir(parents=True)

    case_ids: list[str] = []
    for index, source_case_id in enumerate(selected_sources, start=1):
        case_id = f"nc_{index:06d}"
        source_case_dir = source_dataset / "cases" / source_case_id
        if not source_case_dir.is_dir():
            msg = f"Missing source case directory: {source_case_dir}"
            raise NegativeControlError(msg)
        build_negative_control_case(
            source_case_dir=source_case_dir,
            target_case_dir=cases_root / case_id,
            case_id=case_id,
            source_case_id=source_case_id,
            seed=seed + index,
        )
        validation_errors = validate_negative_control_case(cases_root / case_id)
        if validation_errors:
            msg = f"Invalid negative control case {case_id}: {'; '.join(validation_errors)}"
            raise NegativeControlError(msg)
        case_ids.append(case_id)

    cohort_txt, cohort_json = write_negative_control_cohort_manifest(
        output_dir,
        case_ids=case_ids,
        source_cases=selected_sources,
        seed=seed,
        source_cohort=cohort_file,
    )
    readme = (
        "# Negative Control Dataset (no-fault)\n\n"
        f"- Experiment: {NEGATIVE_CONTROL_EXPERIMENT}\n"
        f"- Cases: {len(case_ids)}\n"
        f"- Selection seed: {seed}\n"
        f"- Source cohort: `{cohort_file.name}`\n\n"
        "These cases copy reference FSMs and oracle suites from v0.2.0-analysis without "
        "injecting mutations. They do not replace the frozen Zenodo release.\n"
    )
    (output_dir / "README.md").write_text(readme, encoding="utf-8")
    return cohort_txt, cohort_json, case_ids


def _read_source_case_id(case_dir: Path) -> str:
    path = case_dir / "source_case_id.txt"
    if path.is_file():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _score_case(case: ExperimentCase) -> tuple[float, float, float]:
    reference_path = case.case_dir / "reference_fsm.json"
    reference = load_fsm_json(reference_path)
    reference_bpr = score_oracle_suite(reference, case.oracle_suite).bpr
    faulty_bpr = score_oracle_suite(case.faulty_fsm, case.oracle_suite).bpr
    return reference_bpr, faulty_bpr, reference_bpr - faulty_bpr


def _aggregate_tool_metrics(rows: list[dict[str, Any]]) -> dict[str, dict[str, float | int]]:
    by_tool: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tool_id = str(row["tool_id"])
        if tool_id:
            by_tool[tool_id].append(row)

    aggregate: dict[str, dict[str, float | int]] = {}
    for tool_id, tool_rows in sorted(by_tool.items()):
        count = len(tool_rows)
        false_repairs = sum(1 for row in tool_rows if row["false_repair"])
        regressions = sum(1 for row in tool_rows if row["regression"])
        patches = sum(1 for row in tool_rows if row["patch_applied"])
        aggregate[tool_id] = {
            "case_count": count,
            "false_repair_rate": round(false_repairs / count, 6) if count else 0.0,
            "regression_rate": round(regressions / count, 6) if count else 0.0,
            "mean_delta_bpr": round(sum(float(row["delta_bpr"]) for row in tool_rows) / count, 6)
            if count
            else 0.0,
            "tools_modifying_correct_fsms": patches,
        }
    return aggregate


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _write_summary_csv(
    path: Path,
    *,
    tool_metrics: dict[str, dict[str, float | int]],
    overall: dict[str, float | int],
) -> None:
    rows: list[dict[str, Any]] = [
        {"metric": key, "tool_id": "", "value": value} for key, value in overall.items()
    ]
    for tool_id, metrics in tool_metrics.items():
        for metric, value in metrics.items():
            rows.append({"metric": metric, "tool_id": tool_id, "value": value})
    _write_csv(path, SUMMARY_COLUMNS, rows)


def _write_report(
    path: Path,
    *,
    dataset_dir: Path,
    output_dir: Path,
    cohort_path: Path,
    case_count: int,
    tool_metrics: dict[str, dict[str, float | int]],
    overall: dict[str, float | int],
    localization_skipped: int,
) -> None:
    lines = [
        "# Negative Control Cohort (No-Fault)",
        "",
        "Construct-validity controls for repair tools on already-correct FSMs. These cases "
        "copy reference machines and oracle suites from the frozen v0.2.0-analysis cohort "
        "without injecting mutations.",
        "",
        "**Important:** This pilot does not replace the Zenodo `v0.2.0-analysis` release.",
        "",
        "## Cohort",
        "",
        f"- Dataset: `{dataset_dir}`",
        f"- Manifest: `{cohort_path.name}`",
        f"- Cases: {case_count}",
        f"- Selection seed: {DEFAULT_COHORT_SEED}",
        "",
        "## Overall metrics",
        "",
        f"- False repair rate: **{float(overall['false_repair_rate']):.2%}**",
        f"- Regression rate: **{float(overall['regression_rate']):.2%}**",
        f"- Mean ΔBPR: **{float(overall['mean_delta_bpr']):.4f}**",
        f"- Tool runs modifying correct FSMs: **{int(overall['tools_modifying_correct_fsms'])}**",
        f"- Localization skipped (not applicable): **{localization_skipped}/{case_count}**",
        "",
        "## Metrics by repair tool",
        "",
        "| Tool | Cases | False repair | Regression | Mean ΔBPR | Patches applied |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for tool_id, metrics in tool_metrics.items():
        lines.append(
            f"| `{tool_id}` | {metrics['case_count']} | "
            f"{float(metrics['false_repair_rate']):.2%} | "
            f"{float(metrics['regression_rate']):.2%} | "
            f"{float(metrics['mean_delta_bpr']):.4f} | "
            f"{int(metrics['tools_modifying_correct_fsms'])} |"
        )

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Summary: `{output_dir / 'summary.csv'}`",
            f"- Per-case results: `{output_dir / 'per_case_results.csv'}`",
            f"- LaTeX tables: `{output_dir / 'tables'}/`",
            "",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_tables(
    tables_dir: Path,
    *,
    tool_metrics: dict[str, dict[str, float | int]],
) -> None:
    tables_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        "% Auto-generated by run-negative-control-campaign",
        "\\begin{table}[t]",
        "\\caption{No-fault negative control outcomes by baseline repair tool.}",
        "\\label{tab:negative-control-summary}",
        "\\small",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Tool & False repair & Regression & Mean $\\Delta$BPR & Patches \\\\",
        "\\midrule",
    ]
    for tool_id, metrics in tool_metrics.items():
        lines.append(
            f"{tool_id} & "
            f"{100 * float(metrics['false_repair_rate']):.1f}\\% & "
            f"{100 * float(metrics['regression_rate']):.1f}\\% & "
            f"{float(metrics['mean_delta_bpr']):.3f} & "
            f"{int(metrics['tools_modifying_correct_fsms'])} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (tables_dir / "table_negative_control_summary.tex").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def _copy_paper_exports(*, output_dir: Path, paper_export_dir: Path) -> None:
    paper_export_dir.mkdir(parents=True, exist_ok=True)
    paper_tables = paper_export_dir / "tables"
    paper_tables.mkdir(parents=True, exist_ok=True)
    for name in ("summary.csv", "per_case_results.csv", "report.md", "manifest.json"):
        source = output_dir / name
        if source.is_file():
            shutil.copy2(source, paper_export_dir / name)
    tex_source = output_dir / "tables" / "table_negative_control_summary.tex"
    if tex_source.is_file():
        shutil.copy2(tex_source, paper_tables / tex_source.name)


def run_negative_control_campaign(
    source_dataset: Path | None = None,
    *,
    dataset_dir: Path | None = None,
    output_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    source_cohort: Path | None = None,
    tools_dir: Path | None = None,
    cohort_size: int = DEFAULT_COHORT_SIZE,
    seed: int = DEFAULT_COHORT_SEED,
    rebuild_dataset: bool = True,
) -> NegativeControlCampaignResult:
    """Build, score, repair, and export the no-fault negative control cohort."""
    source = source_dataset or DEFAULT_SOURCE_DATASET
    data_dir = dataset_dir or DEFAULT_DATASET_DIR
    out = output_dir or DEFAULT_OUTPUT_DIR
    paper_dir = paper_export_dir or DEFAULT_PAPER_EXPORT
    tool_dir = tools_dir or DEFAULT_TOOLS_DIR

    if rebuild_dataset or not (data_dir / "cases").is_dir():
        cohort_txt, _, _ = build_negative_control_dataset(
            source,
            output_dir=data_dir,
            source_cohort=source_cohort,
            cohort_size=cohort_size,
            seed=seed,
        )
    else:
        cohort_txt = data_dir / COHORT_FILENAME

    if not cohort_txt.is_file():
        msg = f"Negative control cohort manifest missing: {cohort_txt}"
        raise NegativeControlError(msg)

    out.mkdir(parents=True, exist_ok=True)
    repair_dir = out / "repair_runs"
    repair_dir.mkdir(parents=True, exist_ok=True)

    cases = discover_experiment_cases(data_dir / "cases")
    tools = load_tool_configs(tool_dir)
    if not tools:
        msg = f"No tool configs found in {tool_dir}"
        raise NegativeControlError(msg)

    per_case_rows: list[dict[str, Any]] = []
    localization_skipped = 0

    for case in cases:
        reference_bpr, faulty_bpr, bpr_delta = _score_case(case)
        localization = localize_case_transitions(case.case_dir)
        localization_applicable = False
        if case.mutation_operator == NO_FAULT_OPERATOR:
            localization_skipped += 1
        _ = localization
        source_case_id = _read_source_case_id(case.case_dir)

        score_row = {
            "case_id": case.case_id,
            "source_case_id": source_case_id,
            "mutation_operator": case.mutation_operator,
            "is_negative_control": True,
            "reference_bpr": round(reference_bpr, 6),
            "faulty_bpr": round(faulty_bpr, 6),
            "bpr_delta": round(bpr_delta, 6),
            "tool_id": "",
            "initial_bpr": round(faulty_bpr, 6),
            "final_bpr": round(faulty_bpr, 6),
            "delta_bpr": 0.0,
            "patch_applied": False,
            "false_repair": False,
            "regression": False,
            "complete_repair": faulty_bpr == 1.0,
            "effective_repair": False,
            "spurious_repair_improvement": False,
            "localization_applicable": False,
            "localization_skipped": case.mutation_operator == NO_FAULT_OPERATOR,
        }
        per_case_rows.append(score_row)

        for task in build_tool_tasks([case], tools):
            result_json = tool_result_path(repair_dir, case.case_id, task.tool.tool_id)
            summary = execute_tool_task(task, output_dir=repair_dir)
            repair_result = None
            if result_json.is_file():
                payload = json.loads(result_json.read_text(encoding="utf-8"))
                if "repair_result" in payload:
                    repair_result = RepairResult.model_validate(payload["repair_result"])

            patch_applied = repair_patch_applied(repair_result)
            false_repair = spurious_repair_improvement(
                complete_repair=summary.complete_repair,
                effective_repair=summary.effective_repair,
                regression=summary.regression,
                patch_applied=patch_applied,
            )
            per_case_rows.append(
                {
                    "case_id": case.case_id,
                    "source_case_id": source_case_id,
                    "mutation_operator": case.mutation_operator,
                    "is_negative_control": True,
                    "reference_bpr": round(reference_bpr, 6),
                    "faulty_bpr": round(faulty_bpr, 6),
                    "bpr_delta": round(bpr_delta, 6),
                    "tool_id": task.tool.tool_id,
                    "initial_bpr": round(summary.initial_bpr, 6),
                    "final_bpr": round(summary.final_bpr, 6),
                    "delta_bpr": round(summary.delta_bpr, 6),
                    "patch_applied": patch_applied,
                    "false_repair": false_repair,
                    "regression": summary.regression,
                    "complete_repair": summary.complete_repair,
                    "effective_repair": summary.effective_repair,
                    "spurious_repair_improvement": false_repair,
                    "localization_applicable": localization_applicable,
                    "localization_skipped": not localization_applicable,
                }
            )

    tool_rows = [row for row in per_case_rows if row["tool_id"]]
    tool_metrics = _aggregate_tool_metrics(tool_rows)
    total_tool_runs = len(tool_rows)
    overall = {
        "case_count": len(cases),
        "tool_run_count": total_tool_runs,
        "false_repair_rate": round(
            sum(1 for row in tool_rows if row["false_repair"]) / total_tool_runs,
            6,
        )
        if total_tool_runs
        else 0.0,
        "regression_rate": round(
            sum(1 for row in tool_rows if row["regression"]) / total_tool_runs,
            6,
        )
        if total_tool_runs
        else 0.0,
        "mean_delta_bpr": round(
            sum(float(row["delta_bpr"]) for row in tool_rows) / total_tool_runs,
            6,
        )
        if total_tool_runs
        else 0.0,
        "tools_modifying_correct_fsms": sum(1 for row in tool_rows if row["patch_applied"]),
        "localization_skipped_cases": localization_skipped,
    }

    summary_path = out / "summary.csv"
    per_case_path = out / "per_case_results.csv"
    report_path = out / "report.md"
    manifest_path = out / "manifest.json"
    tables_dir = out / "tables"

    _write_summary_csv(summary_path, tool_metrics=tool_metrics, overall=overall)
    _write_csv(per_case_path, PER_CASE_COLUMNS, per_case_rows)
    _write_report(
        report_path,
        dataset_dir=data_dir,
        output_dir=out,
        cohort_path=cohort_txt,
        case_count=len(cases),
        tool_metrics=tool_metrics,
        overall=overall,
        localization_skipped=localization_skipped,
    )
    _write_tables(tables_dir, tool_metrics=tool_metrics)

    manifest = {
        "experiment": NEGATIVE_CONTROL_EXPERIMENT,
        "source_dataset": str(source),
        "dataset_dir": str(data_dir),
        "output_dir": str(out),
        "paper_export_dir": str(paper_dir),
        "cohort_path": str(cohort_txt),
        "cohort_sha256": sha256_file(cohort_txt),
        "selection_seed": seed,
        "cohort_size": len(cases),
        "tools_dir": str(tool_dir),
        "tool_ids": [tool.tool_id for tool in tools],
        "overall_metrics": overall,
        "tool_metrics": tool_metrics,
        "replaces_v0_2_analysis": False,
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    _copy_paper_exports(output_dir=out, paper_export_dir=paper_dir)

    return NegativeControlCampaignResult(
        dataset_dir=data_dir,
        output_dir=out,
        paper_export_dir=paper_dir,
        cohort_path=cohort_txt,
        summary_path=summary_path,
        per_case_path=per_case_path,
        report_path=report_path,
        manifest_path=manifest_path,
        tables_dir=tables_dir,
        case_count=len(cases),
    )
