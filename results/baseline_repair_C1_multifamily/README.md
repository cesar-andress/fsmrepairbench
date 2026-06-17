# C1 Baseline Repair Results

Experiment **C1**: deterministic baseline repair on the pinned analysis cohort.

| Field | Value |
|-------|-------|
| Cases analyzed | 1000 |
| DOI | [10.5281/zenodo.20724095](https://doi.org/10.5281/zenodo.20724095) |
| Release label | v0.2.0-analysis |
| Campaign | C1-baseline-repair |
| Tools | missing-transition, wrong-target, random |
| Cohort | `analysis_cohort_multifamily.txt` |

Regenerate:

```bash
cd fsmrepairbench
fsmrepairbench run-tools /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3 tools/baselines_c1/ \
  --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/baseline_repair_C1_multifamily \
  --cohort-file /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3/analysis_cohort_multifamily.txt \
  --workers 4
fsmrepairbench export-c1-baseline-repair /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3 \
  --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/baseline_repair_C1_multifamily \
  --cohort-file /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3/analysis_cohort_multifamily.txt \
  --workers 4
```

One-shot:

```bash
fsmrepairbench run-c1-baseline-repair /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3 --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/baseline_repair_C1_multifamily --workers 4
```
