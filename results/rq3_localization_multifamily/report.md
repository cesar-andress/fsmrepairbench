# RQ3 Fault Localization (Ochiai, Transition-Level)

Spectrum-based fault localization ranks transitions by Ochiai suspiciousness using oracle pass/fail spectra. Ground truth is `changed_transition_id` from `bug_metadata.json`.

## Experimental design

- **Dataset:** `/home/cesar/papers/fsmrepairbench/fsmrepairbench/data/fsmrepairbench_multifamily_v0_3`
- **Campaign:** RQ3-localization-ochiai-1k
- **Method:** ochiai on transition elements only
- **Top-k metrics:** top-1, top-3, top-5, MRR

## Aggregate metrics (legacy all-detectable partition)

The original RQ3 headline metrics include every oracle-detectable case (`n=648`) even when transition-level ground truth is not rankable. This partition is **conservative** and mixes Ochiai weakness with construct-validity failures.

| Metric | Value |
|---|---:|
| Cohort size | 1000 |
| Detectable (localized) cases | 648 |
| Skipped cases | 352 |
| Top-1 hit rate | 40.12% |
| Top-3 hit rate | 51.54% |
| Top-5 hit rate | 57.25% |
| MRR | 0.4677 |

## Construct-valid subset: transition-localizable ground truth

For construct-valid transition-level evaluation, restrict to detectable cases whose `changed_transition_id` refers to a transition that still exists in the faulty FSM and is not a non-transition fault class.

- **Transition-localizable GT cases:** 450
- **Top-1 hit rate:** 57.78%
- **Top-3 hit rate:** 74.22%
- **Top-5 hit rate:** 82.44%
- **MRR:** 0.6734

Use this partition as the primary RQ3 metric set in the paper. The all-detectable partition remains useful as a lower-bound baseline that includes non-rankable faults.

## Ground-truth localizability audit

Per-case audit export: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_multifamily/localizability_audit.csv`.

### Why some detectable faults are not transition-localizable

| Class | Detectable cases | Meaning |
|---|---:|---|
| `localizable_transition_gt` | 450 | `changed_transition_id` exists in the faulty FSM and can be ranked. |
| `missing_or_deleted_transition_gt` | 149 | Ground truth names a transition removed from or absent in the faulty FSM (notably `missing_transition`). |
| `non_transition_fault_gt` | 49 | Fault is not anchored to one transition ID (for example `wrong_initial_state`). |
| `missing_ground_truth` | 0 | `changed_transition_id` is empty or missing. |

Among detectable cases, **198** have non-rankable transition ground truth. These cases inflate `not_ranked` in the legacy partition.

### Operators to exclude or report separately

- **`missing_transition`:** ground truth is the deleted transition; always `missing_or_deleted_transition_gt`. Report separately or exclude from transition-localizable aggregates.
- **`wrong_initial_state`:** state-level fault with no transition ID; classify as `non_transition_fault_gt`. Requires state-level localization metrics outside RQ3.
- **`dead_state_intro`, `unreachable_state_intro`, `action_full_mutation`:** non-transition fault classes when detectable; exclude from transition-localizable GT.

## Operator summary

| Operator | Detectable | Localizable GT | Not localizable | Top-5 all | Top-5 loc. |
|---|---:|---:|---:|---:|---:|
| guard_flip | 100 | 100 | 0 | 71.00% | 71.00% |
| guard_strengthen | 50 | 50 | 0 | 100.00% | 100.00% |
| guard_weaken | 50 | 50 | 0 | 100.00% | 100.00% |
| missing_transition | 149 | 0 | 149 | 0.00% | 0.00% |
| wrong_event | 50 | 50 | 0 | 100.00% | 100.00% |
| wrong_initial_state | 49 | 0 | 49 | 0.00% | 0.00% |
| wrong_source | 50 | 50 | 0 | 0.00% | 0.00% |
| wrong_target | 150 | 150 | 0 | 100.00% | 100.00% |

## Artifacts

- Localizability audit: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_multifamily/localizability_audit.csv`
- Partition metrics: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_multifamily/localization_metrics_localizable_only.csv`
- Legacy per-case results: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_multifamily/per_case_results.csv`
- Legacy summary: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_multifamily/summary.csv`
- LaTeX tables: `/home/cesar/papers/fsmrepairbench/fsmrepairbench/results/rq3_localization_multifamily/tables/`


## Bootstrap confidence intervals
Non-parametric percentile bootstrap over cases (10,000 resamples, 95% CI, seed 44).
Exports: `confidence_intervals.csv` and `confidence_intervals.json`.

- `top_1_hit_rate (RQ3)`: 0.401235 [0.364198, 0.439815] (n=648)
- `top_3_hit_rate (RQ3)`: 0.515432 [0.478395, 0.554012] (n=648)
- `top_5_hit_rate (RQ3)`: 0.572531 [0.535494, 0.609568] (n=648)
- `mrr (RQ3)`: 0.467652 [0.433021, 0.502831] (n=648)

