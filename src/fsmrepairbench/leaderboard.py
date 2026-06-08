"""Benchmark leaderboard generation from experiment results."""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.models import RepairResult

RESULT_FILE_PATTERN = "case_*__*.json"

LEADERBOARD_COLUMNS: tuple[str, ...] = (
    "rank",
    "model",
    "cases",
    "repair_success_rate",
    "complete_repair_rate",
    "avg_bpr_improvement",
    "avg_iterations",
    "avg_runtime_seconds",
)


class LeaderboardError(RuntimeError):
    """Raised when leaderboard generation fails."""


@dataclass(frozen=True)
class CaseResultRecord:
    """One completed repair execution."""

    case_id: str
    model: str
    initial_bpr: float
    final_bpr: float
    delta_bpr: float
    complete_repair: bool
    effective_repair: bool
    iterations_completed: int
    runtime_seconds: float


@dataclass(frozen=True)
class LeaderboardEntry:
    """Aggregated leaderboard metrics for one model."""

    rank: int
    model: str
    cases: int
    repair_success_rate: float
    complete_repair_rate: float
    avg_bpr_improvement: float
    avg_iterations: float
    avg_runtime_seconds: float

    def to_dict(self) -> dict[str, str | int | float]:
        return {
            "rank": self.rank,
            "model": self.model,
            "cases": self.cases,
            "repair_success_rate": self.repair_success_rate,
            "complete_repair_rate": self.complete_repair_rate,
            "avg_bpr_improvement": self.avg_bpr_improvement,
            "avg_iterations": self.avg_iterations,
            "avg_runtime_seconds": self.avg_runtime_seconds,
        }


@dataclass(frozen=True)
class LeaderboardResult:
    """Paths and entries for a generated leaderboard."""

    results_dir: Path
    csv_path: Path
    markdown_path: Path
    entries: tuple[LeaderboardEntry, ...]


def discover_result_files(results_dir: Path) -> list[Path]:
    """Return result JSON files under *results_dir*."""
    return sorted(path for path in results_dir.glob(RESULT_FILE_PATTERN) if path.is_file())


def _runtime_from_payload(payload: dict[str, object]) -> float:
    runtime_value = payload.get("runtime_seconds")
    if isinstance(runtime_value, (int, float, str)):
        return float(runtime_value)
    repair_result = payload.get("repair_result")
    if isinstance(repair_result, dict):
        details = repair_result.get("details")
        if isinstance(details, dict):
            nested_runtime = details.get("runtime_seconds")
            if isinstance(nested_runtime, (int, float, str)):
                return float(nested_runtime)
    return 0.0


