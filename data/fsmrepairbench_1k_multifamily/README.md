# FSMRepairBench v0.3.0 — 1k-plan multi-family dataset

Stratified benchmark cases built from `plans/fsmrepairbench_v0_1k_plan.yaml` (seed **44**)
using the ten-dimensional generation plan: **200 cases each** for `plain_fsm`, `mealy`,
`moore`, `efsm`, and `timed_fsm` (1000 total).

Unlike the frozen Zenodo `fsmrepairbench_1k` release (`v0.2.0-analysis`), which contains
legacy `plain_fsm`-only cases, this directory realises the full machine-type quotas declared
in the v0.1 stratification plan with seed-controlled single-operator mutations.

## Build

```bash
python ../paper1/scripts/build_v0_1k_multifamily_dataset.py
```

## Pin cohort manifests (SHA-256)

```bash
python ../paper1/scripts/pin_v0_1k_multifamily_cohorts.py
python ../paper1/scripts/verify_cohort_manifests.py
```

| Manifest | Cases | Purpose |
|----------|------:|---------|
| `analysis_cohort_1k.txt` | 1,000 | RQ1/RQ2 taxonomy + analysis |
| `localization_cohort_1k.txt` | 1,000 | RQ3 localization |
| `coupling_campaign_250.txt` | 250 | RQ4 HO coupling (stratified) |
| `oracle_depth_ablation_200.txt` | 200 | C3 oracle-depth check |

Release label: **`v0.3.0-1k-plan-multifamily`**

## RQ1 taxonomy coverage

```bash
python ../paper1/scripts/generate_v0_1k_multifamily_rq1_outputs.py
```

Frozen exports: `paper1/results/taxonomy_coverage_1k_multifamily/`

## RQ2 mutation detectability

```bash
fsmrepairbench analyze-benchmark data/fsmrepairbench_1k_multifamily \
  --cohort-file data/fsmrepairbench_1k_multifamily/analysis_cohort_1k.txt \
  --out results/analysis_1k_multifamily
python ../paper1/scripts/generate_v0_1k_multifamily_rq2_outputs.py
```

## Validation

```bash
fsmrepairbench validate-multifamily-cohort data/fsmrepairbench_1k_multifamily
python ../paper1/scripts/verify_multifamily_cohort_completeness.py --dataset data/fsmrepairbench_1k_multifamily
```

See [`../../docs/multifamily_cohorts.md`](../../docs/multifamily_cohorts.md) for full documentation.
