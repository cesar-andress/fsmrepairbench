# Oracle Depth Ablation (C3)

Sensitivity analysis of mutation detection, BPR, and oracle coverage to behavioural oracle depth presets (`shallow`, `medium`, `deep`).

## Experimental design

- **Dataset:** `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3`
- **Cohort:** 200 cases (`oracle_depth_ablation_multifamily.txt`)
- **FSMs:** fixed reference/faulty machines from the published release
- **Oracles:** regenerated with existing `generate_oracle_suite` presets only
- **Depth presets:** shallow (max 5 steps), medium (12), deep (25)

## Research question

**How sensitive are benchmark conclusions to oracle depth?**

Benchmark detection conclusions are **largely insensitive** to oracle depth within the tested presets: overall detection moves from 65.0% (shallow) to 65.0% (medium) and 65.0% (deep). Paired on 200 cases: 0 faults newly detected at deep vs shallow, 0 faults detected only at shallow.

## Summary by oracle depth

| Depth | Max steps | Cases | Detection rate | Detectable ratio | Mean faulty BPR | Mean BPR delta | Max path length | Mean trans. cov. |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `shallow` | 5 | 200 | 65.00% | 65.00% | 0.6272 | 0.3728 | 3 | 100.00% |
| `medium` | 12 | 200 | 65.00% | 65.00% | 0.6272 | 0.3728 | 3 | 100.00% |
| `deep` | 25 | 200 | 65.00% | 65.00% | 0.6272 | 0.3728 | 3 | 100.00% |

## Mutation operator detection by depth

| Operator | Shallow | Medium | Deep |
|---|---:|---:|---:|
| `action_corruption` | 0.00% | 0.00% | 0.00% |
| `dead_state_intro` | 0.00% | 0.00% | 0.00% |
| `delay_corruption` | 0.00% | 0.00% | 0.00% |
| `duplicate_transition` | 0.00% | 0.00% | 0.00% |
| `guard_flip` | 100.00% | 100.00% | 100.00% |
| `guard_strengthen` | 100.00% | 100.00% | 100.00% |
| `guard_weaken` | 100.00% | 100.00% | 100.00% |
| `missing_transition` | 100.00% | 100.00% | 100.00% |
| `nondeterminism_intro` | 0.00% | 0.00% | 0.00% |
| `timeout_corruption` | 0.00% | 0.00% | 0.00% |
| `unreachable_state_intro` | 0.00% | 0.00% | 0.00% |
| `wrong_event` | 100.00% | 100.00% | 100.00% |
| `wrong_initial_state` | 100.00% | 100.00% | 100.00% |
| `wrong_source` | 100.00% | 100.00% | 100.00% |
| `wrong_target` | 100.00% | 100.00% | 100.00% |

## Figures

![Detection rate by depth](figures/detection_rate_by_depth.png)

![Mutation detection by operator and depth](figures/mutation_detection_by_operator_depth.png)

![Mean BPR delta by depth](figures/mean_bpr_delta_by_depth.png)

![Oracle transition coverage by depth](figures/oracle_transition_coverage_by_depth.png)

![Max path length by depth](figures/max_path_length_by_depth.png)

## Artifacts

- Depth summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation_multifamily/depth_summary.csv`
- Combined summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation_multifamily/summary.csv`
- Distributions: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation_multifamily/distributions.csv`
- Per-case results: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation_multifamily/per_case_results.csv`
- Confidence intervals: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation_multifamily/confidence_intervals.csv`
- LaTeX tables: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/oracle_depth_ablation_multifamily/tables/`

## Bootstrap confidence intervals

Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `detection_rate (C3, shallow)`: 0.650000 [0.585000, 0.715000] (n=200)
- `mean_faulty_bpr (C3, shallow)`: 0.627154 [0.566014, 0.686770] (n=200)
- `mean_bpr_delta (C3, shallow)`: 0.372846 [0.313230, 0.433986] (n=200)
- `detection_rate (C3, medium)`: 0.650000 [0.585000, 0.715000] (n=200)
- `mean_faulty_bpr (C3, medium)`: 0.627154 [0.566014, 0.686770] (n=200)
- `mean_bpr_delta (C3, medium)`: 0.372846 [0.313230, 0.433986] (n=200)
- `detection_rate (C3, deep)`: 0.650000 [0.585000, 0.715000] (n=200)
- `mean_faulty_bpr (C3, deep)`: 0.627154 [0.566014, 0.686770] (n=200)
- `mean_bpr_delta (C3, deep)`: 0.372846 [0.313230, 0.433986] (n=200)
