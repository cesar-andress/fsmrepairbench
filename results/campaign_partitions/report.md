# Campaign partition summary

Generated: 2026-06-09T06:48:18.636870+00:00

Unified view of cohort sizes, detectable subsets, and denominators used for primary metrics across paper empirical campaigns.

| Campaign | Cohort | Total | Detectable | Skipped | Denominator |
|----------|--------|------:|-----------:|--------:|-------------|
| v0.2.0-analysis | `data/fsmrepairbench_1k/analysis_cohort_1k.txt` | 1000 | 495 | 0 | n=1000 (full pinned cohort) |
| C1-baseline-repair | `data/fsmrepairbench_1k/analysis_cohort_1k.txt` | 1000 | 495 | 0 | n=1000 cohort-wide; n=495 for detectable-only repair rates |
| RQ3-localization-ochiai-1k | `data/fsmrepairbench_1k/localization_cohort_1k.txt` | 1000 | 495 | 505 | n=495 localized cases with changed_transition_id |
| RQ4-higher-order-coupling-250 | `data/fsmrepairbench_1k/coupling_campaign_250.txt` | 250 | 118 | 0 | n=250 pinned source cases; n=250 order-1, n=250 order-2, n=250 order-3 generated cases per metric stratum |
| C3-oracle-depth-ablation-200 | `data/fsmrepairbench_1k/oracle_depth_ablation_200.txt` | 200 | 97 | 0 | n=200 fixed cases per depth preset |

## Row notes

### v0.2.0-analysis

- Research question: RQ1 (taxonomy coverage) / RQ2 (mutation detection and BPR)
- Release label: `v0.2.0-analysis`
- Cohort SHA-256: `c03c4d5981259510bccfced987c5175f28058d7bdccc164e7ce2ba22410f04f8`
- Primary metrics: RQ2: overall_detection_rate, mean_faulty_bpr, mean_bpr_delta; RQ1: taxonomy dimension/operator coverage on the same cohort
- Notes: Oracle-detectable subset n=495 (bpr_delta>0) used for operator-conditional detection rates; cohort-wide aggregates use all 1,000 cases.

### C1-baseline-repair

- Research question: RQ6 (deterministic baseline repair)
- Release label: `C1-baseline-repair`
- Cohort SHA-256: `c03c4d5981259510bccfced987c5175f28058d7bdccc164e7ce2ba22410f04f8`
- Primary metrics: complete_repair_rate, effective_repair_rate, mean_delta_bpr, complete_repair_rate_detectable_only
- Notes: Leaderboard reports cohort-wide rates for three baselines; detectable-only complete repair conditions on oracle-visible faults (n=495).

### RQ3-localization-ochiai-1k

- Research question: RQ3 (transition-level fault localization)
- Release label: `RQ3-localization-ochiai-1k`
- Cohort SHA-256: `c03c4d5981259510bccfced987c5175f28058d7bdccc164e7ce2ba22410f04f8`
- Primary metrics: top_1_hit_rate, top_3_hit_rate, top_5_hit_rate, mrr
- Notes: Skipped cases lack localizable transition ground truth or missing case assets; hit rates and MRR exclude the 505 skipped cases.

### RQ4-higher-order-coupling-250

- Research question: RQ4 (higher-order mutation coupling)
- Release label: `RQ4-higher-order-coupling-250`
- Cohort SHA-256: `86222a059d56a7c913ecf9f847bbc8650ad1ce0f3cea0decbe124d7147bd7979`
- Primary metrics: detection_rate, complete_repair_rate, effective_repair_rate, mean_bpr_delta by mutation order; coupling_effect_estimate
- Notes: Pinned cohort selects 250 stratified source cases; campaign analyzes 750 generated first-/higher-order instances. Order-specific denominators are 250 per stratum in exported tables.

### C3-oracle-depth-ablation-200

- Research question: C3 (oracle depth sensitivity ablation)
- Release label: `C3-oracle-depth-ablation-200`
- Cohort SHA-256: `144e8efb3b810248e0c9a0852f2fdcd41b3a9ea1b287f4c4500ddbe36371d5c9`
- Primary metrics: overall_detection_rate, mean_faulty_bpr, mean_bpr_delta by oracle depth (shallow/medium/deep)
- Notes: Same 200-case stratified cohort rescored under regenerated shallow, medium, and deep oracle suites; detectable count reflects bpr_delta>0 at each depth.

