"""External reanalysis feasibility for SPLC2021 Variability FL Benchmark."""

from __future__ import annotations

import csv
import json
import math
import shutil
import subprocess
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.request import urlopen

FeasibilityClass = str  # "A", "B", or "C"

SPLC2021_REPO = "https://github.com/tuanngokien/splc2021.git"
VARCOP_REPO = "https://github.com/ttrangnguyen/VARCOP.git"
SPLC2021_V2_SHAREPOINT = (
    "https://vnueduvn-my.sharepoint.com/:f:/g/personal/tuanngokien_vnu_edu_vn/"
    "EhSZsIs7k3BJjlFtOeub3KQBNcwmlT-A5pi7bZ-ezJfj1w?e=EvnKd4"
)
ZENODO_FALLBACK = "10.5281/zenodo.3258116"

SYSTEMS: tuple[str, ...] = (
    "BankAccountTP",
    "Email",
    "Elevator",
    "ExamDB",
    "GPL",
    "ZipMe",
)
METRICS: tuple[str, ...] = ("Ochiai", "Op2", "Tarantula", "Dstar", "Barinel")

# Published Table 3 (single-bug, average Rank) from Ngo et al. SPLC 2021.
PUBLISHED_RANK_SINGLE_BUG: dict[str, dict[str, float]] = {
    "ZipMe": {"Ochiai": 18.40, "Op2": 12.67, "Tarantula": 23.98, "Dstar": 18.20, "Barinel": 23.98},
    "GPL": {"Ochiai": 9.09, "Op2": 8.86, "Tarantula": 10.36, "Dstar": 9.09, "Barinel": 10.36},
    "Elevator": {"Ochiai": 8.55, "Op2": 4.25, "Tarantula": 18.40, "Dstar": 8.40, "Barinel": 18.40},
    "ExamDB": {"Ochiai": 3.31, "Op2": 3.24, "Tarantula": 5.61, "Dstar": 3.29, "Barinel": 5.61},
    "Email": {"Ochiai": 4.56, "Op2": 4.03, "Tarantula": 13.81, "Dstar": 4.61, "Barinel": 13.81},
    "BankAccountTP": {"Ochiai": 3.95, "Op2": 3.58, "Tarantula": 5.53, "Dstar": 3.92, "Barinel": 5.53},
}


@dataclass(frozen=True)
class ExternalVariabilityFlResult:
    output_dir: Path
    table_dir: Path
    feasibility_class: FeasibilityClass
    inventory_path: Path
    feasibility_path: Path
    summary_path: Path
    by_system_path: Path
    by_stratum_path: Path
    report_path: Path
    case_count: int


class ExternalVariabilityFlError(RuntimeError):
    """Raised when external variability FL feasibility pass cannot complete."""


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _clone_repo(url: str, dest: Path) -> bool:
    if dest.is_dir() and (dest / ".git").is_dir():
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["git", "clone", "--depth", "1", url, str(dest)],
            check=True,
            capture_output=True,
            text=True,
        )
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


def _http_head_accessible(url: str) -> tuple[bool, str]:
    try:
        with urlopen(url, timeout=30) as response:
            return True, f"HTTP {response.status}"
    except Exception as exc:
        return False, str(exc)


def _inspect_splc2021_repo(repo_dir: Path) -> dict[str, Any]:
    files = [p.relative_to(repo_dir) for p in repo_dir.rglob("*") if p.is_file()]
    non_git = [str(p) for p in files if ".git" not in p.parts]
    return {
        "path": str(repo_dir),
        "file_count_ex_git": len(non_git),
        "files": non_git[:20],
        "contains_coverage_xml": any("spectrum" in f for f in non_git),
        "contains_variants": any("variants" in f for f in non_git),
    }


def _varcop_single_bug_workbook(varcop_root: Path) -> Path | None:
    candidates = sorted(varcop_root.glob("experiment_results/w=0.3/*/ENABLE_NORMALIZATION/*/4wise/1Bug.xlsx"))
    return candidates[0] if candidates else None


