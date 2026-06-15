"""Tests for unified campaign metrics-by-partition exports."""

from __future__ import annotations

import csv
from pathlib import Path

from fsmrepairbench.campaign_metrics_by_partition import (
    METRICS_BY_PARTITION_COLUMNS,
    build_campaign_metrics_by_partition_rows,
    export_campaign_metrics_by_partition,
)


def test_build_campaign_metrics_by_partition_rows_non_empty() -> None:
    repo = Path(__file__).resolve().parents[1]
    rows = build_campaign_metrics_by_partition_rows(repo_root=repo)
    assert rows
    constructs = {row.construct for row in rows}
    partitions = {row.partition for row in rows}
    assert "detection" in constructs
    assert "localization" in constructs
    assert "repair" in constructs
    assert "detectable_only" in partitions
    assert "cohort_wide" in partitions


def test_export_campaign_metrics_by_partition_writes_csv(tmp_path: Path) -> None:
    repo = Path(__file__).resolve().parents[1]
    result = export_campaign_metrics_by_partition(
        output_dir=tmp_path / "out",
        paper_export_dir=tmp_path / "paper",
        repo_root=repo,
    )
    assert result.csv_path.is_file()
    rows = list(csv.DictReader(result.csv_path.open(encoding="utf-8")))
    assert rows
    assert list(rows[0].keys()) == list(METRICS_BY_PARTITION_COLUMNS)
    c1_rows = list(csv.DictReader(result.c1_csv_path.open(encoding="utf-8")))
    assert all(row["campaign"] == "C1-baseline-repair" for row in c1_rows)
    assert (tmp_path / "paper" / "tables" / "table_construct_metric_partitions.tex").is_file()
