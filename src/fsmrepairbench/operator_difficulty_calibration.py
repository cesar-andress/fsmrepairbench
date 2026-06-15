"""Empirical operator-level benchmark difficulty calibration."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

DifficultyTier = Literal["easy", "medium", "hard"]

OPERATOR_DIFFICULTY_CSV_COLUMNS: tuple[str, ...] = (
    "mutation_operator",
    "cases",
    "detectable_cases",
    "detection_rate",
    "localization_top1",
    "localization_top5",
    "localization_mrr",
    "complete_repair_rate_detectable",
    "effective_repair_rate_detectable",
    "difficulty_index",
    "difficulty_tier",
    "difficulty_rank",
)

DIFFICULTY_INDEX_COMPONENTS: tuple[str, ...] = (
    "detection_rate",
    "localization_top5",
    "complete_repair_rate_detectable",
)


@dataclass(frozen=True)
class OperatorDifficultyExportResult:
    """Paths written by :func:`write_operator_difficulty_exports`."""

    csv_path: Path
    tex_path: Path
    figure_path: Path
    summary_path: Path
    paper_csv_path: Path | None = None
    paper_tex_path: Path | None = None
    paper_figure_path: Path | None = None
    paper_summary_path: Path | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        msg = f"Missing CSV: {path}"
        raise FileNotFoundError(msg)
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _localization_by_operator(audit_path: Path) -> dict[str, dict[str, float | int]]:
    """Aggregate Ochiai top-k and MRR on transition-localizable ground truth."""
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in _read_csv(audit_path):
        if row.get("ground_truth_localizable", "").strip().lower() != "true":
            continue
        if row.get("localized", "").strip().lower() != "true":
            continue
        grouped[row["mutation_operator"]].append(row)

    summary: dict[str, dict[str, float | int]] = {}
    for operator, rows in grouped.items():
        top1 = sum(row.get("top1_hit", "").strip().lower() == "true" for row in rows) / len(rows)
        top5 = sum(row.get("top5_hit", "").strip().lower() == "true" for row in rows) / len(rows)
        mrr_values = [
            float(row["reciprocal_rank"])
            for row in rows
            if row.get("reciprocal_rank", "").strip() not in {"", "nan"}
        ]
        mrr = statistics.mean(mrr_values) if mrr_values else 0.0
        summary[operator] = {
            "localizable_cases": len(rows),
            "localization_top1": round(top1, 6),
            "localization_top5": round(top5, 6),
            "localization_mrr": round(mrr, 6),
        }
    return summary


def compute_operator_difficulty_rows(
    *,
    repair_by_operator_path: Path,
    localizability_audit_path: Path,
    repair_tool: str = "missing-transition",
) -> list[dict[str, Any]]:
    """Merge detection, localization, and repair metrics per mutation operator."""
    repair_rows = _read_csv(repair_by_operator_path)
    localization = _localization_by_operator(localizability_audit_path)
    merged: list[dict[str, Any]] = []

    for row in repair_rows:
        operator = row["mutation_operator"]
        loc = localization.get(
            operator,
            {
                "localizable_cases": 0,
                "localization_top1": 0.0,
                "localization_top5": 0.0,
                "localization_mrr": 0.0,
            },
        )
        detection_rate = float(row["detection_rate"])
        complete_detectable = float(row["complete_repair_rate_detectable_only"])
        effective_detectable = float(row["effective_repair_rate_detectable_only"])
        component_mean = statistics.mean(
            [
                detection_rate,
                float(loc["localization_top5"]),
                complete_detectable,
            ]
        )
        difficulty_index = round(1.0 - component_mean, 6)
        merged.append(
            {
                "mutation_operator": operator,
                "cases": int(row["cases"]),
                "detectable_cases": int(row["detectable_cases"]),
                "detection_rate": round(detection_rate, 6),
                "localization_top1": float(loc["localization_top1"]),
                "localization_top5": float(loc["localization_top5"]),
                "localization_mrr": float(loc["localization_mrr"]),
                "localizable_cases": int(loc["localizable_cases"]),
                "complete_repair_rate_detectable": round(complete_detectable, 6),
                "effective_repair_rate_detectable": round(effective_detectable, 6),
                "repair_tool": repair_tool,
                "difficulty_index": difficulty_index,
            }
        )
    return merged


def assign_difficulty_tiers(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign easy/medium/hard tiers by rank tertiles (hardest third first)."""
    if not rows:
        return rows
    ranked = sorted(rows, key=lambda row: (-row["difficulty_index"], row["mutation_operator"]))
    n = len(ranked)
    hard_cutoff = (n + 2) // 3
    medium_cutoff = (2 * n + 2) // 3

    output: list[dict[str, Any]] = []
    for rank, row in enumerate(ranked, start=1):
        if rank <= hard_cutoff:
            tier: DifficultyTier = "hard"
        elif rank <= medium_cutoff:
            tier = "medium"
        else:
            tier = "easy"
        updated = dict(row)
        updated["difficulty_tier"] = tier
        updated["difficulty_rank"] = rank
        output.append(updated)
    return output


