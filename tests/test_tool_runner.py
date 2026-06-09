"""Tests for the SmartBugs-style multi-tool execution framework."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from fsmrepairbench.cli import app
from fsmrepairbench.tool_runner import (
    ToolRunnerError,
    build_tool_tasks,
    classify_failure,
    execute_tool_task,
    load_tool_config,
    load_tool_configs,
    run_tools,
    tool_result_path,
)
from tests.helpers import setup_cases_root

REPO_ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = REPO_ROOT / "tools"
runner = CliRunner()


def test_load_tool_configs_from_repo_tools_dir() -> None:
    configs = load_tool_configs(TOOLS_DIR)
    tool_ids = {config.tool_id for config in configs}
    assert "baseline_missing_transition" in tool_ids
    assert "baseline_wrong_target" in tool_ids
    assert "qwen_ollama" in tool_ids


def test_load_tool_config_validates_formats(tmp_path: Path) -> None:
    path = tmp_path / "bad.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "tool_id": "bad_tool",
                "tool_type": "baseline",
                "command": "missing-transition",
                "timeout_seconds": 10,
                "environment": {},
                "input_format": "unknown_format",
                "output_format": "fsmrepairbench_repair_result_v1",
            }
        ),
        encoding="utf-8",
    )
    with pytest.raises(ToolRunnerError, match="Unsupported input_format"):
        load_tool_config(path)


def test_build_tool_tasks_cartesian_product(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    from fsmrepairbench.experiments import discover_experiment_cases

    cases = discover_experiment_cases(cases_dir)
    tools = load_tool_configs(TOOLS_DIR)
    tasks = build_tool_tasks(cases, tools[:2])
    assert len(tasks) == len(cases) * 2


def test_execute_baseline_tool_writes_result_json(tmp_path: Path) -> None:
    cases_dir = setup_cases_root(tmp_path)
    from fsmrepairbench.experiments import discover_experiment_cases

    cases = discover_experiment_cases(cases_dir)
    tool = load_tool_config(TOOLS_DIR / "baseline_missing_transition.yaml")
    output_dir = tmp_path / "results"
    task = build_tool_tasks(cases[:1], [tool])[0]

    summary = execute_tool_task(task, output_dir=output_dir)
    result_path = tool_result_path(output_dir, task.case.case_id, tool.tool_id)

    assert result_path.is_file()
    assert summary.status == "completed"
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    assert payload["tool_id"] == tool.tool_id
    assert payload["failure_class"] in {"complete_repair", "effective_repair", "no_improvement"}


def test_run_tools_generates_summary_and_leaderboard(tmp_path: Path) -> None:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "baseline_missing_transition.yaml").write_text(
        (TOOLS_DIR / "baseline_missing_transition.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    (tools_dir / "baseline_wrong_target.yaml").write_text(
        (TOOLS_DIR / "baseline_wrong_target.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output_dir = tmp_path / "tool_runs"

    result = run_tools(cases_root, tools_dir, output_dir, resume=False, workers=1)

    assert result.summary_path.is_file()
    assert result.leaderboard_path.is_file()
    assert (output_dir / "tool_run_manifest.json").is_file()
    assert len(result.rows) == 4
    summary_lines = result.summary_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(summary_lines) == 5  # header + 4 rows


def test_run_tools_resume_skips_existing_results(tmp_path: Path) -> None:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "baseline_missing_transition.yaml").write_text(
        (TOOLS_DIR / "baseline_missing_transition.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output_dir = tmp_path / "tool_runs"

    calls = {"count": 0}

    def counting_executor(task, out_dir):  # type: ignore[no-untyped-def]
        calls["count"] += 1
        return execute_tool_task(task, output_dir=out_dir)

    run_tools(
        cases_root,
        tools_dir,
        output_dir,
        resume=False,
        workers=1,
        executor=counting_executor,
    )
    assert calls["count"] == 2

    run_tools(
        cases_root,
        tools_dir,
        output_dir,
        resume=True,
        workers=1,
        executor=counting_executor,
    )
    assert calls["count"] == 2


def test_external_tool_timeout_is_classified(tmp_path: Path) -> None:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    slow_script = tmp_path / "slow.sh"
    slow_script.write_text("#!/bin/sh\nsleep 2\n", encoding="utf-8")
    slow_script.chmod(slow_script.stat().st_mode | stat.S_IXUSR)
    tool_config = {
        "tool_id": "slow_external",
        "tool_type": "external",
        "command": str(slow_script),
        "timeout_seconds": 1,
        "environment": {},
        "input_format": "fsmrepairbench_case_v1",
        "output_format": "fsmrepairbench_repair_result_v1",
    }
    (tools_dir / "slow_external.yaml").write_text(
        yaml.safe_dump(tool_config),
        encoding="utf-8",
    )
    output_dir = tmp_path / "tool_runs"
    result = run_tools(cases_root, tools_dir, output_dir, resume=False, workers=1)
    assert any(row.failure_class == "timeout" for row in result.rows)


def test_external_tool_success_parses_repair_result(tmp_path: Path) -> None:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    script = tmp_path / "emit_result.sh"
    script.write_text(
        """#!/bin/sh
