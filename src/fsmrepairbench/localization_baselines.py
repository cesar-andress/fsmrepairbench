"""Baseline localization methods for RQ3 transition-localizable ground-truth subset."""

from __future__ import annotations

import csv
import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.fault_localization import (
    SuspiciousnessMethod,
    _all_fsm_elements,
    collect_scenario_spectra,
    localize_fault,
)
from fsmrepairbench.localization_campaign import (
    CaseLocalizationResult,
    LocalizationCampaignError,
    ranked_transition_ids,
    transition_localization_metrics,
)
from fsmrepairbench.models import BugMetadata
from fsmrepairbench.smoke_test_pipeline import infer_injected_fault_elements
from fsmrepairbench.statistics import (
    ConfidenceIntervalRow,
    bootstrap_mean_ci,
    bootstrap_rate_ci,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

LocalizationBaselineMethod = Literal[
    "ochiai",
    "tarantula",
    "jaccard",
    "random",
    "structural_diff",
]

BASELINE_METHODS: tuple[LocalizationBaselineMethod, ...] = (
    "ochiai",
    "tarantula",
    "jaccard",
    "random",
    "structural_diff",
)

BASELINE_METHOD_LABELS: dict[LocalizationBaselineMethod, str] = {
    "ochiai": "Ochiai",
    "tarantula": "Tarantula",
    "jaccard": "Jaccard",
    "random": "Random",
    "structural_diff": "Structural diff",
}

RANDOM_BASELINE_SEED = 44

BASELINE_COMPARISON_COLUMNS: tuple[str, ...] = (
    "method",
    "partition",
    "n_cases",
    "top1_hit_rate",
    "top3_hit_rate",
    "top5_hit_rate",
    "mrr",
    "top1_ci95_low",
    "top1_ci95_high",
    "top3_ci95_low",
    "top3_ci95_high",
    "top5_ci95_low",
    "top5_ci95_high",
    "mrr_ci95_low",
    "mrr_ci95_high",
)


@dataclass(frozen=True)
class BaselineMethodResult:
    """Aggregate metrics and bootstrap CIs for one localization baseline."""

    method: LocalizationBaselineMethod
    display_name: str
    case_rows: tuple[CaseLocalizationResult, ...]
    metrics: dict[str, float | int]
    confidence_intervals: tuple[ConfidenceIntervalRow, ...]


def _random_case_seed(case_id: str) -> int:
    digest = hashlib.sha256(f"{RANDOM_BASELINE_SEED}:{case_id}".encode()).hexdigest()
    return int(digest[:16], 16)


def _sorted_transition_ids(faulty) -> list[str]:
    return sorted(_all_fsm_elements(faulty)["transition"])


def _rank_transitions_random(transition_ids: list[str], *, case_id: str) -> list[str]:
    ranked = list(transition_ids)
    random.Random(_random_case_seed(case_id)).shuffle(ranked)
    return ranked


def _rank_transitions_structural_diff(reference, faulty) -> list[str]:
    fault_transition_ids = {
        element_id
        for element_type, element_id in infer_injected_fault_elements(reference, faulty)
        if element_type == "transition"
    }
    transition_ids = _sorted_transition_ids(faulty)
    fault_first = [transition_id for transition_id in transition_ids if transition_id in fault_transition_ids]
    remainder = [
        transition_id for transition_id in transition_ids if transition_id not in fault_transition_ids
    ]
    return fault_first + remainder


def _case_has_failing_scenario(faulty, oracle) -> bool:
    spectra = collect_scenario_spectra(faulty, oracle)
    return any(not spectrum.passed for spectrum in spectra)


def _empty_case_result(
    *,
    case_id: str,
    operator: str,
    target: str,
) -> CaseLocalizationResult:
    return CaseLocalizationResult(
        case_id=case_id,
        mutation_operator=operator,
        changed_transition_id=target,
        localized=False,
        transition_count=0,
        rank_of_target=None,
        reciprocal_rank=0.0,
        top1_hit=False,
        top3_hit=False,
        top5_hit=False,
        top_ranked_transition="",
    )


def localize_case_baseline(
    case_dir: Path,
    *,
    method: LocalizationBaselineMethod,
) -> CaseLocalizationResult:
    """Run one transition-level localization baseline on a benchmark case."""
    case_id = case_dir.name
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    metadata_path = case_dir / "bug_metadata.json"
    if faulty_path is None or oracle_path is None or not metadata_path.is_file():
        msg = f"Incomplete case directory: {case_dir}"
        raise LocalizationCampaignError(msg)

    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    metadata = BugMetadata.model_validate(
        json.loads(metadata_path.read_text(encoding="utf-8"))
    )
    target = metadata.changed_transition_id or ""
    operator = metadata.mutation_operator

    if metadata.is_negative_control or metadata.mutation_operator == "no_fault":
        return _empty_case_result(case_id=case_id, operator=operator, target=target)

    if not _case_has_failing_scenario(faulty, oracle):
        return _empty_case_result(case_id=case_id, operator=operator, target=target)

    if method in ("ochiai", "tarantula", "jaccard"):
        spectral_method: SuspiciousnessMethod = method
        try:
            report = localize_fault(faulty, oracle, method=spectral_method)
        except ValueError:
            return _empty_case_result(case_id=case_id, operator=operator, target=target)
        ranked_ids = ranked_transition_ids(report)
    elif method == "random":
        ranked_ids = _rank_transitions_random(_sorted_transition_ids(faulty), case_id=case_id)
    else:
        reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
        if reference_path is None or not reference_path.is_file():
            msg = f"Missing reference FSM for structural diff baseline: {case_dir}"
            raise LocalizationCampaignError(msg)
        reference = load_fsm_json(reference_path)
        ranked_ids = _rank_transitions_structural_diff(reference, faulty)

    rank, reciprocal, top1, top3, top5 = transition_localization_metrics(target, ranked_ids)
    return CaseLocalizationResult(
        case_id=case_id,
        mutation_operator=operator,
        changed_transition_id=target,
        localized=True,
        transition_count=len(ranked_ids),
        rank_of_target=rank,
        reciprocal_rank=reciprocal,
        top1_hit=top1,
        top3_hit=top3,
        top5_hit=top5,
        top_ranked_transition=ranked_ids[0] if ranked_ids else "",
    )


def aggregate_baseline_metrics(rows: list[CaseLocalizationResult]) -> dict[str, float | int]:
    """Compute top-k hit rates and MRR on localized baseline rows."""
    localized_rows = [row for row in rows if row.localized]
    localized = len(localized_rows)

    def _rate(attr: str) -> float:
        if not localized_rows:
            return 0.0
        hits = sum(1 for row in localized_rows if getattr(row, attr))
        return round(hits / localized, 6)

    mrr = round(
        sum(row.reciprocal_rank for row in localized_rows) / localized if localized else 0.0,
        6,
    )
    return {
        "localized_cases": localized,
        "top1_hit_rate": _rate("top1_hit"),
        "top3_hit_rate": _rate("top3_hit"),
        "top5_hit_rate": _rate("top5_hit"),
        "mrr": mrr,
    }


def compute_baseline_confidence_intervals(
    rows: list[CaseLocalizationResult],
    *,
    group: str = "RQ3",
    subgroup: str = "",
) -> list[ConfidenceIntervalRow]:
    """Bootstrap 95% CIs for localization metrics on localized rows."""
    localized = [row for row in rows if row.localized]
    if not localized:
        return []

    return [
        bootstrap_rate_ci(
            [row.top1_hit for row in localized],
            "top_1_hit_rate",
            group=group,
            subgroup=subgroup,
        ),
        bootstrap_rate_ci(
            [row.top3_hit for row in localized],
            "top_3_hit_rate",
            group=group,
            subgroup=subgroup,
        ),
        bootstrap_rate_ci(
            [row.top5_hit for row in localized],
            "top_5_hit_rate",
            group=group,
            subgroup=subgroup,
        ),
        bootstrap_mean_ci(
            [row.reciprocal_rank for row in localized],
            "mrr",
            group=group,
            subgroup=subgroup,
        ),
    ]


def run_localization_baseline_comparison(
    dataset_dir: Path,
    *,
    localizable_case_rows: list[CaseLocalizationResult],
) -> list[BaselineMethodResult]:
    """Evaluate all baseline methods on transition-localizable GT cases."""
    case_ids = {row.case_id for row in localizable_case_rows}
    case_dir_by_id = {case_id: dataset_dir / "cases" / case_id for case_id in case_ids}

    results: list[BaselineMethodResult] = []
    for method in BASELINE_METHODS:
        if method == "ochiai":
            method_rows = list(localizable_case_rows)
        else:
            method_rows = [
                localize_case_baseline(case_dir_by_id[row.case_id], method=method)
                for row in localizable_case_rows
            ]

        metrics = aggregate_baseline_metrics(method_rows)
        cis = compute_baseline_confidence_intervals(
            method_rows,
            group="RQ3",
            subgroup=f"{method}_transition_localizable_gt",
        )
        results.append(
            BaselineMethodResult(
                method=method,
                display_name=BASELINE_METHOD_LABELS[method],
                case_rows=tuple(method_rows),
                metrics=metrics,
                confidence_intervals=tuple(cis),
            )
        )
    return results


def _ci_lookup(cis: tuple[ConfidenceIntervalRow, ...]) -> dict[str, ConfidenceIntervalRow]:
    return {row.metric: row for row in cis}


def _pct_with_ci(rate: float, ci_row: ConfidenceIntervalRow | None) -> str:
    if ci_row is None:
        return f"{100.0 * rate:.2f}\\%"
    return (
        f"{100.0 * rate:.2f}\\% "
        f"[{100.0 * ci_row.ci95_low:.1f}--{100.0 * ci_row.ci95_high:.1f}]"
    )


def _mrr_with_ci(mrr: float, ci_row: ConfidenceIntervalRow | None) -> str:
    if ci_row is None:
        return f"{mrr:.3f}"
    return f"{mrr:.3f} [{ci_row.ci95_low:.3f}--{ci_row.ci95_high:.3f}]"


def write_baseline_comparison_csv(
    path: Path,
    results: list[BaselineMethodResult],
    *,
    partition: str = "transition_localizable_gt",
) -> None:
    """Write baseline comparison metrics with bootstrap CIs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, str | float | int]] = []
    for result in results:
        ci = _ci_lookup(result.confidence_intervals)
        rows.append(
            {
                "method": result.method,
                "partition": partition,
                "n_cases": int(result.metrics["localized_cases"]),
                "top1_hit_rate": float(result.metrics["top1_hit_rate"]),
                "top3_hit_rate": float(result.metrics["top3_hit_rate"]),
                "top5_hit_rate": float(result.metrics["top5_hit_rate"]),
                "mrr": float(result.metrics["mrr"]),
                "top1_ci95_low": ci["top_1_hit_rate"].ci95_low,
                "top1_ci95_high": ci["top_1_hit_rate"].ci95_high,
                "top3_ci95_low": ci["top_3_hit_rate"].ci95_low,
                "top3_ci95_high": ci["top_3_hit_rate"].ci95_high,
                "top5_ci95_low": ci["top_5_hit_rate"].ci95_low,
                "top5_ci95_high": ci["top_5_hit_rate"].ci95_high,
                "mrr_ci95_low": ci["mrr"].ci95_low,
                "mrr_ci95_high": ci["mrr"].ci95_high,
            }
        )

    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(BASELINE_COMPARISON_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)


def write_baseline_comparison_tex(
    path: Path,
    results: list[BaselineMethodResult],
    *,
    n_cases: int,
) -> None:
    """Write LaTeX table comparing localization baselines on localizable GT."""
    lines = [
        "% Auto-generated by localization baseline comparison",
        "\\begin{table}[t]",
        "\\caption{Transition-level localization on transition-localizable ground truth "
        f"($n={n_cases}$ detectable cases with rankable \\texttt{{changed\\_transition\\_id}}; "
        "505 oracle-saturated cases excluded). "
        "Bracketed ranges are bootstrap 95\\% confidence intervals (10{,}000 case resamples; seed~44).}",
        "\\label{tab:localization-baselines-localizable}",
        "\\small",
        "\\begin{tabular}{@{}lrrrrr@{}}",
        "\\toprule",
        "Method & $n$ & Top-1 & Top-3 & Top-5 & MRR \\\\",
        "\\midrule",
    ]
    for result in results:
        ci = _ci_lookup(result.confidence_intervals)
        lines.append(
            f"{result.display_name} & {int(result.metrics['localized_cases'])} & "
            f"{_pct_with_ci(float(result.metrics['top1_hit_rate']), ci.get('top_1_hit_rate'))} & "
            f"{_pct_with_ci(float(result.metrics['top3_hit_rate']), ci.get('top_3_hit_rate'))} & "
            f"{_pct_with_ci(float(result.metrics['top5_hit_rate']), ci.get('top_5_hit_rate'))} & "
            f"{_mrr_with_ci(float(result.metrics['mrr']), ci.get('mrr'))} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")
