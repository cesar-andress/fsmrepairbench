"""Spectral-resolution analysis for shallow-oracle transition localization (RQ3)."""

from __future__ import annotations

import csv
import json
import statistics
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scipy.stats import kendalltau, spearmanr

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.fault_localization import (
    ScenarioSpectrum,
    SuspiciousnessMethod,
    collect_scenario_spectra,
    rank_suspicious_elements,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

ExecutionProfile = tuple[int, int]

LOCALIZATION_METHOD: SuspiciousnessMethod = "ochiai"

LOCALIZATION_RESOLUTION_COLUMNS: tuple[str, ...] = (
    "case_id",
    "operator",
    "spectral_resolution",
    "top1_hit",
    "top5_hit",
    "reciprocal_rank",
    "tie_group_size",
    "executed_transition_count",
)

QUARTILE_SUMMARY_COLUMNS: tuple[str, ...] = (
    "quartile",
    "n_cases",
    "spectral_resolution_min",
    "spectral_resolution_max",
    "top1_rate",
    "top5_rate",
    "mrr",
)


@dataclass(frozen=True)
class TransitionExecutionProfile:
    transition_id: str
    failed_cover_count: int
    passed_cover_count: int

    @property
    def profile(self) -> ExecutionProfile:
        return (self.failed_cover_count, self.passed_cover_count)


@dataclass(frozen=True)
class CaseResolutionRow:
    case_id: str
    operator: str
    spectral_resolution: float
    top1_hit: bool
    top5_hit: bool
    reciprocal_rank: float
    tie_group_size: int
    executed_transition_count: int

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "operator": self.operator,
            "spectral_resolution": round(self.spectral_resolution, 6),
            "top1_hit": self.top1_hit,
            "top5_hit": self.top5_hit,
            "reciprocal_rank": round(self.reciprocal_rank, 6),
            "tie_group_size": self.tie_group_size,
            "executed_transition_count": self.executed_transition_count,
        }


@dataclass(frozen=True)
class QuartileSummaryRow:
    quartile: str
    n_cases: int
    spectral_resolution_min: float
    spectral_resolution_max: float
    top1_rate: float
    top5_rate: float
    mrr: float

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "quartile": self.quartile,
            "n_cases": self.n_cases,
            "spectral_resolution_min": round(self.spectral_resolution_min, 6),
            "spectral_resolution_max": round(self.spectral_resolution_max, 6),
            "top1_rate": round(self.top1_rate, 6),
            "top5_rate": round(self.top5_rate, 6),
            "mrr": round(self.mrr, 6),
        }


@dataclass(frozen=True)
class ResolutionCorrelationSummary:
    n_cases: int
    spearman_rho: float
    spearman_pvalue: float
    kendall_tau: float
    kendall_pvalue: float


@dataclass(frozen=True)
class LocalizationResolutionExportResult:
    csv_path: Path
    quartile_csv_path: Path
    tex_path: Path
    figure_path: Path
    manifest_path: Path
    correlation: ResolutionCorrelationSummary
    paper_csv_path: Path | None = None
    paper_tex_path: Path | None = None
    paper_figure_path: Path | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        msg = f"Missing CSV: {path}"
        raise FileNotFoundError(msg)
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row[column] for column in columns})


def transition_execution_profile(
    transition_id: str,
    spectra: Sequence[ScenarioSpectrum],
) -> TransitionExecutionProfile:
    """Summarise pass/fail participation as failing- and passing-scenario cover counts."""
    failed_cover = sum(
        1
        for spectrum in spectra
        if not spectrum.passed and transition_id in spectrum.covered_transitions
    )
    passed_cover = sum(
        1
        for spectrum in spectra
        if spectrum.passed and transition_id in spectrum.covered_transitions
    )
    return TransitionExecutionProfile(
        transition_id=transition_id,
        failed_cover_count=failed_cover,
        passed_cover_count=passed_cover,
    )


def executed_transition_ids(spectra: Sequence[ScenarioSpectrum]) -> set[str]:
    executed: set[str] = set()
    for spectrum in spectra:
        executed.update(spectrum.covered_transitions)
    return executed


