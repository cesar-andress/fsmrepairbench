"""Quantify cohort-wide repair inflation from oracle-saturated C1 cases."""

from __future__ import annotations

import csv
import json
import random
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.statistics import (
    BOOTSTRAP_CI,
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
)

SATURATION_INFLATION_CSV_COLUMNS: tuple[str, ...] = (
    "engine",
    "detectable_only_complete_repair",
    "cohort_wide_complete_repair",
    "saturation_inflation_pp",
    "detectable_only_effective_repair",
    "cohort_wide_effective_repair",
    "saturated_cases",
    "detectable_cases",
    "total_cases",
)

PRIMARY_ENGINES: tuple[str, ...] = (
    "missing-transition",
    "wrong-target",
    "random",
)


@dataclass(frozen=True)
class CaseRepairOutcome:
    case_id: str
    oracle_detected: bool
    complete_repair: bool
    effective_repair: bool


@dataclass(frozen=True)
class SaturationInflationRow:
    engine: str
    detectable_only_complete_repair: float
    cohort_wide_complete_repair: float
    saturation_inflation_pp: float
    detectable_only_effective_repair: float
    cohort_wide_effective_repair: float
    saturated_cases: int
    detectable_cases: int
    total_cases: int
    saturation_inflation_ci95_low_pp: float
    saturation_inflation_ci95_high_pp: float


@dataclass(frozen=True)
class SaturationInflationExportResult:
    csv_path: Path
    tex_path: Path
    figure_path: Path
    manifest_path: Path
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


def _rate(flags: Sequence[bool]) -> float:
    if not flags:
        return 0.0
    return sum(1 for flag in flags if flag) / len(flags)


def _load_case_outcomes(
    per_case_path: Path,
    *,
    tool_id: str,
) -> list[CaseRepairOutcome]:
    outcomes: list[CaseRepairOutcome] = []
    for row in _read_csv(per_case_path):
        if row["tool_id"] != tool_id:
            continue
        outcomes.append(
            CaseRepairOutcome(
                case_id=str(row["case_id"]),
                oracle_detected=str(row["oracle_detected"]).strip().lower() == "true",
                complete_repair=str(row["complete_repair"]).strip().lower() == "true",
                effective_repair=str(row["effective_repair"]).strip().lower() == "true",
            )
        )
    if not outcomes:
        msg = f"No per-case rows for tool_id={tool_id!r} in {per_case_path}"
        raise ValueError(msg)
    return outcomes


def _partition_rates(outcomes: Sequence[CaseRepairOutcome]) -> tuple[float, float, float, float, int, int, int]:
    detectable = [row for row in outcomes if row.oracle_detected]
    saturated_cases = len(outcomes) - len(detectable)
    cohort_complete = _rate([row.complete_repair for row in outcomes])
    detectable_complete = _rate([row.complete_repair for row in detectable])
    cohort_effective = _rate([row.effective_repair for row in outcomes])
    detectable_effective = _rate([row.effective_repair for row in detectable])
    return (
        detectable_complete,
        cohort_complete,
        detectable_effective,
        cohort_effective,
        saturated_cases,
        len(detectable),
        len(outcomes),
    )


def bootstrap_saturation_inflation_pp(
    outcomes: Sequence[CaseRepairOutcome],
    *,
    n_resamples: int = BOOTSTRAP_RESAMPLES,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float, float]:
    """Return point inflation (pp) and bootstrap 95% CI bounds (pp)."""
    detectable_complete, cohort_complete, _, _, _, _, _ = _partition_rates(outcomes)
    point = 100.0 * (cohort_complete - detectable_complete)
    if len(outcomes) <= 1:
        return (point, point, point)

    rng = random.Random(bootstrap_seed)
    boot_inflations: list[float] = []
    sample_size = len(outcomes)
    for _ in range(n_resamples):
        draw = [outcomes[rng.randrange(sample_size)] for _ in range(sample_size)]
        detectable = [row for row in draw if row.oracle_detected]
        cohort_rate = _rate([row.complete_repair for row in draw])
        detectable_rate = _rate([row.complete_repair for row in detectable]) if detectable else 0.0
        boot_inflations.append(100.0 * (cohort_rate - detectable_rate))
    boot_inflations.sort()
    alpha = (1.0 - BOOTSTRAP_CI) / 2.0
    low_index = max(0, int(alpha * n_resamples))
    high_index = min(len(boot_inflations) - 1, int((1.0 - alpha) * n_resamples) - 1)
    return (round(point, 6), round(boot_inflations[low_index], 6), round(boot_inflations[high_index], 6))


