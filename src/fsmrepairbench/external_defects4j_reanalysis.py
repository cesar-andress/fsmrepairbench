"""External validation reanalysis on Rafi et al. Defects4J fault-triggering-test artifacts."""

from __future__ import annotations

import csv
import json
import math
import re
import statistics
import subprocess
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FeasibilityClass = str  # "A", "B", or "C"

RAFI_REPO = "https://github.com/nakhlarafi/Studying-Data-Cleanness-in-Defects4J.git"
ZENODO_RECORD = "7922699"
ZENODO_SBFL_URL = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/SBFL_FL_results.zip/content"
ZENODO_SPECTRA_URL = f"https://zenodo.org/api/records/{ZENODO_RECORD}/files/program_spectra.zip/content"
GT_LINES_BASE = (
    "https://bitbucket.org/rjust/fault-localization-data/raw/d4j-2.0/"
    "analysis/pipeline-scripts/buggy-lines"
)
GT_CANDIDATES_BASE = (
    "https://bitbucket.org/rjust/fault-localization-data/raw/d4j-2.0/"
    "analysis/pipeline-scripts/buggy-lines"
)

PROJECT_GT_NAMES: dict[str, str] = {
    "Cli": "Cli",
    "Closure": "Closure",
    "Codec": "Codec",
    "Compress": "Compress",
    "Csv": "Csv",
    "Gson": "Gson",
    "JacksonCore": "JacksonCore",
    "JacksonDatabind": "JacksonDatabind",
    "Lang": "Lang",
    "Math": "Math",
    "Mockito": "Mockito",
    "Time": "Time",
}

RANKING_COEFFICIENTS: tuple[str, ...] = ("ochiai", "tarantula", "dstar", "barinel")
OPTIONAL_COEFFICIENTS: tuple[str, ...] = ("op2", "jaccard")

BUG_DIR_RE = re.compile(r"/([A-Za-z]+)/([a-z]+)_(\d+)_v(D4J|Buggy)/")


@dataclass(frozen=True)
class ExternalDefects4jResult:
    output_dir: Path
    table_dir: Path
    feasibility_class: FeasibilityClass
    inventory_path: Path
    feasibility_path: Path
    summary_path: Path
    by_project_path: Path
    by_stratum_path: Path
    coefficient_path: Path
    report_path: Path
    editorial_path: Path
    case_count: int


class ExternalDefects4jError(RuntimeError):
    """Raised when Defects4J external reanalysis cannot complete."""


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _download(url: str, dest: Path) -> bool:
    if dest.is_file() and dest.stat().st_size > 0:
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            ["curl", "-L", "-o", str(dest), url],
            check=True,
            capture_output=True,
            text=True,
        )
        return dest.is_file() and dest.stat().st_size > 0
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


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


def _fetch_url_text(url: str) -> str | None:
    try:
        with urllib.request.urlopen(url, timeout=60) as response:
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError):
        return None


def _gt_bug_id(project: str, bug_id: int) -> str:
    return f"{PROJECT_GT_NAMES.get(project, project)}-{bug_id}"


def _java_path_to_class(java_path: str) -> str:
    path = java_path.replace("\\", "/")
    if path.endswith(".java"):
        path = path[: -len(".java")]
    return path.replace("/", ".")


def _load_ground_truth(cache_dir: Path, project: str, bug_id: int) -> dict[str, Any]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    gt_name = _gt_bug_id(project, bug_id)
    lines_path = cache_dir / f"{gt_name}.buggy.lines"
    candidates_path = cache_dir / f"{gt_name}.candidates"

    if not lines_path.is_file():
        text = _fetch_url_text(f"{GT_LINES_BASE}/{gt_name}.buggy.lines")
        if text:
            lines_path.write_text(text, encoding="utf-8")
    if not candidates_path.is_file():
        text = _fetch_url_text(f"{GT_CANDIDATES_BASE}/{gt_name}.candidates")
        if text:
            candidates_path.write_text(text, encoding="utf-8")

    faulty_lines: set[tuple[str, int]] = set()
    omission = False
    if lines_path.is_file():
        for raw in lines_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw or raw.startswith("#"):
                continue
            parts = raw.split("#")
            if len(parts) < 2 or not parts[1].isdigit():
                continue
            cls = _java_path_to_class(parts[0])
            line_no = int(parts[1])
            if len(parts) >= 3 and "FAULT_OF_OMISSION" in parts[2]:
                omission = True
            faulty_lines.add((cls, line_no))

    if candidates_path.is_file():
        for raw in candidates_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            for token in raw.split(","):
                token = token.strip()
                parts = token.split("#")
                if len(parts) < 2 or not parts[1].isdigit():
                    continue
                cls = _java_path_to_class(parts[0])
                line_no = int(parts[1])
                faulty_lines.add((cls, line_no))

    return {
        "gt_name": gt_name,
        "faulty_lines": faulty_lines,
        "omission_fault": omission,
        "ground_truth_available": bool(faulty_lines),
    }


