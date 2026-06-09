"""Tests for RQ4 random-secondary operator sensitivity analysis."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.coupling_campaign import (
    build_operator_chain,
    build_random_operator_chain,
    parse_random_secondary_seeds,
)
from fsmrepairbench.coupling_random_secondary import (
    PER_CASE_RANDOM_COLUMNS,
    PER_SEED_SUMMARY_COLUMNS,
    RANDOM_SECONDARY_EXPERIMENT,
    random_secondary_summary_columns,
    run_random_secondary_coupling_campaign,
)

runner = CliRunner()
FIXTURE_DATASET = Path(__file__).parent / "fixtures" / "stratified_coupling_dataset"


def test_build_random_operator_chain_is_reproducible() -> None:
    chain_a = build_random_operator_chain("wrong_target", 3, "case_000001", 7)
    chain_b = build_random_operator_chain("wrong_target", 3, "case_000001", 7)
    assert chain_a == chain_b
    assert chain_a[0] == "wrong_target"
    assert len(chain_a) == 3


def test_build_random_operator_chain_differs_from_deterministic() -> None:
    deterministic = build_operator_chain("wrong_target", 3, "case_000001", 44)
    random_chain = build_random_operator_chain("wrong_target", 3, "case_000001", 0)
    assert deterministic[0] == random_chain[0] == "wrong_target"
    assert deterministic != random_chain


def test_parse_random_secondary_seeds_defaults_and_overrides() -> None:
    assert parse_random_secondary_seeds(None) == tuple(range(10))
    assert parse_random_secondary_seeds("3") == (0, 1, 2)
    assert parse_random_secondary_seeds("0,5,9") == (0, 5, 9)


def test_run_random_secondary_coupling_campaign_exports_schema(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "results"
    subset_root = tmp_path / "subsets"
    paper_dir = tmp_path / "paper"
    result = run_random_secondary_coupling_campaign(
        FIXTURE_DATASET,
        output_dir=out,
        cohort_path=cohort_path,
        subset_root=subset_root,
        paper_export_dir=paper_dir,
        campaign_seed=44,
        random_secondary_seeds=(0, 1),
        use_symlinks=False,
    )

    assert result.per_seed_summary_path.is_file()
    assert result.per_case_path.is_file()
    assert result.summary_csv_path.is_file()
    assert result.summary_json_path.is_file()
    assert result.report_path.is_file()
    assert result.manifest_path.is_file()
    assert (result.tables_dir / "table_random_secondary_summary.tex").is_file()
    assert (paper_dir / "tables" / "table_random_secondary_summary.tex").is_file()

    per_seed_rows = list(csv.DictReader(result.per_seed_summary_path.open(encoding="utf-8")))
    assert len(per_seed_rows) == 2
    assert list(per_seed_rows[0].keys()) == list(PER_SEED_SUMMARY_COLUMNS)

    per_case_rows = list(csv.DictReader(result.per_case_path.open(encoding="utf-8")))
    assert per_case_rows
    assert list(per_case_rows[0].keys()) == list(PER_CASE_RANDOM_COLUMNS)

    summary_rows = list(csv.DictReader(result.summary_csv_path.open(encoding="utf-8")))
    assert len(summary_rows) == 1
    assert list(summary_rows[0].keys()) == list(random_secondary_summary_columns())
    assert summary_rows[0]["seed_count"] == "2"

    payload = json.loads(result.summary_json_path.read_text(encoding="utf-8"))
    assert payload["experiment"] == RANDOM_SECONDARY_EXPERIMENT
    assert payload["secondary_operator_policy"] == "random"
    assert payload["random_secondary_seeds"] == [0, 1]
    assert payload["bootstrap"]["method"] == "percentile_across_seeds"

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["experiment"] == RANDOM_SECONDARY_EXPERIMENT
    assert manifest["secondary_operator_policy"] == "random"
    assert len(manifest["seed_runs"]) == 2


def test_run_random_secondary_coupling_campaign_is_reproducible(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")

    def run_once(base: Path) -> str:
        result = run_random_secondary_coupling_campaign(
            FIXTURE_DATASET,
            output_dir=base / "out",
            cohort_path=cohort_path,
            subset_root=base / "subsets",
            paper_export_dir=base / "paper",
            campaign_seed=44,
            random_secondary_seeds=(3,),
            use_symlinks=False,
        )
        row = next(csv.DictReader(result.per_seed_summary_path.open(encoding="utf-8")))
        return row["higher_order_detection_rate"]

    assert run_once(tmp_path / "run_a") == run_once(tmp_path / "run_b")


def test_run_coupling_campaign_cli_random_secondary_policy(tmp_path: Path) -> None:
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000002\n", encoding="utf-8")
    out = tmp_path / "out"
    subset_root = tmp_path / "subsets"
    result = runner.invoke(
        app,
        [
            "run-coupling-campaign",
            str(FIXTURE_DATASET),
            "--out",
            str(out),
            "--subset-dir",
            str(subset_root),
            "--cohort-file",
            str(cohort_path),
            "--seed",
            "44",
            "--copy-cases",
            "--secondary-operator-policy",
            "random",
            "--random-secondary-seeds",
            "2",
        ],
    )
    assert result.exit_code == 0, result.stdout
    assert (out / "random_secondary_summary.json").is_file()
    assert (out / "per_seed_summary.csv").is_file()
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["random_secondary_seeds"] == [0, 1]