output_path="$4"
cat > "$output_path" <<'EOF'
{
  "bug_id": "toggle_001__missing_transition__42",
  "passed": true,
  "score": 1.0,
  "details": {
    "backend": "external",
    "runtime_seconds": 0.1,
    "iterations": []
  }
}
EOF
""",
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    tool_config = {
        "tool_id": "emit_external",
        "tool_type": "external",
        "command": f"{script} {{case_dir}} {{faulty_fsm}} {{oracle}} {{output}}",
        "timeout_seconds": 10,
        "environment": {},
        "input_format": "fsmrepairbench_case_v1",
        "output_format": "fsmrepairbench_repair_result_v1",
    }
    (tools_dir / "emit_external.yaml").write_text(yaml.safe_dump(tool_config), encoding="utf-8")
    output_dir = tmp_path / "tool_runs"
    result = run_tools(cases_root, tools_dir, output_dir, resume=False, workers=1)
    assert any(row.failure_class == "complete_repair" for row in result.rows)


def test_classify_failure_helpers() -> None:
    assert (
        classify_failure(
            status="completed",
            initial_bpr=0.5,
            final_bpr=1.0,
            complete_repair=True,
            effective_repair=True,
            regression=False,
        )
        == "complete_repair"
    )
    assert (
        classify_failure(
            status="timeout",
            initial_bpr=0.5,
            final_bpr=0.5,
            complete_repair=False,
            effective_repair=False,
            regression=False,
        )
        == "timeout"
    )


def test_cli_run_tools(tmp_path: Path) -> None:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "baseline_missing_transition.yaml").write_text(
        (TOOLS_DIR / "baseline_missing_transition.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output_dir = tmp_path / "tool_runs"

    result = runner.invoke(
        app,
        [
            "run-tools",
            str(cases_root),
            str(tools_dir),
            "--out",
            str(output_dir),
            "--workers",
            "1",
        ],
    )

    assert result.exit_code == 0, result.stdout
    assert (output_dir / "summary.csv").is_file()
    assert (output_dir / "leaderboard.csv").is_file()


def test_run_tools_filters_by_cohort_file(tmp_path: Path) -> None:
    cases_root = tmp_path / "dataset"
    setup_cases_root(cases_root)
    cohort_path = tmp_path / "cohort.txt"
    cohort_path.write_text("case_000001\n", encoding="utf-8")
    tools_dir = tmp_path / "tools"
    tools_dir.mkdir()
    (tools_dir / "baseline_missing_transition.yaml").write_text(
        (TOOLS_DIR / "baseline_missing_transition.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    output_dir = tmp_path / "tool_runs"

    result = run_tools(
        cases_root,
        tools_dir,
        output_dir,
        cohort_file=cohort_path,
        workers=1,
    )

    assert len(result.rows) == 1
    assert result.rows[0].case_id == "case_000001"
