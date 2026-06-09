"""Aggregate bootstrap confidence intervals for paper headline metrics."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.statistics import (
    BOOTSTRAP_SEED,
    CONFIDENCE_INTERVAL_CSV_COLUMNS,
    ConfidenceIntervalRow,
    compute_c1_detectable_confidence_intervals,
    compute_c3_confidence_intervals,
    compute_rq2_confidence_intervals,
    compute_rq3_confidence_intervals,
    compute_rq4_confidence_intervals,
    confidence_interval_rows_to_dicts,
    filter_paper_main_ci_rows,
    render_paper_main_ci_tex,
    write_confidence_interval_exports,
)

PAPER_CI_DIR_NAME = "confidence_intervals"
DEFAULT_PAPER_CI_RELATIVE = Path("results") / PAPER_CI_DIR_NAME
DEFAULT_PAPER_EXPORT_RELATIVE = Path("../paper1/results") / PAPER_CI_DIR_NAME


@dataclass(frozen=True)
class PaperConfidenceIntervalPaths:
    """Default frozen per-case inputs for headline CI aggregation."""

    rq2_progress_csv: Path
    analysis_cohort_file: Path
    c1_per_case_csv: Path
    rq3_per_case_csv: Path
    rq4_per_case_csv: Path
    c3_per_case_csv: Path


@dataclass(frozen=True)
class PaperConfidenceIntervalResult:
    """Paths written by :func:`export_paper_confidence_intervals`."""

    output_dir: Path
    csv_path: Path
    json_path: Path
    main_tex_path: Path
    paper_csv_path: Path | None
    paper_main_tex_path: Path | None
    rows: tuple[ConfidenceIntervalRow, ...]
    main_rows: tuple[ConfidenceIntervalRow, ...]


class PaperConfidenceIntervalError(RuntimeError):
    """Raised when paper CI aggregation cannot be completed."""


@dataclass(frozen=True)
class _ProgressCase:
    bpr_delta: float
    faulty_bpr: float


def default_paper_ci_paths(repo_root: Path | None = None) -> PaperConfidenceIntervalPaths:
    """Return default frozen CSV paths relative to the repository root."""
    base = repo_root or Path(__file__).resolve().parents[2]
    dataset_dir = base / "data/fsmrepairbench_1k"
    return PaperConfidenceIntervalPaths(
        rq2_progress_csv=dataset_dir / "progress.csv",
        analysis_cohort_file=dataset_dir / "analysis_cohort_1k.txt",
        c1_per_case_csv=base / "results/baseline_repair_C1/per_case_results.csv",
        rq3_per_case_csv=base / "results/rq3_localization_1k/per_case_results.csv",
        rq4_per_case_csv=base / "results/rq4_coupling_250/per_case_results.csv",
        c3_per_case_csv=base / "results/oracle_depth_ablation/per_case_results.csv",
    )


def load_cohort_case_ids(path: Path) -> set[str]:
    """Load pinned analysis cohort case IDs."""
    if not path.is_file():
        msg = f"Cohort manifest not found: {path}"
        raise PaperConfidenceIntervalError(msg)
    return {
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    }


def load_csv_dict_rows(path: Path) -> list[dict[str, str]]:
    """Load a CSV file into dict rows."""
    if not path.is_file():
        msg = f"CSV input not found: {path}"
        raise PaperConfidenceIntervalError(msg)
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            msg = f"CSV has no header: {path}"
            raise PaperConfidenceIntervalError(msg)
        return list(reader)


def load_progress_cases(
    path: Path,
    *,
    cohort_ids: set[str] | None = None,
) -> list[_ProgressCase]:
    """Load RQ2 per-case metrics from a frozen dataset progress/index CSV."""
    rows = load_csv_dict_rows(path)
    cases: list[_ProgressCase] = []
    for row in rows:
        if row.get("status", "completed") != "completed":
            continue
        case_id = str(row["case_id"])
        if cohort_ids is not None and case_id not in cohort_ids:
            continue
        cases.append(
            _ProgressCase(
                bpr_delta=float(row["bpr_delta"]),
                faulty_bpr=float(row["faulty_bpr"]),
            )
        )
    return cases


def detectable_case_ids_from_progress(
    path: Path,
    *,
    cohort_ids: set[str] | None = None,
) -> set[str]:
    """Return case IDs with oracle-detectable faults from frozen progress CSV."""
    rows = load_csv_dict_rows(path)
    detectable: set[str] = set()
    for row in rows:
        if row.get("status", "completed") != "completed":
            continue
        case_id = str(row["case_id"])
        if cohort_ids is not None and case_id not in cohort_ids:
            continue
        if float(row["bpr_delta"]) > 0.0:
            detectable.add(case_id)
    return detectable


def group_c3_rows_by_depth(rows: list[dict[str, str]]) -> dict[str, list[dict[str, str]]]:
    """Partition C3 per-case rows by oracle depth preset."""
    grouped: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        depth = str(row.get("oracle_depth", "")).strip()
        if not depth:
            continue
        grouped.setdefault(depth, []).append(row)
    return grouped


def collect_paper_confidence_intervals(
    *,
    paths: PaperConfidenceIntervalPaths | None = None,
    repo_root: Path | None = None,
) -> list[ConfidenceIntervalRow]:
    """Compute headline bootstrap CIs from frozen per-case campaign exports."""
    resolved_paths = paths or default_paper_ci_paths(repo_root)
    cohort_ids = load_cohort_case_ids(resolved_paths.analysis_cohort_file)
    rq2_cases = load_progress_cases(
        resolved_paths.rq2_progress_csv,
        cohort_ids=cohort_ids,
    )
    detectable_ids = detectable_case_ids_from_progress(
        resolved_paths.rq2_progress_csv,
        cohort_ids=cohort_ids,
    )
    c1_rows = load_csv_dict_rows(resolved_paths.c1_per_case_csv)
    rq3_rows = load_csv_dict_rows(resolved_paths.rq3_per_case_csv)
    rq4_rows = load_csv_dict_rows(resolved_paths.rq4_per_case_csv)
    c3_rows = load_csv_dict_rows(resolved_paths.c3_per_case_csv)

    rows: list[ConfidenceIntervalRow] = []
    rows.extend(compute_rq2_confidence_intervals(rq2_cases))
    rows.extend(
        compute_c1_detectable_confidence_intervals(
            c1_rows,
            detectable_case_ids=detectable_ids,
        )
    )
    rows.extend(compute_rq3_confidence_intervals(rq3_rows))
    rows.extend(compute_rq4_confidence_intervals(rq4_rows))
    rows.extend(compute_c3_confidence_intervals(group_c3_rows_by_depth(c3_rows)))
    return rows


def export_paper_confidence_intervals(
    output_dir: Path | None = None,
    *,
    paper_export_dir: Path | None = None,
    paths: PaperConfidenceIntervalPaths | None = None,
    repo_root: Path | None = None,
) -> PaperConfidenceIntervalResult:
    """Write consolidated CI CSV/JSON exports and the headline LaTeX table."""
    base = repo_root or Path(__file__).resolve().parents[2]
    out = output_dir or (base / DEFAULT_PAPER_CI_RELATIVE)
    paper_dir = paper_export_dir or (base / DEFAULT_PAPER_EXPORT_RELATIVE)

    rows = collect_paper_confidence_intervals(paths=paths, repo_root=base)
    main_rows = filter_paper_main_ci_rows(rows)

    export_result = write_confidence_interval_exports(
        out,
        campaign="paper-headline-metrics",
        rows=rows,
        paper_export_dir=None,
    )

    paper_dir.mkdir(parents=True, exist_ok=True)
    paper_csv_path = paper_dir / "confidence_intervals.csv"
    paper_csv_path.write_text(export_result.csv_path.read_text(encoding="utf-8"), encoding="utf-8")
    paper_json_path = paper_dir / "confidence_intervals.json"
    paper_json_path.write_text(export_result.json_path.read_text(encoding="utf-8"), encoding="utf-8")

    tables_dir = paper_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)
    main_tex_path = out / "tables" / "table_ci_main_results.tex"
    main_tex_path.parent.mkdir(parents=True, exist_ok=True)
    main_tex_content = render_paper_main_ci_tex(main_rows)
    main_tex_path.write_text(main_tex_content, encoding="utf-8")

    paper_main_tex_path = tables_dir / "table_ci_main_results.tex"
    paper_main_tex_path.write_text(main_tex_content, encoding="utf-8")

    report_path = out / "report.md"
    report_lines = [
        "# Paper headline bootstrap confidence intervals",
        "",
        f"Seed: {BOOTSTRAP_SEED}. Schema: `{', '.join(CONFIDENCE_INTERVAL_CSV_COLUMNS)}`.",
        "",
        f"- Full export: `{export_result.csv_path}`",
        f"- Headline LaTeX table: `{main_tex_path}`",
        f"- Paper copy: `{paper_main_tex_path}`",
        "",
        f"Headline metrics exported: {len(main_rows)} of {len(rows)} total CI rows.",
        "",
    ]
    report_path.write_text("\n".join(report_lines), encoding="utf-8")

    return PaperConfidenceIntervalResult(
        output_dir=out,
        csv_path=export_result.csv_path,
        json_path=export_result.json_path,
        main_tex_path=main_tex_path,
        paper_csv_path=paper_csv_path,
        paper_main_tex_path=paper_main_tex_path,
        rows=tuple(rows),
        main_rows=tuple(main_rows),
    )
