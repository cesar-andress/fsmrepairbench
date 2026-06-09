"""FSMRepairBench benchmark campaign orchestration."""

from __future__ import annotations

import csv
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.analytics import (
    ANALYSIS_SUMMARY_COLUMNS,
    compute_benchmark_analytics,
    compute_mutation_detection_rates,
    write_distributions_csv,
)
from fsmrepairbench.coverage_optimizer import generate_coverage_report
from fsmrepairbench.dataset_builder import (
    is_stratified_case_complete,
    load_dataset_cases,
    resolve_coupling_case_file,
)
from fsmrepairbench.fault_localization import localize_fault
from fsmrepairbench.higher_order_mutation import (
    analyze_dataset_coupling,
    dataset_coupling_report_to_dict,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.stratified_builder import build_stratified_dataset
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

MUTATION_SUMMARY_COLUMNS: tuple[str, ...] = (
    "case_id",
    "bug_type",
    "mutation_operator",
    "mutation_order",
    "is_higher_order",
    "reference_bpr",
    "faulty_bpr",
    "fault_detected",
)
LOCALIZATION_METHOD = "ochiai"
LOCALIZATION_TOP_K = 5


class BenchmarkCampaignError(RuntimeError):
    """Raised when a benchmark campaign step fails."""


@dataclass(frozen=True)
class BenchmarkCampaignResult:
    """Paths and summary payload from a benchmark campaign run."""

    dataset_dir: Path
    output_dir: Path
    case_count: int
    mutation_summary_path: Path
    coverage_report_path: Path
    coupling_report_path: Path
    summary_json_path: Path
    summary_csv_path: Path
    distributions_csv_path: Path
    benchmark_report_path: Path
    summary: dict[str, Any]


def _discover_stratified_case_dirs(dataset_dir: Path) -> list[Path]:
    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"Dataset cases directory not found: {cases_root}"
        raise BenchmarkCampaignError(msg)
    return [
        case_dir
        for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir())
        if is_stratified_case_complete(case_dir)
    ]