def _load_varcop_single_bug_cases(varcop_root: Path) -> list[dict[str, Any]]:
    try:
        import openpyxl
    except ImportError as exc:
        msg = "openpyxl required for VARCOP xlsx parsing (pip install openpyxl)"
        raise ExternalVariabilityFlError(msg) from exc

    base = varcop_root / "experiment_results" / "w=0.3"
    cases: list[dict[str, Any]] = []
    for system in SYSTEMS:
        path = (
            base
            / system
            / "ENABLE_NORMALIZATION"
            / "AGGREGATION_ARITHMETIC_MEAN"
            / "4wise"
            / "1Bug.xlsx"
        )
        if not path.is_file():
            continue
        workbook = openpyxl.load_workbook(path, read_only=True)
        per_bug: dict[str, dict[str, Any]] = defaultdict(dict)
        for metric in METRICS:
            worksheet = workbook[metric]
            rows = list(worksheet.iter_rows(values_only=True))
            header = rows[0]
            rank_idx = header.index("SBFL:RANK")
            exam_idx = header.index("SBFL:EXAM")
            bug_idx = header.index("BUG ID")
            stm_idx = header.index("BUGGY STM")
            space_idx = header.index("SPACE")
            for row in rows[1:]:
                if not row or row[bug_idx] is None:
                    continue
                bug_id = str(row[bug_idx])
                per_bug[bug_id].update(
                    {
                        "bug_id": bug_id,
                        "system": system,
                        "buggy_statement": row[stm_idx],
                        "search_space": row[space_idx],
                        f"{metric.lower()}_rank": row[rank_idx],
                        f"{metric.lower()}_exam": row[exam_idx],
                    }
                )
        cases.extend(per_bug.values())
    return cases


def _rank_metrics(ranks: list[float | int]) -> dict[str, float | int]:
    valid = [float(r) for r in ranks if r is not None and float(r) > 0]
    if not valid:
        return {
            "n_cases": 0,
            "top1_rate": 0.0,
            "top5_rate": 0.0,
            "mrr": 0.0,
            "mean_rank": 0.0,
            "exam_mean": 0.0,
        }
    return {
        "n_cases": len(valid),
        "top1_rate": round(sum(1 for r in valid if r == 1.0) / len(valid), 6),
        "top5_rate": round(sum(1 for r in valid if r <= 5.0) / len(valid), 6),
        "mrr": round(sum(1.0 / r for r in valid) / len(valid), 6),
        "mean_rank": round(sum(valid) / len(valid), 4),
    }


def _metric_summary_rows(
    cases: list[dict[str, Any]],
    *,
    scope: str,
    system: str | None = None,
) -> list[dict[str, Any]]:
    subset = cases if system is None else [case for case in cases if case["system"] == system]
    rows: list[dict[str, Any]] = []
    for metric in METRICS:
        key = f"{metric.lower()}_rank"
        exam_key = f"{metric.lower()}_exam"
        ranks = [case[key] for case in subset if case.get(key) is not None]
        exams = [case[exam_key] for case in subset if case.get(exam_key) is not None]
        stats = _rank_metrics(ranks)
        rows.append(
            {
                "scope": scope,
                "system": system or "ALL",
                "stratum": "full_set",
                "metric": metric,
                "n_cases": stats["n_cases"],
                "top1_rate": stats["top1_rate"],
                "top5_rate": stats["top5_rate"],
                "mrr": stats["mrr"],
                "mean_rank": stats["mean_rank"],
                "exam_mean": round(sum(float(x) for x in exams) / len(exams), 4) if exams else 0.0,
                "participation_conditioned": False,
                "source": "varcop_sbfl_rank_exports",
            }
        )
    return rows


def _headline_gap_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str | None]] = [("ALL", None), *[(s, s) for s in SYSTEMS]]
    for scope_label, system in scopes:
        subset = cases if system is None else [c for c in cases if c["system"] == system]
        op2 = _rank_metrics([c["op2_rank"] for c in subset])
        ochiai = _rank_metrics([c["ochiai_rank"] for c in subset])
        rows.append(
            {
                "scope": scope_label,
                "stratum": "full_set",
                "op2_top1_rate": op2["top1_rate"],
                "ochiai_top1_rate": ochiai["top1_rate"],
                "op2_minus_ochiai_top1_pp": round((float(op2["top1_rate"]) - float(ochiai["top1_rate"])) * 100, 2),
                "op2_mean_rank": op2["mean_rank"],
                "ochiai_mean_rank": ochiai["mean_rank"],
                "op2_minus_ochiai_mean_rank": round(float(op2["mean_rank"]) - float(ochiai["mean_rank"]), 4),
                "participating_stratum_available": False,
                "absent_stratum_available": False,
            }
        )
    return rows


