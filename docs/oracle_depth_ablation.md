# Oracle Depth Ablation (C3)

## Enhanced ablation (500 cases, depth-forced, repair metrics)

Release label: **`C3-oracle-depth-ablation-500`**

The enhanced experiment uses **depth-forced** scenario generation so executed walk lengths
actually increase across presets (unlike the legacy shortest-path 200-case run, where all
presets stayed near ~4 steps). It reports detection, complete/effective repair, and ΔBPR
with the `missing-transition` baseline on a **500-case** stratified pin.

| Preset | Max steps | Mean scenario length (500-case run) |
|--------|----------:|------------------------------------:|
| shallow | 5 | ~4.1 |
| medium | 12 | ~9.3 |
| deep | 25 | ~18.5 |

### Cohort (500 cases)

| File | Role |
|------|------|
| `data/fsmrepairbench_1k/oracle_depth_ablation_500.txt` | Pinned 500-case ablation sample |
| `data/fsmrepairbench_1k/oracle_depth_ablation_500.json` | Manifest (SHA-256, release label) |

### Run

```bash
python ../paper1/scripts/pin_oracle_depth_ablation_500_cohort.py
python ../paper1/scripts/run_oracle_depth_ablation_enhanced.py \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_500.txt \
  --no-write-cohort
python ../paper1/scripts/generate_oracle_depth_ablation_outputs.py
```

Or via CLI:

```bash
fsmrepairbench run-oracle-depth-ablation-enhanced data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_500.txt \
  --no-write-cohort \
  --out results/oracle_depth_ablation
```

Frozen paper export: `paper1/results/oracle_depth_ablation/` (includes `manifest.json`
with `release_label`, `zenodo_doi`, `git_commit_hash`, and `depth_summary_sha256`).

---

## Legacy ablation (200 cases, shortest-path)

Construct-validity experiment measuring how sensitive mutation detection, behavioural
pass rate (BPR), and oracle coverage are to the **depth preset** used when generating
behavioural oracle suites.

## Motivation

The EMSE mock review flagged oracle depth as a construct-validity risk: published
`fsmrepairbench_1k` cases use **shallow** oracles (`max_steps = 5`), and aggregate
detection rates may partly reflect shallow scenario walks rather than intrinsic fault
detectability.

This experiment regenerates oracles at three existing presets on a **fixed** set of
200 benchmark cases (same reference/faulty FSMs) and compares:

- mutation detection rate (`bpr_delta > 0`)
- mean reference/faulty BPR and mean BPR delta
- detectable-case ratio
- oracle state/transition/event coverage

No new benchmark dimensions, dataset formats, or oracle algorithms are introduced.

## Depth presets

| Preset | `DEPTH_MAX_STEPS` | CLI `--depth` |
|--------|------------------:|---------------|
| shallow | 5 | `shallow` |
| medium | 12 | `medium` |
| deep | 25 | `deep` |

Implementation: `generate_oracle_suite()` in `src/fsmrepairbench/oracle_generator.py`.

## Cohort

| File | Role |
|------|------|
| `data/fsmrepairbench_1k/analysis_cohort_1k.txt` | Source pool (1,000 published cases) |
| `data/fsmrepairbench_1k/oracle_depth_ablation_200.txt` | Pinned 200-case ablation sample |
| `data/fsmrepairbench_1k/oracle_depth_ablation_200.json` | Manifest (SHA-256, timestamps) |

Selection: round-robin across `(mutation_operator, complexity)` strata from the 1k cohort.

## Run

From the repository root:

```bash
fsmrepairbench run-oracle-depth-ablation data/fsmrepairbench_1k \
  --out results/oracle_depth_ablation \
  --cohort-size 200
```

Reuse a pinned cohort:

```bash
fsmrepairbench run-oracle-depth-ablation data/fsmrepairbench_1k \
  --out results/oracle_depth_ablation \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_200.txt \
  --no-write-cohort
```

Runtime: ~10 s for 200×3 oracle generations on a typical workstation (CPU-only).

## Outputs

Directory: `results/oracle_depth_ablation/`

| File | Description |
|------|-------------|
| `depth_summary.csv` | One row per depth: detection rate, BPR means, path length, coverage means |
| `summary.csv` | Long-format metrics keyed by `(oracle_depth, metric)` |
| `distributions.csv` | Bucketed distributions per depth |
| `per_case_results.csv` | Paired case×depth behavioural metrics |
| `report.md` | Narrative answer to the sensitivity question |
| `manifest.json` | Run metadata and depth summaries |
| `figures/` | Publication PNG figures |
| `tables/` | LaTeX tables (`table_depth_summary.tex`, `table_detection_by_operator_depth.tex`) |

## Key results (200-case cohort, v0.2.0-analysis dataset)

| Depth | Max steps | Detection rate | Mean BPR delta | Mean max path | Max path length |
|-------|----------:|---------------:|---------------:|--------------:|----------------:|
| shallow | 5 | 48.5% | 0.082 | 4.0 | (per run) |
| medium | 12 | 48.5% | 0.082 | 4.0 | (per run) |
| deep | 25 | 48.5% | 0.082 | 4.0 | (per run) |

