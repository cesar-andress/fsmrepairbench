# C1 Extended Baseline Repair Report

Generated: 2026-06-15T17:55:06.732534+00:00
Dataset: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k`
Cohort: `analysis_cohort_1k.txt` (1000 cases)
Campaign: C1-extended-baseline-repair

## Leaderboard

- **baseline_search_bpr** (search-bpr): detectable-only complete=0.8626, effective=0.9798, mean ΔBPR=0.0610
- **baseline_oracle_composite** (oracle-composite): detectable-only complete=0.6747, effective=0.8263, mean ΔBPR=0.0760
- **baseline_llm_template** (llm-template): detectable-only complete=0.6747, effective=0.8263, mean ΔBPR=0.0760

## Localization coupling

- Structural-diff top-k ranks joined in `repair_localization_coupling.csv`
- Detectable cases in cohort: 495 (per primary tool row)

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

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
