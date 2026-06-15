# C1 Baseline Repair Experiment Report

Generated: 2026-06-09T16:50:12.529155+00:00
Dataset: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k`
Cohort: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/replication_cohort_20.txt` (20 cases)
Run-tools output: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/repair`

## Leaderboard

- **baseline_missing_transition**: detectable-only complete=0.5000, detectable-only effective=0.5000 (n=10); cohort-wide complete=0.7500, effective=0.2500 (includes 10 oracle-saturated); mean ΔBPR=0.0404
- **baseline_wrong_target**: detectable-only complete=0.1000, detectable-only effective=0.2000 (n=10); cohort-wide complete=0.5500, effective=0.1000 (includes 10 oracle-saturated); mean ΔBPR=0.0370
- **baseline_random**: detectable-only complete=0.0000, detectable-only effective=0.0000 (n=10); cohort-wide complete=0.5000, effective=0.0000 (includes 10 oracle-saturated); mean ΔBPR=-0.0135

## Outputs

- `per_case_results.csv`
- `summary.csv` (per-case run-tools rows)
- `cohort_summary.csv`
- `leaderboard.csv`
- `manifest.json`
- `figures/` (PNG)
- `tables/` (LaTeX)
- `benchmark_utility.csv`
- `utility_summary.json`
- `benchmark_utility.png` (benchmark utility figure)

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `detection_rate (C1, baseline_missing_transition)`: 0.500000 [0.300000, 0.700000] (n=20)
- `complete_repair_rate (C1, baseline_missing_transition)`: 0.750000 [0.550000, 0.900000] (n=20)
- `effective_repair_rate (C1, baseline_missing_transition)`: 0.250000 [0.100000, 0.450000] (n=20)
- `mean_bpr_delta (C1, baseline_missing_transition)`: 0.040357 [0.004321, 0.093507] (n=20)
- `detection_rate (C1, baseline_missing_transition)`: 1.000000 [1.000000, 1.000000] (n=10)
- `complete_repair_rate (C1, baseline_missing_transition)`: 0.500000 [0.200000, 0.800000] (n=10)
- `effective_repair_rate (C1, baseline_missing_transition)`: 0.500000 [0.200000, 0.800000] (n=10)
- `mean_bpr_delta (C1, baseline_missing_transition)`: 0.080714 [0.010525, 0.178439] (n=10)
- `detection_rate (C1, baseline_wrong_target)`: 0.500000 [0.300000, 0.700000] (n=20)
- `complete_repair_rate (C1, baseline_wrong_target)`: 0.550000 [0.350000, 0.750000] (n=20)
- `effective_repair_rate (C1, baseline_wrong_target)`: 0.100000 [0.000000, 0.250000] (n=20)
- `mean_bpr_delta (C1, baseline_wrong_target)`: 0.037022 [0.000000, 0.110407] (n=20)
- `detection_rate (C1, baseline_wrong_target)`: 1.000000 [1.000000, 1.000000] (n=10)
- `complete_repair_rate (C1, baseline_wrong_target)`: 0.100000 [0.000000, 0.300000] (n=10)
- `effective_repair_rate (C1, baseline_wrong_target)`: 0.200000 [0.000000, 0.500000] (n=10)
- `mean_bpr_delta (C1, baseline_wrong_target)`: 0.074043 [0.000000, 0.219498] (n=10)
- `detection_rate (C1, baseline_random)`: 0.500000 [0.300000, 0.700000] (n=20)
- `complete_repair_rate (C1, baseline_random)`: 0.500000 [0.300000, 0.700000] (n=20)
- `effective_repair_rate (C1, baseline_random)`: 0.000000 [0.000000, 0.000000] (n=20)
- `mean_bpr_delta (C1, baseline_random)`: -0.013498 [-0.028527, -0.001291] (n=20)
- `detection_rate (C1, baseline_random)`: 1.000000 [1.000000, 1.000000] (n=10)
- `complete_repair_rate (C1, baseline_random)`: 0.000000 [0.000000, 0.000000] (n=10)
- `effective_repair_rate (C1, baseline_random)`: 0.000000 [0.000000, 0.000000] (n=10)
- `mean_bpr_delta (C1, baseline_random)`: -0.026996 [-0.052690, -0.004905] (n=10)
