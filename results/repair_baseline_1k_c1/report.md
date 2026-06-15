# C1 Baseline Repair Experiment Report

Generated: 2026-06-09T12:55:34.132290+00:00
Dataset: `data/fsmrepairbench_1k`
Cohort: `data/fsmrepairbench_1k/analysis_cohort_1k.txt` (1000 cases)
Run-tools output: `results/repair_baseline_1k_c1`

## Leaderboard

- **baseline_missing_transition**: detectable-only complete=0.6848, detectable-only effective=0.7798 (n=495); cohort-wide complete=0.8440, effective=0.3860 (includes 505 oracle-saturated); mean ΔBPR=0.0521
- **baseline_wrong_target**: detectable-only complete=0.1212, detectable-only effective=0.2202 (n=495); cohort-wide complete=0.5650, effective=0.1090 (includes 505 oracle-saturated); mean ΔBPR=0.0241
- **baseline_random**: detectable-only complete=0.0020, detectable-only effective=0.0061 (n=495); cohort-wide complete=0.5060, effective=0.0030 (includes 505 oracle-saturated); mean ΔBPR=-0.0081

## Outputs

- `per_case_results.csv`
- `summary.csv` (per-case run-tools rows)
- `cohort_summary.csv`
- `leaderboard.csv`
- `manifest.json`
- `figures/` (PNG)
- `tables/` (LaTeX)

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `complete_repair_rate (baseline_missing_transition)`: 0.844000 [0.821000, 0.866000] (n=1000)
- `effective_repair_rate (baseline_missing_transition)`: 0.386000 [0.356000, 0.416000] (n=1000)
- `mean_delta_bpr (baseline_missing_transition)`: 0.052122 [0.042111, 0.062306] (n=1000)
- `complete_repair_rate_detectable_only (baseline_missing_transition)`: 0.684848 [0.644444, 0.725253] (n=495)
- `effective_repair_rate_detectable_only (baseline_missing_transition)`: 0.779798 [0.743434, 0.816162] (n=495)
