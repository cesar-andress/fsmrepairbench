# Taxonomy Coverage Report

Empirical coverage audit of the FSMRepairBench taxonomy on an existing published dataset.

## Dataset

- **Dataset directory:** `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k_multifamily`
- **Cases analysed:** 1000
- **Cohort manifest:** `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k_multifamily/analysis_cohort_1k.txt`

## Executive summary

Taxonomy claims are **only weakly supported** on this cohort; several declared dimensions or operator families are underrepresented. Mean dimension value coverage is 61.2%; mutation-operator coverage is 78.9%; machine-type/bug-type/size-class triple coverage is 3.3%.

## Coverage per taxonomy dimension

| Dimension | Observed values | Universe | Coverage | Entropy |
|-----------|----------------:|---------:|---------:|--------:|
| `machine_type` | 5 | 8 | 62.5% | 2.322 |
| `determinism` | 1 | 2 | 50.0% | 0.000 |
| `completeness` | 2 | 2 | 100.0% | 0.571 |
| `arity_class` | 3 | 4 | 75.0% | 1.279 |
| `size_class` | 1 | 5 | 20.0% | 0.000 |
| `guard_complexity` | 3 | 4 | 75.0% | 1.522 |
| `time_features` | 2 | 5 | 40.0% | 0.722 |
| `graph_structure` | 6 | 7 | 85.7% | 2.296 |
| `oracle_depth` | 1 | 4 | 25.0% | 0.000 |
| `bug_type` | 15 | 19 | 78.9% | 3.746 |

![Dimension coverage ratios](figures/dimension_coverage_ratio.png)

## Coverage per FSM family

| FSM family | Cases | Cohort share | Mutation operators |
|------------|------:|-------------:|-------------------:|
| `efsm` | 200 | 20.0% | 4 |
| `mealy` | 200 | 20.0% | 4 |
| `moore` | 200 | 20.0% | 4 |
| `plain_fsm` | 200 | 20.0% | 4 |
| `timed_fsm` | 200 | 20.0% | 4 |

![FSM family case counts](figures/fsm_family_case_counts.png)

## Coverage per mutation operator

| Operator | Cases | Cohort share | FSM families |
|----------|------:|-------------:|-------------:|
| `action_corruption` | 50 | 5.0% | 1 |
| `dead_state_intro` | 50 | 5.0% | 1 |
| `delay_corruption` | 50 | 5.0% | 1 |
| `duplicate_transition` | 50 | 5.0% | 1 |
| `guard_flip` | 100 | 10.0% | 2 |
| `guard_strengthen` | 50 | 5.0% | 1 |
| `guard_weaken` | 50 | 5.0% | 1 |
| `missing_transition` | 150 | 15.0% | 3 |
| `nondeterminism_intro` | 50 | 5.0% | 1 |
| `timeout_corruption` | 50 | 5.0% | 1 |
| `unreachable_state_intro` | 50 | 5.0% | 1 |
| `wrong_event` | 50 | 5.0% | 1 |
| `wrong_initial_state` | 50 | 5.0% | 1 |
| `wrong_source` | 50 | 5.0% | 1 |
| `wrong_target` | 150 | 15.0% | 3 |

![Mutation operator case counts](figures/mutation_operator_case_counts.png)

## Coverage per complexity tier

| Tier | Cases | Cohort share | Mutation operators |
|------|------:|-------------:|-------------------:|
| `small` | 1000 | 100.0% | 15 |

![Complexity tier case counts](figures/complexity_tier_case_counts.png)

## Feature-space saturation

- Unique full-taxonomy combinations: **39**
- Duplicate-combination cases: **961**
- Missing core 5-feature combinations: **4777** (of 4800 possible)
- Triple (`machine_type`, `bug_type`, `size_class`) coverage: **3.3%**

![Unique combinations summary](figures/unique_combinations_summary.png)

![Feature-space coverage ratios](figures/feature_space_coverage_ratios.png)

## Artefacts

- Summary metrics: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/summary.csv`
- Unique combinations: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/unique_combinations_summary.csv`
- Top combinations: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/coverage_by_unique_combinations.csv`
- Dimension detail: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/coverage_by_dimension.csv`
- Feature-space report: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/feature_space_report.json`
- Frozen manifest: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/manifest.json`
- LaTeX tables: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/taxonomy_coverage_1k_multifamily/tables`