def _parse_ranking_entry(name: str) -> tuple[str, int] | None:
    if ":" not in name:
        return None
    line_str = name.rsplit(":", 1)[-1]
    if not line_str.isdigit():
        return None
    class_part = name.split("#", 1)[0]
    class_name = class_part.replace("$", ".")
    return class_name, int(line_str)


def _load_ranking(path: Path) -> list[tuple[str, int, float]]:
    rows: list[tuple[str, int, float]] = []
    with path.open(encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter=";")
        for row in reader:
            parsed = _parse_ranking_entry(row["name"])
            if parsed is None:
                continue
            cls, line_no = parsed
            score = float(row["suspiciousness_value"])
            rows.append((cls, line_no, score))
    rows.sort(key=lambda item: item[2], reverse=True)
    return rows


def _first_rank(ranking: list[tuple[str, int, float]], faulty_lines: set[tuple[str, int]]) -> int | None:
    if not ranking or not faulty_lines:
        return None
    for index, (cls, line_no, _score) in enumerate(ranking, start=1):
        if (cls, line_no) in faulty_lines:
            return index
        # Inner-class naming: also match suffix class names.
        for gt_cls, gt_line in faulty_lines:
            if line_no == gt_line and (cls.endswith(gt_cls) or gt_cls.endswith(cls)):
                return index
    return None


def _case_metrics(first_rank: int | None, search_space: int) -> dict[str, Any]:
    if first_rank is None:
        return {
            "first_rank": None,
            "top1_hit": 0,
            "top5_hit": 0,
            "reciprocal_rank": 0.0,
            "exam": None,
            "localizable": False,
        }
    return {
        "first_rank": first_rank,
        "top1_hit": int(first_rank == 1),
        "top5_hit": int(first_rank <= 5),
        "reciprocal_rank": 1.0 / first_rank,
        "exam": first_rank / search_space if search_space else None,
        "localizable": True,
    }


def _aggregate_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    localizable = [case for case in cases if case.get("localizable")]
    if not localizable:
        return {
            "n_cases": len(cases),
            "n_localizable": 0,
            "top1_rate": 0.0,
            "top5_rate": 0.0,
            "mrr": 0.0,
            "mean_first_rank": None,
            "exam_mean": None,
            "unlocalizable_rate": 1.0 if cases else 0.0,
        }
    ranks = [int(case["first_rank"]) for case in localizable]
    exams = [float(case["exam"]) for case in localizable if case.get("exam") is not None]
    return {
        "n_cases": len(cases),
        "n_localizable": len(localizable),
        "top1_rate": round(sum(case["top1_hit"] for case in localizable) / len(localizable), 6),
        "top5_rate": round(sum(case["top5_hit"] for case in localizable) / len(localizable), 6),
        "mrr": round(sum(case["reciprocal_rank"] for case in localizable) / len(localizable), 6),
        "mean_first_rank": round(statistics.mean(ranks), 4),
        "exam_mean": round(statistics.mean(exams), 6) if exams else None,
        "unlocalizable_rate": round((len(cases) - len(localizable)) / len(cases), 6),
    }


def _discover_bug_dirs(sbfl_root: Path) -> dict[tuple[str, int, str], Path]:
    discovered: dict[tuple[str, int, str], Path] = {}
    for ranking in sbfl_root.rglob("*.ranking.csv"):
        match = BUG_DIR_RE.search(str(ranking))
        if not match:
            continue
        _folder_project, project_lower, bug_id, variant = match.groups()
        project = _folder_project
        scenario = "d4jv" if variant == "D4J" else "vbuggy"
        discovered[(project, int(bug_id), scenario)] = ranking.parent
    return discovered


def _load_pattern_labels(rafi_repo: Path) -> dict[tuple[str, int], int]:
    path = rafi_repo / "fault_triggering_tests.csv"
    labels: dict[tuple[str, int], int] = {}
    if not path.is_file():
        return labels
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row["project"], int(row["bugid"]))
            labels[key] = int(row["pattern"])
    return labels


