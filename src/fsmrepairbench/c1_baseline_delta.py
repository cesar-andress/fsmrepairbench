"""Paired delta metrics between C1 baseline repair engines."""

from __future__ import annotations

import csv
import json
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.baseline_repair_campaign import (
    CAMPAIGN_LABEL,
    RELEASE_LABEL,
    ZENODO_DOI,
)
from fsmrepairbench.benchmark_utility import C1_TOOL_IDS, TOOL_LABELS
from fsmrepairbench.freeze import get_git_commit, get_git_tag, sha256_file

BASELINE_PAIRS: tuple[tuple[str, str, str], ...] = (
    (
        "baseline_missing_transition",
        "baseline_wrong_target",
        "missing-transition vs wrong-target",
    ),
    (
        "baseline_missing_transition",
        "baseline_random",
        "missing-transition vs random",
    ),
    (
        "baseline_wrong_target",
        "baseline_random",
        "wrong-target vs random",
    ),
)

PARTITIONS: tuple[tuple[str, bool], ...] = (
    ("cohort_wide", False),
    ("detectable_only", True),
)

SCOPES: tuple[tuple[str, str], ...] = (
    ("overall", "all"),
    ("by_operator", "mutation_operator"),
    ("by_tier", "complexity_tier"),
)

DELTA_CSV_COLUMNS: tuple[str, ...] = (
    "scope",
    "group_key",
    "group_value",
    "partition",
    "tool_a",
    "tool_b",
    "comparison_label",
    "n_cases",
    "complete_repair_rate_a",
    "complete_repair_rate_b",
    "delta_complete_repair_rate",
    "effective_repair_rate_a",
    "effective_repair_rate_b",
    "delta_effective_repair_rate",
    "mean_delta_bpr_a",
    "mean_delta_bpr_b",
    "delta_mean_delta_bpr",
    "regression_rate_a",
    "regression_rate_b",
    "delta_regression_rate",
)


@dataclass(frozen=True)
class C1BaselineDeltaExportResult:
    """Paths written by :func:`write_c1_baseline_delta_exports`."""

    output_dir: Path
    manifest_path: Path
    summary_csv_path: Path
    by_operator_csv_path: Path
    by_tier_csv_path: Path
    summary_tex_path: Path
    by_operator_tex_path: Path
    by_tier_tex_path: Path
    operator_figure_path: Path
    tier_figure_path: Path
    summary_figure_path: Path
    paper_output_dir: Path | None = None


def _load_enriched_rows(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in csv.DictReader(path.open(encoding="utf-8")):
        rows.append(
            {
                "case_id": row["case_id"],
                "tool_id": row["tool_id"],
                "mutation_operator": row["mutation_operator"],
                "complexity_tier": row.get("complexity_tier", ""),
                "delta_bpr": float(row["delta_bpr"]),
                "complete_repair": row["complete_repair"].strip().lower() == "true",
                "effective_repair": row["effective_repair"].strip().lower() == "true",
                "regression": row.get("regression", "false").strip().lower() == "true",
                "oracle_detected": row.get("oracle_detected", "false").strip().lower() == "true",
            }
        )
    return rows


def _rate(values: Sequence[bool]) -> float:
    return sum(1 for value in values if value) / len(values) if values else 0.0


def _mean(values: Sequence[float]) -> float:
    return statistics.mean(values) if values else 0.0


def _group_values(enriched: Sequence[dict[str, Any]], group_key: str) -> list[str]:
    if group_key == "all":
        return ["all"]
    seen: set[str] = set()
    for row in enriched:
        seen.add(str(row[group_key]))
    return sorted(seen)


def _paired_rows_for_group(
    enriched: Sequence[dict[str, Any]],
    *,
    group_key: str,
    group_value: str,
    detectable_only: bool,
) -> dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]]:
    by_case: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
    case_meta: dict[str, dict[str, Any]] = {}
    for row in enriched:
        case_id = str(row["case_id"])
        by_case[case_id][str(row["tool_id"])] = row
        case_meta[case_id] = row

    paired: dict[tuple[str, str], list[tuple[dict[str, Any], dict[str, Any]]]] = {
        (tool_a, tool_b): [] for tool_a, tool_b, _label in BASELINE_PAIRS
    }
    for case_id, tool_map in by_case.items():
        meta = case_meta[case_id]
        if detectable_only and not meta["oracle_detected"]:
            continue
        if group_key != "all" and str(meta[group_key]) != group_value:
            continue
        for tool_a, tool_b, _label in BASELINE_PAIRS:
            if tool_a in tool_map and tool_b in tool_map:
                paired[(tool_a, tool_b)].append((tool_map[tool_a], tool_map[tool_b]))
    return paired


