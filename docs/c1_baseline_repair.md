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

## Multi-seed random baseline

Deterministic baselines (`missing-transition`, `wrong-target`) are unchanged. The
single-seed random row in `leaderboard.csv` (seed 0) remains for backward
compatibility. The multi-seed random summary is the preferred floor estimate for
STVR reporting.

Default seeds: `0,1,2,3,4,5,6,7,8,9` (override with `--random-seeds`).

Exports:

| Path | Role |
|------|------|
| `results/repair_baseline_1k_c1/random_multiseed_summary.csv` | Flattened mean/std/min/max + bootstrap 95% CI |
| `results/repair_baseline_1k_c1/random_multiseed_summary.json` | Same summary plus bootstrap metadata |
| `results/repair_baseline_1k_c1/random_multiseed_per_seed.csv` | Per-seed cohort metrics |
| `results/repair_baseline_1k_c1/report.md` | Bootstrap method and interpretation |
| `../paper1/results/baseline_repair_C1/tables/table_random_multiseed.tex` | LaTeX table |

Bootstrap: percentile resampling on seed-level metrics, 10,000 resamples, 95% CI,
RNG seed 42 (see `report.md`).

CLI-only multi-seed refresh:

```bash
fsmrepairbench export-c1-baseline-repair data/fsmrepairbench_1k \
  --out ../paper1/results/baseline_repair_C1 \
  --random-seeds 0,1,2,3,4,5,6,7,8,9 \
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
