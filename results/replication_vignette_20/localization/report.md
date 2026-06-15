# RQ3 Fault Localization (Ochiai, Transition-Level)

Spectrum-based fault localization ranks transitions by Ochiai suspiciousness using oracle pass/fail spectra. Ground truth is `changed_transition_id` from `bug_metadata.json`.

## Experimental design

- **Dataset:** `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k`
- **Campaign:** RQ3-localization-ochiai-1k
- **Method:** ochiai on transition elements only
- **Top-k metrics:** top-1, top-3, top-5, MRR

## Aggregate metrics (legacy all-detectable partition)

The original RQ3 headline metrics include every oracle-detectable case (`n=10`) even when transition-level ground truth is not rankable. This partition is **conservative** and mixes Ochiai weakness with construct-validity failures.

| Metric | Value |
|---|---:|
| Cohort size | 20 |
| Detectable (localized) cases | 10 |
| Skipped cases | 10 |
| Top-1 hit rate | 20.00% |
| Top-3 hit rate | 20.00% |
| Top-5 hit rate | 20.00% |
| MRR | 0.2334 |

## Construct-valid subset: transition-localizable ground truth

For construct-valid transition-level evaluation, restrict to detectable cases whose `changed_transition_id` refers to a transition that still exists in the faulty FSM and is not a non-transition fault class.

- **Transition-localizable GT cases:** 8
- **Top-1 hit rate:** 25.00%
- **Top-3 hit rate:** 25.00%
- **Top-5 hit rate:** 25.00%
- **MRR:** 0.2917

Use this partition as the primary RQ3 metric set in the paper. The all-detectable partition remains useful as a lower-bound baseline that includes non-rankable faults.

## Ground-truth localizability audit

Per-case audit export: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/localization/localizability_audit.csv`.

### Why some detectable faults are not transition-localizable

| Class | Detectable cases | Meaning |
|---|---:|---|
| `localizable_transition_gt` | 8 | `changed_transition_id` exists in the faulty FSM and can be ranked. |
| `missing_or_deleted_transition_gt` | 1 | Ground truth names a transition removed from or absent in the faulty FSM (notably `missing_transition`). |
| `non_transition_fault_gt` | 1 | Fault is not anchored to one transition ID (for example `wrong_initial_state`). |
| `missing_ground_truth` | 0 | `changed_transition_id` is empty or missing. |

Among detectable cases, **2** have non-rankable transition ground truth. These cases inflate `not_ranked` in the legacy partition.

### Operators to exclude or report separately

- **`missing_transition`:** ground truth is the deleted transition; always `missing_or_deleted_transition_gt`. Report separately or exclude from transition-localizable aggregates.
- **`wrong_initial_state`:** state-level fault with no transition ID; classify as `non_transition_fault_gt`. Requires state-level localization metrics outside RQ3.
- **`dead_state_intro`, `unreachable_state_intro`, `action_full_mutation`:** non-transition fault classes when detectable; exclude from transition-localizable GT.

## Operator summary

| Operator | Detectable | Localizable GT | Not localizable | Top-5 all | Top-5 loc. |
|---|---:|---:|---:|---:|---:|
| guard_flip | 2 | 2 | 0 | 50.00% | 50.00% |
| guard_inter_class | 1 | 1 | 0 | 0.00% | 0.00% |
| guard_strengthen | 1 | 1 | 0 | 0.00% | 0.00% |
| guard_weaken | 1 | 1 | 0 | 0.00% | 0.00% |
| missing_transition | 1 | 0 | 1 | 0.00% | 0.00% |
| wrong_event | 1 | 1 | 0 | 0.00% | 0.00% |
| wrong_initial_state | 1 | 0 | 1 | 0.00% | 0.00% |
| wrong_source | 1 | 1 | 0 | 0.00% | 0.00% |
| wrong_target | 1 | 1 | 0 | 100.00% | 100.00% |

## Artifacts

- Localizability audit: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/localization/localizability_audit.csv`
- Partition metrics: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/localization/localization_metrics_localizable_only.csv`
- Legacy per-case results: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/localization/per_case_results.csv`
- Legacy summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/localization/summary.csv`
- LaTeX tables: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/replication_vignette_20/localization/tables/`


## Bootstrap confidence intervals
Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `top_1_hit_rate (RQ3)`: 0.200000 [0.000000, 0.500000] (n=10)
- `top_3_hit_rate (RQ3)`: 0.200000 [0.000000, 0.500000] (n=10)
- `top_5_hit_rate (RQ3)`: 0.200000 [0.000000, 0.500000] (n=10)
- `mrr (RQ3)`: 0.233394 [0.031102, 0.513043] (n=10)
- `top_1_hit_rate (RQ3)`: 0.200000 [0.000000, 0.500000] (n=10)
- `top_3_hit_rate (RQ3)`: 0.200000 [0.000000, 0.500000] (n=10)
- `top_5_hit_rate (RQ3)`: 0.200000 [0.000000, 0.500000] (n=10)
- `mrr (RQ3)`: 0.233394 [0.031102, 0.513043] (n=10)
- `detection_rate (RQ3)`: 0.500000 [0.300000, 0.700000] (n=20)
- `mean_bpr_delta (RQ3)`: 0.091835 [0.011063, 0.207587] (n=20)