def _pair_delta_row(
    *,
    scope: str,
    group_key: str,
    group_value: str,
    partition: str,
    tool_a: str,
    tool_b: str,
    comparison_label: str,
    pairs: Sequence[tuple[dict[str, Any], dict[str, Any]]],
) -> dict[str, Any]:
    if not pairs:
        return {}
    complete_a = [bool(left["complete_repair"]) for left, _right in pairs]
    complete_b = [bool(right["complete_repair"]) for _left, right in pairs]
    effective_a = [bool(left["effective_repair"]) for left, _right in pairs]
    effective_b = [bool(right["effective_repair"]) for _left, right in pairs]
    regression_a = [bool(left["regression"]) for left, _right in pairs]
    regression_b = [bool(right["regression"]) for _left, right in pairs]
    delta_bpr_a = [float(left["delta_bpr"]) for left, _right in pairs]
    delta_bpr_b = [float(right["delta_bpr"]) for _left, right in pairs]
    delta_bpr_diff = [left - right for left, right in zip(delta_bpr_a, delta_bpr_b, strict=True)]

    complete_rate_a = _rate(complete_a)
    complete_rate_b = _rate(complete_b)
    effective_rate_a = _rate(effective_a)
    effective_rate_b = _rate(effective_b)
    regression_rate_a = _rate(regression_a)
    regression_rate_b = _rate(regression_b)
    mean_delta_a = _mean(delta_bpr_a)
    mean_delta_b = _mean(delta_bpr_b)

    return {
        "scope": scope,
        "group_key": group_key,
        "group_value": group_value,
        "partition": partition,
        "tool_a": tool_a,
        "tool_b": tool_b,
        "comparison_label": comparison_label,
        "n_cases": len(pairs),
        "complete_repair_rate_a": round(complete_rate_a, 6),
        "complete_repair_rate_b": round(complete_rate_b, 6),
        "delta_complete_repair_rate": round(complete_rate_a - complete_rate_b, 6),
        "effective_repair_rate_a": round(effective_rate_a, 6),
        "effective_repair_rate_b": round(effective_rate_b, 6),
        "delta_effective_repair_rate": round(effective_rate_a - effective_rate_b, 6),
        "mean_delta_bpr_a": round(mean_delta_a, 6),
        "mean_delta_bpr_b": round(mean_delta_b, 6),
        "delta_mean_delta_bpr": round(_mean(delta_bpr_diff), 6),
        "regression_rate_a": round(regression_rate_a, 6),
        "regression_rate_b": round(regression_rate_b, 6),
        "delta_regression_rate": round(regression_rate_a - regression_rate_b, 6),
    }


def compute_c1_baseline_delta_rows(
    enriched: Sequence[dict[str, Any]],
    *,
    tool_ids: Sequence[str] = C1_TOOL_IDS,
) -> list[dict[str, Any]]:
    """Compute paired baseline deltas for overall, operator, and tier scopes."""
    _ = tool_ids
    rows: list[dict[str, Any]] = []
    for scope, group_field in SCOPES:
        group_key = "all" if group_field == "all" else group_field
        for group_value in _group_values(enriched, group_key):
            for partition, detectable_only in PARTITIONS:
                paired = _paired_rows_for_group(
                    enriched,
                    group_key=group_key,
                    group_value=group_value,
                    detectable_only=detectable_only,
                )
                for tool_a, tool_b, comparison_label in BASELINE_PAIRS:
                    pair_rows = paired[(tool_a, tool_b)]
                    delta_row = _pair_delta_row(
                        scope=scope,
                        group_key=group_key,
                        group_value=group_value,
                        partition=partition,
                        tool_a=tool_a,
                        tool_b=tool_b,
                        comparison_label=comparison_label,
                        pairs=pair_rows,
                    )
                    if delta_row:
                        rows.append(delta_row)
    return rows


def _filter_rows(
    rows: Sequence[dict[str, Any]],
    *,
    scope: str | None = None,
    partition: str | None = None,
) -> list[dict[str, Any]]:
    filtered = list(rows)
    if scope is not None:
        filtered = [row for row in filtered if row["scope"] == scope]
    if partition is not None:
        filtered = [row for row in filtered if row["partition"] == partition]
    return filtered


def _write_delta_csv(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DELTA_CSV_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row[key] for key in DELTA_CSV_COLUMNS})


def _tex_escape(value: str) -> str:
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("_", "\\_")
        .replace("%", "\\%")
        .replace("&", "\\&")
    )


