# C1 Random Baseline Multi-Seed Analysis

Generated: 2026-06-09T06:36:00.124997+00:00

## Interpretation

Deterministic baselines (`missing-transition`, `wrong-target`) are unchanged.
The original single-seed random baseline (seed 0) remains in `leaderboard.csv` for backward compatibility.
The multi-seed random summary below is the preferred floor estimate for STVR reporting.

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `complete_repair_rate (baseline_missing_transition)`: 0.844000 [0.821000, 0.866000] (n=1000)
- `effective_repair_rate (baseline_missing_transition)`: 0.386000 [0.356000, 0.416000] (n=1000)
- `mean_delta_bpr (baseline_missing_transition)`: 0.052122 [0.042111, 0.062306] (n=1000)
- `complete_repair_rate_detectable_only (baseline_missing_transition)`: 0.684848 [0.644444, 0.725253] (n=495)
