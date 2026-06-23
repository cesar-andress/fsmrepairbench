# C1 Baseline Repair Results

Experiment **C1**: deterministic baseline repair on the pinned analysis cohort.

| Field | Value |
|-------|-------|
| Cases analyzed | 1000 |
| DOI | [10.5281/zenodo.20602577](https://doi.org/10.5281/zenodo.20602577) |
| Release label | v0.2.0-analysis |
| Campaign | C1-baseline-repair |
| Tools | missing-transition, wrong-target, random |
| Cohort | `analysis_cohort_1k.txt` |

Regenerate:

```bash
cd fsmrepairbench
fsmrepairbench run-tools data/fsmrepairbench_1k tools/baselines_c1/ \
  --out results/repair_baseline_1k_c1 \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --workers 4
fsmrepairbench export-c1-baseline-repair data/fsmrepairbench_1k \
  --out results/repair_baseline_1k_c1 \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --workers 4
```

One-shot:

```bash
fsmrepairbench run-c1-baseline-repair data/fsmrepairbench_1k --out results/repair_baseline_1k_c1 --workers 4
```