def _load_case_index_rows(dataset_dir: Path) -> dict[str, dict[str, str]]:
    index_path = dataset_dir / "case_index.csv"
    if not index_path.is_file():
        return {}
    with index_path.open(encoding="utf-8", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


def _automata_family(machine_type: str, determinism: str) -> str:
    if machine_type == "plain_fsm":
        return "NFA" if determinism == "nondeterministic" else "DFA"
    mapping = {
        "mealy": "Mealy",
        "moore": "Moore",
        "efsm": "EFSM",
        "timed_fsm": "Timed FSM",
    }
    return mapping.get(machine_type, machine_type)


def write_mutation_summary_csv(dataset_dir: Path, path: Path) -> Path:
    """Write mutation_summary.csv from existing stratified case outputs."""
    case_dirs = _discover_stratified_case_dirs(dataset_dir)
    if not case_dirs:
        msg = f"No complete stratified cases found under {dataset_dir / 'cases'}"
        raise BenchmarkCampaignError(msg)

    index_rows = _load_case_index_rows(dataset_dir)
    rows: list[dict[str, str | int | float | bool]] = []
    for case_dir in case_dirs:
        case_id = case_dir.name
        metadata = BugMetadata.model_validate(
            json.loads((case_dir / "bug_metadata.json").read_text(encoding="utf-8"))
        )
        features = json.loads((case_dir / "case_features.json").read_text(encoding="utf-8"))
        index_row = index_rows.get(case_id, {})
        reference_bpr = float(index_row.get("reference_bpr", "1.0"))
        faulty_bpr = float(index_row.get("faulty_bpr", "0.0"))
        if not index_row:
            reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
            faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
            oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
            if reference_path and faulty_path and oracle_path:
                reference = load_fsm_json(reference_path)
                faulty = load_fsm_json(faulty_path)
                oracle = load_oracle_suite(oracle_path)
                reference_bpr = score_oracle_suite(reference, oracle).bpr
                faulty_bpr = score_oracle_suite(faulty, oracle).bpr

        rows.append(
            {
                "case_id": case_id,
                "bug_type": str(features.get("bug_type", metadata.mutation_operator)),
                "mutation_operator": metadata.mutation_operator,
                "mutation_order": metadata.mutation_order or 1,
                "is_higher_order": bool(metadata.is_higher_order),
                "reference_bpr": round(reference_bpr, 6),
                "faulty_bpr": round(faulty_bpr, 6),
                "fault_detected": int(faulty_bpr < reference_bpr),
            }
        )

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(MUTATION_SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    return path


def _run_behavioural_scoring(dataset_dir: Path) -> dict[str, Any]:
    cases = load_dataset_cases(dataset_dir)
    detected = sum(1 for case in cases if case.bpr_delta > 0.0)
    return {
        "case_count": len(cases),
        "mean_reference_bpr": round(sum(case.reference_bpr for case in cases) / len(cases), 6),
        "mean_faulty_bpr": round(sum(case.faulty_bpr for case in cases) / len(cases), 6),
        "mean_bpr_delta": round(sum(case.bpr_delta for case in cases) / len(cases), 6),
        "fault_detection_rate": round(detected / len(cases), 6),
        "reference_bpr_min": round(min(case.reference_bpr for case in cases), 6),
        "faulty_bpr_min": round(min(case.faulty_bpr for case in cases), 6),
    }


def _run_fault_localization(dataset_dir: Path) -> dict[str, Any]:
    case_dirs = _discover_stratified_case_dirs(dataset_dir)
    localized = 0
    top1_hits = 0
    topk_hits = 0
    skipped = 0

    for case_dir in case_dirs:
        reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
        faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
        oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
        metadata_path = resolve_coupling_case_file(case_dir, "bug_metadata.json")
        if not reference_path or not faulty_path or not oracle_path or not metadata_path:
            skipped += 1
            continue

        faulty = load_fsm_json(faulty_path)
        oracle = load_oracle_suite(oracle_path)
        metadata = BugMetadata.model_validate(
            json.loads(metadata_path.read_text(encoding="utf-8"))
        )
        try:
            report = localize_fault(faulty, oracle, method=LOCALIZATION_METHOD)
        except ValueError:
            skipped += 1
            continue

        localized += 1
        target = metadata.changed_transition_id
        if not target:
            continue
        ranked_ids = [element.element_id for element in report.ranked_elements]
        if ranked_ids and ranked_ids[0] == target:
            top1_hits += 1
        if target in ranked_ids[:LOCALIZATION_TOP_K]:
            topk_hits += 1

    return {
        "method": LOCALIZATION_METHOD,
        "top_k": LOCALIZATION_TOP_K,
        "localized_cases": localized,
        "skipped_cases": skipped,
        "top1_hit_rate": round(top1_hits / localized, 6) if localized else 0.0,
        "topk_hit_rate": round(topk_hits / localized, 6) if localized else 0.0,
    }


def _family_distribution(dataset_dir: Path) -> dict[str, int]:
    plan_path = dataset_dir / "dataset_plan.json"
    index_path = dataset_dir / "case_index.csv"
    if plan_path.is_file() and index_path.is_file():
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        cells = plan["cells"]
        counts: Counter[str] = Counter()
        with index_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                cell = cells[int(row["cell_index"])]
                counts[_automata_family(str(cell["machine_type"]), str(cell["determinism"]))] += 1
        return dict(sorted(counts.items()))

    matrix_path = dataset_dir / "feature_matrix.csv"
    if not matrix_path.is_file():
        return {}
    counts = Counter(
        _automata_family(row["machine_type"], row["determinism"])
        for row in csv.DictReader(matrix_path.open(encoding="utf-8", newline=""))
    )
    return dict(sorted(counts.items()))


def _planned_determinism_distribution(dataset_dir: Path) -> dict[str, int]:
    plan_path = dataset_dir / "dataset_plan.json"
    index_path = dataset_dir / "case_index.csv"
    if not plan_path.is_file() or not index_path.is_file():
        return {}
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    cells = plan["cells"]
    counts: Counter[str] = Counter()
    with index_path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            counts[str(cells[int(row["cell_index"])]["determinism"])] += 1
    return dict(sorted(counts.items()))


def _write_summary_csv(path: Path, summary: dict[str, Any]) -> None:
    rows: list[dict[str, str | float | int]] = []

    def flatten(prefix: str, payload: dict[str, Any]) -> None:
        for key, value in payload.items():
            metric = f"{prefix}.{key}" if prefix else key
            if isinstance(value, dict):
                flatten(metric, value)
            else:
                rows.append({"metric": metric, "value": value})

    flatten("", {key: value for key, value in summary.items() if key != "coverage_analysis"})
    rows.append({"metric": "coverage_analysis.case_count", "value": summary["coverage_analysis"]["case_count"]})
    rows.append(
        {
            "metric": "coverage_analysis.missing_combinations.missing_count",
            "value": summary["coverage_analysis"]["missing_combinations"]["missing_count"],
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(ANALYSIS_SUMMARY_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def _write_benchmark_report_markdown(
    path: Path,
    *,
    dataset_dir: Path,
    summary: dict[str, Any],
) -> None:
    families = summary.get("automata_families", {})
    scoring = summary.get("behavioural_scoring", {})
    localization = summary.get("fault_localization", {})
    coupling = summary.get("coupling_analysis", {})
    coverage = summary.get("coverage_analysis", {})
    generated_at = summary.get("generated_at", "")

    lines = [
        "# FSMRepairBench v0.2.0 Benchmark Campaign Report",
        "",
        f"**Dataset:** `{dataset_dir}`  ",
        f"**Generated:** {generated_at}  ",
        f"**Cases:** {summary.get('case_count', 0)}",
        "",
        "## Campaign Overview",
        "",
        (
            "This campaign builds a taxonomy-balanced stratified benchmark and runs "
            "existing FSMRepairBench analyses: feature-space coverage, behavioural "
            "scoring (BPR), spectrum-based fault localization, and mutation coupling."
        ),
        "",
        "## Automata Family Coverage",
        "",
        "| Family | Cases | Share |",
        "|---|---:|---:|",
    ]
    total = summary.get("case_count", 1)
    for family, count in families.items():
        lines.append(f"| {family} | {count} | {count / total:.2%} |")

    lines.extend(
        [
            "",
            "## Behavioural Scoring",
            "",
            f"- Mean reference BPR: **{scoring.get('mean_reference_bpr', 0.0):.4f}**",
            f"- Mean faulty BPR: **{scoring.get('mean_faulty_bpr', 0.0):.4f}**",
            f"- Mean BPR delta: **{scoring.get('mean_bpr_delta', 0.0):.4f}**",
            f"- Fault detection rate: **{scoring.get('fault_detection_rate', 0.0):.2%}**",
            "",
            "## Fault Localization",
            "",
            f"- Method: `{localization.get('method', LOCALIZATION_METHOD)}`",
            f"- Localized cases: **{localization.get('localized_cases', 0)}**",
            f"- Top-1 transition hit rate: **{localization.get('top1_hit_rate', 0.0):.2%}**",
            f"- Top-{LOCALIZATION_TOP_K} transition hit rate: **{localization.get('topk_hit_rate', 0.0):.2%}**",
            "",
            "## Coupling Analysis",
            "",
            f"- First-order detection rate: **{coupling.get('first_order_detection_rate', 0.0):.2%}**",
            f"- Higher-order detection rate: **{coupling.get('higher_order_detection_rate', 0.0):.2%}**",
            f"- Coupling effect estimate: **{coupling.get('coupling_effect_estimate', 0.0):.2%}**",
            "",
            "## Feature-Space Coverage",
            "",
            f"- Unique taxonomy combinations: **{coverage.get('unique_feature_combinations', {}).get('unique_count', 0)}**",
            f"- Missing core combinations: **{coverage.get('missing_combinations', {}).get('missing_count', 0)}**",
            "",
            "## Artifacts",
            "",
            "- `summary.json` / `summary.csv` — campaign aggregates",
            "- `distributions.csv` — bucketed taxonomy and BPR distributions",
            "- `mutation_summary.csv` — per-case mutation and detection table (dataset root)",
            "- `coverage_report.json` — feature-space coverage analysis (dataset root)",
            "- `coupling_report.json` — coupling-effect report (campaign directory)",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_benchmark_campaign(
    plan_path: Path,
    dataset_dir: Path,
    *,
    output_dir: Path,
    skip_build: bool = False,
    coverage_suggestion_count: int = 200,
) -> BenchmarkCampaignResult:
    """Build a stratified dataset and execute the v0.2 campaign analyses."""
    if not skip_build:
        build_stratified_dataset(plan_path, dataset_dir)

    case_dirs = _discover_stratified_case_dirs(dataset_dir)
    if not case_dirs:
        msg = f"No complete stratified benchmark cases found under {dataset_dir}"
        raise BenchmarkCampaignError(msg)

    mutation_summary_path = dataset_dir / "mutation_summary.csv"
    write_mutation_summary_csv(dataset_dir, mutation_summary_path)

    coverage_result = generate_coverage_report(
        dataset_dir,
        suggestion_count=coverage_suggestion_count,
    )
    behavioural = _run_behavioural_scoring(dataset_dir)
    localization = _run_fault_localization(dataset_dir)
    coupling_report = analyze_dataset_coupling(dataset_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    coupling_report_path = output_dir / "coupling_report.json"
    coupling_report_path.write_text(
        json.dumps(dataset_coupling_report_to_dict(coupling_report), indent=2) + "\n",
        encoding="utf-8",
    )

    cases = load_dataset_cases(dataset_dir)
    analytics = compute_benchmark_analytics(cases)
    families = _family_distribution(dataset_dir)
    detection_rates = compute_mutation_detection_rates(cases)

    summary: dict[str, Any] = {
        "campaign": "fsmrepairbench_v0_2",
        "plan_path": str(plan_path),
        "dataset_dir": str(dataset_dir),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "case_count": len(case_dirs),
        "automata_families": families,
        "determinism_distribution": _planned_determinism_distribution(dataset_dir),
        "behavioural_scoring": behavioural,
        "fault_localization": localization,
        "coupling_analysis": {
            "first_order_case_count": coupling_report.first_order_case_count,
            "higher_order_case_count": coupling_report.higher_order_case_count,
            "first_order_detection_rate": coupling_report.first_order_detection_rate,
            "higher_order_detection_rate": coupling_report.higher_order_detection_rate,
            "coupling_effect_estimate": coupling_report.coupling_effect_estimate,
        },
        "coverage_analysis": coverage_result.report,
        "mutation_detection_rates": detection_rates,
    }

    summary_json_path = output_dir / "summary.json"
    summary_json_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    summary_csv_path = output_dir / "summary.csv"
    _write_summary_csv(summary_csv_path, summary)

    distributions_csv_path = output_dir / "distributions.csv"
    write_distributions_csv(
        distributions_csv_path,
        cases=cases,
        analytics=analytics,
        dataset_dir=dataset_dir,
    )

    benchmark_report_path = output_dir / "benchmark_report.md"
    _write_benchmark_report_markdown(
        benchmark_report_path,
        dataset_dir=dataset_dir,
        summary=summary,
    )

    return BenchmarkCampaignResult(
        dataset_dir=dataset_dir,
        output_dir=output_dir,
        case_count=len(case_dirs),
        mutation_summary_path=mutation_summary_path,
        coverage_report_path=coverage_result.report_path,
        coupling_report_path=coupling_report_path,
        summary_json_path=summary_json_path,
        summary_csv_path=summary_csv_path,
        distributions_csv_path=distributions_csv_path,
        benchmark_report_path=benchmark_report_path,
        summary=summary,
    )
