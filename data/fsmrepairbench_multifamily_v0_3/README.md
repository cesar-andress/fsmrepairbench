# FSMRepairBench v0.3.0 — multi-family external-validity cohort

Stratified benchmark cases built from `plans/fsmrepairbench_multifamily_v0_3_plan.yaml`
(seed **46**): **200 cases each** for `plain_fsm`, `mealy`, `moore`, `efsm`, and
`timed_fsm` (1,000 total).

Release label: **`v0.3.0-multifamily-cohort`**

This track complements the frozen Zenodo `v0.2.0-analysis` release (`plain_fsm` only).
For the canonical **10D 1k-plan** multi-family track (seed 44), see
[`fsmrepairbench_1k_multifamily/README.md`](../fsmrepairbench_1k_multifamily/README.md).

## Build

```bash
fsmrepairbench build-stratified-dataset \
  plans/fsmrepairbench_multifamily_v0_3_plan.yaml \
  data/fsmrepairbench_multifamily_v0_3
```

Or:

```bash
python ../paper1/scripts/build_multifamily_v0_3_dataset.py
```

## Pin cohort manifests (SHA-256)

```bash
python ../paper1/scripts/pin_multifamily_cohorts.py
python ../paper1/scripts/verify_cohort_manifests.py
python ../paper1/scripts/verify_multifamily_cohort_completeness.py \
  --dataset data/fsmrepairbench_multifamily_v0_3
```

| Manifest | Cases | Purpose |
|----------|------:|---------|
| `analysis_cohort_multifamily.txt` | 1,000 | Analysis / pilot summaries |
| `localization_cohort_multifamily.txt` | 1,000 | RQ3 localization |
| `coupling_campaign_multifamily.txt` | 250 | RQ4 HO coupling (stratified) |
| `oracle_depth_ablation_multifamily.txt` | 200 | C3 oracle-depth check |

## Analysis and campaigns

```bash
fsmrepairbench analyze-multifamily-cohort data/fsmrepairbench_multifamily_v0_3 \
  --plan plans/fsmrepairbench_multifamily_v0_3_plan.yaml \
  --out results/multifamily_v0_3 \
  --paper-export-dir ../paper1/results/multifamily_v0_3

python ../paper1/scripts/run_multifamily_campaigns.py --seed 44
python ../paper1/scripts/generate_multifamily_v0_3_outputs.py
```

## Links

- Documentation: [`../../docs/multifamily_cohorts.md`](../../docs/multifamily_cohorts.md)
- GitHub: https://github.com/cesar-andress/fsmrepairbench
- Zenodo (frozen paper dataset): https://doi.org/10.5281/zenodo.20724095
