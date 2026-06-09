# RQ3 Fault Localization (Ochiai, Transition-Level)

Spectrum-based fault localization ranks transitions by Ochiai suspiciousness using oracle pass/fail spectra. Ground truth is `changed_transition_id` from `bug_metadata.json`.

## Experimental design

- **Dataset:** `data/fsmrepairbench_1k`
- **Cohort:** 1000 cases (`localization_cohort_1k.txt`)
- **Method:** ochiai on transition elements only
- **Top-k metrics:** top-1, top-3, top-5

## Aggregate metrics

| Metric | Value |
|---|---:|
| Localized cases | 495 |
| Skipped cases | 505 |
| Top-1 hit rate | 14.95% |
| Top-3 hit rate | 18.79% |
| Top-5 hit rate | 22.83% |
| MRR | 0.2010 |

## Rank distribution

| Rank bucket | Cases | Fraction |
|---|---:|---:|
| 1 | 74 | 14.95% |
| 2 | 5 | 1.01% |
| 3 | 14 | 2.83% |
| 4 | 11 | 2.22% |
| 5 | 9 | 1.82% |
| 6-10 | 58 | 11.72% |
| 11-20 | 34 | 6.87% |
| 21+ | 169 | 34.14% |
| not_ranked | 121 | 24.44% |

## Figures

![Top-k hit rates](figures/topk_hit_rates.png)

![Rank distribution](figures/rank_distribution.png)

![Top-5 hit rate by operator](figures/top5_hit_rate_by_operator.png)

## Artifacts

- Summary: `results/rq3_localization_1k/summary.csv`
- Localization metrics: `results/rq3_localization_1k/localization_metrics.csv`
- Per-case results: `results/rq3_localization_1k/per_case_results.csv`
- LaTeX tables: `results/rq3_localization_1k/tables/`

