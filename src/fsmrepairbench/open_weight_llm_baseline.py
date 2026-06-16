"""External open-weight LLM repair baseline (single-attempt, protocol-safe)."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.experiments import ExperimentCase
from fsmrepairbench.llm.clients.registry import create_model_client, parse_model_spec
from fsmrepairbench.llm.clients.base import ModelBackend
from fsmrepairbench.llm.repair import run_llm_repair_with_client
from fsmrepairbench.models import FSM, OracleSuite, RepairResult
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.tool_runner import (
    ToolRunSummaryRow,
    classify_failure,
    resolve_cases_dir,
)
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite

OPENWEIGHT_TOOL_ID = "baseline_openweight_llm_qwen25_coder_7b"
OPENWEIGHT_MODEL_LABEL = "Qwen2.5-Coder-7B-Instruct (Ollama)"
DEFAULT_OLLAMA_MODEL = "qwen2.5-coder:7b"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_MAX_ITERATIONS = 1

CANDIDATE_MODELS: tuple[dict[str, str], ...] = (
    {
        "name": "Qwen2.5-Coder-7B-Instruct",
        "ollama_tag": "qwen2.5-coder:7b",
        "params_b": "7",
        "notes": "Best fit for 24GB GPU; already available locally via Ollama (~4.7GB quant).",
    },
    {
        "name": "DeepSeek-Coder-V2-Lite-Instruct",
        "ollama_tag": "(not pulled)",
        "params_b": "16 MoE",
        "notes": "Requires fresh download; active params lower but total weights larger than 7B.",
    },
    {
        "name": "StarCoder2-15B",
        "ollama_tag": "(not pulled)",
        "params_b": "15",
        "notes": "Tight on RTX 4090 for long FSM+oracle prompts unless aggressively quantized.",
    },
)


class OpenWeightLLMBaselineError(ValueError):
    """Raised when open-weight LLM baseline inputs or execution fail."""


@dataclass(frozen=True)
class OpenWeightRepairOutcome:
    """Single-case open-weight LLM repair outcome."""

    case_id: str
    mutation_operator: str
    oracle_detected: bool
    initial_bpr: float
    final_bpr: float
    delta_bpr: float
    complete_repair: bool
    effective_repair: bool
    regression: bool
    patch_parse_failures: int
    patch_validation_failures: int
    patch_application_failures: int
    iterations_completed: int
    runtime_seconds: float
    status: str
    failure_class: str
    patched_fsm_path: Path | None
    repair_result: RepairResult | None


def load_protocol_safe_case(case_dir: Path) -> tuple[FSM, OracleSuite]:
    """Load only faulty FSM and oracle suite allowed at repair time."""
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if faulty_path is None or oracle_path is None:
        msg = f"Incomplete case directory (protocol inputs missing): {case_dir}"
        raise OpenWeightLLMBaselineError(msg)
    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)
    return faulty, oracle


def case_is_oracle_detectable(case_dir: Path) -> bool:
    """Return True when faulty BPR < reference BPR (cohort labelling only)."""
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if faulty_path is None or reference_path is None or oracle_path is None:
        return False
    faulty = load_fsm_json(faulty_path)
    reference = load_fsm_json(reference_path)
    oracle = load_oracle_suite(oracle_path)
    faulty_bpr = score_oracle_suite(faulty, oracle).bpr
    reference_bpr = score_oracle_suite(reference, oracle).bpr
    return faulty_bpr < reference_bpr - 1e-9


DEFAULT_COHORT_FILE = "analysis_cohort_1k.txt"


def load_frozen_c1_detectable_case_ids(c1_per_case_path: Path) -> list[str]:
    """Return sorted detectable-only case IDs from frozen C1 per-case export."""
    if not c1_per_case_path.is_file():
        msg = f"Missing frozen C1 per-case results: {c1_per_case_path}"
        raise OpenWeightLLMBaselineError(msg)
    detectable: set[str] = set()
    with c1_per_case_path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("oracle_detected", "").strip().lower() != "true":
                continue
            detectable.add(raw["case_id"])
    return sorted(detectable)


def list_detectable_case_ids(
    dataset_dir: Path,
    *,
    cohort_file: Path | None = None,
    c1_per_case_path: Path | None = None,
) -> list[str]:
    """Sorted detectable-only case IDs aligned with frozen C1 exports when available."""
    if c1_per_case_path is not None:
        frozen = load_frozen_c1_detectable_case_ids(c1_per_case_path)
        if cohort_file is None:
            return frozen
        cohort_ids = set(load_cohort_case_ids(cohort_file))
        return [case_id for case_id in frozen if case_id in cohort_ids]

    cases_dir = resolve_cases_dir(dataset_dir)
    cohort_ids: set[str] | None = None
    if cohort_file is not None:
        cohort_ids = set(load_cohort_case_ids(cohort_file))
    detectable: list[str] = []
    for case_dir in sorted(cases_dir.iterdir()):
        if not case_dir.is_dir() or not case_dir.name.startswith("case_"):
            continue
        if cohort_ids is not None and case_dir.name not in cohort_ids:
            continue
        if case_is_oracle_detectable(case_dir):
            detectable.append(case_dir.name)
    return detectable


def write_cohort_manifest(case_ids: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(case_ids) + ("\n" if case_ids else ""), encoding="utf-8")
    return path


def build_detectable_cohort_manifests(
    dataset_dir: Path,
    *,
    output_dir: Path,
    pilot_n: int = 200,
    c1_per_case_path: Path | None = None,
) -> dict[str, Path]:
    """Write detectable-only cohort manifests (pilot + full)."""
    cohort_file = dataset_dir / DEFAULT_COHORT_FILE
    detectable = list_detectable_case_ids(
        dataset_dir,
        cohort_file=cohort_file if cohort_file.is_file() else None,
        c1_per_case_path=c1_per_case_path,
    )
    if len(detectable) < pilot_n:
        msg = f"Expected at least {pilot_n} detectable cases, found {len(detectable)}"
        raise OpenWeightLLMBaselineError(msg)
    paths = {
        "detectable_all": write_cohort_manifest(
            detectable,
            output_dir / "detectable_repair_eval_all.txt",
        ),
        "detectable_pilot_200": write_cohort_manifest(
            detectable[:pilot_n],
            output_dir / "detectable_repair_eval_200.txt",
        ),
    }
    meta = {
        "generated_at": datetime.now(UTC).isoformat(),
        "detectable_count": len(detectable),
        "pilot_count": pilot_n,
        "pilot_case_ids": detectable[:pilot_n],
    }
    meta_path = output_dir / "detectable_cohort_manifest.json"
    meta_path.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    paths["manifest_json"] = meta_path
    return paths


def run_open_weight_llm_repair(
    case_dir: Path,
    *,
    model: str = DEFAULT_OLLAMA_MODEL,
    backend: str = "ollama",
    base_url: str | None = None,
    temperature: float = DEFAULT_TEMPERATURE,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
    patched_output_dir: Path | None = None,
) -> OpenWeightRepairOutcome:
    """Run exactly one open-weight LLM repair attempt on a benchmark case."""
    faulty, oracle = load_protocol_safe_case(case_dir)
    detectable = case_is_oracle_detectable(case_dir)
    spec = parse_model_spec(
        {
            "name": model,
            "backend": backend,
            **({"base_url": base_url} if base_url else {}),
        },
        default_backend=ModelBackend.OLLAMA,
    )
    client = create_model_client(spec)

    initial_score = score_oracle_suite(faulty, oracle)
    try:
        repair_result = run_llm_repair_with_client(
            faulty,
            oracle,
            model=spec.name,
            max_iterations=max_iterations,
            temperature=temperature,
            client=client,
        )
        status = "completed"
        error_kind = None
    except Exception:
        repair_result = None
        status = "failed"
        error_kind = "tool_error"

    if repair_result is None:
        final_bpr = initial_score.bpr
        delta = 0.0
        complete = False
        effective = False
        regression = False
        parse_failures = 1
        validation_failures = 0
        application_failures = 0
        iterations = 0
        runtime = 0.0
    else:
        final_bpr = float(repair_result.score)
        delta = round(final_bpr - initial_score.bpr, 12)
        complete = final_bpr == 1.0
        effective = final_bpr > initial_score.bpr
        regression = final_bpr < initial_score.bpr
        details = repair_result.details
        iteration_rows = details.get("iterations", [])
        iterations = len(iteration_rows) if isinstance(iteration_rows, list) else 1
        runtime = float(details.get("runtime_seconds") or 0.0)
        parse_failures = sum(
            1
            for item in iteration_rows
            if isinstance(item, dict) and item.get("error") and not item.get("patch")
        )
        validation_failures = sum(
            1
            for item in iteration_rows
            if isinstance(item, dict) and item.get("patch_valid") is False
        )
        application_failures = sum(
            1
            for item in iteration_rows
            if isinstance(item, dict)
            and item.get("patch_valid") is True
            and item.get("patch_applied") is False
        )

    failure_class = classify_failure(
        status=status,  # type: ignore[arg-type]
        initial_bpr=initial_score.bpr,
        final_bpr=final_bpr,
        complete_repair=complete,
        effective_repair=effective,
        regression=regression,
        error_kind=error_kind,
    )

    patched_path: Path | None = None
    if repair_result is not None and patched_output_dir is not None:
        patched_output_dir.mkdir(parents=True, exist_ok=True)
        patched_path = patched_output_dir / f"{case_dir.name}__patched_fsm.json"
        final_fsm_payload = repair_result.details.get("final_fsm")
        if isinstance(final_fsm_payload, dict):
            patched_path.write_text(json.dumps(final_fsm_payload, indent=2) + "\n", encoding="utf-8")

    return OpenWeightRepairOutcome(
        case_id=case_dir.name,
        mutation_operator="",
        oracle_detected=detectable,
        initial_bpr=initial_score.bpr,
        final_bpr=final_bpr,
        delta_bpr=delta,
        complete_repair=complete,
        effective_repair=effective,
        regression=regression,
        patch_parse_failures=parse_failures,
        patch_validation_failures=validation_failures,
        patch_application_failures=application_failures,
        iterations_completed=iterations,
        runtime_seconds=runtime,
        status=status,
        failure_class=failure_class,
        patched_fsm_path=patched_path,
        repair_result=repair_result,
    )


def outcome_to_summary_row(outcome: OpenWeightRepairOutcome) -> ToolRunSummaryRow:
    return ToolRunSummaryRow(
        case_id=outcome.case_id,
        tool_id=OPENWEIGHT_TOOL_ID,
        tool_type="llm",
        model=DEFAULT_OLLAMA_MODEL,
        mutation_operator=outcome.mutation_operator,
        status=outcome.status,  # type: ignore[arg-type]
        failure_class=outcome.failure_class,  # type: ignore[arg-type]
        initial_bpr=outcome.initial_bpr,
        final_bpr=outcome.final_bpr,
        delta_bpr=outcome.delta_bpr,
        complete_repair=outcome.complete_repair,
        effective_repair=outcome.effective_repair,
        regression=outcome.regression,
        patch_parse_failures=outcome.patch_parse_failures,
        patch_validation_failures=outcome.patch_validation_failures,
        patch_application_failures=outcome.patch_application_failures,
        iterations_completed=outcome.iterations_completed,
        runtime_seconds=outcome.runtime_seconds,
    )


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    return text in {"1", "true", "yes"}


def aggregate_partition_metrics(rows: list[dict[str, Any]]) -> dict[str, float | int]:
    if not rows:
        return {
            "n_cases": 0,
            "complete_repair_rate": 0.0,
            "effective_repair_rate": 0.0,
            "mean_delta_bpr": 0.0,
        }
    n = len(rows)
    return {
        "n_cases": n,
        "complete_repair_rate": round(
            sum(_as_bool(r["complete_repair"]) for r in rows) / n,
            6,
        ),
        "effective_repair_rate": round(
            sum(_as_bool(r["effective_repair"]) for r in rows) / n,
            6,
        ),
        "mean_delta_bpr": round(sum(float(r["delta_bpr"]) for r in rows) / n, 6),
    }


def write_per_case_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    columns = (
        "case_id",
        "tool_id",
        "model",
        "mutation_operator",
        "oracle_detected",
        "status",
        "failure_class",
        "initial_bpr",
        "final_bpr",
        "delta_bpr",
        "complete_repair",
        "effective_repair",
        "regression",
        "patch_parse_failures",
        "patch_validation_failures",
        "patch_application_failures",
        "iterations_completed",
        "runtime_seconds",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def load_c1_deterministic_detectable_metrics(
    leaderboard_path: Path,
) -> list[dict[str, str | float | int]]:
    """Load detectable-only metrics for the three primary C1 deterministic baselines."""
    target_tools = {
        "baseline_missing_transition": "missing-transition",
        "baseline_wrong_target": "wrong-target",
        "baseline_random": "random",
    }
    rows: list[dict[str, str | float | int]] = []
    with leaderboard_path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            tool_id = raw["tool_id"]
            if tool_id not in target_tools:
                continue
            rows.append(
                {
                    "tool_id": tool_id,
                    "tool_label": target_tools[tool_id],
                    "n_cases": int(raw["detectable_cases"]),
                    "complete_repair_rate": float(raw["complete_repair_rate_detectable_only"]),
                    "effective_repair_rate": float(raw["effective_repair_rate_detectable_only"]),
                    "mean_delta_bpr": float(raw["mean_delta_bpr_cohort_wide"]),
                }
            )
    return rows


def experiment_case_from_dir(case_dir: Path) -> ExperimentCase:
    faulty, oracle = load_protocol_safe_case(case_dir)
    return ExperimentCase(
        case_id=case_dir.name,
        case_dir=case_dir,
        faulty_fsm=faulty,
        oracle_suite=oracle,
        mutation_operator="",
    )


def resolve_cases_dir_public(dataset_dir: Path) -> Path:
    return resolve_cases_dir(dataset_dir)


def load_cohort_case_ids(manifest_path: Path) -> list[str]:
    text = manifest_path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    return [line.strip() for line in text.splitlines() if line.strip()]


def outcome_to_row_dict(outcome: OpenWeightRepairOutcome) -> dict[str, Any]:
    return {
        "case_id": outcome.case_id,
        "tool_id": OPENWEIGHT_TOOL_ID,
        "model": DEFAULT_OLLAMA_MODEL,
        "mutation_operator": outcome.mutation_operator,
        "oracle_detected": outcome.oracle_detected,
        "status": outcome.status,
        "failure_class": outcome.failure_class,
        "initial_bpr": outcome.initial_bpr,
        "final_bpr": outcome.final_bpr,
        "delta_bpr": outcome.delta_bpr,
        "complete_repair": outcome.complete_repair,
        "effective_repair": outcome.effective_repair,
        "regression": outcome.regression,
        "patch_parse_failures": outcome.patch_parse_failures,
        "patch_validation_failures": outcome.patch_validation_failures,
        "patch_application_failures": outcome.patch_application_failures,
        "iterations_completed": outcome.iterations_completed,
        "runtime_seconds": outcome.runtime_seconds,
    }


def enrich_mutation_operators(rows: list[dict[str, Any]], dataset_dir: Path) -> None:
    """Attach mutation operators post-hoc for reporting (not used during repair)."""
    cases_dir = resolve_cases_dir(dataset_dir)
    for row in rows:
        metadata_path = cases_dir / row["case_id"] / "bug_metadata.json"
        if metadata_path.is_file():
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            row["mutation_operator"] = str(payload.get("mutation_operator") or "")


def run_open_weight_llm_cohort(
    dataset_dir: Path,
    *,
    cohort_manifest: Path,
    output_dir: Path,
    model: str = DEFAULT_OLLAMA_MODEL,
    backend: str = "ollama",
    base_url: str | None = None,
    resume: bool = True,
) -> list[dict[str, Any]]:
    """Run one repair attempt per case in *cohort_manifest*."""
    case_ids = load_cohort_case_ids(cohort_manifest)
    cases_dir = resolve_cases_dir(dataset_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    patched_dir = output_dir / "patched_fsms"
    per_case_path = output_dir / "per_case_results.csv"

    existing: dict[str, dict[str, Any]] = {}
    if resume and per_case_path.is_file():
        with per_case_path.open(encoding="utf-8", newline="") as handle:
            for raw in csv.DictReader(handle):
                existing[raw["case_id"]] = raw

    rows: list[dict[str, Any]] = []
    for case_id in case_ids:
        if case_id in existing:
            rows.append(existing[case_id])
            continue
        case_dir = cases_dir / case_id
        outcome = run_open_weight_llm_repair(
            case_dir,
            model=model,
            backend=backend,
            base_url=base_url,
            temperature=DEFAULT_TEMPERATURE,
            max_iterations=DEFAULT_MAX_ITERATIONS,
            patched_output_dir=patched_dir,
        )
        row = outcome_to_row_dict(outcome)
        rows.append(row)
        write_per_case_csv(per_case_path, rows)
        enrich_mutation_operators(rows, dataset_dir)
        write_per_case_csv(per_case_path, rows)

    enrich_mutation_operators(rows, dataset_dir)
    write_per_case_csv(per_case_path, rows)
    return rows


def aggregate_c1_subset_metrics(
    per_case_path: Path,
    *,
    cohort_case_ids: set[str],
    tool_ids: set[str] | None = None,
) -> list[dict[str, str | float | int]]:
    """Recompute detectable-only metrics for C1 tools on a fixed case subset."""
    if tool_ids is None:
        tool_ids = {
            "baseline_missing_transition",
            "baseline_wrong_target",
            "baseline_random",
        }
    labels = {
        "baseline_missing_transition": "missing-transition",
        "baseline_wrong_target": "wrong-target",
        "baseline_random": "random",
    }
    grouped: dict[str, list[dict[str, str]]] = {tool_id: [] for tool_id in tool_ids}
    with per_case_path.open(encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw["case_id"] not in cohort_case_ids:
                continue
            if raw.get("oracle_detected", "").lower() not in {"true", "1", "yes"}:
                continue
            tool_id = raw["tool_id"]
            if tool_id in grouped:
                grouped[tool_id].append(raw)

    metrics: list[dict[str, str | float | int]] = []
    for tool_id in sorted(grouped):
        subset = grouped[tool_id]
        if not subset:
            continue
        n = len(subset)
        metrics.append(
            {
                "tool_id": tool_id,
                "tool_label": labels.get(tool_id, tool_id),
                "n_cases": n,
                "complete_repair_rate": round(
                    sum(raw.get("complete_repair", "").lower() == "true" for raw in subset) / n,
                    6,
                ),
                "effective_repair_rate": round(
                    sum(raw.get("effective_repair", "").lower() == "true" for raw in subset) / n,
                    6,
                ),
                "mean_delta_bpr": round(
                    sum(float(raw["delta_bpr"]) for raw in subset) / n,
                    6,
                ),
            }
        )
    return metrics


def write_leaderboard_csv(path: Path, rows: list[dict[str, str | float | int]]) -> None:
    columns = (
        "tool_id",
        "tool_label",
        "n_cases",
        "complete_repair_rate",
        "effective_repair_rate",
        "mean_delta_bpr",
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in columns})


def format_pct(value: float) -> str:
    return f"{100.0 * value:.1f}\\%"


def format_delta(value: float) -> str:
    if value < 0:
        return f"$-${abs(value):.4f}"
    return f"{value:.4f}"


def write_comparison_table_tex(
    path: Path,
    *,
    cohort_label: str,
    n_cases: int,
    rows: list[dict[str, str | float | int]],
) -> None:
    lines = [
        "% Auto-generated open-weight LLM external baseline comparison (do not edit by hand).",
        "\\begin{table}[t]",
        (
            f"\\caption{{External open-weight LLM repair baseline versus deterministic C1 "
            f"engines on detectable-only cases ({cohort_label}, $n={n_cases}$). "
            f"Qwen2.5-Coder-7B-Instruct via Ollama; temperature $=0$; one repair attempt per case. "
            f"This baseline is illustrative, not a state-of-the-art FSM repair method.}}"
        ),
        "\\label{tab:openweight-llm-baseline}",
        "\\begingroup",
        "\\footnotesize",
        "\\setlength{\\tabcolsep}{4pt}",
        "\\begin{tabular}{@{}l r r r r@{}}",
        "\\toprule",
        "Engine & $n$ & Compl. repair & Eff. repair & Mean $\\Delta$BPR \\\\",
        "\\midrule",
    ]
    for row in rows:
        label = str(row["tool_label"])
        if row["tool_id"] == OPENWEIGHT_TOOL_ID:
            label = f"\\textbf{{{OPENWEIGHT_MODEL_LABEL}}}"
        lines.append(
            " & ".join(
                [
                    label,
                    str(int(row["n_cases"])),
                    format_pct(float(row["complete_repair_rate"])),
                    format_pct(float(row["effective_repair_rate"])),
                    format_delta(float(row["mean_delta_bpr"])),
                ]
            )
            + " \\\\"
        )
    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
            "\\endgroup",
            "\\end{table}",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_technical_report(
    path: Path,
    *,
    cohort_label: str,
    n_cases: int,
    metrics_rows: list[dict[str, str | float | int]],
    total_runtime_seconds: float,
    output_dir: Path,
) -> None:
    llm_row = next((row for row in metrics_rows if row["tool_id"] == OPENWEIGHT_TOOL_ID), None)
    c1_rows = [row for row in metrics_rows if row["tool_id"] != OPENWEIGHT_TOOL_ID]
    lines = [
        "# Open-weight LLM external repair baseline — technical report",
        "",
        "## Model feasibility (RTX 4090, 24 GB)",
        "",
        "| Candidate | Ollama tag | Params | Notes |",
        "| --- | --- | --- | --- |",
    ]
    for candidate in CANDIDATE_MODELS:
        lines.append(
            f"| {candidate['name']} | {candidate['ollama_tag']} | {candidate['params_b']} | {candidate['notes']} |"
        )
    lines.extend(
        [
            "",
            "**Selected model:** Qwen2.5-Coder-7B-Instruct (`qwen2.5-coder:7b`, ~4.7 GB quant). "
            "It is the only candidate already available locally and fits comfortably on a single RTX 4090 "
            "with long FSM+oracle prompts. DeepSeek-Coder-V2-Lite and StarCoder2-15B were not pulled in Ollama "
            "and would require additional download/quantization tuning.",
            "",
            "## Protocol",
            "",
            "- Repair inputs: `faulty_fsm.json` + `oracle_suite.json` only.",
            "- Excluded at repair time: `reference_fsm.json`, mutation metadata, localization hints.",
            "- Decoding: temperature 0; exactly one LLM repair attempt per case.",
            "- Cohort labelling (`oracle_detected`) uses reference BPR offline and is not shown to the model.",
            "",
            f"## Results ({cohort_label}, n={n_cases})",
            "",
            "| Engine | Complete repair | Effective repair | Mean ΔBPR |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for row in metrics_rows:
        label = str(row["tool_label"])
        if row["tool_id"] == OPENWEIGHT_TOOL_ID:
            label = OPENWEIGHT_MODEL_LABEL
        lines.append(
            f"| {label} | {100 * float(row['complete_repair_rate']):.1f}% | "
            f"{100 * float(row['effective_repair_rate']):.1f}% | "
            f"{float(row['mean_delta_bpr']):.4f} |"
        )
    if llm_row and c1_rows:
        best_complete = max(c1_rows, key=lambda row: float(row["complete_repair_rate"]))
        lines.extend(
            [
                "",
                "### Interpretation",
                "",
                f"- The open-weight LLM baseline achieved "
                f"{100 * float(llm_row['complete_repair_rate']):.1f}% complete repair and "
                f"{100 * float(llm_row['effective_repair_rate']):.1f}% effective repair on this cohort.",
                f"- Among deterministic C1 engines on the same cases, "
                f"{best_complete['tool_label']} reached "
                f"{100 * float(best_complete['complete_repair_rate']):.1f}% complete repair.",
                "- This run is an **external open-weight LLM baseline** for benchmark anchoring; "
                "it is not presented as a state-of-the-art FSM repair method.",
            ]
        )
    lines.extend(
        [
            "",
            "## Runtime",
            "",
            f"- Total wall time (LLM cohort run): {total_runtime_seconds / 60.0:.1f} minutes.",
            f"- Mean per case: {total_runtime_seconds / max(n_cases, 1):.2f} s.",
            "",
            "## Artifacts",
            "",
            f"- Per-case CSV: `per_case_results.csv`",
            f"- Leaderboard CSV: `leaderboard_comparison.csv`",
            f"- LaTeX table: `tables/table_openweight_llm_baseline.tex`",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


@dataclass(frozen=True)
class OpenWeightExportResult:
    output_dir: Path
    per_case_csv: Path
    leaderboard_csv: Path
    table_tex: Path
    report_md: Path


def export_openweight_llm_repair_assets(
    *,
    dataset_dir: Path,
    run_dir: Path,
    cohort_manifest: Path,
    c1_per_case_path: Path,
    paper_output_dir: Path,
) -> OpenWeightExportResult:
    """Aggregate run outputs and sync manuscript-ready assets."""
    case_ids = set(load_cohort_case_ids(cohort_manifest))
    per_case_path = run_dir / "per_case_results.csv"
    if not per_case_path.is_file():
        msg = f"Missing per-case results: {per_case_path}"
        raise OpenWeightLLMBaselineError(msg)

    with per_case_path.open(encoding="utf-8", newline="") as handle:
        llm_rows = [
            row for row in csv.DictReader(handle) if row["case_id"] in case_ids
        ]
    llm_metrics = aggregate_partition_metrics(llm_rows)
    llm_metrics_row = {
        "tool_id": OPENWEIGHT_TOOL_ID,
        "tool_label": OPENWEIGHT_MODEL_LABEL,
        "n_cases": int(llm_metrics["n_cases"]),
        "complete_repair_rate": float(llm_metrics["complete_repair_rate"]),
        "effective_repair_rate": float(llm_metrics["effective_repair_rate"]),
        "mean_delta_bpr": float(llm_metrics["mean_delta_bpr"]),
    }
    c1_subset = aggregate_c1_subset_metrics(
        c1_per_case_path,
        cohort_case_ids=case_ids,
    )
    comparison_rows = c1_subset + [llm_metrics_row]
    comparison_rows.sort(
        key=lambda row: (
            row["tool_id"] != OPENWEIGHT_TOOL_ID,
            -float(row["complete_repair_rate"]),
        )
    )

    paper_output_dir.mkdir(parents=True, exist_ok=True)
    tables_dir = paper_output_dir / "tables"
    leaderboard_path = paper_output_dir / "leaderboard_comparison.csv"
    table_tex = tables_dir / "table_openweight_llm_baseline.tex"
    report_md = paper_output_dir / "openweight_llm_baseline_report.md"

    write_leaderboard_csv(leaderboard_path, comparison_rows)
    cohort_name = cohort_manifest.stem.replace("_", "-")
    write_comparison_table_tex(
        table_tex,
        cohort_label=cohort_name,
        n_cases=len(case_ids),
        rows=comparison_rows,
    )
    total_runtime = sum(float(row.get("runtime_seconds") or 0.0) for row in llm_rows)
    write_technical_report(
        report_md,
        cohort_label=cohort_name,
        n_cases=len(case_ids),
        metrics_rows=comparison_rows,
        total_runtime_seconds=total_runtime,
        output_dir=paper_output_dir,
    )

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(),
        "tool_id": OPENWEIGHT_TOOL_ID,
        "model": DEFAULT_OLLAMA_MODEL,
        "cohort_manifest": str(cohort_manifest),
        "n_cases": len(case_ids),
        "metrics": llm_metrics_row,
    }
    (paper_output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    return OpenWeightExportResult(
        output_dir=paper_output_dir,
        per_case_csv=per_case_path,
        leaderboard_csv=leaderboard_path,
        table_tex=table_tex,
        report_md=report_md,
    )
