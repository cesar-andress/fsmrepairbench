# Multi-tool execution framework

FSMRepairBench includes a **SmartBugs-inspired** execution framework for running
multiple repair tools or models reproducibly on the same benchmark dataset.
The design follows reproducible multi-tool benchmark frameworks where each tool
is described declaratively, executed uniformly on every case, and summarized in
machine-readable reports suitable for leaderboard comparison.

## Inspiration

Frameworks such as [SmartBugs](https://github.com/smartbugs/smartbugs) demonstrate
how to:

- describe analysis tools in YAML configuration files
- run every tool on every benchmark artefact
- capture per-run JSON results with timeout and failure metadata
- resume long-running campaigns without redoing completed work
- aggregate tool outcomes into comparison tables

FSMRepairBench adapts this pattern to **FSM repair evaluation**: each tool receives
a benchmark case (`faulty_fsm.json`, `oracle_suite.json`) and produces a repair
result scored against the oracle suite.

## Tool configuration

Tool configs live in a directory of YAML files, for example `tools/`:

```yaml
tool_id: baseline_missing_transition
tool_type: baseline
command: missing-transition
timeout_seconds: 60
environment: {}
input_format: fsmrepairbench_case_v1
output_format: fsmrepairbench_repair_result_v1
iterations: 1
temperature: 0.0
```

### Required fields

| Field | Description |
|-------|-------------|
| `tool_id` | Stable identifier used in result filenames and leaderboard rows |
| `tool_type` | `llm`, `baseline`, or `external` |
| `command` | Model name, baseline engine name, or external shell command template |
| `timeout_seconds` | Per-run timeout |
| `environment` | Extra environment variables for the tool process |
| `input_format` | Currently `fsmrepairbench_case_v1` |
| `output_format` | Currently `fsmrepairbench_repair_result_v1` |

Optional fields:

- `iterations` — repair loop depth (default `3` for LLM, `1` for baselines)
- `temperature` — LLM sampling temperature (default `0.0`)

### Built-in example configs

| File | Type | Purpose |
|------|------|---------|
| `tools/qwen_ollama.yaml` | LLM | Ollama Qwen model |
| `tools/llama_ollama.yaml` | LLM | Ollama Llama model |
| `tools/baseline_missing_transition.yaml` | Baseline | Oracle-guided missing transition repair |
| `tools/baseline_wrong_target.yaml` | Baseline | Oracle-guided wrong-target repair |

### External command placeholders

For `tool_type: external`, `command` may reference:

| Placeholder | Value |
|-------------|-------|
| `{case_dir}` | Source benchmark case directory |
| `{case_id}` | Case identifier |
| `{faulty_fsm}` | Path to staged faulty FSM JSON |
| `{oracle}` | Path to staged oracle suite JSON |
| `{output}` | Path where the tool must write JSON output |
| `{tool_id}` | Tool identifier |

The external tool must write JSON compatible with `fsmrepairbench_repair_result_v1`
(either a full `RepairResult` object or a wrapper containing `repair_result`).

## CLI

```bash
fsmrepairbench run-tools DATASET_DIR tools/ --out results/tool_runs
```

Options:

- `--resume/--no-resume` — skip case/tool pairs whose JSON result already exists
- `--workers N` — parallel execution (default `1`)
- `--quiet` — print a short summary only

Example with two baseline tools on a generated dataset:

```bash
fsmrepairbench build-dataset --size 10 --seed 42 --output data/run1
fsmrepairbench run-tools data/run1 tools/ \
  --out results/tool_runs \
  --workers 2 \
  --resume
```

## Output layout

```
results/tool_runs/
├── case_000001__baseline_missing_transition.json
├── case_000001__baseline_wrong_target.json
├── case_000002__baseline_missing_transition.json
├── ...
├── summary.csv
├── leaderboard.csv
└── tool_run_manifest.json
```

### Per-run JSON

One JSON file per `(case, tool)` pair containing:

- case and tool identifiers
- `status`: `completed`, `failed`, `skipped`, or `timeout`
- `failure_class`: outcome category (see below)
- BPR metrics (`initial_bpr`, `final_bpr`, `delta_bpr`)
- nested `repair_result` when execution succeeded

### Failure classification

| Class | Meaning |
|-------|---------|
| `complete_repair` | Final BPR == 1.0 |
| `effective_repair` | Final BPR improved but < 1.0 |
| `no_improvement` | No BPR change |
| `regression` | Final BPR decreased |
| `timeout` | Run exceeded `timeout_seconds` |
| `tool_error` | Tool crashed or returned invalid output |
| `parse_error` | Output could not be parsed |
| `skipped` | Loaded from an existing result during resume |

### Aggregates

- **`summary.csv`** — one row per case/tool run with status and metrics
- **`leaderboard.csv`** — tool-level aggregates (success rates, average BPR delta, runtime)
- **`tool_run_manifest.json`** — run metadata (dataset path, tool ids, resume flag)

## Python API

```python
from pathlib import Path
from fsmrepairbench.tool_runner import load_tool_configs, run_tools

tools = load_tool_configs(Path("tools"))
result = run_tools(
    Path("data/fsmrepairbench_v1"),
    Path("tools"),
    Path("results/tool_runs"),
    resume=True,
    workers=4,
)
print(result.summary_path, result.leaderboard_path)
```

## Reproducibility notes

- Pin tool configs in version control alongside dataset manifests.
- Use `--resume` for fault-tolerant long campaigns.
- Keep `environment` values (API hosts, keys) outside committed configs when needed.
- Compare tools with `leaderboard.csv` or the existing `fsmrepairbench leaderboard` command on the same output directory.

## Related commands

| Command | Role |
|---------|------|
| `build-dataset` | Generate benchmark cases |
| `run-experiment` | YAML-driven LLM experiment runner |
| `run-tools` | Multi-tool SmartBugs-style runner |
| `leaderboard` | Rank models/tools from result JSON files |
| `freeze-release` | Package results for publication |