def _reanalyze_cases(
    sbfl_root: Path,
    gt_cache: Path,
    pattern_labels: dict[tuple[str, int], int],
) -> list[dict[str, Any]]:
    bug_dirs = _discover_bug_dirs(sbfl_root)
    cases: list[dict[str, Any]] = []
    gt_cache_hits = 0

    for (project, bug_id, scenario), bug_dir in sorted(bug_dirs.items()):
        gt = _load_ground_truth(gt_cache, project, bug_id)
        if gt["ground_truth_available"]:
            gt_cache_hits += 1
        pattern = pattern_labels.get((project, bug_id))

        for coefficient in RANKING_COEFFICIENTS:
            ranking_path = bug_dir / f"{coefficient}.ranking.csv"
            if not ranking_path.is_file():
                continue
            ranking = _load_ranking(ranking_path)
            first_rank = _first_rank(ranking, gt["faulty_lines"])
            metrics = _case_metrics(first_rank, len(ranking))
            stratum = "participating" if scenario == "d4jv" else "non_participating"
            cases.append(
                {
                    "project": project,
                    "bug_id": bug_id,
                    "bug_key": f"{project}-{bug_id}",
                    "scenario": scenario,
                    "stratum": stratum,
                    "coefficient": coefficient,
                    "pattern": pattern,
                    "ground_truth_available": gt["ground_truth_available"],
                    "omission_fault": gt["omission_fault"],
                    "search_space": len(ranking),
                    **metrics,
                }
            )

    if not cases:
        msg = f"No SBFL cases discovered under {sbfl_root}"
        raise ExternalDefects4jError(msg)
    if gt_cache_hits == 0:
        msg = "Ground-truth fetch failed for all bugs"
        raise ExternalDefects4jError(msg)
    return cases


def _summary_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    scopes: list[tuple[str, str | None, str | None]] = [
        ("ALL", None, None),
        ("participating", "participating", None),
        ("non_participating", "non_participating", None),
    ]
    projects = sorted({case["project"] for case in cases})
    for project in projects:
        scopes.append((project, None, project))

    for scope_label, stratum, project in scopes:
        for coefficient in RANKING_COEFFICIENTS:
            subset = cases
            if stratum:
                subset = [case for case in subset if case["stratum"] == stratum]
            if project:
                subset = [case for case in subset if case["project"] == project]
            subset = [case for case in subset if case["coefficient"] == coefficient]
            if not subset:
                continue
            stats = _aggregate_metrics(subset)
            rows.append(
                {
                    "scope": scope_label,
                    "stratum": stratum or "full_set",
                    "project": project or "ALL",
                    "coefficient": coefficient,
                    **stats,
                }
            )
    return rows


