# RQ4 Random Secondary Operator Sensitivity

Generated: 2026-06-09T15:33:19.306706+00:00

## Motivation

The primary RQ4 campaign chains deterministic secondary operators. This sensitivity analysis repeats higher-order generation with reproducible random secondary operator selection across multiple seeds to assess whether deterministic chaining inflates higher-order detection.

## Configuration

- Cohort: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k/coupling_campaign_250.txt`
- Campaign seed (repair / HO mutation): 44
- Secondary operator policy: random
- Random secondary seeds: 0, 1, 2, 3, 4, 5, 6, 7, 8, 9

## Bootstrap confidence intervals

Across-seed percentile bootstrap on seed-level campaign metrics (10,000 resamples, 95% CI, seed 44).

## Comparison to deterministic RQ4

- Deterministic HO detection (primary campaign): 0.996000
- Random-secondary HO detection mean: 0.995800
- Random-secondary HO detection 95% CI: [0.994400, 0.997000]

## Across-seed summary

- `seed_count`: 10
- `higher_order_detection_rate_mean`: 0.9958
- `higher_order_detection_rate_std`: 0.002088
- `higher_order_detection_rate_min`: 0.992
- `higher_order_detection_rate_max`: 0.998
- `higher_order_detection_rate_ci95_low`: 0.9944
- `higher_order_detection_rate_ci95_high`: 0.997
- `coupling_effect_estimate_mean`: 1.0
- `coupling_effect_estimate_std`: 0.0
- `coupling_effect_estimate_min`: 1.0
- `coupling_effect_estimate_max`: 1.0
- `coupling_effect_estimate_ci95_low`: 1.0
- `coupling_effect_estimate_ci95_high`: 1.0
- `detection_rate_order_1_mean`: 0.472
- `detection_rate_order_1_std`: 0.0
- `detection_rate_order_1_min`: 0.472
- `detection_rate_order_1_max`: 0.472
- `detection_rate_order_1_ci95_low`: 0.472
- `detection_rate_order_1_ci95_high`: 0.472
- `detection_rate_order_2_mean`: 0.9936
- `detection_rate_order_2_std`: 0.005122
- `detection_rate_order_2_min`: 0.984
- `detection_rate_order_2_max`: 1.0
- `detection_rate_order_2_ci95_low`: 0.9904
- `detection_rate_order_2_ci95_high`: 0.9964
- `detection_rate_order_3_mean`: 0.998
- `detection_rate_order_3_std`: 0.002683
- `detection_rate_order_3_min`: 0.992
- `detection_rate_order_3_max`: 1.0
- `detection_rate_order_3_ci95_low`: 0.9964
- `detection_rate_order_3_ci95_high`: 0.9996
- `complete_repair_rate_order_1_mean`: 0.892
- `complete_repair_rate_order_1_std`: 0.0
- `complete_repair_rate_order_1_min`: 0.892
- `complete_repair_rate_order_1_max`: 0.892
- `complete_repair_rate_order_1_ci95_low`: 0.892
- `complete_repair_rate_order_1_ci95_high`: 0.892
- `complete_repair_rate_order_2_mean`: 0.616
- `complete_repair_rate_order_2_std`: 0.022698
- `complete_repair_rate_order_2_min`: 0.588
- `complete_repair_rate_order_2_max`: 0.672
- `complete_repair_rate_order_2_ci95_low`: 0.6032
- `complete_repair_rate_order_2_ci95_high`: 0.6312
- `complete_repair_rate_order_3_mean`: 0.3732
- `complete_repair_rate_order_3_std`: 0.031549
- `complete_repair_rate_order_3_min`: 0.304
- `complete_repair_rate_order_3_max`: 0.424
- `complete_repair_rate_order_3_ci95_low`: 0.3528
- `complete_repair_rate_order_3_ci95_high`: 0.3916
- `effective_repair_rate_order_1_mean`: 0.42
- `effective_repair_rate_order_1_std`: 0.0
- `effective_repair_rate_order_1_min`: 0.42
- `effective_repair_rate_order_1_max`: 0.42
- `effective_repair_rate_order_1_ci95_low`: 0.42
- `effective_repair_rate_order_1_ci95_high`: 0.42
- `effective_repair_rate_order_2_mean`: 0.912
- `effective_repair_rate_order_2_std`: 0.020707
- `effective_repair_rate_order_2_min`: 0.884
- `effective_repair_rate_order_2_max`: 0.952
- `effective_repair_rate_order_2_ci95_low`: 0.9
- `effective_repair_rate_order_2_ci95_high`: 0.9252
- `effective_repair_rate_order_3_mean`: 0.9728
- `effective_repair_rate_order_3_std`: 0.009261
- `effective_repair_rate_order_3_min`: 0.952
- `effective_repair_rate_order_3_max`: 0.984
- `effective_repair_rate_order_3_ci95_low`: 0.9668
- `effective_repair_rate_order_3_ci95_high`: 0.978
- `mean_bpr_delta_order_1_mean`: 0.0677
- `mean_bpr_delta_order_1_std`: 0.0
- `mean_bpr_delta_order_1_min`: 0.0677
- `mean_bpr_delta_order_1_max`: 0.0677
- `mean_bpr_delta_order_1_ci95_low`: 0.0677
- `mean_bpr_delta_order_1_ci95_high`: 0.0677
- `mean_bpr_delta_order_2_mean`: 0.240708
- `mean_bpr_delta_order_2_std`: 0.017192
- `mean_bpr_delta_order_2_min`: 0.208363
- `mean_bpr_delta_order_2_max`: 0.26388
- `mean_bpr_delta_order_2_ci95_low`: 0.229804
- `mean_bpr_delta_order_2_ci95_high`: 0.250768
- `mean_bpr_delta_order_3_mean`: 0.386055
- `mean_bpr_delta_order_3_std`: 0.025856
- `mean_bpr_delta_order_3_min`: 0.346842
- `mean_bpr_delta_order_3_max`: 0.443311
- `mean_bpr_delta_order_3_ci95_low`: 0.370546
- `mean_bpr_delta_order_3_ci95_high`: 0.403262
- `detectable_count_order_1_mean`: 118.0
- `detectable_count_order_1_std`: 0.0
- `detectable_count_order_1_min`: 118.0
- `detectable_count_order_1_max`: 118.0
- `detectable_count_order_1_ci95_low`: 118.0
- `detectable_count_order_1_ci95_high`: 118.0
- `detectable_count_order_2_mean`: 248.4
- `detectable_count_order_2_std`: 1.280625
- `detectable_count_order_2_min`: 246.0
- `detectable_count_order_2_max`: 250.0
- `detectable_count_order_2_ci95_low`: 247.6
- `detectable_count_order_2_ci95_high`: 249.2
- `detectable_count_order_3_mean`: 249.5
- `detectable_count_order_3_std`: 0.67082
- `detectable_count_order_3_min`: 248.0
- `detectable_count_order_3_max`: 250.0
- `detectable_count_order_3_ci95_low`: 249.1
- `detectable_count_order_3_ci95_high`: 249.9
- `complete_repair_rate_order_1_detectable_mean`: 0.771186
- `complete_repair_rate_order_1_detectable_std`: 0.0
- `complete_repair_rate_order_1_detectable_min`: 0.771186
- `complete_repair_rate_order_1_detectable_max`: 0.771186
- `complete_repair_rate_order_1_detectable_ci95_low`: 0.771186
- `complete_repair_rate_order_1_detectable_ci95_high`: 0.771186
- `complete_repair_rate_order_2_detectable_mean`: 0.613479
- `complete_repair_rate_order_2_detectable_std`: 0.023475
- `complete_repair_rate_order_2_detectable_min`: 0.582996
- `complete_repair_rate_order_2_detectable_max`: 0.672
- `complete_repair_rate_order_2_detectable_ci95_low`: 0.600191
- `complete_repair_rate_order_2_detectable_ci95_high`: 0.629339
- `complete_repair_rate_order_3_detectable_mean`: 0.372003
- `complete_repair_rate_order_3_detectable_std`: 0.03039
- `complete_repair_rate_order_3_detectable_min`: 0.304
- `complete_repair_rate_order_3_detectable_max`: 0.419355
- `complete_repair_rate_order_3_detectable_ci95_low`: 0.35223
- `complete_repair_rate_order_3_detectable_ci95_high`: 0.390244
- `effective_repair_rate_order_1_detectable_mean`: 0.889831
- `effective_repair_rate_order_1_detectable_std`: 0.0
- `effective_repair_rate_order_1_detectable_min`: 0.889831
- `effective_repair_rate_order_1_detectable_max`: 0.889831
- `effective_repair_rate_order_1_detectable_ci95_low`: 0.889831
- `effective_repair_rate_order_1_detectable_ci95_high`: 0.889831
- `effective_repair_rate_order_2_detectable_mean`: 0.917873
- `effective_repair_rate_order_2_detectable_std`: 0.020211
- `effective_repair_rate_order_2_detectable_min`: 0.891566
- `effective_repair_rate_order_2_detectable_max`: 0.952
- `effective_repair_rate_order_2_detectable_ci95_low`: 0.906105
- `effective_repair_rate_order_2_detectable_ci95_high`: 0.930388
- `effective_repair_rate_order_3_detectable_mean`: 0.974749
- `effective_repair_rate_order_3_detectable_std`: 0.008804
- `effective_repair_rate_order_3_detectable_min`: 0.955823
- `effective_repair_rate_order_3_detectable_max`: 0.987952
- `effective_repair_rate_order_3_detectable_ci95_low`: 0.969136
- `effective_repair_rate_order_3_detectable_ci95_high`: 0.979963
- `mean_bpr_delta_order_1_detectable_mean`: 0.143432
- `mean_bpr_delta_order_1_detectable_std`: 0.0
- `mean_bpr_delta_order_1_detectable_min`: 0.143432
- `mean_bpr_delta_order_1_detectable_max`: 0.143432
- `mean_bpr_delta_order_1_detectable_ci95_low`: 0.143432
- `mean_bpr_delta_order_1_detectable_ci95_high`: 0.143432
- `mean_bpr_delta_order_2_detectable_mean`: 0.24232
- `mean_bpr_delta_order_2_detectable_std`: 0.018106
- `mean_bpr_delta_order_2_detectable_min`: 0.2092
- `mean_bpr_delta_order_2_detectable_max`: 0.267085
- `mean_bpr_delta_order_2_detectable_ci95_low`: 0.230906
- `mean_bpr_delta_order_2_detectable_ci95_high`: 0.253096
- `mean_bpr_delta_order_3_detectable_mean`: 0.386795
- `mean_bpr_delta_order_3_detectable_std`: 0.025374
- `mean_bpr_delta_order_3_detectable_min`: 0.348235
- `mean_bpr_delta_order_3_detectable_max`: 0.443311
- `mean_bpr_delta_order_3_detectable_ci95_low`: 0.371418
- `mean_bpr_delta_order_3_detectable_ci95_high`: 0.403117

## Artifacts

- `per_seed_summary.csv`
- `per_case_results.csv`
- `random_secondary_summary.csv`
- `random_secondary_summary.json`
- `per_seed_summary.csv`
- `tables/`
- `figures/`

