# C1 Baseline Repair Experiment Report

Generated: 2026-06-15T17:50:26.113854+00:00
Dataset: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k`
Cohort: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/analysis_cohort_1k.txt` (1000 cases)
Run-tools output: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/baseline_repair_C1`

## Leaderboard

- **baseline_missing_transition**: detectable-only complete=0.6848, detectable-only effective=0.7798 (n=495); cohort-wide complete=0.8440, effective=0.3860 (includes 505 oracle-saturated); mean ΔBPR=0.0521
- **baseline_wrong_target**: detectable-only complete=0.1212, detectable-only effective=0.2202 (n=495); cohort-wide complete=0.5650, effective=0.1090 (includes 505 oracle-saturated); mean ΔBPR=0.0241
- **baseline_random**: detectable-only complete=0.0020, detectable-only effective=0.0061 (n=495); cohort-wide complete=0.5060, effective=0.0030 (includes 505 oracle-saturated); mean ΔBPR=-0.0081
- **baseline_search_bpr**: detectable-only complete=0.8626, detectable-only effective=0.9798 (n=495); cohort-wide complete=0.9320, effective=0.4850 (includes 505 oracle-saturated); mean ΔBPR=0.0610
- **baseline_oracle_composite**: detectable-only complete=0.6747, detectable-only effective=0.8263 (n=495); cohort-wide complete=0.8390, effective=0.4090 (includes 505 oracle-saturated); mean ΔBPR=0.0760
- **baseline_llm_template**: detectable-only complete=0.6747, detectable-only effective=0.8263 (n=495); cohort-wide complete=0.8390, effective=0.4090 (includes 505 oracle-saturated); mean ΔBPR=0.0760

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

- `detection_rate (C1, baseline_missing_transition)`: 0.495000 [0.465000, 0.525000] (n=1000)
- `complete_repair_rate (C1, baseline_missing_transition)`: 0.844000 [0.821000, 0.866000] (n=1000)
- `effective_repair_rate (C1, baseline_missing_transition)`: 0.386000 [0.356000, 0.416000] (n=1000)
- `mean_bpr_delta (C1, baseline_missing_transition)`: 0.052122 [0.042111, 0.062306] (n=1000)
- `detection_rate (C1, baseline_missing_transition)`: 1.000000 [1.000000, 1.000000] (n=495)
- `complete_repair_rate (C1, baseline_missing_transition)`: 0.684848 [0.644444, 0.725253] (n=495)
- `effective_repair_rate (C1, baseline_missing_transition)`: 0.779798 [0.743434, 0.816162] (n=495)
- `mean_bpr_delta (C1, baseline_missing_transition)`: 0.105298 [0.086775, 0.124760] (n=495)
- `detection_rate (C1, baseline_wrong_target)`: 0.495000 [0.465000, 0.525000] (n=1000)
- `complete_repair_rate (C1, baseline_wrong_target)`: 0.565000 [0.535000, 0.595000] (n=1000)
- `effective_repair_rate (C1, baseline_wrong_target)`: 0.109000 [0.090000, 0.129000] (n=1000)
- `mean_bpr_delta (C1, baseline_wrong_target)`: 0.024094 [0.017727, 0.030811] (n=1000)
- `detection_rate (C1, baseline_wrong_target)`: 1.000000 [1.000000, 1.000000] (n=495)
- `complete_repair_rate (C1, baseline_wrong_target)`: 0.121212 [0.092929, 0.149495] (n=495)
- `effective_repair_rate (C1, baseline_wrong_target)`: 0.220202 [0.183838, 0.256566] (n=495)
- `mean_bpr_delta (C1, baseline_wrong_target)`: 0.048675 [0.036205, 0.061917] (n=495)
- `detection_rate (C1, baseline_random)`: 0.495000 [0.465000, 0.525000] (n=1000)
- `complete_repair_rate (C1, baseline_random)`: 0.506000 [0.476000, 0.537000] (n=1000)
- `effective_repair_rate (C1, baseline_random)`: 0.003000 [0.000000, 0.007000] (n=1000)
- `mean_bpr_delta (C1, baseline_random)`: -0.008077 [-0.009680, -0.006565] (n=1000)
- `detection_rate (C1, baseline_random)`: 1.000000 [1.000000, 1.000000] (n=495)
- `complete_repair_rate (C1, baseline_random)`: 0.002020 [0.000000, 0.006061] (n=495)
- `effective_repair_rate (C1, baseline_random)`: 0.006061 [0.000000, 0.014141] (n=495)
- `mean_bpr_delta (C1, baseline_random)`: -0.016318 [-0.019298, -0.013422] (n=495)
- `detection_rate (C1, baseline_search_bpr)`: 0.495000 [0.465000, 0.525000] (n=1000)
- `complete_repair_rate (C1, baseline_search_bpr)`: 0.932000 [0.916000, 0.947000] (n=1000)
- `effective_repair_rate (C1, baseline_search_bpr)`: 0.485000 [0.454000, 0.516000] (n=1000)
- `mean_bpr_delta (C1, baseline_search_bpr)`: 0.060952 [0.050832, 0.071507] (n=1000)
- `detection_rate (C1, baseline_search_bpr)`: 1.000000 [1.000000, 1.000000] (n=495)
- `complete_repair_rate (C1, baseline_search_bpr)`: 0.862626 [0.832323, 0.892929] (n=495)
- `effective_repair_rate (C1, baseline_search_bpr)`: 0.979798 [0.967677, 0.991919] (n=495)
- `mean_bpr_delta (C1, baseline_search_bpr)`: 0.123135 [0.104907, 0.142650] (n=495)
- `detection_rate (C1, baseline_oracle_composite)`: 0.495000 [0.465000, 0.525000] (n=1000)
- `complete_repair_rate (C1, baseline_oracle_composite)`: 0.839000 [0.816000, 0.862000] (n=1000)
- `effective_repair_rate (C1, baseline_oracle_composite)`: 0.409000 [0.378000, 0.439000] (n=1000)
- `mean_bpr_delta (C1, baseline_oracle_composite)`: 0.075999 [0.061600, 0.090405] (n=1000)
- `detection_rate (C1, baseline_oracle_composite)`: 1.000000 [1.000000, 1.000000] (n=495)
- `complete_repair_rate (C1, baseline_oracle_composite)`: 0.674747 [0.632323, 0.715152] (n=495)
- `effective_repair_rate (C1, baseline_oracle_composite)`: 0.826263 [0.791919, 0.858586] (n=495)
- `mean_bpr_delta (C1, baseline_oracle_composite)`: 0.153533 [0.127566, 0.181118] (n=495)
- `detection_rate (C1, baseline_llm_template)`: 0.495000 [0.465000, 0.525000] (n=1000)
- `complete_repair_rate (C1, baseline_llm_template)`: 0.839000 [0.816000, 0.862000] (n=1000)
- `effective_repair_rate (C1, baseline_llm_template)`: 0.409000 [0.378000, 0.439000] (n=1000)
- `mean_bpr_delta (C1, baseline_llm_template)`: 0.075999 [0.061600, 0.090405] (n=1000)
- `detection_rate (C1, baseline_llm_template)`: 1.000000 [1.000000, 1.000000] (n=495)
- `complete_repair_rate (C1, baseline_llm_template)`: 0.674747 [0.632323, 0.715152] (n=495)
- `effective_repair_rate (C1, baseline_llm_template)`: 0.826263 [0.791919, 0.858586] (n=495)
- `mean_bpr_delta (C1, baseline_llm_template)`: 0.153533 [0.127566, 0.181118] (n=495)