def compute_spectral_resolution(spectra: Sequence[ScenarioSpectrum]) -> tuple[float, int]:
    """Return (spectral_resolution, executed_transition_count).

    An execution profile is the pass/fail participation signature
    ``(failed_cover_count, passed_cover_count)`` of a transition across all scenarios.
    """
    executed = executed_transition_ids(spectra)
    if not executed:
        return 0.0, 0
    profiles = {
        transition_execution_profile(transition_id, spectra).profile
        for transition_id in executed
    }
    return len(profiles) / len(executed), len(executed)


def transition_tie_group_size(
    fsm,
    spectra: Sequence[ScenarioSpectrum],
    *,
    method: SuspiciousnessMethod = LOCALIZATION_METHOD,
) -> int:
    ranked = rank_suspicious_elements(fsm, spectra, method=method)
    transition_scores = [
        element.suspiciousness
        for element in ranked
        if element.element_type == "transition"
    ]
    if not transition_scores:
        return 0
    top_score = max(transition_scores)
    return sum(1 for score in transition_scores if score == top_score)


def _bool_from_csv(value: str) -> bool:
    return str(value).strip().lower() == "true"


def _float_from_csv(value: str) -> float:
    text = str(value).strip()
    if not text:
        return 0.0
    return float(text)


def load_localizable_audit_rows(audit_path: Path) -> list[dict[str, str]]:
    """Return the 376-case RQ3 primary partition (localized + transition-localizable GT)."""
    rows = [
        row
        for row in _read_csv(audit_path)
        if _bool_from_csv(row.get("ground_truth_localizable", ""))
        and _bool_from_csv(row.get("localized", ""))
    ]
    if not rows:
        msg = f"No localized transition-localizable rows in {audit_path}"
        raise ValueError(msg)
    return rows


def compute_case_resolution_row(
    case_dir: Path,
    audit_row: dict[str, str],
    *,
    method: SuspiciousnessMethod = LOCALIZATION_METHOD,
) -> CaseResolutionRow | None:
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if faulty_path is None or oracle_path is None:
        return None

    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    try:
        spectra = collect_scenario_spectra(faulty, oracle)
        failed_count = sum(1 for spectrum in spectra if not spectrum.passed)
        if failed_count == 0:
            return None
        spectral_resolution, executed_count = compute_spectral_resolution(spectra)
        tie_group_size = transition_tie_group_size(faulty, spectra, method=method)
    except ValueError:
        return None

    return CaseResolutionRow(
        case_id=audit_row["case_id"],
        operator=audit_row["mutation_operator"],
        spectral_resolution=spectral_resolution,
        top1_hit=_bool_from_csv(audit_row["top1_hit"]),
        top5_hit=_bool_from_csv(audit_row["top5_hit"]),
        reciprocal_rank=_float_from_csv(audit_row["reciprocal_rank"]),
        tie_group_size=tie_group_size,
        executed_transition_count=executed_count,
    )


def build_case_resolution_rows(
    dataset_dir: Path,
    audit_path: Path,
    *,
    method: SuspiciousnessMethod = LOCALIZATION_METHOD,
) -> list[CaseResolutionRow]:
    audit_rows = load_localizable_audit_rows(audit_path)
    rows: list[CaseResolutionRow] = []
    for audit_row in audit_rows:
        case_dir = dataset_dir / "cases" / audit_row["case_id"]
        case_row = compute_case_resolution_row(case_dir, audit_row, method=method)
        if case_row is not None:
            rows.append(case_row)
    if not rows:
        msg = "No transition-localizable resolution rows could be computed"
        raise ValueError(msg)
    return rows


def compute_resolution_correlations(
    rows: Sequence[CaseResolutionRow],
) -> ResolutionCorrelationSummary:
    resolutions = [row.spectral_resolution for row in rows]
    reciprocal_ranks = [row.reciprocal_rank for row in rows]
    spearman = spearmanr(resolutions, reciprocal_ranks)
    kendall = kendalltau(resolutions, reciprocal_ranks)
    return ResolutionCorrelationSummary(
        n_cases=len(rows),
        spearman_rho=float(spearman.statistic),
        spearman_pvalue=float(spearman.pvalue),
        kendall_tau=float(kendall.statistic),
        kendall_pvalue=float(kendall.pvalue),
    )


