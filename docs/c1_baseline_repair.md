# C1 baseline repair campaign

Campaign label: **`C1-baseline-repair`**  
Zenodo release: **`v0.2.0-analysis`** (`10.5281/zenodo.20724095`)

## Cohort and engines

| Item | Value |
|------|-------|
| Dataset | `data/fsmrepairbench_1k/` |
| Cohort | `data/fsmrepairbench_1k/analysis_cohort_1k.txt` ($n=1{,}000$) |
| Tools | `tools/baselines_c1/` |
| Engines | `missing-transition`, `wrong-target`, `random` (control) |
| Patch policy | Single-pass typed patch from `faulty_fsm.json` + `oracle_suite.json` |

Metrics: **complete repair**, **effective repair**, **ΔBPR**, cohort **leaderboard**, per-case enriched CSV.

## Output directory

| Path | Role |
|------|------|
| `results/baseline_repair_C1/` | Canonical C1 run-tools output + frozen exports |
| `results/repair_baseline_1k_c1/` | Legacy raw runs (still accepted as input) |
| `../paper1/results/baseline_repair_C1/` | Paper tree mirror (LaTeX, PNG, manifest) |

Key artefacts under `results/baseline_repair_C1/`:

- `summary.csv` — per-case run-tools rows (preserved for bootstrap CIs)
- `cohort_summary.csv` — flat cohort metric/value aggregates
- `leaderboard.csv` — tool-level complete/effective repair and mean ΔBPR
- `per_case_results.csv` — enriched per-case table
- `figures/*.png` — histogram and breakdown figures
- `tables/*.tex` — paper-ready LaTeX tables
- `manifest.json` — Zenodo v0.2.0-analysis freeze metadata

## Reproducibility

### Step 1 — run-tools (low-level)

```bash
fsmrepairbench run-tools data/fsmrepairbench_1k tools/baselines_c1/ \
  --out results/baseline_repair_C1 \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --workers 4
```

### Step 2 — export CSV / LaTeX / PNG / manifest

```bash
fsmrepairbench export-c1-baseline-repair data/fsmrepairbench_1k \
  --out results/baseline_repair_C1 \
  --paper-export-dir ../paper1/results/baseline_repair_C1 \
  --workers 4
```

### One-shot

```bash
fsmrepairbench run-c1-baseline-repair data/fsmrepairbench_1k \
  --out results/baseline_repair_C1 \
  --paper-export-dir ../paper1/results/baseline_repair_C1 \
  --workers 4
```

Legacy paper script (export-only from existing run-tools output):

```bash
python ../paper1/scripts/generate_baseline_repair_C1_outputs.py --workers 4
```

## Multi-seed random baseline

Deterministic baselines are unchanged. The seed-0 random row in `leaderboard.csv` remains for backward compatibility; the multi-seed summary is the preferred floor estimate.

Default seeds: `0,1,2,3,4,5,6,7,8,9` (override with `--random-seeds`).

Exports:

| Path | Role |
|------|------|
| `random_multiseed_summary.csv` | Mean/std/min/max + bootstrap 95% CI |
| `random_multiseed_per_seed.csv` | Per-seed cohort metrics |
| `confidence_intervals.csv` | Case-level bootstrap 95% CI (`baseline_missing_transition`) |
| `tables/table_confidence_intervals.tex` | LaTeX CI table |
| `tables/table_random_multiseed.tex` | LaTeX multi-seed table |

## Manifest schema

`manifest.json` records:

- `release_label`, `campaign_label`, `zenodo_doi`
- `dataset_path`, `cohort_file`, `cohort_sha256`, `number_of_cases`
- `tool_names`, `tool_config_paths`, `workers`
- `timestamp_utc`, `git_commit_hash`
- `output_files`, `regeneration_commands`
