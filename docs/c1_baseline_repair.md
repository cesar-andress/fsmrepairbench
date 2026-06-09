# C1 baseline repair campaign

Campaign label: **`C1-baseline-repair`**  
Zenodo release: **`v0.2.0-analysis`** (`10.5281/zenodo.20602528`)

## Directories

| Path | Role |
|------|------|
| `data/fsmrepairbench_1k/` | Pinned dataset |
| `data/fsmrepairbench_1k/analysis_cohort_1k.txt` | Cohort manifest ($n=1{,}000$) |
| `tools/baselines_c1/` | Deterministic baseline tool configs |
| `results/repair_baseline_1k_c1/` | Raw `run-tools` output + `manifest.json` |
| `../paper1/results/baseline_repair_C1/` | Frozen paper export + `manifest.json` |

## Regeneration

```bash
fsmrepairbench run-tools data/fsmrepairbench_1k tools/baselines_c1/ \
  --out results/repair_baseline_1k_c1 --workers 4
python ../paper1/scripts/generate_baseline_repair_C1_outputs.py --workers 4
```

Write or refresh manifests only:

```bash
fsmrepairbench write-c1-manifest \
  --dataset data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --raw-runs-dir results/repair_baseline_1k_c1 \
  --paper-export-dir ../paper1/results/baseline_repair_C1 \
  --workers 4
```

## Manifest schema

Both `results/repair_baseline_1k_c1/manifest.json` and
`../paper1/results/baseline_repair_C1/manifest.json` record:

- `release_label`, `campaign_label`, `zenodo_doi`
- `dataset_path`, `cohort_file`, `cohort_sha256`, `number_of_cases`
- `tool_names`, `tool_config_paths`, `workers`
- `timestamp_utc`, `git_commit_hash`
- `output_files`, `regeneration_commands`

The paper export manifest lists frozen artefacts such as `leaderboard.csv` and
`per_case_results.csv`. The raw-runs manifest lists `summary.csv`, `leaderboard.csv`,
`tool_run_manifest.json`, and per-case JSON result files.
