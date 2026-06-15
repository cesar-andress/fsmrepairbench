"""Generate C1 baseline repair CSV, LaTeX tables, figures, and Zenodo manifests."""

from __future__ import annotations

import csv
import json
import shutil
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from fsmrepairbench.baseline_repair_campaign import (
    CAMPAIGN_LABEL,
    DEFAULT_COHORT_FILE,
    DEFAULT_RANDOM_SEEDS,
    DEFAULT_RAW_RUNS_DIR,
    DEFAULT_TOOLS_DIR,
    RELEASE_LABEL,
    ZENODO_DOI,
    load_cohort_manifest,
    publish_c1_manifests,
    run_c1_random_multiseed_analysis,
    write_c1_confidence_interval_exports,
)
from fsmrepairbench.dataset_builder import DatasetBuilderError, DatasetCaseRow, load_dataset_cases
from fsmrepairbench.freeze import sha256_file

C1_TOOL_IDS: tuple[str, ...] = (
    "baseline_missing_transition",
    "baseline_wrong_target",
    "baseline_random",
)
DEFAULT_V02_SUMMARY = Path("../paper1/results/v0_2_analysis/summary.csv")
FALLBACK_V02_SUMMARY = Path("results/analysis/summary.csv")


class C1BaselineRepairExportError(ValueError):
    """Raised when C1 baseline repair export inputs are invalid."""


@dataclass(frozen=True)
class C1BaselineRepairExportResult:
    """Paths written by :func:`generate_c1_baseline_repair_exports`."""

    output_dir: Path
    per_case_results_path: Path
    tool_run_summary_path: Path
    cohort_summary_path: Path
    leaderboard_path: Path
    report_path: Path
    manifest_path: Path
    figures_dir: Path
    tables_dir: Path


