# C1 Baseline Repair Experiment Report

Generated: 2026-06-09T15:45:48.435495+00:00
Dataset: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3`
Cohort: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3/analysis_cohort_multifamily.txt` (1000 cases)
Run-tools output: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/baseline_repair_C1_multifamily`

## Leaderboard

- **baseline_missing_transition**: detectable-only complete=0.7685, detectable-only effective=0.5401 (n=648); cohort-wide complete=0.8220, effective=0.4950 (includes 352 oracle-saturated); mean ΔBPR=0.2222
- **baseline_wrong_target**: detectable-only complete=0.4599, detectable-only effective=0.2315 (n=648); cohort-wide complete=0.5030, effective=0.1770 (includes 352 oracle-saturated); mean ΔBPR=0.0917
- **baseline_random**: detectable-only complete=0.2284, detectable-only effective=0.0000 (n=648); cohort-wide complete=0.3290, effective=0.0020 (includes 352 oracle-saturated); mean ΔBPR=-0.1780

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

- `complete_repair_rate (baseline_missing_transition)`: 0.822000 [0.798000, 0.846000] (n=1000)
- `effective_repair_rate (baseline_missing_transition)`: 0.495000 [0.464000, 0.526000] (n=1000)
- `mean_delta_bpr (baseline_missing_transition)`: 0.222244 [0.200960, 0.244230] (n=1000)
- `complete_repair_rate_detectable_only (baseline_missing_transition)`: 0.768519 [0.734568, 0.799383] (n=648)
- `effective_repair_rate_detectable_only (baseline_missing_transition)`: 0.540123 [0.501543, 0.578704] (n=648)
