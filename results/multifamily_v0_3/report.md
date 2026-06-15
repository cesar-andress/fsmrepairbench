# Multi-Family External-Validity Pilot (v0.3.0-external-validity-pilot)

**Status:** pilot external-validity mini-cohort for manuscript sensitivity analysis.

This dataset is **not** part of the frozen Zenodo `v0.2.0-analysis` release and does **not** replace the published 1,000-case analysis cohort (which contains only `plain_fsm` cases). It is intended to inform future benchmark releases with balanced coverage across Mealy, Moore, EFSM, and timed FSM families.

## Dataset

- Plan: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/plans/fsmrepairbench_multifamily_v0_3_plan.yaml` (`fsmrepairbench_multifamily_v0_3`, version 0.3.0, seed 46)
- Built dataset: `data/fsmrepairbench_multifamily_v0_3`
- Built cases: 1000
- Target families: plain_fsm, mealy, moore, efsm, timed_fsm
- Frozen v0.2.0 reference cohort: `data/fsmrepairbench_1k/analysis_cohort_1k.txt` (unchanged)

## Overall metrics

- Overall detection rate: **64.80%**
- Mean BPR delta: **0.3654**

## Family summary

| Family | Planned | Built | Failures | Detection | Mean faulty BPR | Mean BPR delta | Trans. cov. |
|---|---:|---:|---:|---:|---:|---:|---:|
| `plain_fsm` | 200 | 200 | 0 | 74.50% | 0.3033 | 0.6967 | 100.00% |
| `mealy` | 200 | 200 | 0 | 50.00% | 0.8062 | 0.1938 | 100.00% |
| `moore` | 200 | 200 | 0 | 49.50% | 0.5050 | 0.4950 | 100.00% |
| `efsm` | 200 | 200 | 0 | 100.00% | 0.6462 | 0.3538 | 100.00% |
| `timed_fsm` | 200 | 200 | 0 | 50.00% | 0.9122 | 0.0878 | 100.00% |

## Operator distribution by family

| Family | Operator | Cases | Share within family |
|---|---|---:|---:|
| `efsm` | `guard_flip` | 50 | 25.00% |
| `efsm` | `guard_strengthen` | 50 | 25.00% |
| `efsm` | `guard_weaken` | 50 | 25.00% |
| `efsm` | `missing_transition` | 50 | 25.00% |
| `mealy` | `action_corruption` | 50 | 25.00% |
| `mealy` | `duplicate_transition` | 50 | 25.00% |
| `mealy` | `guard_flip` | 50 | 25.00% |
| `mealy` | `wrong_target` | 50 | 25.00% |
| `moore` | `dead_state_intro` | 50 | 25.00% |
| `moore` | `unreachable_state_intro` | 50 | 25.00% |
| `moore` | `wrong_initial_state` | 50 | 25.00% |
| `moore` | `wrong_target` | 50 | 25.00% |
| `plain_fsm` | `missing_transition` | 50 | 25.00% |
| `plain_fsm` | `nondeterminism_intro` | 50 | 25.00% |
| `plain_fsm` | `wrong_event` | 50 | 25.00% |
| `plain_fsm` | `wrong_source` | 50 | 25.00% |
| `timed_fsm` | `delay_corruption` | 50 | 25.00% |
| `timed_fsm` | `missing_transition` | 50 | 25.00% |
| `timed_fsm` | `timeout_corruption` | 50 | 25.00% |
| `timed_fsm` | `wrong_target` | 50 | 25.00% |

## Figures

![Family case counts](figures/family_case_counts.png)

![Detection rate by family](figures/detection_rate_by_family.png)

![Mean BPR delta by family](figures/mean_bpr_delta_by_family.png)

![Operator distribution by family](figures/operator_distribution_by_family.png)

## Artifacts

- Summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/multifamily_v0_3/summary.csv`
- Family summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/multifamily_v0_3/family_summary.csv`
- Operator by family: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/multifamily_v0_3/operator_by_family.csv`
- Detection by family: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/multifamily_v0_3/detection_by_family.csv`
- LaTeX tables: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/multifamily_v0_3/tables/`


## Taxonomy coverage ratios

Coverage ratios are computed on the pilot cohort using the same taxonomy dimensions as the frozen `v0.2.0-analysis` release.

- Mean dimension coverage: **61.2%**
- Mutation-operator coverage: **78.9%**
- Complexity-tier coverage: **25.0%**
- Machine-type coverage: **0.0%**

### Coverage by taxonomy dimension

| Dimension | Observed | Universe | Coverage |
|-----------|---------:|---------:|---------:|
| `machine_type` | 5 | 8 | 62.5% |
| `determinism` | 1 | 2 | 50.0% |
| `completeness` | 2 | 2 | 100.0% |
| `arity_class` | 3 | 4 | 75.0% |
| `size_class` | 1 | 5 | 20.0% |
| `guard_complexity` | 3 | 4 | 75.0% |
| `time_features` | 2 | 5 | 40.0% |
| `graph_structure` | 6 | 7 | 85.7% |
| `oracle_depth` | 1 | 4 | 25.0% |
| `bug_type` | 15 | 19 | 78.9% |

### Coverage by mutation operator

| Operator | Cases | Cohort share | Subgroup coverage |
|----------|------:|-------------:|------------------:|
| `action_corruption` | 50 | 5.0% | 20.0% |
| `dead_state_intro` | 50 | 5.0% | 20.0% |
| `delay_corruption` | 50 | 5.0% | 20.0% |
| `duplicate_transition` | 50 | 5.0% | 20.0% |
| `guard_flip` | 100 | 10.0% | 40.0% |
| `guard_strengthen` | 50 | 5.0% | 20.0% |
| `guard_weaken` | 50 | 5.0% | 20.0% |
| `missing_transition` | 150 | 15.0% | 60.0% |
| `nondeterminism_intro` | 50 | 5.0% | 20.0% |
| `timeout_corruption` | 50 | 5.0% | 20.0% |
| `unreachable_state_intro` | 50 | 5.0% | 20.0% |
| `wrong_event` | 50 | 5.0% | 20.0% |
| `wrong_initial_state` | 50 | 5.0% | 20.0% |
| `wrong_source` | 50 | 5.0% | 20.0% |
| `wrong_target` | 150 | 15.0% | 60.0% |

### Coverage by complexity tier

| Tier | Cases | Cohort share | Subgroup coverage |
|------|------:|-------------:|------------------:|
| `small` | 1000 | 100.0% | 100.0% |

### Coverage by machine type

| Machine type | Cases | Cohort share | Operator diversity |
|--------------|------:|-------------:|-------------------:|
| `efsm` | 200 | 20.0% | 4 |
| `mealy` | 200 | 20.0% | 4 |
| `moore` | 200 | 20.0% | 4 |
| `plain_fsm` | 200 | 20.0% | 4 |
| `timed_fsm` | 200 | 20.0% | 4 |

Full taxonomy coverage artefacts: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/multifamily_v0_3/coverage`