**Answer (v1, shortest-path):** On this cohort, benchmark detection conclusions are **insensitive** to oracle
depth within the shallow/medium/deep presets because the shipped shortest-path generator never lengthened
executed walks (mean max steps ≈ 4 at every preset).

**Answer (v2, depth-forced):** With `--scenario-policy depth-forced`, mean scenario length rises to
4.1 / 9.3 / 18.5 steps and mean ΔBPR rises to 0.093 / 0.126 / 0.165, but detection stays 48.5%
with zero paired gains or losses vs shallow. The v1 null reflects **preset inoperability**, not general
depth insensitivity; v2 shows BPR metrics respond when walks lengthen even though the detectable
partition is unchanged on this pin.

Implications for §10 Threats to Validity:

1. Detection rates on `fsmrepairbench_1k` are **not** artificially lowered by the shallow
   preset alone; deeper caps do not expose additional faults in this sample.
2. Residual 0% detection operators (e.g. `action_corruption`, `dead_state_intro`) reflect
   oracle–mutation interaction limits, not merely shallow walks.
3. Future work may still need **richer oracle generation** (not just higher step caps) to
   stress subtle behavioural faults.

## Figures

- `figures/detection_rate_by_depth.png` — overall detection by preset
- `figures/mutation_detection_by_operator_depth.png` — operator×depth grouped bars
- `figures/mean_bpr_delta_by_depth.png` — mean BPR delta by preset
- `figures/bpr_delta_distribution_{shallow,medium,deep}.png` — per-depth BPR delta histograms

## API

Python module: `fsmrepairbench.oracle_depth_ablation`

```python
from pathlib import Path
from fsmrepairbench.oracle_depth_ablation import run_oracle_depth_ablation

result = run_oracle_depth_ablation(
    Path("data/fsmrepairbench_1k"),
    output_dir=Path("results/oracle_depth_ablation"),
    cohort_size=200,
)
print(result.report_path)
```

## Tests

```bash
pytest tests/test_oracle_depth_ablation.py -q
```

## Related artefacts

- Paper design note: `paper1/reviews/minimum_publishable_experiment.md` (C3)
- Oracle specification: `docs/oracle_spec.md`
- Published analysis baseline: `results/analysis/` (1,000-case shallow oracles)

## Depth-forced sensitivity (C3 v2)

The original C3 campaign (`--scenario-policy shortest-path`, default) preserves
shortest-path oracle generation. Because compact FSMs already fit within the
shallow step cap, shallow/medium/deep produce identical suites (~4 steps).

The **depth-forced** policy (`--scenario-policy depth-forced`) actively lengthens
scenario walks and adds extra random-walk scenarios when medium/deep presets are
requested, so depth presets change the executed scenario catalogue.

```bash
fsmrepairbench run-oracle-depth-ablation data/fsmrepairbench_1k \
  --scenario-policy depth-forced \
  --out results/oracle_depth_ablation_v2 \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_200.txt \
  --no-write-cohort
```

Outputs under `results/oracle_depth_ablation_v2/`:

| File | Description |
|------|-------------|
| `depth_summary.csv` | Per-depth detection, BPR, scenario length, gains/losses vs shallow |
| `per_case_results.csv` | Case×depth metrics incl. declared/observed depth |
| `paired_detection_changes.csv` | McNemar-style paired detection table vs shallow |
| `coverage_by_depth.csv` | State/transition/event coverage and scenario counts |
| `report.md` | Narrative sensitivity report |
| `manifest.json` | Run metadata |
| `figures/`, `tables/` | Publication assets |

Paper export: `../paper1/results/oracle_depth_ablation_v2/tables/`

## Extended depth ladder (C3 extended)

The v2 campaign still capped analysis at `deep` (25 declared steps). The
**extended** follow-up adds `exhaustive_like` (40), `extended_50`, and
`extended_60` presets under `--scenario-policy depth-forced`, and evaluates
`missing-transition` repair at every depth on the same 200-case pin.

```bash
fsmrepairbench run-oracle-depth-ablation-extended data/fsmrepairbench_1k \
  --out results/oracle_depth_ablation_extended \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_200.txt \
  --no-write-cohort

python ../paper1/scripts/generate_oracle_depth_ablation_extended_outputs.py
```

| File | Description |
|------|-------------|
| `per_case_results.csv` | Case×depth detection, ΔBPR, and repair metrics |
| `depth_summary.csv` | Aggregate detection, ΔBPR, repair, scenario length |
| `paired_detection_changes.csv` | Paired detection vs shallow for all higher presets |
| `report.md` | Documents prior depth ceiling and extended sensitivity insights |
| `figures/`, `tables/` | Detection, ΔBPR, repair, and path-length plots |

Paper export: `../paper1/results/oracle_depth_ablation_extended/`
