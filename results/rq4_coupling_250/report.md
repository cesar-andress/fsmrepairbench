# RQ4 Higher-Order Coupling Campaign

Higher-order mutants (orders 2 and 3) were generated on the pinned 250-case cohort
by chaining the source first-order operator with deterministic secondary operators
(campaign seed 44).

## Experimental design

- **Source dataset:** `data/fsmrepairbench_1k`
- **Cohort:** `coupling_campaign_250.txt` (250 cases)
- **Enriched subset:** `results/rq4_coupling_subset`
- **Repair baseline:** `missing-transition` (seed 44)

## Aggregate metrics

| Metric | Value |
|---|---:|
| Total analyzed cases | 750 |
| First-order cases | 250 |
| Higher-order cases | 500 |
| First-order detection rate | 47.20% |
| Higher-order detection rate | 99.60% |
| Coupling effect estimate | 100.00% |
| Skipped HO generations | 0 |

## Detection and repair by mutation order

| Order | Cases | Detection | Complete repair | Effective repair | Mean faulty BPR | Mean $\Delta$BPR |
|---|---:|---:|---:|---:|---:|---:|
| 1 | 250 | 47.20% | 89.20% | 42.00% | 0.932 | 0.068 |
| 2 | 250 | 99.20% | 60.00% | 92.00% | 0.733 | 0.267 |
| 3 | 250 | 100.00% | 40.40% | 98.00% | 0.612 | 0.388 |

## Figures

![Detection by order](figures/detection_rate_by_order.png)

![Complete repair by order](figures/complete_repair_rate_by_order.png)

![Coupling effect by operator (order 2)](figures/coupling_effect_by_operator_order2.png)

## Artifacts

- Summary: `results/rq4_coupling_250/summary.csv`
- Coupling metrics: `results/rq4_coupling_250/coupling_metrics.csv`
- Per-case results: `results/rq4_coupling_250/per_case_results.csv`
- Coupling report JSON: `results/rq4_coupling_250/coupling_report.json`
- LaTeX tables: `results/rq4_coupling_250/tables/`

