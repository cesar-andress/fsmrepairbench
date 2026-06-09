"""Tests for unified campaign partition summary exports."""

from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.campaign_partitions import (
    PARTITION_COLUMNS,
    build_campaign_partition_rows,
    summarize_campaign_partitions,
)
from fsmrepairbench.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
DATASET = REPO_ROOT / "data" / "fsmrepairbench_1k"
runner = CliRunner()


def test_build_campaign_partition_rows_returns_five_campaigns() -> None:
    rows = build_campaign_partition_rows(dataset_dir=DATASET, repo_root=REPO_ROOT)
    assert len(rows) == 5
    assert {row.campaign for row in rows} == {
        "v0.2.0-analysis",
        "C1-baseline-repair",
        "RQ3-localization-ochiai-1k",
        "RQ4-higher-order-coupling-250",
        "C3-oracle-depth-ablation-200",
    }
    analysis = next(row for row in rows if row.campaign == "v0.2.0-analysis")
    assert analysis.cases_total == 1000
    assert analysis.cases_detectable == 495
    rq3 = next(row for row in rows if row.campaign.startswith("RQ3"))
    assert rq3.cases_skipped == 505
    rq4 = next(row for row in rows if row.campaign.startswith("RQ4"))
    assert rq4.cases_total == 250


def test_summarize_campaign_partitions_writes_csv_json_and_report(tmp_path: Path) -> None:
    out = tmp_path / "partitions"
    paper = tmp_path / "paper"
    result = summarize_campaign_partitions(
        dataset_dir=DATASET,
        output_dir=out,
        paper_export_dir=paper,
        repo_root=REPO_ROOT,
    )
    assert result.csv_path.is_file()
    assert result.json_path.is_file()
    assert result.report_path.is_file()
    assert result.paper_tex_path is not None and result.paper_tex_path.is_file()

    with result.csv_path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        assert reader.fieldnames == list(PARTITION_COLUMNS)
        csv_rows = list(reader)
    assert len(csv_rows) == 5

    payload = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert len(payload["campaigns"]) == 5
    assert payload["columns"] == list(PARTITION_COLUMNS)


def test_cli_summarize_campaign_partitions(tmp_path: Path) -> None:
    out = tmp_path / "out"
    paper = tmp_path / "paper"
    result = runner.invoke(
        app,
        [
            "summarize-campaign-partitions",
            "--out",
            str(out),
            "--paper-export-dir",
            str(paper),
            "--quiet",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "partition_summary.csv").is_file()
    assert (paper / "tables" / "table_campaign_partitions.tex").is_file()