def build_saturation_inflation_rows(
    c1_dir: Path,
    *,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> list[SaturationInflationRow]:
    leaderboard_path = c1_dir / "leaderboard.csv"
    per_case_path = c1_dir / "per_case_results.csv"
    rows: list[SaturationInflationRow] = []
    for leader_row in _read_csv(leaderboard_path):
        tool_id = str(leader_row["tool_id"])
        engine = str(leader_row.get("tool_label") or tool_id)
        outcomes = _load_case_outcomes(per_case_path, tool_id=tool_id)
        (
            detectable_complete,
            cohort_complete,
            detectable_effective,
            cohort_effective,
            saturated_cases,
            detectable_cases,
            total_cases,
        ) = _partition_rates(outcomes)
        inflation_pp, ci_low, ci_high = bootstrap_saturation_inflation_pp(
            outcomes,
            bootstrap_seed=bootstrap_seed,
        )
        rows.append(
            SaturationInflationRow(
                engine=engine,
                detectable_only_complete_repair=round(detectable_complete, 6),
                cohort_wide_complete_repair=round(cohort_complete, 6),
                saturation_inflation_pp=inflation_pp,
                detectable_only_effective_repair=round(detectable_effective, 6),
                cohort_wide_effective_repair=round(cohort_effective, 6),
                saturated_cases=saturated_cases,
                detectable_cases=detectable_cases,
                total_cases=total_cases,
                saturation_inflation_ci95_low_pp=ci_low,
                saturation_inflation_ci95_high_pp=ci_high,
            )
        )
    return rows


def saturation_inflation_rows_to_csv_dicts(rows: Sequence[SaturationInflationRow]) -> list[dict[str, Any]]:
    return [
        {
            "engine": row.engine,
            "detectable_only_complete_repair": row.detectable_only_complete_repair,
            "cohort_wide_complete_repair": row.cohort_wide_complete_repair,
            "saturation_inflation_pp": row.saturation_inflation_pp,
            "detectable_only_effective_repair": row.detectable_only_effective_repair,
            "cohort_wide_effective_repair": row.cohort_wide_effective_repair,
            "saturated_cases": row.saturated_cases,
            "detectable_cases": row.detectable_cases,
            "total_cases": row.total_cases,
        }
        for row in rows
    ]


def _tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _write_saturation_inflation_tex(path: Path, rows: Sequence[SaturationInflationRow]) -> None:
    lines = [
        "% Auto-generated from fsmrepairbench.saturation_inflation",
        "\\begin{table}[t]",
        (
            "\\caption{Saturation inflation in cohort-wide complete repair for C1 baseline engines "
            "($n=1{,}000$ \\texttt{plain\\_fsm} shallow-oracle cohort; 505/1{,}000 oracle-saturated). "
            "Inflation is cohort-wide minus detectable-only complete repair (percentage points); "
            "bracketed ranges are case-level bootstrap 95\\% confidence intervals (10{,}000 resamples; seed~44). "
            "Takeaway: the random control shows the largest inflation because it repairs almost nothing on "
            "detectable faults yet reaches the saturation floor cohort-wide.}"
        ),
        "\\label{tab:saturation-inflation}",
        "\\scriptsize",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{@{}lrrrr@{}}",
        "\\toprule",
        "Engine & Detectable-only complete & Cohort-wide complete$^\\dagger$ & "
        "Inflation (pp) & Effective inflation (pp) \\\\",
        "\\midrule",
    ]
    for row in rows:
        effective_inflation = 100.0 * (
            row.cohort_wide_effective_repair - row.detectable_only_effective_repair
        )
        lines.append(
            f"\\texttt{{{_tex_escape(row.engine)}}} & "
            f"{_pct(row.detectable_only_complete_repair)} & "
            f"{_pct(row.cohort_wide_complete_repair)} & "
            f"{row.saturation_inflation_pp:.1f} "
            f"[{row.saturation_inflation_ci95_low_pp:.1f}--{row.saturation_inflation_ci95_high_pp:.1f}] & "
            f"{effective_inflation:.1f} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _pyplot():
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as exc:
        msg = f"Plotting dependencies missing for saturation inflation figure: {exc}"
        raise RuntimeError(msg) from exc
    return plt


def _write_saturation_inflation_figure(path: Path, rows: Sequence[SaturationInflationRow]) -> None:
    plt = _pyplot()
    ordered = sorted(rows, key=lambda row: row.saturation_inflation_pp, reverse=True)
    labels = [row.engine for row in ordered]
    detectable_pct = [100.0 * row.detectable_only_complete_repair for row in ordered]
    cohort_pct = [100.0 * row.cohort_wide_complete_repair for row in ordered]

    figure, axis = plt.subplots(figsize=(9, max(4.0, 0.55 * len(labels) + 1.5)))
    y_positions = list(range(len(labels)))
    for index, (engine, detectable, cohort) in enumerate(zip(labels, detectable_pct, cohort_pct)):
        color = "#C00000" if engine == "random" else "#4472C4"
        alpha = 1.0 if engine in PRIMARY_ENGINES else 0.65
        axis.plot(
            [detectable, cohort],
            [index, index],
            color=color,
            linewidth=2.5 if engine == "random" else 2.0,
            alpha=alpha,
            zorder=1,
        )
        axis.scatter(
            [detectable, cohort],
            [index, index],
            color=color,
            s=70 if engine == "random" else 55,
            zorder=2,
            alpha=alpha,
        )
        if engine == "random":
            axis.annotate(
                f"{detectable:.1f}% → {cohort:.1f}%",
                xy=(cohort, index),
                xytext=(8, 0),
                textcoords="offset points",
                va="center",
                fontsize=9,
                color=color,
            )

    axis.set_yticks(y_positions, labels=labels)
    axis.set_xlabel("Complete repair rate (%)")
    axis.set_title("Detectable-only vs cohort-wide complete repair (C1 engines)")
    axis.set_xlim(-2, 105)
    axis.grid(axis="x", linestyle="--", alpha=0.35)
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=120)
    plt.close(figure)


def write_saturation_inflation_exports(
    c1_dir: Path,
    *,
    out_dir: Path,
    paper_export_dir: Path | None = None,
    bootstrap_seed: int = BOOTSTRAP_SEED,
) -> SaturationInflationExportResult:
    """Build saturation inflation CSV, LaTeX table, and slope chart from frozen C1 exports."""
    rows = build_saturation_inflation_rows(c1_dir, bootstrap_seed=bootstrap_seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = out_dir / "tables"
    figures_dir = out_dir / "figures"
    tables_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "saturation_inflation.csv"
    _write_csv(csv_path, SATURATION_INFLATION_CSV_COLUMNS, saturation_inflation_rows_to_csv_dicts(rows))

    tex_path = tables_dir / "table_saturation_inflation.tex"
    _write_saturation_inflation_tex(tex_path, rows)

    figure_path = figures_dir / "saturation_inflation_slope_chart.png"
    _write_saturation_inflation_figure(figure_path, rows)

    manifest = {
        "release_label": "C1-baseline-repair",
        "source_dir": str(c1_dir),
        "bootstrap": {
            "method": "percentile_case_resample",
            "ci": BOOTSTRAP_CI,
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": bootstrap_seed,
        },
        "rows": [
            {
                **saturation_inflation_rows_to_csv_dicts([row])[0],
                "saturation_inflation_ci95_low_pp": row.saturation_inflation_ci95_low_pp,
                "saturation_inflation_ci95_high_pp": row.saturation_inflation_ci95_high_pp,
            }
            for row in rows
        ],
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_csv_path = paper_tex_path = paper_figure_path = None
    if paper_export_dir is not None:
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        (paper_export_dir / "tables").mkdir(parents=True, exist_ok=True)
        (paper_export_dir / "figures").mkdir(parents=True, exist_ok=True)
        paper_csv_path = paper_export_dir / csv_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_figure_path = paper_export_dir / "figures" / figure_path.name
        paper_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_figure_path.write_bytes(figure_path.read_bytes())
        (paper_export_dir / "manifest.json").write_text(
            manifest_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    return SaturationInflationExportResult(
        csv_path=csv_path,
        tex_path=tex_path,
        figure_path=figure_path,
        manifest_path=manifest_path,
        paper_csv_path=paper_csv_path,
        paper_tex_path=paper_tex_path,
        paper_figure_path=paper_figure_path,
    )
