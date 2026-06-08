"""Machine-readable export helpers for SOTA analysis artefacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel


def write_json_report(path: Path, payload: BaseModel | dict[str, Any]) -> None:
    """Write a JSON report from a Pydantic model or mapping."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(payload, indent=2, sort_keys=True)
    path.write_text(text + "\n", encoding="utf-8")


def write_csv_report(
    path: Path,
    *,
    columns: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> None:
    """Write rows as CSV using fixed *columns*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
