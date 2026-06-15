# RQ3 Fault Localization (Ochiai, Transition-Level)

Spectrum-based fault localization ranks transitions by Ochiai suspiciousness using oracle pass/fail spectra. Ground truth is `changed_transition_id` from `bug_metadata.json`.

## Experimental design

- **Dataset:** `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_1k`
- **Campaign:** RQ3-localization-ochiai-1k
- **Method:** ochiai on transition elements only
- **Top-k metrics:** top-1, top-3, top-5, MRR

## Aggregate metrics (legacy all-detectable partition)

The original RQ3 headline metrics include every oracle-detectable case (`n=495`) even when transition-level ground truth is not rankable. This partition is **conservative** and mixes Ochiai weakness with construct-validity failures.

| Metric | Value |
|---|---:|
| Cohort size | 1000 |
| Detectable (localized) cases | 495 |
| Skipped cases | 505 |
| Top-1 hit rate | 14.95% |
| Top-3 hit rate | 18.79% |
| Top-5 hit rate | 22.83% |
| MRR | 0.2010 |

## Construct-valid subset: transition-localizable ground truth

For construct-valid transition-level evaluation, restrict to detectable cases whose `changed_transition_id` refers to a transition that still exists in the faulty FSM and is not a non-transition fault class.

- **Transition-localizable GT cases:** 376
- **Top-1 hit rate:** 19.68%
- **Top-3 hit rate:** 24.73%
- **Top-5 hit rate:** 30.05%
- **MRR:** 0.2646

Use this partition as the primary RQ3 metric set in the paper. The all-detectable partition remains useful as a lower-bound baseline that includes non-rankable faults.

## Ground-truth localizability audit

Per-case audit export: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_1k/localizability_audit.csv`.

### Why some detectable faults are not transition-localizable

| Class | Detectable cases | Meaning |
|---|---:|---|
| `localizable_transition_gt` | 376 | `changed_transition_id` exists in the faulty FSM and can be ranked. |
| `missing_or_deleted_transition_gt` | 60 | Ground truth names a transition removed from or absent in the faulty FSM (notably `missing_transition`). |
| `non_transition_fault_gt` | 59 | Fault is not anchored to one transition ID (for example `wrong_initial_state`). |
| `missing_ground_truth` | 0 | `changed_transition_id` is empty or missing. |

Among detectable cases, **119** have non-rankable transition ground truth. These cases inflate `not_ranked` in the legacy partition.

### Operators to exclude or report separately

- **`missing_transition`:** ground truth is the deleted transition; always `missing_or_deleted_transition_gt`. Report separately or exclude from transition-localizable aggregates.
- **`wrong_initial_state`:** state-level fault with no transition ID; classify as `non_transition_fault_gt`. Requires state-level localization metrics outside RQ3.
- **`dead_state_intro`, `unreachable_state_intro`, `action_full_mutation`:** non-transition fault classes when detectable; exclude from transition-localizable GT.

## Operator summary

| Operator | Detectable | Localizable GT | Not localizable | Top-5 all | Top-5 loc. |
|---|---:|---:|---:|---:|---:|
| guard_flip | 59 | 59 | 0 | 15.25% | 15.25% |
| guard_inter_class | 20 | 20 | 0 | 15.00% | 15.00% |
| guard_strengthen | 59 | 59 | 0 | 13.56% | 13.56% |
| guard_weaken | 59 | 59 | 0 | 13.56% | 13.56% |
| missing_transition | 60 | 0 | 60 | 0.00% | 0.00% |
| wrong_event | 59 | 59 | 0 | 22.03% | 22.03% |
| wrong_initial_state | 59 | 0 | 59 | 0.00% | 0.00% |
| wrong_source | 60 | 60 | 0 | 20.00% | 20.00% |
| wrong_target | 60 | 60 | 0 | 100.00% | 100.00% |

## Artifacts

- Localizability audit: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_1k/localizability_audit.csv`
- Partition metrics: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_1k/localization_metrics_localizable_only.csv`
- Legacy per-case results: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_1k/per_case_results.csv`
- Legacy summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_1k/summary.csv`
- LaTeX tables: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_1k/tables/`


## Bootstrap confidence intervals
Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `top_1_hit_rate`: 0.149495 [0.119192, 0.181818] (n=495)
- `top_3_hit_rate`: 0.187879 [0.153535, 0.222222] (n=495)
- `top_5_hit_rate`: 0.228283 [0.191919, 0.264646] (n=495)
- `mrr`: 0.201018 [0.170688, 0.231904] (n=495)