def _write_summary_tex(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    body_lines = [
        "\\begin{tabular}{@{}llrrrr@{}}",
        "\\toprule",
        "Partition & Comparison & $n$ & $\\Delta$ complete & $\\Delta$ effective & $\\Delta$ mean $\\Delta$BPR \\\\",
        "\\midrule",
    ]
    for row in sorted(rows, key=lambda item: (item["partition"], item["comparison_label"])):
        body_lines.append(
            " & ".join(
                [
                    _tex_escape(str(row["partition"]).replace("_", "-")),
                    _tex_escape(str(row["comparison_label"])),
                    str(row["n_cases"]),
                    f"{row['delta_complete_repair_rate'] * 100:+.1f}",
                    f"{row['delta_effective_repair_rate'] * 100:+.1f}",
                    f"{row['delta_mean_delta_bpr']:+.3f}",
                ]
            )
            + " \\\\"
        )
    body_lines.extend(["\\bottomrule", "\\end{tabular}"])
    detectable = next(
        (row for row in rows if row["partition"] == "detectable_only"),
        None,
    )
    detectable_note = ""
    if detectable is not None:
        detectable_note = (
            f"Detectable-only primary subset ($n={detectable['n_cases']}$); "
            "505/1{,}000 oracle-saturated cases excluded. "
        )
    tex = (
        "\\begin{table}[t]\n"
        "\\caption{Paired baseline deltas on the C1 1{,}000-case "
        "\\texttt{plain\\_fsm}/shallow-oracle cohort. "
        "Each row subtracts tool~B from tool~A on aligned per-case outcomes "
        "(complete/effective repair rates in percentage points; mean $\\Delta$BPR as paired differences). "
        + detectable_note
        + "Cohort-wide rows inherit oracle-saturation confounds "
        "(Section~\\ref{sec:threats-construct}).}\n"
        "\\label{tab:baseline-delta-summary}\n"
        + "\n".join(body_lines)
        + "\n\\end{table}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")


def _write_grouped_tex(
    path: Path,
    rows: Sequence[dict[str, Any]],
    *,
    group_label: str,
    caption: str,
    label: str,
) -> None:
    pair_labels = [label for _a, _b, label in BASELINE_PAIRS]
    body_lines = [
        "\\begin{tabular}{@{}l" + "r" * len(pair_labels) + "@{}}",
        "\\toprule",
        f"{group_label} & "
        + " & ".join(_tex_escape(label.replace(" vs ", " $-$ ")) for label in pair_labels)
        + " \\\\",
        "\\midrule",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["group_value"])].append(row)
    for group_value in sorted(grouped):
        by_pair = {row["comparison_label"]: row for row in grouped[group_value]}
        cells = [f"\\texttt{{{_tex_escape(group_value)}}}"]
        for _tool_a, _tool_b, comparison_label in BASELINE_PAIRS:
            pair_row = by_pair.get(comparison_label)
            if pair_row is None:
                cells.append("--")
            else:
                cells.append(f"{pair_row['delta_complete_repair_rate'] * 100:+.1f}")
        body_lines.append(" & ".join(cells) + " \\\\")
    body_lines.extend(["\\bottomrule", "\\end{tabular}"])
    tex = (
        "\\begin{table}[t]\n"
        f"\\caption{{{caption}}}\n"
        f"\\label{{{label}}}\n"
        + "\n".join(body_lines)
        + "\n\\end{table}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")


