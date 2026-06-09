# C1 Baseline Repair Experiment Report

Generated: 2026-06-09T07:38:41.565376+00:00
Dataset: `data/fsmrepairbench_1k`
Cohort: `data/fsmrepairbench_1k/analysis_cohort_1k.txt` (1000 cases)
Run-tools output: `results/repair_baseline_1k_c1`

## Leaderboard

- **baseline_missing_transition**: complete=0.8440, effective=0.3860, mean ΔBPR=0.0521, detectable-only complete=0.6848 (n=495)
- **baseline_wrong_target**: complete=0.5650, effective=0.1090, mean ΔBPR=0.0241, detectable-only complete=0.1212 (n=495)
- **baseline_random**: complete=0.5060, effective=0.0030, mean ΔBPR=-0.0081, detectable-only complete=0.0020 (n=495)

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
