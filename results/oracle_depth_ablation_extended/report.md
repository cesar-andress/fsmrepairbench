# C3 Extended Oracle Depth Ablation Report

Generated: 2026-06-09T17:36:38.854666+00:00
Dataset: `data/fsmrepairbench_1k`
Cohort: `data/fsmrepairbench_1k/oracle_depth_ablation_200.txt`
Output: `results/oracle_depth_ablation_extended`

## Prior depth ceiling (documented limitation)

The original C3 v1 campaign used the shipped **shortest-path** generator with
declared ceilings shallow/medium/deep (5/12/25 max steps). On the compact
`plain_fsm` pin, executed scenario length stayed at ~4 steps for every preset,
so detection and ΔBPR did not respond to depth manipulation (construct-validity
failure). C3 v2 introduced **depth-forced** walks for the same three presets;
this extended follow-up adds `exhaustive_like` (40), `extended_50`, and
`extended_60` to probe sensitivity beyond the historical deep=25 ceiling.

## Extended sensitivity insights

- Detection at shallow remains 48.5% and is unchanged at extended_60 (48.5%; max 60 declared steps).
- Mean ΔBPR rises from 0.093 (shallow) to 0.234 (extended_60), confirming behavioural separation grows with walk length even when detection partition is stable.
- `missing-transition` complete repair ranges 88.5%–88.5% across presets; effective repair tracks complete repair on detectable faults.
- Paired McNemar counts vs shallow show zero detection gains at every higher preset (see `paired_detection_changes.csv`).

## Depth summary

| Depth | Max steps | Detection | Mean ΔBPR | Complete repair | Effective repair | Mean len. |
|-------|-----------|-----------|-----------|-----------------|------------------|-----------|
| shallow | 5 | 48.5% | 0.093 | 88.5% | 44.0% | 4.1 |
| medium | 12 | 48.5% | 0.126 | 88.5% | 44.0% | 9.3 |
| deep | 25 | 48.5% | 0.165 | 88.5% | 44.0% | 18.5 |
| exhaustive_like | 40 | 48.5% | 0.202 | 88.5% | 44.0% | 33.2 |
| extended_50 | 50 | 48.5% | 0.218 | 88.5% | 44.0% | 42.2 |
| extended_60 | 60 | 48.5% | 0.234 | 88.5% | 44.0% | 51.3 |

## Paired detection vs shallow

- **medium** (max 12): gains=0, losses=0, McNemar χ²=0.0
- **deep** (max 25): gains=0, losses=0, McNemar χ²=0.0
- **exhaustive_like** (max 40): gains=0, losses=0, McNemar χ²=0.0
- **extended_50** (max 50): gains=0, losses=0, McNemar χ²=0.0
- **extended_60** (max 60): gains=0, losses=0, McNemar χ²=0.0

## Regeneration

```bash
fsmrepairbench run-oracle-depth-ablation-extended data/fsmrepairbench_1k \
  --out results/oracle_depth_ablation_extended \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_200.txt \
  --no-write-cohort
python ../paper1/scripts/generate_oracle_depth_ablation_extended_outputs.py
```

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `detection_rate (C3-extended, shallow)`: 0.485000 [0.415000, 0.555000] (n=200)
- `mean_bpr_delta (C3-extended, shallow)`: 0.092764 [0.060854, 0.128938] (n=200)
- `complete_repair_rate (C3-extended, shallow)`: 0.885000 [0.840000, 0.930000] (n=200)
- `effective_repair_rate (C3-extended, shallow)`: 0.440000 [0.370000, 0.510000] (n=200)
- `mean_repair_delta_bpr (C3-extended, shallow)`: 0.060385 [0.040669, 0.082621] (n=200)
- `detection_rate (C3-extended, medium)`: 0.485000 [0.415000, 0.555000] (n=200)
- `mean_bpr_delta (C3-extended, medium)`: 0.125981 [0.091941, 0.162951] (n=200)
- `complete_repair_rate (C3-extended, medium)`: 0.885000 [0.840000, 0.930000] (n=200)
- `effective_repair_rate (C3-extended, medium)`: 0.440000 [0.370000, 0.510000] (n=200)
- `mean_repair_delta_bpr (C3-extended, medium)`: 0.089639 [0.066316, 0.115248] (n=200)
- `detection_rate (C3-extended, deep)`: 0.485000 [0.415000, 0.555000] (n=200)
- `mean_bpr_delta (C3-extended, deep)`: 0.165145 [0.126975, 0.206300] (n=200)
- `complete_repair_rate (C3-extended, deep)`: 0.885000 [0.840000, 0.930000] (n=200)
- `effective_repair_rate (C3-extended, deep)`: 0.440000 [0.370000, 0.510000] (n=200)
- `mean_repair_delta_bpr (C3-extended, deep)`: 0.125249 [0.095966, 0.156572] (n=200)
- `detection_rate (C3-extended, exhaustive_like)`: 0.485000 [0.415000, 0.555000] (n=200)
- `mean_bpr_delta (C3-extended, exhaustive_like)`: 0.201623 [0.160313, 0.245371] (n=200)
- `complete_repair_rate (C3-extended, exhaustive_like)`: 0.885000 [0.840000, 0.930000] (n=200)
- `effective_repair_rate (C3-extended, exhaustive_like)`: 0.440000 [0.370000, 0.510000] (n=200)
- `mean_repair_delta_bpr (C3-extended, exhaustive_like)`: 0.158375 [0.124880, 0.193923] (n=200)
- `detection_rate (C3-extended, extended_50)`: 0.485000 [0.415000, 0.555000] (n=200)
- `mean_bpr_delta (C3-extended, extended_50)`: 0.217950 [0.174953, 0.263142] (n=200)
- `complete_repair_rate (C3-extended, extended_50)`: 0.885000 [0.840000, 0.930000] (n=200)
- `effective_repair_rate (C3-extended, extended_50)`: 0.440000 [0.370000, 0.510000] (n=200)
- `mean_repair_delta_bpr (C3-extended, extended_50)`: 0.173953 [0.138280, 0.211902] (n=200)
- `detection_rate (C3-extended, extended_60)`: 0.485000 [0.415000, 0.555000] (n=200)
- `mean_bpr_delta (C3-extended, extended_60)`: 0.233691 [0.188728, 0.280358] (n=200)
- `complete_repair_rate (C3-extended, extended_60)`: 0.885000 [0.840000, 0.930000] (n=200)
- `effective_repair_rate (C3-extended, extended_60)`: 0.440000 [0.370000, 0.510000] (n=200)
- `mean_repair_delta_bpr (C3-extended, extended_60)`: 0.187478 [0.149942, 0.226826] (n=200)