def _sync_paper_export(out_dir: Path, paper_export_dir: Path) -> None:
    """Mirror C1 artefacts into a separate frozen paper export directory."""
    if paper_export_dir.resolve() == out_dir.resolve():
        return
    paper_export_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "per_case_results.csv",
        "summary.csv",
        "cohort_summary.csv",
        "leaderboard.csv",
        "repair_by_operator.csv",
        "repair_by_complexity_tier.csv",
        "repair_by_operator_missing_transition.csv",
        "repair_by_operator_wrong_target.csv",
        "repair_by_operator_random.csv",
        "report.md",
        "README.md",
        "manifest.json",
        "confidence_intervals.csv",
        "confidence_intervals.json",
        "random_multiseed_summary.csv",
        "random_multiseed_summary.json",
        "random_multiseed_per_seed.csv",
    ):
        src = out_dir / name
        if src.is_file():
            shutil.copy2(src, paper_export_dir / name)
    if (out_dir / "cohort_summary.csv").is_file():
        shutil.copy2(out_dir / "cohort_summary.csv", paper_export_dir / "summary.csv")
    for subdir in ("figures", "tables", "notes", "multi_seed"):
        src_dir = out_dir / subdir
        if src_dir.is_dir():
            dest = paper_export_dir / subdir
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(src_dir, dest)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _rate(values: list[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0.0


def _mean(values: list[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _load_v02_detection(summary_path: Path | None) -> dict[str, float]:
    candidates = [summary_path, DEFAULT_V02_SUMMARY, FALLBACK_V02_SUMMARY]
    for path in candidates:
        if path is None or not path.is_file():
            continue
        out: dict[str, float] = {}
        for row in csv.DictReader(path.open(encoding="utf-8")):
            key = row["metric"]
            if key.startswith("detection_rate_"):
                out[key.removeprefix("detection_rate_")] = float(row["value"])
            if key == "overall_detection_rate":
                out["__overall__"] = float(row["value"])
        return out
    return {}


def _load_enriched_from_per_case(
    per_case_path: Path,
    cohort_ids: set[str],
) -> list[dict[str, str | float | bool | int]]:
    """Load enriched C1 rows from a frozen ``per_case_results.csv`` export."""
    if not per_case_path.is_file():
        msg = f"Missing per-case export: {per_case_path}"
        raise C1BaselineRepairExportError(msg)
    enriched: list[dict[str, str | float | bool | int]] = []
    for row in csv.DictReader(per_case_path.open(encoding="utf-8")):
        if row["case_id"] not in cohort_ids:
            continue
        parsed: dict[str, str | float | bool | int] = {
            "case_id": row["case_id"],
            "tool_id": row["tool_id"],
            "mutation_operator": row["mutation_operator"],
            "complexity_tier": row.get("complexity_tier", ""),
            "initial_bpr": float(row["initial_bpr"]),
            "final_bpr": float(row["final_bpr"]),
            "delta_bpr": float(row["delta_bpr"]),
            "complete_repair": row["complete_repair"].strip().lower() == "true",
            "effective_repair": row["effective_repair"].strip().lower() == "true",
            "regression": row.get("regression", "false").strip().lower() == "true",
            "faulty_bpr": float(row.get("faulty_bpr", row["initial_bpr"])),
            "reference_bpr": float(row.get("reference_bpr", "1.0")),
            "difficulty_score": float(row.get("difficulty_score", "0") or 0),
            "oracle_detected": row.get("oracle_detected", "false").strip().lower() == "true",
            "bpr_delta_pre_repair": float(row.get("bpr_delta_pre_repair", row["delta_bpr"])),
        }
        enriched.append(parsed)
    return enriched


def _tex_escape(name: str) -> str:
    return name.replace("_", "\\_")


def _tex_filename(name: str) -> str:
    return f"\\texttt{{{_tex_escape(name)}}}"


def _repair_table_note(
    *,
    csv_name: str,
    manifest_path: Path | None = None,
    cohort_path: Path | None = None,
    include_delta_zero_note: bool = False,
) -> str:
    parts = [
        "Cohort-wide complete/effective repair includes 505 oracle-saturated cases "
        "(faulty BPR $= 1.0$).",
    ]
    if include_delta_zero_note:
        parts.append(
            "Rows with detection $= 0\\%$ and mean $\\Delta$BPR $= 0$ but cohort-wide "
            "complete repair $= 100\\%$ reflect oracle saturation, not structural repair."
        )
    cohort_sha = ""
    if manifest_path and manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        cohort_sha = str(manifest.get("cohort_sha256", ""))[:16]
    elif cohort_path and cohort_path.is_file():
        cohort_sha = sha256_file(cohort_path)[:16]
    csv_sha = ""
    if manifest_path and manifest_path.is_file():
        csv_path = manifest_path.parent / csv_name
        if csv_path.is_file():
            csv_sha = sha256_file(csv_path)[:16]
    if csv_sha or cohort_sha:
        source_bits = []
        if csv_sha:
            source_bits.append(
                f"{_tex_filename(csv_name)} (SHA-256 prefix \\texttt{{{csv_sha}...}})"
            )
        if cohort_sha:
            source_bits.append(
                f"cohort digest prefix \\texttt{{{cohort_sha}...}} in {_tex_filename('manifest.json')}"
            )
        parts.append("Source: " + "; ".join(source_bits) + ".")
    return r"\par\footnotesize " + " ".join(parts)


def _load_tool_runs(summary_path: Path, cohort_ids: set[str]) -> list[dict[str, str | float | bool]]:
    if not summary_path.is_file():
        msg = f"Missing run-tools summary: {summary_path}"
        raise C1BaselineRepairExportError(msg)
    rows: list[dict[str, str | float | bool]] = []
    for row in csv.DictReader(summary_path.open(encoding="utf-8")):
        if row["case_id"] not in cohort_ids:
            continue
        parsed: dict[str, str | float | bool] = dict(row)
        for key in ("initial_bpr", "final_bpr", "delta_bpr", "runtime_seconds"):
            parsed[key] = float(row[key])
        for key in ("complete_repair", "effective_repair", "regression"):
            parsed[key] = row[key].strip().lower() == "true"
        rows.append(parsed)
    return rows


def _dataset_rows_by_id(dataset_dir: Path, cohort_ids: set[str]) -> dict[str, DatasetCaseRow]:
    try:
        rows = load_dataset_cases(dataset_dir)
    except DatasetBuilderError:
        return {}
    return {row.case_id: row for row in rows if row.case_id in cohort_ids}


def _enriched_rows(
    runs: list[dict[str, str | float | bool]],
    dataset_rows: dict[str, DatasetCaseRow],
) -> list[dict[str, str | float | bool | int]]:
    enriched: list[dict[str, str | float | bool | int]] = []
    for row in runs:
        meta = dataset_rows.get(str(row["case_id"]))
        if meta is None:
            faulty_bpr = float(row["initial_bpr"])
            ref_bpr = 1.0
            complexity = ""
            difficulty = 0.0
            bpr_delta_pre = 0.0
            operator = str(row["mutation_operator"])
        else:
            faulty_bpr = meta.faulty_bpr
            ref_bpr = meta.reference_bpr
            complexity = meta.complexity
            difficulty = meta.difficulty_score
            bpr_delta_pre = meta.bpr_delta
            operator = meta.mutation_operator
        detected = faulty_bpr < ref_bpr - 1e-9
        enriched.append(
            {
                **row,
                "complexity_tier": complexity,
                "difficulty_score": difficulty,
                "faulty_bpr": faulty_bpr,
                "reference_bpr": ref_bpr,
                "oracle_detected": detected,
                "bpr_delta_pre_repair": bpr_delta_pre,
                "mutation_operator": operator,
            }
        )
    return enriched


def _summary_metrics(enriched: list[dict], tool_id: str) -> dict[str, float | int | str]:
    subset = [row for row in enriched if row["tool_id"] == tool_id]
    detectable = [row for row in subset if row["oracle_detected"]]
    oracle_saturated_cases = len(subset) - len(detectable)
    return {
        "tool_id": tool_id,
        "cases": len(subset),
        "complete_repair_rate": round(_rate([bool(row["complete_repair"]) for row in subset]), 6),
        "effective_repair_rate": round(_rate([bool(row["effective_repair"]) for row in subset]), 6),
        "regression_rate": round(_rate([bool(row["regression"]) for row in subset]), 6),
        "mean_delta_bpr": round(_mean([float(row["delta_bpr"]) for row in subset]), 6),
        "mean_initial_bpr": round(_mean([float(row["initial_bpr"]) for row in subset]), 6),
        "mean_final_bpr": round(_mean([float(row["final_bpr"]) for row in subset]), 6),
        "complete_repair_rate_detectable_only": round(
            _rate([bool(row["complete_repair"]) for row in detectable]),
            6,
        )
        if detectable
        else 0.0,
        "effective_repair_rate_detectable_only": round(
            _rate([bool(row["effective_repair"]) for row in detectable]),
            6,
        )
        if detectable
        else 0.0,
        "detectable_cases": len(detectable),
        "oracle_saturated_cases": oracle_saturated_cases,
    }


def _operator_table(
    enriched: list[dict],
    tool_id: str,
    detection: dict[str, float],
) -> list[dict]:
    by_op: dict[str, list[dict]] = defaultdict(list)
    for row in enriched:
        if row["tool_id"] == tool_id:
            by_op[str(row["mutation_operator"])].append(row)
    rows: list[dict] = []
    for operator in sorted(by_op):
        items = by_op[operator]
        detectable_items = [row for row in items if row["oracle_detected"]]
        rows.append(
            {
                "mutation_operator": operator,
                "cases": len(items),
                "detectable_cases": len(detectable_items),
                "oracle_saturated_cases": len(items) - len(detectable_items),
                "detection_rate": detection.get(operator, float("nan")),
                "mean_faulty_bpr": round(_mean([float(row["faulty_bpr"]) for row in items]), 6),
                "complete_repair_rate": round(
                    _rate([bool(row["complete_repair"]) for row in items]),
                    6,
                ),
                "complete_repair_rate_detectable_only": round(
                    _rate([bool(row["complete_repair"]) for row in detectable_items]),
                    6,
                )
                if detectable_items
                else 0.0,
                "effective_repair_rate": round(
                    _rate([bool(row["effective_repair"]) for row in items]),
                    6,
                ),
                "effective_repair_rate_detectable_only": round(
                    _rate([bool(row["effective_repair"]) for row in detectable_items]),
                    6,
                )
                if detectable_items
                else 0.0,
                "mean_delta_bpr": round(_mean([float(row["delta_bpr"]) for row in items]), 6),
            }
        )
    return rows


def _tier_table(enriched: list[dict], tool_id: str) -> list[dict]:
    by_tier: dict[str, list[dict]] = defaultdict(list)
    for row in enriched:
        if row["tool_id"] == tool_id:
            by_tier[str(row["complexity_tier"])].append(row)
    order = ("small", "medium", "large", "very_large")
    rows: list[dict] = []
    for tier in order:
        items = by_tier.get(tier, [])
        if not items:
            continue
        detectable_items = [row for row in items if row["oracle_detected"]]
        rows.append(
            {
                "complexity_tier": tier,
                "cases": len(items),
                "detectable_cases": len(detectable_items),
                "oracle_saturated_cases": len(items) - len(detectable_items),
                "complete_repair_rate": round(
                    _rate([bool(row["complete_repair"]) for row in items]),
                    6,
                ),
                "complete_repair_rate_detectable_only": round(
                    _rate([bool(row["complete_repair"]) for row in detectable_items]),
                    6,
                )
                if detectable_items
                else 0.0,
                "mean_delta_bpr": round(_mean([float(row["delta_bpr"]) for row in items]), 6),
                "mean_difficulty_score": round(
                    _mean([float(row["difficulty_score"]) for row in items]),
                    2,
                ),
            }
        )
    return rows


def _tex_pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _write_tex_table(
    path: Path,
    caption: str,
    label: str,
    headers: list[str],
    rows: list[list[str]],
    *,
    note: str | None = None,
) -> None:
    if " Takeaway: " in caption and "\nTakeaway:" not in caption:
        lead, takeaway = caption.split(" Takeaway: ", 1)
        caption = f"{lead}\nTakeaway: {takeaway}"
    col_spec = "@{}" + "l" + "r" * (len(headers) - 1) + "@{}"
    lines = [
        "% Auto-generated from fsmrepairbench.c1_baseline_repair_exports",
        "\\begin{table}[t]",
        f"\\caption{{{caption}}}",
        f"\\label{{{label}}}",
        f"\\begin{{tabular}}{{{col_spec}}}",
        "\\toprule",
        " & ".join(headers) + " \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(" & ".join(row) + " \\\\")
    lines.extend(["\\bottomrule", "\\end{tabular}"])
    if note:
        lines.append(note)
    lines.extend(["\\end{table}", ""])
    path.write_text("\n".join(lines), encoding="utf-8")


def _make_figures(enriched: list[dict], *, figures_dir: Path, case_count: int) -> None:
    import matplotlib.pyplot as plt

    figures_dir.mkdir(parents=True, exist_ok=True)
    primary = "baseline_missing_transition"

    primary_rows = [row for row in enriched if row["tool_id"] == primary]
    detectable_primary = [row for row in primary_rows if row["oracle_detected"]]
    finals = [float(row["final_bpr"]) for row in primary_rows]
    plt.figure(figsize=(8, 4))
    plt.hist(finals, bins=20, color="#2c7bb6", edgecolor="white")
    plt.xlabel("Final BPR after repair")
    plt.ylabel("Case count")
    plt.title(
        f"Final BPR distribution ({primary}, n={case_count}; "
        f"{len(detectable_primary)} detectable, {case_count - len(detectable_primary)} oracle-saturated)"
    )
    plt.tight_layout()
    plt.savefig(figures_dir / "repair_success_histogram.png", dpi=150)
    plt.close()

    operators = sorted({str(row["mutation_operator"]) for row in enriched})
    x = range(len(operators))
    width = 0.25
    plt.figure(figsize=(14, 5))
    for idx, tool_id in enumerate(C1_TOOL_IDS):
        means = []
        for operator in operators:
            items = [
                row
                for row in enriched
                if row["tool_id"] == tool_id
                and row["mutation_operator"] == operator
                and row["oracle_detected"]
            ]
            means.append(_mean([float(row["delta_bpr"]) for row in items]) if items else 0.0)
        offset = (idx - 1) * width
        plt.bar([i + offset for i in x], means, width=width, label=tool_id.replace("baseline_", ""))
    plt.xticks(list(x), operators, rotation=45, ha="right")
    plt.axhline(0.0, color="black", linewidth=0.8)
    plt.ylabel("Mean ΔBPR")
    plt.title("Mean ΔBPR by mutation operator and baseline (detectable faults only)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures_dir / "delta_bpr_by_operator.png", dpi=150)
    plt.close()

    tier_rows = _tier_table(enriched, primary)
    tiers = [row["complexity_tier"] for row in tier_rows]
    detectable_rates = [row["complete_repair_rate_detectable_only"] for row in tier_rows]
    cohort_rates = [row["complete_repair_rate"] for row in tier_rows]
    x = range(len(tiers))
    width = 0.35
    plt.figure(figsize=(8, 4))
    plt.bar([i - width / 2 for i in x], detectable_rates, width=width, label="Detectable only", color="#2c7bb6")
    plt.bar([i + width / 2 for i in x], cohort_rates, width=width, label="Cohort-wide", color="#fdae61")
    plt.xticks(list(x), tiers)
    plt.ylim(0, 1.05)
    plt.ylabel("Complete repair rate")
    plt.xlabel("Complexity tier")
    plt.title(f"Complete repair by tier ({primary}; detectable vs cohort-wide)")
    plt.legend()
    plt.tight_layout()
    plt.savefig(figures_dir / "repair_rate_by_complexity_tier.png", dpi=150)
    plt.close()


def _default_regeneration_commands(*, dataset_path: str, out_dir: str, workers: int) -> list[str]:
    return [
        (
            f"fsmrepairbench run-tools {dataset_path} {DEFAULT_TOOLS_DIR}/ "
            f"--out {out_dir} "
            f"--cohort-file {dataset_path}/{DEFAULT_COHORT_FILE} "
            f"--workers {workers}"
        ),
        (
            f"fsmrepairbench export-c1-baseline-repair {dataset_path} "
            f"--out {out_dir} --workers {workers}"
        ),
    ]


def generate_c1_baseline_repair_exports(
    dataset_dir: Path,
    *,
    out_dir: Path,
    cohort_file: Path | None = None,
    tools_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    v02_summary_path: Path | None = None,
    workers: int = 4,
    random_seeds: Sequence[int] = DEFAULT_RANDOM_SEEDS,
    skip_multi_seed: bool = False,
    write_per_seed_json: bool = True,
    repo_root: Path | None = None,
) -> C1BaselineRepairExportResult:
    """Write C1 CSV/LaTeX/PNG exports and Zenodo manifests from run-tools output."""
    repo_root = repo_root or Path(__file__).resolve().parents[2]
    cohort_path = cohort_file or (dataset_dir / DEFAULT_COHORT_FILE)
    tools_path = tools_dir or (repo_root / DEFAULT_TOOLS_DIR)
    cohort_ids = set(load_cohort_manifest(cohort_path))
    case_count = len(cohort_ids)
    detection = _load_v02_detection(v02_summary_path)

    per_case_path = out_dir / "per_case_results.csv"
    summary_path = out_dir / "summary.csv"
    if per_case_path.is_file():
        enriched = _load_enriched_from_per_case(per_case_path, cohort_ids)
    elif summary_path.is_file():
        runs = _load_tool_runs(summary_path, cohort_ids)
        if not runs:
            msg = (
                f"No run-tools rows matched cohort ({case_count} cases) in {summary_path}"
            )
            raise C1BaselineRepairExportError(msg)
        dataset_rows = _dataset_rows_by_id(dataset_dir, cohort_ids)
        enriched = _enriched_rows(runs, dataset_rows)
    else:
        msg = f"Missing C1 run output in {out_dir} (expected per_case_results.csv or summary.csv)"
        raise C1BaselineRepairExportError(msg)
    detectable_case_ids = {
        str(row["case_id"]) for row in enriched if row["oracle_detected"]
    }
    detectable_count = len(detectable_case_ids)
    saturated_count = case_count - detectable_count

    out_dir.mkdir(parents=True, exist_ok=True)
    figures_dir = out_dir / "figures"
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    per_case_fields = list(enriched[0].keys()) if enriched else []
    per_case_path = out_dir / "per_case_results.csv"
    _write_csv(per_case_path, per_case_fields, enriched)

    summaries = [_summary_metrics(enriched, tool_id) for tool_id in C1_TOOL_IDS]
    summary_rows = [{"metric": key, "value": value} for summary in summaries for key, value in summary.items()]
    cohort_summary_path = out_dir / "cohort_summary.csv"
    _write_csv(cohort_summary_path, ["metric", "value"], summary_rows)

    leaderboard_fields = [
        "tool_id",
        "cases",
        "detectable_cases",
        "oracle_saturated_cases",
        "complete_repair_rate_detectable_only",
        "effective_repair_rate_detectable_only",
        "complete_repair_rate",
        "effective_repair_rate",
        "regression_rate",
        "mean_delta_bpr",
        "mean_initial_bpr",
        "mean_final_bpr",
    ]
    leaderboard_path = out_dir / "leaderboard.csv"
    _write_csv(leaderboard_path, leaderboard_fields, summaries)

    op_primary = _operator_table(enriched, "baseline_missing_transition", detection)
    op_wrong = _operator_table(enriched, "baseline_wrong_target", detection)
    _write_csv(
        out_dir / "repair_by_operator.csv",
        list(op_primary[0].keys()) if op_primary else ["mutation_operator"],
        op_primary,
    )
    for tool_id in C1_TOOL_IDS:
        slug = tool_id.removeprefix("baseline_")
        operator_rows = _operator_table(enriched, tool_id, detection)
        _write_csv(
            out_dir / f"repair_by_operator_{slug}.csv",
            list(operator_rows[0].keys()) if operator_rows else ["mutation_operator"],
            operator_rows,
        )

    tier_primary = _tier_table(enriched, "baseline_missing_transition")
    _write_csv(
        out_dir / "repair_by_complexity_tier.csv",
        list(tier_primary[0].keys()) if tier_primary else ["complexity_tier"],
        tier_primary,
    )

    cohort_sha_prefix = sha256_file(cohort_path)[:16]
    repair_note = _repair_table_note(
        csv_name="leaderboard.csv",
        manifest_path=out_dir / "manifest.json",
        cohort_path=cohort_path,
        include_delta_zero_note=False,
    )
    repair_note_with_delta = _repair_table_note(
        csv_name="leaderboard.csv",
        manifest_path=out_dir / "manifest.json",
        cohort_path=cohort_path,
        include_delta_zero_note=True,
    )
    _write_tex_table(
        tables_dir / "table_dataset_summary.tex",
        "Metadata linking the C1 baseline repair campaign to the v0.2.0-analysis cohort "
        f"($n={case_count:,}$; {detectable_count} oracle-detectable, {saturated_count} "
        "oracle-saturated at faulty BPR $= 1.0$). "
        f"Takeaway: overall oracle mutation detection is "
        f"{_tex_pct(detection.get('__overall__', 0.495))}; repairability is reported on the "
        "detectable subset as the primary partition.",
        "tab:baseline-dataset-summary",
        ["Metric", "Value"],
        [
            ["Analyzed cases", f"{case_count:,}"],
            ["Oracle-detectable cases", f"{detectable_count:,}"],
            ["Oracle-saturated cases (faulty BPR $= 1.0$)", f"{saturated_count:,}"],
            ["Cohort manifest", f"\\texttt{{{_tex_escape(cohort_path.name)}}}"],
            [
                "Cohort manifest SHA-256 (prefix)",
                f"\\texttt{{{cohort_sha_prefix}...}}",
            ],
            ["Tools", "3 (missing-transition, wrong-target, random)"],
            [
                "Overall detection rate (v0.2.0-analysis)",
                f"{detection.get('__overall__', 0.495):.4f}",
            ],
        ],
        note=_repair_table_note(
            csv_name="per_case_results.csv",
            manifest_path=out_dir / "manifest.json",
            cohort_path=cohort_path,
        ),
    )

    det_rows = [
        [
            _tex_escape(row["mutation_operator"]),
            str(row["cases"]),
            f"{row['detection_rate']:.4f}"
            if row["detection_rate"] == row["detection_rate"]
            else "---",
            f"{row['mean_faulty_bpr']:.4f}",
        ]
        for row in op_primary
    ]
    _write_tex_table(
        tables_dir / "table_mutation_detection.tex",
        f"Oracle mutation detection rate and mean faulty behavioural pass rate (BPR) by operator "
        f"($n={case_count:,}$).",
        "tab:baseline-mutation-detection",
        ["Operator", "Cases", "Detection rate", "Mean faulty BPR"],
        det_rows,
    )

    repair_rows = [
        [
            _tex_escape(row["mutation_operator"]),
            str(row["detectable_cases"]),
            f"{row['detection_rate']:.4f}"
            if row["detection_rate"] == row["detection_rate"]
            else "---",
            _tex_pct(row["complete_repair_rate_detectable_only"]),
            _tex_pct(row["complete_repair_rate"]),
            f"{row['mean_delta_bpr']:.4f}",
        ]
        for row in op_primary
    ]
    _write_tex_table(
        tables_dir / "table_repair_by_operator.tex",
        "Repair outcomes by mutation operator under the \\texttt{missing-transition} baseline "
        f"($n={case_count:,}$ cohort). \\textbf{{Detectable-only primary}}; "
        f"cohort-wide$^\\dagger$ includes {saturated_count}/1{{,}}000 oracle-saturated cases.",
        "tab:baseline-repair-by-operator",
        [
            "Operator",
            "Detectable",
            "Detection",
            "Complete (detectable-only)",
            "Complete (cohort-wide$^\\dagger$)",
            "Mean $\\Delta$BPR",
        ],
        repair_rows,
        note=repair_note_with_delta,
    )

    tier_rows = [
        [
            _tex_escape(row["complexity_tier"]),
            str(row["detectable_cases"]),
            _tex_pct(row["complete_repair_rate_detectable_only"]),
            _tex_pct(row["complete_repair_rate"]),
            f"{row['mean_difficulty_score']:.2f}",
            f"{row['mean_delta_bpr']:.4f}",
        ]
        for row in tier_primary
    ]
    _write_tex_table(
        tables_dir / "table_repair_by_tier.tex",
        "Complete repair by structural complexity tier under the \\texttt{missing-transition} "
        f"baseline ($n={case_count:,}$). \\textbf{{Detectable-only primary}}; "
        f"cohort-wide$^\\dagger$ includes {saturated_count}/1{{,}}000 oracle-saturated cases.",
        "tab:baseline-repair-by-tier",
        [
            "Tier",
            "Detectable",
            "Complete (detectable-only)",
            "Complete (cohort-wide$^\\dagger$)",
            "Mean difficulty",
            "Mean $\\Delta$BPR",
        ],
        tier_rows,
        note=repair_note_with_delta,
    )

    lb_rows = [
        [
            _tex_escape(str(summary["tool_id"])),
            str(summary["cases"]),
            _tex_pct(summary["complete_repair_rate_detectable_only"]),
            _tex_pct(summary["complete_repair_rate"]),
            _tex_pct(summary["effective_repair_rate_detectable_only"]),
            _tex_pct(summary["effective_repair_rate"]),
            f"{summary['mean_delta_bpr']:.4f}",
        ]
        for summary in summaries
    ]
    _write_tex_table(
        tables_dir / "table_baseline_leaderboard.tex",
        "C1 baseline repair leaderboard ($n=1{,}000$). "
        f"\\textbf{{Detectable-only primary}} ($n={detectable_count}$); "
        f"cohort-wide$^\\dagger$ columns include {saturated_count}/1{{,}}000 oracle-saturated cases "
        "(faulty BPR $= 1.0$).",
        "tab:baseline-leaderboard",
        [
            "Tool",
            "Cases",
            "Complete (detectable-only)",
            "Complete (cohort-wide$^\\dagger$)",
            "Effective (detectable-only)",
            "Effective (cohort-wide$^\\dagger$)",
            "Mean $\\Delta$BPR",
        ],
        lb_rows,
        note=repair_note,
    )

    _make_figures(enriched, figures_dir=figures_dir, case_count=case_count)

    report_lines = [
        "# C1 Baseline Repair Experiment Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        f"Dataset: `{dataset_dir}`",
        f"Cohort: `{cohort_path}` ({case_count} cases)",
        f"Run-tools output: `{out_dir}`",
        "",
        "## Leaderboard",
        "",
    ]
    for summary in summaries:
        report_lines.append(
            f"- **{summary['tool_id']}**: detectable-only complete="
            f"{summary['complete_repair_rate_detectable_only']:.4f}, "
            f"detectable-only effective="
            f"{summary['effective_repair_rate_detectable_only']:.4f} "
            f"(n={summary['detectable_cases']}); cohort-wide complete="
            f"{summary['complete_repair_rate']:.4f}, effective="
            f"{summary['effective_repair_rate']:.4f} "
            f"(includes {summary['oracle_saturated_cases']} oracle-saturated); "
            f"mean ΔBPR={summary['mean_delta_bpr']:.4f}"
        )
    report_lines.extend(
        [
            "",
            "## Outputs",
            "",
            "- `per_case_results.csv`",
            "- `summary.csv` (per-case run-tools rows)",
            "- `cohort_summary.csv`",
            "- `leaderboard.csv`",
            "- `manifest.json`",
            "- `figures/` (PNG)",
            "- `tables/` (LaTeX)",
        ]
    )
    report_path = out_dir / "report.md"
    report_path.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    readme = f"""# C1 Baseline Repair Results

Experiment **C1**: deterministic baseline repair on the pinned analysis cohort.

| Field | Value |
|-------|-------|
| Cases analyzed | {case_count} |
| DOI | [{ZENODO_DOI}](https://doi.org/{ZENODO_DOI}) |
| Release label | {RELEASE_LABEL} |
| Campaign | {CAMPAIGN_LABEL} |
| Tools | missing-transition, wrong-target, random |
| Cohort | `{cohort_path.name}` |

Regenerate:

```bash
cd fsmrepairbench
fsmrepairbench run-tools {dataset_dir} {DEFAULT_TOOLS_DIR}/ \\
  --out {out_dir} \\
  --cohort-file {cohort_path} \\
  --workers {workers}
fsmrepairbench export-c1-baseline-repair {dataset_dir} \\
  --out {out_dir} \\
  --cohort-file {cohort_path} \\
  --workers {workers}
```

One-shot:

```bash
fsmrepairbench run-c1-baseline-repair {dataset_dir} --out {out_dir} --workers {workers}
```
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")

    write_c1_confidence_interval_exports(
        raw_runs_dir=out_dir,
        dataset_dir=dataset_dir,
        cohort_file=cohort_path,
        paper_export_dir=paper_export_dir or out_dir,
    )

    if not skip_multi_seed:
        multiseed = run_c1_random_multiseed_analysis(
            dataset_dir,
            cohort_path,
            tools_path,
            out_dir,
            paper_export_dir or out_dir,
            random_seeds=random_seeds,
            workers=workers,
            write_per_seed_json=write_per_seed_json,
        )
        report_path.write_text(
            report_path.read_text(encoding="utf-8").rstrip()
            + "\n\n"
            + multiseed.report_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    dataset_rel = str(dataset_dir)
    out_rel = str(out_dir)
    manifest_result = publish_c1_manifests(
        dataset_dir=dataset_dir,
        cohort_file=cohort_path,
        tools_dir=tools_path,
        raw_runs_dir=out_dir,
        paper_export_dir=paper_export_dir or out_dir,
        workers=workers,
        number_of_cases=case_count,
        regeneration_commands=_default_regeneration_commands(
            dataset_path=dataset_rel,
            out_dir=out_rel,
            workers=workers,
        ),
        repo_root=repo_root,
    )

    paper_dir = paper_export_dir or out_dir
    _sync_paper_export(out_dir, paper_dir)

    return C1BaselineRepairExportResult(
        output_dir=out_dir,
        per_case_results_path=per_case_path,
        tool_run_summary_path=out_dir / "summary.csv",
        cohort_summary_path=cohort_summary_path,
        leaderboard_path=leaderboard_path,
        report_path=report_path,
        manifest_path=manifest_result.paper_manifest_path,
        figures_dir=figures_dir,
        tables_dir=tables_dir,
    )


@dataclass(frozen=True)
class C1BaselineRepairExperimentResult:
    """Paths produced by the end-to-end C1 baseline repair experiment."""

    output_dir: Path
    tool_run_summary_path: Path
    export: C1BaselineRepairExportResult


def run_c1_baseline_repair_experiment(
    dataset_dir: Path,
    *,
    out_dir: Path | None = None,
    cohort_file: Path | None = None,
    tools_dir: Path | None = None,
    paper_export_dir: Path | None = None,
    workers: int = 4,
    random_seeds: Sequence[int] = DEFAULT_RANDOM_SEEDS,
    resume: bool = True,
    skip_tool_runs: bool = False,
    skip_multi_seed: bool = False,
    write_per_seed_json: bool = True,
    v02_summary_path: Path | None = None,
    repo_root: Path | None = None,
) -> C1BaselineRepairExperimentResult:
    """Run C1 baseline repair on the pinned cohort and write frozen exports."""
    from fsmrepairbench.tool_runner import run_tools

    repo_root = repo_root or Path(__file__).resolve().parents[2]
    output_dir = out_dir or (repo_root / DEFAULT_RAW_RUNS_DIR)
    cohort_path = cohort_file or (dataset_dir / DEFAULT_COHORT_FILE)
    tools_path = tools_dir or (repo_root / DEFAULT_TOOLS_DIR)
    paper_dir = paper_export_dir or output_dir

    if not skip_tool_runs:
        tool_result = run_tools(
            dataset_dir,
            tools_path,
            output_dir,
            cohort_file=cohort_path,
            resume=resume,
            workers=workers,
        )
        summary_path = tool_result.summary_path
    else:
        summary_path = output_dir / "summary.csv"
        if not summary_path.is_file():
            msg = f"Missing run-tools summary for export-only mode: {summary_path}"
            raise C1BaselineRepairExportError(msg)

    export_result = generate_c1_baseline_repair_exports(
        dataset_dir,
        out_dir=output_dir,
        cohort_file=cohort_path,
        tools_dir=tools_path,
        paper_export_dir=paper_dir,
        v02_summary_path=v02_summary_path,
        workers=workers,
        random_seeds=random_seeds,
        skip_multi_seed=skip_multi_seed,
        write_per_seed_json=write_per_seed_json,
        repo_root=repo_root,
    )
    return C1BaselineRepairExperimentResult(
        output_dir=output_dir,
        tool_run_summary_path=summary_path,
        export=export_result,
    )
