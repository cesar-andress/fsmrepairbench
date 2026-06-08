"""Progress tracking with checkpointed CSV writes."""

from __future__ import annotations

import csv
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from fsmrepairbench.experiments import ExperimentSummaryRow

PROGRESS_COLUMNS: tuple[str, ...] = (
    "case_id",
    "model",
    "mutation_operator",
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
    "status",
)

SUMMARY_COLUMNS: tuple[str, ...] = PROGRESS_COLUMNS[:-1]


class ProgressTracker:
    """Track experiment rows and checkpoint progress periodically."""

    def __init__(
        self,
        *,
        progress_path: Path,
        summary_path: Path,
        checkpoint_interval: int = 100,
    ) -> None:
        self.progress_path = progress_path
        self.summary_path = summary_path
        self.checkpoint_interval = max(1, checkpoint_interval)
        self._rows: list[ExperimentSummaryRow] = []
        self._lock = Lock()
        self._completed_since_checkpoint = 0

    def add_row(self, row: ExperimentSummaryRow) -> None:
        with self._lock:
            self._rows.append(row)
            self._completed_since_checkpoint += 1
            if self._completed_since_checkpoint >= self.checkpoint_interval:
                self._write_progress_locked()
                self._completed_since_checkpoint = 0

    def extend_rows(self, rows: list[ExperimentSummaryRow]) -> None:
        with self._lock:
            self._rows.extend(rows)

    def finalize(self) -> tuple[ExperimentSummaryRow, ...]:
        with self._lock:
            self._write_progress_locked()
            self._write_summary_locked()
            return tuple(self._rows)

    def _write_progress_locked(self) -> None:
        _write_csv(
            self.progress_path,
            PROGRESS_COLUMNS,
            [row.to_progress_dict() for row in self._rows],
        )

    def _write_summary_locked(self) -> None:
        _write_csv(
            self.summary_path,
            SUMMARY_COLUMNS,
            [row.to_summary_dict() for row in self._rows],
        )


def _write_csv(path: Path, fieldnames: tuple[str, ...], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)