def load_case_result_record(path: Path) -> CaseResultRecord:
    """Load one case/model result record from JSON."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        RepairResult.model_validate(payload["repair_result"])
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        msg = f"Invalid result file {path}: {exc}"
        raise LeaderboardError(msg) from exc

    return CaseResultRecord(
        case_id=str(payload["case_id"]),
        model=str(payload["model"]),
        initial_bpr=float(payload["initial_bpr"]),
        final_bpr=float(payload["final_bpr"]),
        delta_bpr=float(payload["delta_bpr"]),
        complete_repair=bool(payload["complete_repair"]),
        effective_repair=bool(payload["effective_repair"]),
        iterations_completed=int(payload["iterations_completed"]),
        runtime_seconds=_runtime_from_payload(payload),
    )


def load_case_result_records(results_dir: Path) -> list[CaseResultRecord]:
    """Load all case/model result records from *results_dir*."""
    if not results_dir.is_dir():
        msg = f"Results directory not found: {results_dir}"
        raise LeaderboardError(msg)

    result_files = discover_result_files(results_dir)
    if not result_files:
        msg = f"No result files matching {RESULT_FILE_PATTERN} found in {results_dir}"
        raise LeaderboardError(msg)

    return [load_case_result_record(path) for path in result_files]


def compute_leaderboard_entries(records: list[CaseResultRecord]) -> list[LeaderboardEntry]:
    """Aggregate *records* into ranked leaderboard entries."""
    if not records:
        msg = "Cannot compute leaderboard from an empty result set"
        raise LeaderboardError(msg)

    grouped: dict[str, list[CaseResultRecord]] = {}
    for record in records:
        grouped.setdefault(record.model, []).append(record)

    entries: list[LeaderboardEntry] = []
    for model, model_records in grouped.items():
        cases = len(model_records)
        repair_success_rate = sum(1 for item in model_records if item.effective_repair) / cases
        complete_repair_rate = sum(1 for item in model_records if item.complete_repair) / cases
        avg_bpr_improvement = sum(item.delta_bpr for item in model_records) / cases
        avg_iterations = sum(item.iterations_completed for item in model_records) / cases
        avg_runtime_seconds = sum(item.runtime_seconds for item in model_records) / cases
        entries.append(
            LeaderboardEntry(
                rank=0,
                model=model,
                cases=cases,
                repair_success_rate=round(repair_success_rate, 6),
                complete_repair_rate=round(complete_repair_rate, 6),
                avg_bpr_improvement=round(avg_bpr_improvement, 6),
                avg_iterations=round(avg_iterations, 4),
                avg_runtime_seconds=round(avg_runtime_seconds, 4),
            )
        )

    entries.sort(
        key=lambda entry: (
            -entry.complete_repair_rate,
            -entry.repair_success_rate,
            -entry.avg_bpr_improvement,
            entry.avg_runtime_seconds,
            entry.model,
        )
    )
    return [
        LeaderboardEntry(
            rank=index,
            model=entry.model,
            cases=entry.cases,
            repair_success_rate=entry.repair_success_rate,
            complete_repair_rate=entry.complete_repair_rate,
            avg_bpr_improvement=entry.avg_bpr_improvement,
            avg_iterations=entry.avg_iterations,
            avg_runtime_seconds=entry.avg_runtime_seconds,
        )
        for index, entry in enumerate(entries, start=1)
    ]


def write_leaderboard_csv(path: Path, entries: list[LeaderboardEntry]) -> None:
    """Write leaderboard metrics to CSV."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(LEADERBOARD_COLUMNS))
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    key: (
                        f"{value:.6f}"
                        if key
                        in {
                            "repair_success_rate",
                            "complete_repair_rate",
                            "avg_bpr_improvement",
                        }
                        and isinstance(value, float)
                        else (
                            f"{value:.4f}"
                            if key in {"avg_iterations", "avg_runtime_seconds"}
                            and isinstance(value, float)
                            else value
                        )
                    )
                    for key, value in entry.to_dict().items()
                }
            )


def write_leaderboard_markdown(path: Path, entries: list[LeaderboardEntry]) -> None:
    """Write a Markdown leaderboard table."""
    headers = [
        "Rank",
        "Model",
        "Cases",
        "Repair Success",
        "Complete Repair",
        "Avg BPR Δ",
        "Avg Iterations",
        "Avg Runtime (s)",
    ]
    lines = [
        "# FSMRepairBench Leaderboard",
        "",
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join(["---"] * len(headers)) + " |",
    ]
    for entry in entries:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(entry.rank),
                    entry.model,
                    str(entry.cases),
                    f"{entry.repair_success_rate:.2%}",
                    f"{entry.complete_repair_rate:.2%}",
                    f"{entry.avg_bpr_improvement:.4f}",
                    f"{entry.avg_iterations:.2f}",
                    f"{entry.avg_runtime_seconds:.2f}",
                ]
            )
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def generate_leaderboard(results_dir: Path) -> LeaderboardResult:
    """Generate leaderboard CSV and Markdown for experiment *results_dir*."""
    records = load_case_result_records(results_dir)
    entries = compute_leaderboard_entries(records)
    csv_path = results_dir / "leaderboard.csv"
    markdown_path = results_dir / "leaderboard.md"
    write_leaderboard_csv(csv_path, entries)
    write_leaderboard_markdown(markdown_path, entries)
    return LeaderboardResult(
        results_dir=results_dir,
        csv_path=csv_path,
        markdown_path=markdown_path,
        entries=tuple(entries),
    )
