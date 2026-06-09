# C1 Random Baseline Multi-Seed Analysis

Generated: 2026-06-09T06:36:00.124997+00:00

## Interpretation

Deterministic baselines (`missing-transition`, `wrong-target`) are unchanged.
The original single-seed random baseline (seed 0) remains in `leaderboard.csv` for backward compatibility.
The multi-seed random summary below is the preferred floor estimate for STVR reporting.

## Bootstrap confidence intervals

- Method: percentile bootstrap on seed-level cohort metrics
- Confidence level: 95%
- Resamples: 10000
- Bootstrap RNG seed: 42
- Random baseline seeds: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

## Multi-seed summary (preferred random floor)

- `complete_repair_rate_mean`: 0.5064
- `complete_repair_rate_std`: 0.0018
- `complete_repair_rate_min`: 0.505
- `complete_repair_rate_max`: 0.511
- `complete_repair_rate_ci95_low`: 0.5055
- `complete_repair_rate_ci95_high`: 0.5076
- `effective_repair_rate_mean`: 0.0059
- `effective_repair_rate_std`: 0.003048
- `effective_repair_rate_min`: 0.003
- `effective_repair_rate_max`: 0.014
- `effective_repair_rate_ci95_low`: 0.0043
- `effective_repair_rate_ci95_high`: 0.008
- `mean_delta_bpr_mean`: -0.024526
- `mean_delta_bpr_std`: 0.01202
- `mean_delta_bpr_min`: -0.0488
- `mean_delta_bpr_max`: -0.008077
- `mean_delta_bpr_ci95_low`: -0.032372
- `mean_delta_bpr_ci95_high`: -0.01753
- `regression_rate_mean`: 0.3377
- `regression_rate_std`: 0.040383
- `regression_rate_ci95_low`: 0.3117
- `regression_rate_ci95_high`: 0.3612
