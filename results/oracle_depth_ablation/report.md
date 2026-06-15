# C3 Extended Oracle Depth Ablation Report

Generated: 2026-06-09T18:31:49.853865+00:00
Dataset: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k`
Cohort: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/oracle_depth_ablation_500.txt`
Output: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation`

## Prior depth ceiling (documented limitation)

The original C3 v1 campaign used the shipped **shortest-path** generator with
declared ceilings shallow/medium/deep (5/12/25 max steps). On the compact
`plain_fsm` pin, executed scenario length stayed at ~4 steps for every preset,
so detection and ΔBPR did not respond to depth manipulation (construct-validity
failure). C3 v2 introduced **depth-forced** walks for the same three presets;
this extended follow-up adds `exhaustive_like` (40), `extended_50`, and
`extended_60` to probe sensitivity beyond the historical deep=25 ceiling.

## Extended sensitivity insights

- Detection at shallow remains 47.6% and is unchanged at deep (47.6%; max 25 declared steps).
- Mean ΔBPR rises from 0.085 (shallow) to 0.157 (deep), confirming behavioural separation grows with walk length even when detection partition is stable.
- `missing-transition` complete repair ranges 88.0%–88.0% across presets; effective repair tracks complete repair on detectable faults.
- Paired McNemar counts vs shallow show zero detection gains at every higher preset (see `paired_detection_changes.csv`).

## Depth summary

| Depth | Max steps | Detection | Mean ΔBPR | Complete repair | Effective repair | Mean len. |
|-------|-----------|-----------|-----------|-----------------|------------------|-----------|
| shallow | 5 | 47.6% | 0.085 | 88.0% | 41.6% | 4.1 |
| medium | 12 | 47.6% | 0.118 | 88.0% | 41.6% | 9.3 |
| deep | 25 | 47.6% | 0.157 | 88.0% | 41.6% | 18.5 |

## Paired detection vs shallow

- **medium** (max 12): gains=0, losses=0, McNemar χ²=0.0
- **deep** (max 25): gains=0, losses=0, McNemar χ²=0.0

## Regeneration

```bash
fsmrepairbench run-oracle-depth-ablation-extended data/fsmrepairbench_1k \
  --out /home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation \
  --cohort-file /home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/oracle_depth_ablation_500.txt \
  --no-write-cohort
python ../paper1/scripts/generate_oracle_depth_ablation_extended_outputs.py
```

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `detection_rate (C3-extended, shallow)`: 0.476000 [0.432000, 0.520000] (n=500)
- `mean_bpr_delta (C3-extended, shallow)`: 0.085419 [0.066553, 0.106013] (n=500)
- `complete_repair_rate (C3-extended, shallow)`: 0.880000 [0.850000, 0.906000] (n=500)
- `effective_repair_rate (C3-extended, shallow)`: 0.416000 [0.374000, 0.460000] (n=500)
- `mean_repair_delta_bpr (C3-extended, shallow)`: 0.056979 [0.044656, 0.070779] (n=500)
- `detection_rate (C3-extended, medium)`: 0.476000 [0.432000, 0.520000] (n=500)
- `mean_bpr_delta (C3-extended, medium)`: 0.118220 [0.097992, 0.140162] (n=500)
- `complete_repair_rate (C3-extended, medium)`: 0.880000 [0.850000, 0.906000] (n=500)
- `effective_repair_rate (C3-extended, medium)`: 0.416000 [0.374000, 0.460000] (n=500)
- `mean_repair_delta_bpr (C3-extended, medium)`: 0.083850 [0.069483, 0.099158] (n=500)
- `detection_rate (C3-extended, deep)`: 0.476000 [0.432000, 0.520000] (n=500)
- `mean_bpr_delta (C3-extended, deep)`: 0.156615 [0.133563, 0.181135] (n=500)
- `complete_repair_rate (C3-extended, deep)`: 0.880000 [0.850000, 0.906000] (n=500)
- `effective_repair_rate (C3-extended, deep)`: 0.416000 [0.374000, 0.460000] (n=500)
- `mean_repair_delta_bpr (C3-extended, deep)`: 0.118017 [0.099936, 0.137155] (n=500)
