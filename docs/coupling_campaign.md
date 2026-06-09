# RQ4 higher-order coupling campaign

The RQ4 campaign measures whether oracles that detect first-order faults also detect
coupled higher-order faults on a pinned 250-case cohort from `fsmrepairbench_1k`.

## Primary (deterministic) campaign

The default campaign chains secondary mutation operators deterministically from a
CRC32-seeded rotation over the operator pool (`build_operator_chain`). This is the
frozen primary RQ4 result under `results/rq4_coupling_250/`.

```bash
cd fsmrepairbench
fsmrepairbench run-coupling-campaign data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/coupling_campaign_250.txt \
  --out results/rq4_coupling_250 \
  --subset-dir results/rq4_coupling_subset \
  --seed 44
```

Exports include `summary.csv`, `coupling_metrics.csv`, `per_case_results.csv`,
`confidence_intervals.csv`, figures, LaTeX tables, `report.md`, and `manifest.json`.

## Random-secondary sensitivity analysis

Reviewers may argue that deterministic secondary-operator chaining inflates
higher-order detection. The random-secondary sensitivity analysis repeats HO
generation (orders 2 and 3) with reproducible random secondary operator selection
across multiple seeds while leaving the primary deterministic campaign unchanged.

```bash
fsmrepairbench run-coupling-campaign data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/coupling_campaign_250.txt \
  --secondary-operator-policy random \
  --out results/rq4_coupling_250_random_secondary \
  --subset-dir results/rq4_coupling_subset_random_secondary \
  --seed 44
```

### CLI options

| Option | Default | Description |
|--------|---------|-------------|
| `--secondary-operator-policy` | `deterministic` | `deterministic` (primary RQ4) or `random` |
| `--random-secondary-seeds` | `0,1,…,9` | Comma-separated seeds or integer count (`3` → `0,1,2`) |
| `--paper-export-dir` | `../paper1/results/rq4_coupling_250_random_secondary` | LaTeX table copy for the manuscript tree |

For each random secondary seed the campaign:

1. Materializes an enriched subset under `subset_root/seed_XXXX/`
2. Generates order-2 and order-3 higher-order mutants with `build_random_operator_chain`
3. Computes detection, complete repair, effective repair, mean ΔBPR, and coupling effect

### Random-secondary exports

Written to `results/rq4_coupling_250_random_secondary/`:

| File | Content |
|------|---------|
| `per_seed_summary.csv` | Seed-level campaign metrics |
| `per_case_results.csv` | All analyzed rows with `secondary_random_seed` |
| `random_secondary_summary.csv` | Across-seed aggregate (mean, std, min, max, 95% CI) |
| `random_secondary_summary.json` | Same summary plus bootstrap metadata |
| `report.md` | Human-readable report |
| `manifest.json` | Full provenance including per-seed payloads |
| `tables/table_random_secondary_summary.tex` | LaTeX table for sensitivity metrics |

LaTeX tables are also copied to `../paper1/results/rq4_coupling_250_random_secondary/tables/`.

### Bootstrap confidence intervals

Across-seed percentile bootstrap (10,000 resamples, seed 44) is computed on
seed-level metrics for:

- Higher-order detection rate
- Coupling effect estimate
- Complete and effective repair rates by order (1–3)
- Mean ΔBPR by order (1–3)

This is distinct from the case-level bootstrap in the primary RQ4 campaign
(`confidence_intervals.csv`).

## Related documents

- [higher_order_mutation.md](higher_order_mutation.md) — HO mutant definitions
- [fault_localization.md](fault_localization.md) — RQ3 localization campaign
- [c1_baseline_repair.md](c1_baseline_repair.md) — C1 baseline repair campaign