def _write_operator_figure(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    operators = sorted({str(row["group_value"]) for row in rows})
    pair_labels = [label.split(" vs ")[1] for _a, _b, label in BASELINE_PAIRS]
    matrix = np.full((len(operators), len(BASELINE_PAIRS)), np.nan)
    for row in rows:
        operator_index = operators.index(str(row["group_value"]))
        pair_index = next(
            index
            for index, (_a, _b, label) in enumerate(BASELINE_PAIRS)
            if label == row["comparison_label"]
        )
        matrix[operator_index, pair_index] = row["delta_complete_repair_rate"] * 100.0

    fig_height = max(4.5, 0.28 * len(operators) + 1.5)
    fig, axis = plt.subplots(figsize=(8.5, fig_height))
    im = axis.imshow(matrix, aspect="auto", cmap="RdBu_r", vmin=-80.0, vmax=80.0)
    axis.set_yticks(range(len(operators)))
    axis.set_yticklabels(operators, fontsize=8)
    axis.set_xticks(range(len(pair_labels)))
    axis.set_xticklabels(
        [f"missing-transition\nvs\n{name}" for name in pair_labels],
        fontsize=8,
    )
    axis.set_title(
        "Detectable-only $\\Delta$ complete repair (percentage points)\n"
        "by mutation operator and baseline pair (C1 cohort; n=495 overall)"
    )
    for row_index in range(matrix.shape[0]):
        for col_index in range(matrix.shape[1]):
            value = matrix[row_index, col_index]
            if np.isnan(value):
                continue
            axis.text(
                col_index,
                row_index,
                f"{value:+.0f}",
                ha="center",
                va="center",
                color="black",
                fontsize=7,
            )
    fig.colorbar(im, ax=axis, shrink=0.85, label="$\\Delta$ complete repair (pp)")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _write_tier_figure(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    tiers = sorted({str(row["group_value"]) for row in rows})
    pair_labels = [label for _a, _b, label in BASELINE_PAIRS]
    width = 0.24
    x = np.arange(len(tiers))
    fig, axis = plt.subplots(figsize=(9.0, 4.5))
    for pair_index, comparison_label in enumerate(pair_labels):
        values = []
        for tier in tiers:
            match = next(
                (row for row in rows if row["group_value"] == tier and row["comparison_label"] == comparison_label),
                None,
            )
            values.append(match["delta_complete_repair_rate"] * 100.0 if match else 0.0)
        offset = (pair_index - 1) * width
        axis.bar(
            x + offset,
            values,
            width,
            label=comparison_label.replace(" vs ", " − "),
        )
    axis.axhline(0.0, color="black", linewidth=0.8)
    axis.set_xticks(x)
    axis.set_xticklabels(tiers)
    axis.set_ylabel("$\\Delta$ complete repair (percentage points)")
    axis.set_title(
        "Detectable-only paired baseline deltas by complexity tier\n"
        "(tool A minus tool B on complete repair; C1 cohort)"
    )
    axis.legend(fontsize=8, loc="upper right")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _write_summary_figure(path: Path, rows: Sequence[dict[str, Any]]) -> None:
    import matplotlib.pyplot as plt
    import numpy as np

    detectable_rows = sorted(rows, key=lambda item: item["comparison_label"])
    labels = [row["comparison_label"].replace(" vs ", "\nvs\n") for row in detectable_rows]
    metrics = [
        ("delta_complete_repair_rate", "$\\Delta$ complete (pp)"),
        ("delta_effective_repair_rate", "$\\Delta$ effective (pp)"),
        ("delta_mean_delta_bpr", "$\\Delta$ mean $\\Delta$BPR"),
        ("delta_regression_rate", "$\\Delta$ regression (pp)"),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10.0, 7.0))
    x = np.arange(len(labels))
    for axis, (field, ylabel) in zip(axes.ravel(), metrics, strict=True):
        values = [
            row[field] * 100.0 if "rate" in field else row[field]
            for row in detectable_rows
        ]
        colors = ["#2ca02c" if value >= 0 else "#d62728" for value in values]
        axis.bar(x, values, color=colors)
        axis.axhline(0.0, color="black", linewidth=0.8)
        axis.set_xticks(x)
        axis.set_xticklabels(labels, fontsize=8)
        axis.set_ylabel(ylabel)
    fig.suptitle(
        "Detectable-only paired baseline deltas (tool A $-$ tool B; C1; n=495)",
        fontsize=11,
    )
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def _sync_tree(source_dir: Path, destination_dir: Path) -> None:
    import shutil

    if source_dir.resolve() == destination_dir.resolve():
        return
    destination_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(source_dir)
        target = destination_dir / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in {".png", ".pdf"}:
            target.write_bytes(path.read_bytes())
        else:
            target.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")


def _write_manifest(
    path: Path,
    *,
    per_case_path: Path,
    output_files: Sequence[str],
    regeneration_commands: Sequence[str],
) -> None:
    github_tag = get_git_tag() or RELEASE_LABEL
    manifest = {
        "campaign_label": CAMPAIGN_LABEL,
        "release_label": RELEASE_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "github_tag": github_tag,
        "git_commit_hash": get_git_commit(),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "source_per_case_csv": str(per_case_path.resolve()),
        "source_per_case_sha256": sha256_file(per_case_path),
        "baseline_pairs": [
            {
                "tool_a": tool_a,
                "tool_b": tool_b,
                "comparison_label": label,
                "tool_a_label": TOOL_LABELS[tool_a],
                "tool_b_label": TOOL_LABELS[tool_b],
            }
            for tool_a, tool_b, label in BASELINE_PAIRS
        ],
        "partitions": [partition for partition, _detectable in PARTITIONS],
        "scopes": [scope for scope, _field in SCOPES],
        "output_files": list(output_files),
        "regeneration_commands": list(regeneration_commands),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_c1_baseline_delta_exports(
    per_case_path: Path,
    out_dir: Path,
    *,
    paper_export_dir: Path | None = None,
    regeneration_commands: Sequence[str] | None = None,
) -> C1BaselineDeltaExportResult:
    """Write paired C1 baseline delta CSV, LaTeX, figure, and manifest exports."""
    enriched = _load_enriched_rows(per_case_path)
    all_rows = compute_c1_baseline_delta_rows(enriched)

    delta_dir = out_dir / "baseline_delta"
    tables_dir = delta_dir / "tables"
    figures_dir = delta_dir / "figures"

    summary_rows = _filter_rows(all_rows, scope="overall")
    operator_rows = _filter_rows(all_rows, scope="by_operator", partition="detectable_only")
    tier_rows = _filter_rows(all_rows, scope="by_tier", partition="detectable_only")

    summary_csv = delta_dir / "baseline_delta_summary.csv"
    operator_csv = delta_dir / "baseline_delta_by_operator.csv"
    tier_csv = delta_dir / "baseline_delta_by_tier.csv"
    _write_delta_csv(summary_csv, summary_rows)
    _write_delta_csv(operator_csv, operator_rows)
    _write_delta_csv(tier_csv, tier_rows)

    summary_tex = tables_dir / "table_baseline_delta_summary.tex"
    operator_tex = tables_dir / "table_baseline_delta_by_operator.tex"
    tier_tex = tables_dir / "table_baseline_delta_by_tier.tex"
    _write_summary_tex(summary_tex, summary_rows)
    _write_grouped_tex(
        operator_tex,
        operator_rows,
        group_label="Mutation operator",
        caption=(
            "Detectable-only $\\Delta$ complete repair (percentage points; tool~A minus tool~B) "
            "by mutation operator and baseline pair on the C1 cohort ($n=495$ overall; "
            "505/1{,}000 oracle-saturated excluded). "
            "Positive values favour the first engine in each column header."
        ),
        label="tab:baseline-delta-by-operator",
    )
    _write_grouped_tex(
        tier_tex,
        tier_rows,
        group_label="Complexity tier",
        caption=(
            "Detectable-only $\\Delta$ complete repair (percentage points) by structural "
            "complexity tier and baseline pair (C1 cohort). "
            "Paired deltas complement tier-stratified absolute rates in "
            "\\Tab{tab:baseline-repair-by-tier}."
        ),
        label="tab:baseline-delta-by-tier",
    )

    operator_figure = figures_dir / "delta_complete_repair_by_operator.png"
    tier_figure = figures_dir / "delta_complete_repair_by_tier.png"
    summary_figure = figures_dir / "delta_summary_metrics.png"
    _write_operator_figure(operator_figure, operator_rows)
    _write_tier_figure(tier_figure, tier_rows)
    _write_summary_figure(
        summary_figure,
        _filter_rows(summary_rows, partition="detectable_only"),
    )

    regen = regeneration_commands or [
        "python ../paper1/scripts/generate_c1_baseline_delta_outputs.py",
        "python ../paper1/scripts/compile_results_latex.py",
    ]
    manifest_path = delta_dir / "manifest.json"
    _write_manifest(
        manifest_path,
        per_case_path=per_case_path,
        output_files=[
            "baseline_delta_summary.csv",
            "baseline_delta_by_operator.csv",
            "baseline_delta_by_tier.csv",
            "tables/table_baseline_delta_summary.tex",
            "tables/table_baseline_delta_by_operator.tex",
            "tables/table_baseline_delta_by_tier.tex",
            "figures/delta_complete_repair_by_operator.png",
            "figures/delta_complete_repair_by_tier.png",
            "figures/delta_summary_metrics.png",
            "manifest.json",
        ],
        regeneration_commands=regen,
    )

    paper_output_dir = None
    if paper_export_dir is not None:
        paper_output_dir = paper_export_dir / "baseline_delta"
        _sync_tree(delta_dir, paper_output_dir)

    return C1BaselineDeltaExportResult(
        output_dir=delta_dir,
        manifest_path=manifest_path,
        summary_csv_path=summary_csv,
        by_operator_csv_path=operator_csv,
        by_tier_csv_path=tier_csv,
        summary_tex_path=summary_tex,
        by_operator_tex_path=operator_tex,
        by_tier_tex_path=tier_tex,
        operator_figure_path=operator_figure,
        tier_figure_path=tier_figure,
        summary_figure_path=summary_figure,
        paper_output_dir=paper_output_dir,
    )