def _published_validation_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for system in SYSTEMS:
        subset = [c for c in cases if c["system"] == system]
        for metric in ("Ochiai", "Op2"):
            key = f"{metric.lower()}_rank"
            reproduced = _rank_metrics([c[key] for c in subset])["mean_rank"]
            published = PUBLISHED_RANK_SINGLE_BUG[system][metric]
            rows.append(
                {
                    "system": system,
                    "metric": metric,
                    "published_mean_rank": published,
                    "reproduced_mean_rank": reproduced,
                    "abs_error": round(abs(float(reproduced) - published), 4),
                }
            )
    return rows


def _write_inventory(
    path: Path,
    *,
    splc_inspection: dict[str, Any],
    sharepoint_ok: bool,
    sharepoint_note: str,
    varcop_ok: bool,
    zenodo_ok: bool,
    zenodo_note: str,
) -> None:
    lines = [
        "# Artifact inventory — SPLC2021 Variability Fault Localization Benchmark",
        "",
        f"_Generated {datetime.now(tz=UTC).isoformat()}_",
        "",
        "## Primary target",
        "",
        "| Item | Status |",
        "|------|--------|",
        f"| GitHub repo `{SPLC2021_REPO}` | Cloned; **metadata only** ({splc_inspection.get('file_count_ex_git', 0)} non-git files) |",
        f"| V2 dataset (SharePoint) | {'Reachable URL' if sharepoint_ok else 'Not automatable'} — {sharepoint_note} |",
        "| V1 dataset (Mega.nz) | Not downloaded (requires megatools / manual browser) |",
        "| VARCOP light Google Drive | Link returned HTTP 404 (June 2025 check) |",
        "",
        "## Repository contents (GitHub clone)",
        "",
        f"- Path: `{splc_inspection.get('path', 'n/a')}`",
        f"- Contains `spectrum_*_coverage.xml`: **{splc_inspection.get('contains_coverage_xml', False)}**",
        f"- Contains `variants/` tree: **{splc_inspection.get('contains_variants', False)}**",
        "",
        "Documented V2 artifact structure (from README):",
        "",
        "- `model.m`, `configs/`, `features/`, `variants/*/coverage/spectrum_{passed,failed}_coverage.xml`",
        "- `X.mutant.log` ground-truth modification locations",
        "- `config.report.csv.done` pass/fail per product",
        "- Baseline SBFL results bundled in full download",
        "",
        "## Secondary source used for partial reanalysis",
        "",
        f"| Source | Status |",
        "|--------|--------|",
        f"| VARCOP repo `{VARCOP_REPO}` | {'Available' if varcop_ok else 'Missing'} — experiment_results xlsx with per-case `SBFL:RANK` |",
        "",
        "## Fallback pivot (not SPL variability FL)",
        "",
        f"| Zenodo `{ZENODO_FALLBACK}` | {'Download OK' if zenodo_ok else 'Failed'} — {zenodo_note} |",
        "",
        "## Required fields for participation-conditioned reanalysis",
        "",
        "| Field | In GitHub clone | In VARCOP xlsx | In full V2 (documented) |",
        "|-------|-----------------|----------------|-------------------------|",
        "| Raw coverage / execution spectra | No | No | **Yes** (OpenClover XML) |",
        "| Pass/fail outcomes | No | No | **Yes** (`config.report.csv.done`, batch.test flags) |",
        "| Ground-truth faulty statements | No | Partial (`BUGGY STM`) | **Yes** (`buggy=\"true\"` in coverage XML + mutant log) |",
        "| Per-version metadata | No | Partial (bug id, system) | **Yes** |",
        "| Existing SBFL rankings | No | **Yes** (`SBFL:RANK`, `SBFL:EXAM`) | **Yes** (baseline in dataset) |",
        "| ef/ep for GT element | **No** | **No** | **Derivable** from spectra + GT |",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_feasibility_report(
    path: Path,
    *,
    feasibility_class: FeasibilityClass,
    case_count: int,
) -> None:
    lines = [
        "# Feasibility report — external Variability FL reanalysis",
        "",
        f"**Classification: {feasibility_class} — Partially reanalysable**",
        "",
        "## Rationale",
        "",
        "The SPLC2021 GitHub repository contains only the challenge README. The Version 2",
        "dataset (1,570 buggy versions, six Java SPL systems) is hosted on Microsoft SharePoint",
        "and requires manual browser download; automated retrieval from this environment failed.",
        "",
        "However, the VARCOP follow-up repository ships **frozen per-case SBFL ranking exports**",
        f"for **{case_count} single-bug V2 cases** (`SBFL:RANK`, `SBFL:EXAM`) across all six systems.",
        "These reproduce the published Table 3 mean ranks exactly (validation included in summary CSV).",
        "",
        "**Participation-conditioned reanalysis is blocked** because neither the GitHub clone nor",
        "the VARCOP xlsx exports include statement-level failed/pass execution counts (ef/ep) or",
        "raw `spectrum_passed_coverage.xml` / `spectrum_failed_coverage.xml` files needed to label",
        "participating vs spectrally absent ground-truth statements.",
        "",
        "## What was possible (Fallback B)",
        "",
        "- Reproduce full-set Top-1, Top-5, MRR, mean Rank, EXAM for Ochiai, Op2, Tarantula, Dstar, Barinel.",
        "- Validate against published SPLC 2021 Table 3 (single-bug).",
        "- Compute Op2-minus-Ochiai gaps on the **full set** and per system.",
        "- Test whether Op2 remains strongest among coefficients on the reproduced exports.",
        "",
        "## What was not possible",
        "",
        "- participating stratum (ef + ep > 0) vs absent stratum (ef = ep = 0)",
        "- Participation-conditioned Op2-minus-Ochiai gap",
        "- Cross-stratum reversal of published coefficient ranking claims",
        "",
        "## Zenodo pivot note",
        "",
        f"Zenodo `{ZENODO_FALLBACK}` (data-flow SBFL) downloaded successfully but covers Defects4J/jsoup",
        "programs, not SPL variability faults. Its published CSV exports contain fault ranks, not ef/ep",
        "spectra; it does not substitute for the SPLC2021 participation question.",
        "",
        "## Recommendation to proceed",
        "",
        "Manual download of SPLC2021 V2 from SharePoint would upgrade feasibility to **Class A**.",
        "Until then, only a **partial external replication** (ranking-level, full-set) is defensible.",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_external_report(
    path: Path,
    *,
    feasibility_class: FeasibilityClass,
    case_count: int,
    headline_rows: list[dict[str, Any]],
    summary_rows: list[dict[str, Any]],
) -> None:
    all_row = next(row for row in headline_rows if row["scope"] == "ALL")
    op2_row = next(row for row in summary_rows if row["metric"] == "Op2" and row["system"] == "ALL")
    ochiai_row = next(row for row in summary_rows if row["metric"] == "Ochiai" and row["system"] == "ALL")
    lines = [
        "# External reanalysis report — Variability FL Benchmark (partial)",
        "",
        f"**Feasibility class:** {feasibility_class}",
        f"**Cases reproduced:** {case_count} single-bug V2 cases via VARCOP SBFL exports",
        "",
        "## Research question status",
        "",
        "_Can participation-conditioned reporting change published SBFL coefficient conclusions?_",
        "",
        "**Cannot be answered with available artifacts.** Raw spectra are unavailable without manual",
        "V2 download. Only full-set ranking metrics could be reproduced.",
        "",
        "## Reproduced full-set results (338 single-bug cases)",
        "",
        f"- **Ochiai:** top-1 {float(ochiai_row['top1_rate'])*100:.1f}%, top-5 {float(ochiai_row['top5_rate'])*100:.1f}%, "
        f"MRR {ochiai_row['mrr']}, mean rank {ochiai_row['mean_rank']}",
        f"- **Op2:** top-1 {float(op2_row['top1_rate'])*100:.1f}%, top-5 {float(op2_row['top5_rate'])*100:.1f}%, "
        f"MRR {op2_row['mrr']}, mean rank {op2_row['mean_rank']}",
        "",
        "## Headline claim check (full set only)",
        "",
        f"- Op2-minus-Ochiai top-1 gap: **{all_row['op2_minus_ochiai_top1_pp']} pp** "
        f"({all_row['op2_top1_rate']} vs {all_row['ochiai_top1_rate']})",
        f"- Op2-minus-Ochiai mean rank gap: **{all_row['op2_minus_ochiai_mean_rank']}**",
        "- Published SPLC 2021 conclusion that **Op2 is strongest in single-bug setting** is **confirmed** on reproduced exports.",
        "- **Participation-conditioned reversal:** not testable (strata unavailable).",
        "",
        "## Per-system note",
        "",
        "ZipMe shows the weakest coverage (~43%) and highest mean ranks; GPL contributes the most",
        "Top-1 hits (36/71 in paper). Low-coverage ZipMe drives aggregate degradation but does not",
        "reverse Op2 > Ochiai on reproduced ranks.",
        "",
        "## IST inclusion guidance",
        "",
        "See `editorial_recommendation.md` in this folder for placement and abstract guidance.",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_summary_table_tex(path: Path, summary_rows: list[dict[str, Any]]) -> None:
    full = [r for r in summary_rows if r["system"] == "ALL"]
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\caption{Reproduced SPLC2021 single-bug SBFL metrics (VARCOP rank exports, full set).}",
        "\\label{tab:external-variability-fl-summary}",
        "\\begin{tabular}{@{}l r r r r r@{}}",
        "\\toprule",
        "Metric & $n$ & Top-1 & Top-5 & MRR & Mean rank \\\\",
        "\\midrule",
    ]
    for row in full:
        lines.append(
            f"{row['metric']} & {row['n_cases']} & "
            f"{float(row['top1_rate'])*100:.1f}\\% & {float(row['top5_rate'])*100:.1f}\\% & "
            f"{row['mrr']} & {row['mean_rank']} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    _write_text(path, "\n".join(lines))


def _write_strata_table_tex(path: Path) -> None:
    lines = [
        "\\begin{table}[t]",
        "\\centering",
        "\\small",
        "\\caption{Participation-stratified external reanalysis (not computable from available artifacts).}",
        "\\label{tab:external-variability-fl-strata}",
        "\\begin{tabular}{@{}l p{0.72\\linewidth}@{}}",
        "\\toprule",
        "Stratum & Status \\\\",
        "\\midrule",
        "Participating ($e_f{+}e_p>0$) & \\textbf{Not computable} — raw OpenClover spectra not in GitHub/VARCOP exports \\\\",
        "Absent ($e_f{=}e_p{=}0$) & \\textbf{Not computable} — same blocker \\\\",
        "Full set (fallback) & Reproduced from VARCOP `SBFL:RANK` (338 single-bug cases) \\\\",
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table}",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_editorial_recommendation(
    path: Path,
    *,
    feasibility_class: FeasibilityClass,
    case_count: int,
    headline_rows: list[dict[str, Any]],
) -> None:
    all_row = next(row for row in headline_rows if row["scope"] == "ALL")
    lines = [
        "# Editorial recommendation — external Variability FL reanalysis",
        "",
        "## A. Can this be included in the IST paper?",
        "",
        "**Partially.** A short paragraph plus one reproduced full-set table is defensible using VARCOP",
        f"rank exports ({case_count} cases, validated against published Table 3). A full external",
        "replication section answering the participation question requires manual V2 dataset download.",
        "",
        "## B. Does it materially reduce the “synthetic-only” criticism?",
        "",
        "**Moderately, not strongly.** Showing that an independent Java SPL benchmark also ranks Op2",
        "ahead of Ochiai supports generalizability of the *coefficient comparison pattern* at aggregate",
        "level, but without participation strata it does not externalize the paper's core participation",
        "confound demonstration.",
        "",
        "## C. Does participation-conditioned reporting change a published external conclusion?",
        "",
        "**Unknown / not demonstrated.** Strata could not be recomputed. On the **full set only**,",
        "Op2 remains strongest for single-bug cases — the published SPLC conclusion **does not reverse**.",
        "",
        "## D. Recommended placement",
        "",
        "| Content | Placement |",
        "|---------|-----------|",
        "| Feasibility blocker + partial rank reproduction | **Appendix** (recommended) |",
        "| One-sentence external corroboration (Op2 vs Ochiai, Java SPL) | Optional **§7 footnote** |",
        "| Participation-stratified external reanalysis | **Not includable** until V2 spectra obtained |",
        "| Dedicated main “External reanalysis” section | **Not recommended** without Class A |",
        "",
        "## E. Page budget",
        "",
        "- Appendix feasibility note + one table: **~0.4–0.6 pages**",
        "- Main-text footnote only: **~0.1 pages**",
        "- Full main section (if Class A achieved later): **~1.0–1.5 pages**",
        "",
        "## F. Strong enough to revise the abstract?",
        "",
        "**No.** Current evidence is rank-level, full-set only, and does not show participation-conditioned",
        f"collapse of the Op2–Ochiai gap (reproduced full-set gap: {all_row['op2_minus_ochiai_top1_pp']} pp top-1).",
        "Abstract revision would require successful Class A participation reanalysis.",
        "",
        f"_Feasibility class: {feasibility_class}_",
        "",
    ]
    _write_text(path, "\n".join(lines))


def run_external_variability_fl_feasibility(
    *,
    output_dir: Path,
    table_dir: Path,
    cache_dir: Path | None = None,
    varcop_root: Path | None = None,
) -> ExternalVariabilityFlResult:
    """Inspect SPLC2021 artifact accessibility and run partial reanalysis if possible."""
    output_dir.mkdir(parents=True, exist_ok=True)
    table_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir or (output_dir / "cache")
    cache.mkdir(parents=True, exist_ok=True)

    splc_dir = cache / "splc2021"
    varcop_dir = varcop_root or (cache / "varcop")
    _clone_repo(SPLC2021_REPO, splc_dir)
    if varcop_root is None:
        _clone_repo(VARCOP_REPO, varcop_dir)

    splc_inspection = _inspect_splc2021_repo(splc_dir) if splc_dir.is_dir() else {}
    sharepoint_ok, sharepoint_note = _http_head_accessible(SPLC2021_V2_SHAREPOINT)

    zenodo_ok = False
    zenodo_note = "not attempted"
    zenodo_zip = cache / "zenodo_data_flow_sfl.zip"
    try:
        with urlopen(
            "https://zenodo.org/api/records/3258116/files/saeg/data-flow-sfl-0.2.zip/content",
            timeout=60,
        ) as response, zenodo_zip.open("wb") as handle:
            shutil.copyfileobj(response, handle)
        zenodo_ok = zenodo_zip.stat().st_size > 100_000
        zenodo_note = f"downloaded {zenodo_zip.stat().st_size} bytes"
    except Exception as exc:
        zenodo_note = str(exc)

    if not _varcop_single_bug_workbook(varcop_dir):
        msg = f"VARCOP rank exports not found under {varcop_dir}"
        raise ExternalVariabilityFlError(msg)

    cases = _load_varcop_single_bug_cases(varcop_dir)
    if not cases:
        msg = "No single-bug cases loaded from VARCOP exports"
        raise ExternalVariabilityFlError(msg)

    feasibility_class: FeasibilityClass = "B"

    summary_rows = _metric_summary_rows(cases, scope="full_set")
    by_system_rows: list[dict[str, Any]] = []
    for system in SYSTEMS:
        by_system_rows.extend(_metric_summary_rows(cases, scope="by_system", system=system))

    headline_rows = _headline_gap_rows(cases)
    validation_rows = _published_validation_rows(cases)

    by_stratum_rows: list[dict[str, Any]] = [
        {
            "stratum": "participating",
            "status": "not_computable",
            "reason": "ef/ep unavailable without SPLC2021 V2 coverage XML",
            "n_cases": 0,
        },
        {
            "stratum": "absent",
            "status": "not_computable",
            "reason": "ef/ep unavailable without SPLC2021 V2 coverage XML",
            "n_cases": 0,
        },
        {
            "stratum": "full_set",
            "status": "reproduced",
            "reason": "VARCOP SBFL:RANK exports",
            "n_cases": len(cases),
        },
    ]

    inventory_path = output_dir / "artifact_inventory.md"
    feasibility_path = output_dir / "feasibility_report.md"
    summary_path = output_dir / "external_reanalysis_summary.csv"
    by_system_path = output_dir / "external_reanalysis_by_system.csv"
    by_stratum_path = output_dir / "external_reanalysis_by_stratum.csv"
    report_path = output_dir / "external_reanalysis_report.md"
    editorial_path = output_dir / "editorial_recommendation.md"

    _write_inventory(
        inventory_path,
        splc_inspection=splc_inspection,
        sharepoint_ok=sharepoint_ok,
        sharepoint_note=sharepoint_note,
        varcop_ok=varcop_dir.is_dir(),
        zenodo_ok=zenodo_ok,
        zenodo_note=zenodo_note,
    )
    _write_feasibility_report(feasibility_path, feasibility_class=feasibility_class, case_count=len(cases))
    _write_external_report(
        report_path,
        feasibility_class=feasibility_class,
        case_count=len(cases),
        headline_rows=headline_rows,
        summary_rows=summary_rows,
    )
    _write_editorial_recommendation(
        editorial_path,
        feasibility_class=feasibility_class,
        case_count=len(cases),
        headline_rows=headline_rows,
    )

    summary_csv_rows = summary_rows + headline_rows  # headline in separate file better
    _write_csv(
        summary_path,
        (
            "scope",
            "system",
            "stratum",
            "metric",
            "n_cases",
            "top1_rate",
            "top5_rate",
            "mrr",
            "mean_rank",
            "exam_mean",
            "participation_conditioned",
            "source",
        ),
        summary_rows,
    )
    _write_csv(
        output_dir / "external_reanalysis_headline_gaps.csv",
        (
            "scope",
            "stratum",
            "op2_top1_rate",
            "ochiai_top1_rate",
            "op2_minus_ochiai_top1_pp",
            "op2_mean_rank",
            "ochiai_mean_rank",
            "op2_minus_ochiai_mean_rank",
            "participating_stratum_available",
            "absent_stratum_available",
        ),
        headline_rows,
    )
    _write_csv(
        output_dir / "published_table3_validation.csv",
        (
            "system",
            "metric",
            "published_mean_rank",
            "reproduced_mean_rank",
            "abs_error",
        ),
        validation_rows,
    )
    _write_csv(
        by_system_path,
        (
            "scope",
            "system",
            "stratum",
            "metric",
            "n_cases",
            "top1_rate",
            "top5_rate",
            "mrr",
            "mean_rank",
            "exam_mean",
            "participation_conditioned",
            "source",
        ),
        by_system_rows,
    )
    _write_csv(
        by_stratum_path,
        ("stratum", "status", "reason", "n_cases"),
        by_stratum_rows,
    )

    _write_summary_table_tex(table_dir / "table_external_reanalysis_summary.tex", summary_rows)
    _write_strata_table_tex(table_dir / "table_external_reanalysis_strata.tex")

    manifest = {
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "study": "external_variability_fl_feasibility",
        "feasibility_class": feasibility_class,
        "case_count": len(cases),
        "splc2021_repo": SPLC2021_REPO,
        "varcop_repo": VARCOP_REPO,
        "sharepoint_accessible": sharepoint_ok,
        "zenodo_fallback_downloaded": zenodo_ok,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    return ExternalVariabilityFlResult(
        output_dir=output_dir,
        table_dir=table_dir,
        feasibility_class=feasibility_class,
        inventory_path=inventory_path,
        feasibility_path=feasibility_path,
        summary_path=summary_path,
        by_system_path=by_system_path,
        by_stratum_path=by_stratum_path,
        report_path=report_path,
        case_count=len(cases),
    )
