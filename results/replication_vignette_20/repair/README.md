# C1 Baseline Repair Results

Experiment **C1**: deterministic baseline repair on the pinned analysis cohort.

| Field | Value |
|-------|-------|
| Cases analyzed | 20 |
| DOI | [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528) |
| Release label | v0.2.0-analysis |
| Campaign | C1-baseline-repair |
| Tools | missing-transition, wrong-target, random |
| Cohort | `replication_cohort_20.txt` |

Regenerate:

```bash
cd fsmrepairbench
fsmrepairbench run-tools /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k tools/baselines_c1/ \
  --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/repair \
  --cohort-file /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/replication_cohort_20.txt \
  --workers 4
fsmrepairbench export-c1-baseline-repair /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k \
  --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/repair \
  --cohort-file /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/replication_cohort_20.txt \
  --workers 4
```

One-shot:

```bash
fsmrepairbench run-c1-baseline-repair /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/repair --workers 4
```