def summarize_operator_difficulty(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Build JSON summary for operator difficulty calibration."""
    tiers: dict[str, list[str]] = {"easy": [], "medium": [], "hard": []}
    for row in rows:
        tiers[str(row["difficulty_tier"])].append(str(row["mutation_operator"]))
    scores = [float(row["difficulty_index"]) for row in rows]
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "operator_count": len(rows),
        "difficulty_index_definition": (
            "1 - mean(detection_rate, localization_top5 on transition-localizable GT, "
            "complete_repair_rate_detectable under missing-transition baseline)"
        ),
        "difficulty_index_components": list(DIFFICULTY_INDEX_COMPONENTS),
        "mean_difficulty_index": round(statistics.mean(scores), 6) if scores else 0.0,
        "median_difficulty_index": round(statistics.median(scores), 6) if scores else 0.0,
        "tier_counts": {tier: len(operators) for tier, operators in tiers.items()},
        "operators_by_tier": tiers,
        "operators": rows,
    }


def _tex_escape(value: str) -> str:
    return value.replace("_", "\\_")


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def _write_operator_difficulty_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=OPERATOR_DIFFICULTY_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in OPERATOR_DIFFICULTY_CSV_COLUMNS})


def _write_difficulty_ranking_tex(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    body: list[str] = [
        "\\begin{tabular}{@{}rlrrrrrrrr@{}}",
        "\\toprule",
        "Rank & Operator & Detect & Top-1 & Top-5 & MRR & Complete & Effective & Index & Tier \\\\",
        "\\midrule",
    ]
    for row in rows:
        body.append(
            " & ".join(
                [
                    str(row["difficulty_rank"]),
                    f"\\texttt{{{_tex_escape(str(row['mutation_operator']))}}}",
                    _pct(float(row["detection_rate"])),
                    _pct(float(row["localization_top1"])),
                    _pct(float(row["localization_top5"])),
                    f"{float(row['localization_mrr']):.3f}",
                    _pct(float(row["complete_repair_rate_detectable"])),
                    _pct(float(row["effective_repair_rate_detectable"])),
                    f"{float(row['difficulty_index']):.3f}",
                    str(row["difficulty_tier"]),
                ]
            )
            + " \\\\"
        )
    body.extend(["\\bottomrule", "\\end{tabular}"])
    tier_text = (
        f"easy ({summary['tier_counts']['easy']}), "
        f"medium ({summary['tier_counts']['medium']}), "
        f"hard ({summary['tier_counts']['hard']})"
    )
    tex = (
        "\\begin{table}[t]\n"
        "\\caption{Operator-level benchmark difficulty calibration on the "
        "1{,}000-case \\texttt{plain\\_fsm}/shallow-oracle cohort. "
        "Detection and repair use cohort-wide operator counts; localization metrics "
        "use Ochiai on transition-localizable ground truth only. "
        f"Difficulty index $=1-\\mathrm{{mean}}($detection, top-5, detectable-only complete repair$)$; "
        f"tiers by rank tertiles ({tier_text}). "
        "Takeaway: difficulty spans oracle-invisible families (index $\\approx 1.0$) "
        "to aligned transition faults with high repair success (index $<0.35$).}\n"
        "\\label{tab:operator-difficulty-ranking}\n"
        "\\small\n"
        + "\n".join(body)
        + "\n\\end{table}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")


def _write_difficulty_heatmap(path: Path, rows: list[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    columns = [
        ("detection_rate", "Detection"),
        ("localization_top1", "Top-1"),
        ("localization_top5", "Top-5"),
        ("localization_mrr", "MRR"),
        ("complete_repair_rate_detectable", "Complete"),
        ("effective_repair_rate_detectable", "Effective"),
        ("difficulty_index", "Difficulty"),
    ]
    ordered = sorted(rows, key=lambda row: (-float(row["difficulty_index"]), str(row["mutation_operator"])))
    operators = [str(row["mutation_operator"]) for row in ordered]
    matrix = np.array([[float(row[key]) for key, _label in columns] for row in ordered])

    fig_height = max(6.0, 0.28 * len(operators) + 1.5)
    fig, ax = plt.subplots(figsize=(10, fig_height))
    im = ax.imshow(matrix, aspect="auto", cmap="YlOrRd", vmin=0.0, vmax=1.0)
    ax.set_xticks(range(len(columns)))
    ax.set_xticklabels([label for _key, label in columns], rotation=30, ha="right")
    ax.set_yticks(range(len(operators)))
    ax.set_yticklabels(operators, fontsize=8)
    for row_index in range(matrix.shape[0]):
        for col_index in range(matrix.shape[1]):
            ax.text(
                col_index,
                row_index,
                f"{matrix[row_index, col_index]:.2f}",
                ha="center",
                va="center",
                color="black" if matrix[row_index, col_index] < 0.72 else "white",
                fontsize=7,
            )
    fig.colorbar(im, ax=ax, shrink=0.85, label="Normalized score (higher = harder for Difficulty column)")
    ax.set_title("Operator difficulty calibration heatmap (sorted by difficulty index)")
    fig.subplots_adjust(left=0.22, bottom=0.12, right=0.92, top=0.94)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def write_operator_difficulty_exports(
    *,
    repair_by_operator_path: Path,
    localizability_audit_path: Path,
    out_dir: Path,
    paper_export_dir: Path | None = None,
    repair_tool: str = "missing-transition",
) -> OperatorDifficultyExportResult:
    """Write operator difficulty CSV, LaTeX table, heatmap, and JSON summary."""
    rows = compute_operator_difficulty_rows(
        repair_by_operator_path=repair_by_operator_path,
        localizability_audit_path=localizability_audit_path,
        repair_tool=repair_tool,
    )
    ranked_rows = assign_difficulty_tiers(rows)
    summary = summarize_operator_difficulty(ranked_rows)

    csv_path = out_dir / "operator_difficulty.csv"
    tex_path = out_dir / "tables" / "difficulty_ranking.tex"
    figure_path = out_dir / "figures" / "difficulty_heatmap.png"
    summary_path = out_dir / "operator_difficulty_summary.json"

    _write_operator_difficulty_csv(csv_path, ranked_rows)
    _write_difficulty_ranking_tex(tex_path, ranked_rows, summary)
    _write_difficulty_heatmap(figure_path, ranked_rows)
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    paper_csv_path = paper_tex_path = paper_figure_path = paper_summary_path = None
    if paper_export_dir is not None and paper_export_dir.resolve() != out_dir.resolve():
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        paper_csv_path = paper_export_dir / csv_path.name
        paper_summary_path = paper_export_dir / summary_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_figure_path = paper_export_dir / "figures" / figure_path.name
        paper_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_summary_path.write_text(summary_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_tex_path.parent.mkdir(parents=True, exist_ok=True)
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_figure_path.parent.mkdir(parents=True, exist_ok=True)
        paper_figure_path.write_bytes(figure_path.read_bytes())

    return OperatorDifficultyExportResult(
        csv_path=csv_path,
        tex_path=tex_path,
        figure_path=figure_path,
        summary_path=summary_path,
        paper_csv_path=paper_csv_path,
        paper_tex_path=paper_tex_path,
        paper_figure_path=paper_figure_path,
        paper_summary_path=paper_summary_path,
    )