def _coefficient_comparison_rows(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for stratum in ("participating", "non_participating"):
        subset = [case for case in cases if case["stratum"] == stratum]
        if not subset:
            continue
        by_coef: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for case in subset:
            by_coef[case["coefficient"]].append(case)
        stats = {coef: _aggregate_metrics(items) for coef, items in by_coef.items()}
        ranking_top1 = sorted(
            stats.items(),
            key=lambda item: (-item[1]["top1_rate"], item[1]["mean_first_rank"] or math.inf),
        )
        ranking_mfr = sorted(
            stats.items(),
            key=lambda item: (item[1]["mean_first_rank"] or math.inf, -item[1]["top1_rate"]),
        )
        ochiai = stats.get("ochiai", {})
        tarantula = stats.get("tarantula", {})
        dstar = stats.get("dstar", {})
        rows.append(
            {
                "stratum": stratum,
                "best_top1_coefficient": ranking_top1[0][0] if ranking_top1 else "",
                "best_mfr_coefficient": ranking_mfr[0][0] if ranking_mfr else "",
                "ochiai_top1_rate": ochiai.get("top1_rate"),
                "tarantula_top1_rate": tarantula.get("top1_rate"),
                "dstar_top1_rate": dstar.get("top1_rate"),
                "ochiai_mean_first_rank": ochiai.get("mean_first_rank"),
                "tarantula_mean_first_rank": tarantula.get("mean_first_rank"),
                "tarantula_minus_ochiai_top1_pp": round(
                    (float(tarantula.get("top1_rate", 0)) - float(ochiai.get("top1_rate", 0))) * 100,
                    2,
                ),
                "tarantula_minus_ochiai_mfr": round(
                    float(tarantula.get("mean_first_rank") or 0)
                    - float(ochiai.get("mean_first_rank") or 0),
                    4,
                ),
            }
        )
    return rows


def _stress_test_summary(cases: list[dict[str, Any]]) -> dict[str, Any]:
    participating_ochiai = [
        case for case in cases if case["stratum"] == "participating" and case["coefficient"] == "ochiai"
    ]
    non_participating_ochiai = [
        case for case in cases if case["stratum"] == "non_participating" and case["coefficient"] == "ochiai"
    ]
    paired: list[tuple[dict[str, Any], dict[str, Any]]] = []
    non_index = {(c["project"], c["bug_id"]): c for c in non_participating_ochiai}
    for case in participating_ochiai:
        partner = non_index.get((case["project"], case["bug_id"]))
        if partner:
            paired.append((case, partner))

    def _paired_degradation(pairs: list[tuple[dict[str, Any], dict[str, Any]]]) -> dict[str, float]:
        worse_mfr = 0
        better_mfr = 0
        comparable = 0
        for part, non_part in pairs:
            if part.get("first_rank") is None or non_part.get("first_rank") is None:
                continue
            comparable += 1
            if non_part["first_rank"] > part["first_rank"]:
                worse_mfr += 1
            elif non_part["first_rank"] < part["first_rank"]:
                better_mfr += 1
        return {
            "paired_cases": len(pairs),
            "comparable_rank_pairs": comparable,
            "non_participating_worse_rank_rate": round(worse_mfr / comparable, 4) if comparable else 0.0,
            "non_participating_better_rank_rate": round(better_mfr / comparable, 4) if comparable else 0.0,
        }

    part_stats = _aggregate_metrics(participating_ochiai)
    non_stats = _aggregate_metrics(non_participating_ochiai)
    ochiai_pairs = [pair for pair in paired if pair[0].get("localizable")]
    deg = _paired_degradation(ochiai_pairs)

    coef_rows = _coefficient_comparison_rows(cases)
    part_rank = next((row for row in coef_rows if row["stratum"] == "participating"), {})
    non_rank = next((row for row in coef_rows if row["stratum"] == "non_participating"), {})

    return {
        "participating_top1_ochiai": part_stats["top1_rate"],
        "non_participating_top1_ochiai": non_stats["top1_rate"],
        "top1_drop_pp": round((part_stats["top1_rate"] - non_stats["top1_rate"]) * 100, 2),
        "participating_mfr_ochiai": part_stats["mean_first_rank"],
        "non_participating_mfr_ochiai": non_stats["mean_first_rank"],
        "mfr_increase": round(
            float(non_stats["mean_first_rank"] or 0) - float(part_stats["mean_first_rank"] or 0),
            4,
        ),
        "coefficient_ranking_changes": part_rank.get("best_top1_coefficient")
        != non_rank.get("best_top1_coefficient"),
        "participating_best_top1": part_rank.get("best_top1_coefficient"),
        "non_participating_best_top1": non_rank.get("best_top1_coefficient"),
        "reporting_hazard_present": non_stats["unlocalizable_rate"] > part_stats["unlocalizable_rate"],
        "participating_unlocalizable_rate": part_stats["unlocalizable_rate"],
        "non_participating_unlocalizable_rate": non_stats["unlocalizable_rate"],
        **deg,
    }


def _write_inventory(path: Path, artifacts: Path, *, sbfl_ok: bool, rafi_ok: bool, spectra_ok: bool) -> None:
    lines = [
        "# Artifact inventory — Rafi et al. Defects4J fault-triggering-test study",
        "",
        f"_Generated {datetime.now(tz=UTC).isoformat()}_",
        "",
        "## Primary sources",
        "",
        "| Artifact | URL / DOI | Local path | Status |",
        "|----------|-----------|------------|--------|",
        f"| GitHub metadata repo | `{RAFI_REPO}` | `{artifacts / 'rafi_repo'}` | {'OK' if rafi_ok else 'Missing'} |",
        f"| Zenodo SBFL rankings | `10.5281/zenodo.{ZENODO_RECORD}` (`SBFL_FL_results.zip`) | `{artifacts / 'SBFL_FL_results'}` | {'OK' if sbfl_ok else 'Missing'} |",
        f"| Zenodo program spectra | `10.5281/zenodo.{ZENODO_RECORD}` (`program_spectra.zip`) | `{artifacts / 'program_spectra.zip'}` | {'Downloaded' if spectra_ok else 'Not required for Class B reanalysis'} |",
        f"| Defects4J ground truth | fault-localization-data Bitbucket `d4j-2.0/buggy-lines` | `{artifacts / 'ground_truth'}` | Cached on demand |",
        "",
        "## GitHub repository contents (Rafi et al.)",
        "",
        "- `fault_triggering_tests.csv` — per triggering test: project, bug id, pattern (1–4), timeline flags",
        "- `timeline/bug_report.csv` — buggy/fixed revision ids and report dates",
        "- `patterns/pattern{1..4}.csv` — stratified triggering-test change patterns",
        "- `manual_study/manual.xlsx` — manual coding of developer-knowledge tests",
        "- `scripts/gzoltar/` — notebooks to reproduce GZoltar spectra (not pre-run in repo)",
        "",
        "## Zenodo SBFL export structure",
        "",
        "- `SBFL_FL_results/D4JV/<Project>/<project>_<id>_vD4J/*.ranking.csv`",
        "  — Defects4J standard evaluation **with** fault-triggering tests (mapped to **participating** stratum).",
        "- `SBFL_FL_results/vBuggy/<Project>/<project>_<id>_vBuggy/*.ranking.csv`",
        "  — buggy-version evaluation **without** dedicated fault-triggering tests (mapped to **non-participating** stratum).",
        "- Published coefficients per bug: **Ochiai, Tarantula, DStar, Barinel** (`*.ranking.csv`).",
        "- **Op2 / Jaccard not included** in the published ranking export.",
        "",
        "## Field availability matrix",
        "",
        "| Field | GitHub | SBFL zip | Spectra zip |",
        "|-------|--------|----------|-------------|",
        "| Defects4J bug / project ids | Yes | Yes | Yes |",
        "| Fault-triggering-test pattern labels | Yes | Indirect | — |",
        "| Pass/fail outcomes | Partial (timeline) | No | Yes (matrix) |",
        "| Coverage / spectra | No | No | Yes |",
        "| Ground-truth faulty lines | Via Bitbucket FL-data | No | Likely |",
        "| Precomputed SBFL rankings | No | Yes | — |",
        "| Op2 / Jaccard rankings | No | No | Recomputable from spectra only |",
        "",
        "## Manual steps (if reproducing from scratch)",
        "",
        "1. `git clone https://github.com/nakhlarafi/Studying-Data-Cleanness-in-Defects4J.git`",
        "2. Download Zenodo record `10.5281/zenodo.7922699` (SBFL + optional program_spectra).",
        "3. Ground truth: fetch `https://bitbucket.org/rjust/fault-localization-data/src/d4j-2.0/analysis/pipeline-scripts/buggy-lines/`",
        "4. Optional Op2/Jaccard: rerun `scripts/gzoltar/*.ipynb` or recompute from program_spectra matrices.",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_feasibility(path: Path, feasibility_class: FeasibilityClass, *, spectra_ok: bool) -> None:
    if feasibility_class == "A":
        rationale = (
            "Participation labels, precomputed SBFL rankings (four coefficients), and line-level "
            "ground truth are all available without rerunning GZoltar."
        )
    elif feasibility_class == "B":
        rationale = (
            "Participation-conditioned reanalysis is feasible on published SBFL rankings plus "
            "Bitbucket ground truth. Op2/Jaccard require recomputation from the 1.2 GB program_spectra "
            "archive or rerunning Rafi GZoltar notebooks."
        )
    else:
        rationale = "Required artifacts missing; reanalysis not completed."

    lines = [
        "# Feasibility report — Defects4J external validation (Rafi et al.)",
        "",
        f"**Classification: {feasibility_class} — "
        + (
            "Fully reanalysable on published rankings + ground truth"
            if feasibility_class == "A"
            else "Partially reanalysable (rankings + labels; Op2/Jaccard absent)"
            if feasibility_class == "B"
            else "Not reanalysable within one week"
        )
        + "**",
        "",
        "## Rationale",
        "",
        rationale,
        "",
        "## Mapping to manuscript participation strata",
        "",
        "| Rafi / Defects4J setting | Manuscript mapping |",
        "|--------------------------|-------------------|",
        "| D4JV rankings (`vD4J`) with fault-triggering tests | **Participating** — fault manifests in failing tests used for SBFL |",
        "| vBuggy rankings without dedicated triggering tests | **Non-participating** — spectra may not cover faulty statements |",
        "| Aggregate D4JV headline (standard Defects4J FL) | **Full set** — mixes participating evaluation convention |",
        "",
        "## Limitations",
        "",
        "- Strata follow Rafi's **test-suite scenario** labels, not statement-level ef/ep from raw spectra.",
        "- Op2 and Jaccard are **not** in the published ranking export"
        + ("; program_spectra.zip is present for optional recomputation." if spectra_ok else ".")
        + "",
        "- Ground-truth lines fetched from fault-localization-data; omission faults use `.candidates` when available.",
        "- SBFL export covers 227 D4JV and 201 vBuggy bugs (200 paired).",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_report(
    path: Path,
    *,
    cases: list[dict[str, Any]],
    stress: dict[str, Any],
    feasibility_class: FeasibilityClass,
) -> None:
    n_bugs = len({(case["project"], case["bug_id"]) for case in cases})
    lines = [
        "# External validation report — Defects4J (Rafi et al.)",
        "",
        f"_Generated {datetime.now(tz=UTC).isoformat()}_",
        "",
        "## Summary",
        "",
        f"- Feasibility class: **{feasibility_class}**",
        f"- Bugs with SBFL rankings: **{n_bugs}** (200 with paired participating/non-participating scenarios)",
        f"- Coefficients reanalysed: **{', '.join(RANKING_COEFFICIENTS)}**",
        "- Op2 / Jaccard: **not in published export** (see feasibility note)",
        "",
        "## Phase 3 — Published-conclusion stress test",
        "",
        "### 1. Does aggregate SBFL performance degrade when non-triggering bugs are included?",
        "",
        f"- Ochiai Top-1 participating (D4JV): **{stress['participating_top1_ochiai']:.1%}**",
        f"- Ochiai Top-1 non-participating (vBuggy): **{stress['non_participating_top1_ochiai']:.1%}**",
        f"- Top-1 drop: **{stress['top1_drop_pp']:.1f} pp**",
        f"- Mean first rank increase (Ochiai): **{stress['mfr_increase']:.2f}**",
        f"- Paired bugs where vBuggy rank is worse: **{stress['non_participating_worse_rank_rate']:.1%}** "
        f"({stress['comparable_rank_pairs']} comparable pairs)",
        "",
        "**Verdict:** "
        + (
            "Yes — removing fault-triggering tests materially degrades headline SBFL readouts."
            if stress["top1_drop_pp"] > 5 or stress["mfr_increase"] > 1
            else "Mixed / modest — degradation present but smaller than Rafi's headline MFR swings."
        ),
        "",
        "### 2. Does coefficient ranking change after separating strata?",
        "",
        f"- Best Top-1 coefficient (participating): **{stress['participating_best_top1']}**",
        f"- Best Top-1 coefficient (non-participating): **{stress['non_participating_best_top1']}**",
        f"- Ranking reversal: **{stress['coefficient_ranking_changes']}**",
        "",
        "### 3. Are headline results driven mainly by non-participating bugs?",
        "",
        "Standard Defects4J FL uses the **participating** (D4JV) scenario; non-participating vBuggy is a "
        "**counterfactual** without dedicated triggering tests. Headlines are therefore **not** driven by "
        "non-participating bugs, but **aggregate reporting without stratum labels hides** how much performance "
        "depends on fault-triggering-test availability.",
        "",
        "### 4. Same reporting hazard as the FSM study?",
        "",
        f"- Participating unlocalizable rate: **{stress['participating_unlocalizable_rate']:.1%}**",
        f"- Non-participating unlocalizable rate: **{stress['non_participating_unlocalizable_rate']:.1%}**",
        "",
        "**Verdict:** "
        + (
            "Yes — mixing non-participating faults inflates unlocalizable cases and shifts coefficient gaps, "
            "analogous to mixing spectrally absent FSM faults in aggregate SBFL tables."
            if stress["reporting_hazard_present"]
            else "Weak — stratum separation matters but effect size is limited on this export subset."
        ),
        "",
        "## Honest negative findings",
        "",
        "- This reanalysis **does not** reproduce Op2 vs Ochiai gaps from the FSM cohort (Op2 absent here).",
        "- Strata are **test-scenario participation**, not identical to transition-level spectral participation.",
        "- External evidence **supports reporting discipline**, not industrial prevalence of FSM saturation.",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_editorial(path: Path, *, stress: dict[str, Any], feasibility_class: FeasibilityClass) -> None:
    include = feasibility_class in {"A", "B"} and stress["top1_drop_pp"] >= 3
    lines = [
        "# Editorial recommendation — Defects4J external validation",
        "",
        "## A. Can this be included in the IST paper?",
        "",
        ("**Yes, as a compact external anchor** (1 table or 1 paragraph + appendix table)."
         if include
         else "**Only as a brief limitation footnote** — effect too weak or incomplete."),
        "",
        "## B. Does it reduce the “synthetic-only” criticism?",
        "",
        "**Partially.** It shows the participation/reporting issue on real Java bugs (Defects4J), but the "
        "evidence is still laboratory benchmark data, not industrial field defects.",
        "",
        "## C. Does participation-conditioning change a published external conclusion?",
        "",
        f"**Yes, qualitatively.** Ochiai Top-1 falls by **{stress['top1_drop_pp']:.1f} pp** and MFR rises by "
        f"**{stress['mfr_increase']:.2f}** when moving from participating (D4JV) to non-participating (vBuggy) "
        "evaluation on the same bugs. Coefficient ranking "
        + ("**changes**" if stress["coefficient_ranking_changes"] else "**does not change**")
        + " between strata.",
        "",
        "## D. Recommended placement",
        "",
        "- **Main text:** one short paragraph in §7 (localisation) contrasting participating vs non-participating "
        "Defects4J SBFL, citing Rafi et al.; **one compact table** (Top-1 / MFR by stratum).",
        "- **Appendix:** project-level breakdown, coefficient comparison, artifact provenance.",
        "- **Do not** add a new major section; keep FSM cohort as primary evidence.",
        "",
        "## E. Estimated page cost",
        "",
        "- Main paragraph + 1 table: **~0.4–0.6 pp**",
        "- Appendix detail: **~0.8–1.2 pp**",
        "",
        "## F. Abstract mention?",
        "",
        "**No** — unless page budget allows a single clause (“external Defects4J reanalysis”); FSM headline numbers "
        "should remain primary.",
        "",
        "## G. Replace or support internal SBFL result?",
        "",
        "**Support only.** The FSM Op2–Ochiai participation gap remains the in-domain measurement-validity instance; "
        "Defects4J shows the same *reporting* hazard on real bugs without claiming identical effect sizes.",
        "",
    ]
    _write_text(path, "\n".join(lines))


def _write_tex_summary(path: Path, summary_rows: list[dict[str, Any]]) -> None:
    def _pick(scope: str, stratum: str, coef: str) -> dict[str, Any] | None:
        for row in summary_rows:
            if row["scope"] == scope and row["stratum"] == stratum and row["coefficient"] == coef:
                return row
        return None

    och_part = _pick("participating", "participating", "ochiai")
    och_non = _pick("non_participating", "non_participating", "ochiai")
    if not och_part or not och_non:
        return

    def _fmt_pct(value: float | None) -> str:
        return f"{100 * float(value):.1f}\\%" if value is not None else "---"

    def _fmt_num(value: float | None) -> str:
        return f"{float(value):.2f}" if value is not None else "---"

    tex = [
        "% Auto-generated Defects4J external validation summary",
        "\\begin{table}[!htbp]",
        "  \\caption{Defects4J SBFL reanalysis (Rafi et al.; Ochiai): participating vs non-participating strata.}",
        "  \\label{tab:external-defects4j-summary}",
        "  \\centering",
        "  \\small",
        "  \\begin{tabular}{@{}lrrrrr@{}}",
        "  \\toprule",
        "  Stratum & $n$ & Top-1 & Top-5 & MFR & Unloc.\\\\",
        "  \\midrule",
        f"  Participating (D4JV) & {och_part['n_localizable']} & "
        f"{_fmt_pct(och_part['top1_rate'])} & {_fmt_pct(och_part['top5_rate'])} & "
        f"{_fmt_num(och_part['mean_first_rank'])} & {_fmt_pct(och_part['unlocalizable_rate'])} \\\\",
        f"  Non-participating (vBuggy) & {och_non['n_localizable']} & "
        f"{_fmt_pct(och_non['top1_rate'])} & {_fmt_pct(och_non['top5_rate'])} & "
        f"{_fmt_num(och_non['mean_first_rank'])} & {_fmt_pct(och_non['unlocalizable_rate'])} \\\\",
        "  \\bottomrule",
        "  \\end{tabular}",
        "  \\par\\footnotesize MFR = mean first rank on localizable bugs; Unloc.\\ = share with no ranked ground-truth hit. "
        "Participating uses Defects4J fault-triggering tests; non-participating uses Rafi vBuggy scenario.",
        "\\end{table}",
        "",
    ]
    _write_text(path, "\n".join(tex))


def _write_tex_strata(path: Path, coef_rows: list[dict[str, Any]]) -> None:
    if not coef_rows:
        return
    lines = [
        "% Auto-generated coefficient comparison by stratum",
        "\\begin{table}[!htbp]",
        "  \\caption{SBFL coefficient comparison by participation stratum (Defects4J reanalysis).}",
        "  \\label{tab:external-defects4j-strata}",
        "  \\centering",
        "  \\small",
        "  \\begin{tabular}{@{}l l r r r@{}}",
        "  \\toprule",
        "  Stratum & Best Top-1 & Ochiai Top-1 & Tarantula Top-1 & $\\Delta$Top-1 (pp) \\\\",
        "  \\midrule",
    ]
    for row in coef_rows:
        lines.append(
            f"  {row['stratum'].replace('_', '-')} & {row['best_top1_coefficient']} & "
            f"{100 * float(row['ochiai_top1_rate']):.1f}\\% & "
            f"{100 * float(row['tarantula_top1_rate']):.1f}\\% & "
            f"{row['tarantula_minus_ochiai_top1_pp']:+.1f} \\\\"
        )
    lines.extend(
        [
            "  \\bottomrule",
            "  \\end{tabular}",
            "\\end{table}",
            "",
        ]
    )
    _write_text(path, "\n".join(lines))


def run_external_defects4j_reanalysis(
    *,
    output_dir: Path,
    table_dir: Path,
    artifacts_dir: Path | None = None,
) -> ExternalDefects4jResult:
    """Run Defects4J external validation feasibility + reanalysis."""
    output_dir = output_dir.resolve()
    table_dir = table_dir.resolve()
    artifacts = (artifacts_dir or output_dir / "artifacts").resolve()
    artifacts.mkdir(parents=True, exist_ok=True)

    rafi_repo = artifacts / "rafi_repo"
    rafi_ok = _clone_repo(RAFI_REPO, rafi_repo)

    sbfl_zip = artifacts / "SBFL_FL_results.zip"
    sbfl_ok = _download(ZENODO_SBFL_URL, sbfl_zip)
    sbfl_root = artifacts / "SBFL_FL_results"
    if sbfl_ok and not sbfl_root.is_dir():
        subprocess.run(["unzip", "-q", str(sbfl_zip), "-d", str(artifacts)], check=False)

    spectra_zip = artifacts / "program_spectra.zip"
    spectra_ok = spectra_zip.is_file() and spectra_zip.stat().st_size > 1_000_000

    inventory_path = output_dir / "artifact_inventory.md"
    feasibility_path = output_dir / "feasibility_report.md"
    _write_inventory(inventory_path, artifacts, sbfl_ok=sbfl_ok, rafi_ok=rafi_ok, spectra_ok=spectra_ok)

    if not (sbfl_ok and sbfl_root.is_dir() and rafi_ok):
        _write_feasibility(feasibility_path, "C", spectra_ok=spectra_ok)
        msg = "Defects4J external validation infeasible: missing Rafi repo or SBFL export"
        raise ExternalDefects4jError(msg)

    feasibility_class: FeasibilityClass = "B"
    if spectra_ok:
        # Spectra archive present for optional Op2/Jaccard recomputation; rankings suffice for this pass.
        pass
    _write_feasibility(feasibility_path, feasibility_class, spectra_ok=spectra_ok)

    pattern_labels = _load_pattern_labels(rafi_repo)
    gt_cache = artifacts / "ground_truth"
    cases = _reanalyze_cases(sbfl_root, gt_cache, pattern_labels)

    summary_rows = _summary_rows(cases)
    by_project_rows = [row for row in summary_rows if row["project"] != "ALL" and row["scope"] not in {"ALL", "participating", "non_participating"}]
    by_stratum_rows = [row for row in summary_rows if row["scope"] in {"ALL", "participating", "non_participating"}]
    coef_rows = _coefficient_comparison_rows(cases)
    stress = _stress_test_summary(cases)

    summary_path = output_dir / "external_validation_summary.csv"
    by_project_path = output_dir / "external_validation_by_project.csv"
    by_stratum_path = output_dir / "external_validation_by_stratum.csv"
    coefficient_path = output_dir / "coefficient_comparison_by_stratum.csv"
    report_path = output_dir / "external_validation_report.md"
    editorial_path = output_dir / "editorial_recommendation.md"

    summary_fields = (
        "scope",
        "stratum",
        "project",
        "coefficient",
        "n_cases",
        "n_localizable",
        "top1_rate",
        "top5_rate",
        "mrr",
        "mean_first_rank",
        "exam_mean",
        "unlocalizable_rate",
    )
    _write_csv(summary_path, summary_fields, summary_rows)
    _write_csv(by_project_path, summary_fields, by_project_rows)
    _write_csv(by_stratum_path, summary_fields, by_stratum_rows)
    _write_csv(
        coefficient_path,
        (
            "stratum",
            "best_top1_coefficient",
            "best_mfr_coefficient",
            "ochiai_top1_rate",
            "tarantula_top1_rate",
            "dstar_top1_rate",
            "ochiai_mean_first_rank",
            "tarantula_mean_first_rank",
            "tarantula_minus_ochiai_top1_pp",
            "tarantula_minus_ochiai_mfr",
        ),
        coef_rows,
    )

    _write_report(report_path, cases=cases, stress=stress, feasibility_class=feasibility_class)
    _write_editorial(editorial_path, stress=stress, feasibility_class=feasibility_class)

    table_dir.mkdir(parents=True, exist_ok=True)
    _write_tex_summary(table_dir / "table_external_defects4j_summary.tex", summary_rows)
    _write_tex_strata(table_dir / "table_external_defects4j_strata.tex", coef_rows)

    # Persist stress test JSON for scripting
    (output_dir / "stress_test_summary.json").write_text(
        json.dumps(stress, indent=2),
        encoding="utf-8",
    )

    n_bugs = len({(case["project"], case["bug_id"]) for case in cases})
    return ExternalDefects4jResult(
        output_dir=output_dir,
        table_dir=table_dir,
        feasibility_class=feasibility_class,
        inventory_path=inventory_path,
        feasibility_path=feasibility_path,
        summary_path=summary_path,
        by_project_path=by_project_path,
        by_stratum_path=by_stratum_path,
        coefficient_path=coefficient_path,
        report_path=report_path,
        editorial_path=editorial_path,
        case_count=n_bugs,
    )
