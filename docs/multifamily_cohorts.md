# Multi-family FSM cohorts (package docs)

See the monorepo guide: [`../../docs/multifamily_cohorts.md`](../../docs/multifamily_cohorts.md)

Quick reference from the `fsmrepairbench/` package root:

```bash
# Build 1k-plan multi-family cohort (10D stratification, seed 44)
fsmrepairbench build-stratified-dataset \
  plans/fsmrepairbench_v0_1k_plan.yaml \
  data/fsmrepairbench_1k_multifamily

python ../paper1/scripts/pin_v0_1k_multifamily_cohorts.py
fsmrepairbench validate-multifamily-cohort data/fsmrepairbench_1k_multifamily

fsmrepairbench analyze-benchmark data/fsmrepairbench_1k_multifamily \
  --cohort-file data/fsmrepairbench_1k_multifamily/analysis_cohort_1k.txt \
  --out results/analysis_1k_multifamily
```

Dataset READMEs:

- [`data/fsmrepairbench_1k_multifamily/README.md`](../data/fsmrepairbench_1k_multifamily/README.md)
- [`data/fsmrepairbench_multifamily_v0_3/README.md`](../data/fsmrepairbench_multifamily_v0_3/README.md)