def _equal_quartile_buckets(rows: Sequence[CaseResolutionRow]) -> list[list[CaseResolutionRow]]:
    if len(rows) < 4:
        msg = "At least four cases are required for quartile stratification"
        raise ValueError(msg)
    ordered = sorted(rows, key=lambda row: row.spectral_resolution)
    n = len(ordered)
    base_size = n // 4
    remainder = n % 4
    buckets: list[list[CaseResolutionRow]] = []
    start = 0
    for index in range(4):
        size = base_size + (1 if index < remainder else 0)
        buckets.append(ordered[start : start + size])
        start += size
    return buckets


def build_quartile_summary_rows(rows: Sequence[CaseResolutionRow]) -> list[QuartileSummaryRow]:
    labels = ("Q1 (lowest)", "Q2", "Q3", "Q4 (highest)")
    summaries: list[QuartileSummaryRow] = []
    for label, bucket in zip(labels, _equal_quartile_buckets(list(rows)), strict=True):
        resolutions = [item.spectral_resolution for item in bucket]
        summaries.append(
            QuartileSummaryRow(
                quartile=label,
                n_cases=len(bucket),
                spectral_resolution_min=min(resolutions),
                spectral_resolution_max=max(resolutions),
                top1_rate=sum(1 for item in bucket if item.top1_hit) / len(bucket),
                top5_rate=sum(1 for item in bucket if item.top5_hit) / len(bucket),
                mrr=statistics.mean(item.reciprocal_rank for item in bucket),
            )
        )
    return summaries


def _write_localization_resolution_tex(
    path: Path,
    quartiles: Sequence[QuartileSummaryRow],
    correlation: ResolutionCorrelationSummary,
) -> None:
    lines = [
        "% Auto-generated from fsmrepairbench.localization_resolution",
        "\\begin{table}[htbp]",
        "  \\centering",
        "  \\caption{Localization performance stratified by shallow-oracle spectral resolution "
        f"($n={correlation.n_cases}$ transition-localizable cases). "
        f"Spearman $\\rho={correlation.spearman_rho:.3f}$ "
        f"($p={correlation.spearman_pvalue:.3g}$); "
        f"Kendall $\\tau={correlation.kendall_tau:.3f}$ "
        f"($p={correlation.kendall_pvalue:.3g}$) between spectral resolution and reciprocal rank."
        "}",
        "  \\label{tab:localization-resolution}",
        "  \\begin{tabular}{lrrrrr}",
        "    \\toprule",
        "    Quartile & $n$ & Resolution range & Top-1 & Top-5 & MRR \\\\",
        "    \\midrule",
    ]
    for row in quartiles:
        resolution_range = (
            f"[{row.spectral_resolution_min:.3f}, {row.spectral_resolution_max:.3f}]"
        )
        lines.append(
            f"    {row.quartile} & {row.n_cases} & {resolution_range} & "
            f"{100.0 * row.top1_rate:.1f}\\% & {100.0 * row.top5_rate:.1f}\\% & "
            f"{row.mrr:.3f} \\\\"
        )
    lines.extend(
        [
            "    \\bottomrule",
            "  \\end{tabular}",
            "\\end{table}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_resolution_vs_mrr_figure(
    path: Path,
    rows: Sequence[CaseResolutionRow],
    correlation: ResolutionCorrelationSummary,
) -> None:
    import matplotlib.pyplot as plt

    x_values = [row.spectral_resolution for row in rows]
    y_values = [row.reciprocal_rank for row in rows]

    plt.rcParams.update(
        {
            "font.size": 10,
            "axes.labelsize": 10,
            "xtick.labelsize": 9,
            "ytick.labelsize": 9,
            "savefig.dpi": 200,
        }
    )
    figure, axis = plt.subplots(figsize=(6.8, 4.5))
    axis.scatter(
        x_values,
        y_values,
        alpha=0.55,
        s=28,
        color="#4472C4",
        edgecolors="white",
        linewidths=0.4,
    )
    if len(x_values) >= 2:
        mean_x = statistics.mean(x_values)
        mean_y = statistics.mean(y_values)
        numerator = sum(
            (x - mean_x) * (y - mean_y) for x, y in zip(x_values, y_values, strict=True)
        )
        denominator = sum((x - mean_x) ** 2 for x in x_values)
        if denominator > 0.0:
            slope = numerator / denominator
            intercept = mean_y - slope * mean_x
            x_line = [min(x_values), max(x_values)]
            y_line = [slope * x + intercept for x in x_line]
            axis.plot(x_line, y_line, color="#333333", linewidth=1.2, linestyle="--")

    axis.set_xlabel("Spectral resolution (distinct profiles / executed transitions)")
    axis.set_ylabel("Reciprocal rank (MRR contribution)")
    axis.set_xlim(0.0, 1.05)
    axis.set_ylim(-0.02, 1.05)
    axis.grid(True, alpha=0.25)
    axis.text(
        0.03,
        0.97,
        f"Spearman rho={correlation.spearman_rho:.3f}\nn={len(rows)}",
        transform=axis.transAxes,
        ha="left",
        va="top",
        fontsize=9,
        bbox={"boxstyle": "round,pad=0.25", "facecolor": "white", "edgecolor": "#CCCCCC", "alpha": 0.9},
    )
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=200, bbox_inches="tight")
    figure.savefig(path.with_suffix(".pdf"), bbox_inches="tight")
    plt.close(figure)


def write_localization_resolution_exports(
    dataset_dir: Path,
    rq3_dir: Path,
    *,
    out_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    method: SuspiciousnessMethod = LOCALIZATION_METHOD,
) -> LocalizationResolutionExportResult:
    """Write spectral-resolution CSV, quartile table, figure, and manifest."""
    audit_path = rq3_dir / "localizability_audit.csv"
    export_root = out_dir or rq3_dir
    figures_dir = export_root / "figures"
    tables_dir = export_root / "tables"

    rows = build_case_resolution_rows(dataset_dir, audit_path, method=method)
    correlation = compute_resolution_correlations(rows)
    quartiles = build_quartile_summary_rows(rows)

    csv_path = export_root / "localization_resolution.csv"
    _write_csv(csv_path, LOCALIZATION_RESOLUTION_COLUMNS, [row.to_csv_dict() for row in rows])

    quartile_csv_path = export_root / "localization_resolution_quartiles.csv"
    _write_csv(
        quartile_csv_path,
        QUARTILE_SUMMARY_COLUMNS,
        [row.to_csv_dict() for row in quartiles],
    )

    tex_path = tables_dir / "table_localization_resolution.tex"
    _write_localization_resolution_tex(tex_path, quartiles, correlation)

    figure_path = figures_dir / "figure_resolution_vs_mrr.png"
    _write_resolution_vs_mrr_figure(figure_path, rows, correlation)

    manifest = {
        "release_label": "RQ3-localization-ochiai-1k",
        "dataset_dir": str(dataset_dir),
        "source_audit": str(audit_path),
        "partition": "localized_transition_localizable_gt",
        "method": method,
        "n_cases": len(rows),
        "correlation": {
            "spearman_rho": round(correlation.spearman_rho, 6),
            "spearman_pvalue": round(correlation.spearman_pvalue, 6),
            "kendall_tau": round(correlation.kendall_tau, 6),
            "kendall_pvalue": round(correlation.kendall_pvalue, 6),
        },
        "quartiles": [row.to_csv_dict() for row in quartiles],
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest_path = export_root / "localization_resolution_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_csv_path = paper_tex_path = paper_figure_path = None
    if paper_export_dir is not None:
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        (paper_export_dir / "figures").mkdir(parents=True, exist_ok=True)
        (paper_export_dir / "tables").mkdir(parents=True, exist_ok=True)
        paper_csv_path = paper_export_dir / csv_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_figure_path = paper_export_dir / "figures" / figure_path.name
        paper_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
        (paper_export_dir / quartile_csv_path.name).write_text(
            quartile_csv_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_figure_path.write_bytes(figure_path.read_bytes())
        (paper_export_dir / manifest_path.name).write_text(
            manifest_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    return LocalizationResolutionExportResult(
        csv_path=csv_path,
        quartile_csv_path=quartile_csv_path,
        tex_path=tex_path,
        figure_path=figure_path,
        manifest_path=manifest_path,
        correlation=correlation,
        paper_csv_path=paper_csv_path,
        paper_tex_path=paper_tex_path,
        paper_figure_path=paper_figure_path,
    )
