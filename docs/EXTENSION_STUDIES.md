# Extension studies: multi-seed stability and observability boundary

This document describes two post-freeze experiments that strengthen scientific contribution without changing the frozen IST manuscript until new results are integrated.

## Goal 1 — Multi-seed stability

### Design

- Build **≥10 independent cohorts** from the same stratified plan (`plans/fsmrepairbench_v0_1k_plan.yaml`) with only `plan.seed` changed.
- Default seeds: `44, 54, 64, 74, 84, 94, 104, 114, 124, 134` (canonical cohort uses seed 44).
- Fixed across seeds: cell taxonomy, counts, oracle depth, repair tool (`baseline_random`), repair seed (default `0`).
- Per cohort, recompute:
  - detection rate, saturation rate
  - detectable-only random complete-repair rate (floor)
  - participation split (structural GT / spectrally participating / absent)
  - saturation inflation (cohort-wide CRR − detectable-only CRR, in pp)
- Aggregate across seeds: mean, std, min, max, bootstrap 95% CI, stability label (`stable` / `moderate` / `seed_sensitive`).

### Commands

```bash
cd fsmrepairbench

# Fast validation (100 cases × 2 seeds, no repair)
fsmrepairbench run-multiseed-stability \
  --smoke \
  --seeds 44,54 \
  --output-dir results/multiseed_stability_smoke \
  --skip-repair

# Full study (1000 cases × 10 seeds + random repair per cohort)
fsmrepairbench run-multiseed-stability \
  --output-dir results/multiseed_stability \
  --workers 4

# Resume after cohort builds (repair only)
fsmrepairbench run-multiseed-stability \
  --output-dir results/multiseed_stability \
  --skip-build \
  --workers 4
```

### Outputs

| Path | Content |
|------|---------|
| `results/multiseed_stability/per_seed_metrics.csv` | One row per cohort seed |
| `results/multiseed_stability/cross_seed_aggregates.csv` | Mean/std/min/max/CI/stability |
| `results/multiseed_stability/table_multiseed_stability.tex` | Manuscript table |
| `results/multiseed_stability/INTERPRETATION.md` | Ready-to-adapt prose |
| `results/multiseed_stability/figures/multiseed_stability_bars.png` | Bar chart (requires `[analytics]`) |

### Expected runtime

| Mode | Cohort build | Random repair | Total (10 seeds) |
|------|--------------|---------------|------------------|
| Smoke (100 cases, 2 seeds) | ~2–4 min | ~1 min optional | ~5 min |
| Full (1000 cases, 10 seeds) | ~40–70 min/seed | ~20–40 min/seed | **~10–18 h** (parallel `--workers 4` reduces repair wall time) |

---

## Goal 2 — Observability boundary (S0→S3)

### Design

On the **frozen** `data/fsmrepairbench_1k` cohort:

| Surface | Visible fields checked | Step pass rule |
|---------|------------------------|----------------|
| S0 | state | state match (published) |
| S1 | state, action | + action match |
| S2 | state, action, guard | + guard match |
| S3 | state, action, guard, event | + event match |

Per surface: detection, saturation, surface-aware spectral participation, random-repair CRR (cohort-wide and detectable-only) via **rescore** of cached `final_fsm` from C1 seed 0.

Identifies thresholds where saturation, inflation, and participation artifacts shrink below practical relevance (~5–10 pp inflation).

### Commands

```bash
cd fsmrepairbench

fsmrepairbench run-observability-boundary \
  --dataset-dir data/fsmrepairbench_1k \
  --output-dir results/observability_boundary \
  --repair-runs-dir results/baseline_repair_C1/multi_seed/seed_0000
```

### Outputs

| Path | Content |
|------|---------|
| `results/observability_boundary/surface_ladder_summary.csv` | S0–S3 metrics |
| `results/observability_boundary/surface_transitions.csv` | Stepwise deltas |
| `results/observability_boundary/table_observability_boundary.tex` | Manuscript table |
| `results/observability_boundary/INTERPRETATION.md` | Boundary answer + thresholds |
| `results/observability_boundary/figures/observability_boundary_ladder.png` | Line plot |

### Expected runtime

- Rescore only (1000 cases × 4 surfaces + participation + repair rescore): **~15–25 min** on a typical workstation.

---

## Manuscript section outline (new material, post-freeze)

### §6.5 Cross-seed stability (or §11 if appendix-first)

1. **Motivation** — Single-seed cohort (seed 44) may leave seed-specific partition ratios uncharacterized.
2. **Protocol** — Ten stratified cohorts; fixed taxonomy; random repair seed 0.
3. **Results** — Table `tab:multiseed-stability`; figure with dispersion bars.
4. **Interpretation** — Which constructs are seed-stable (expect: detectable-only floor ≈ 0%; inflation magnitude seed-sensitive with saturation rate).

### §6.6 Observability boundary (extends §6)

1. **Motivation** — Prior S0/S1 sensitivity shows observability matters; open question: when does it stop mattering?
2. **Progressive surfaces S0→S3** — Field-visibility ladder.
3. **Results** — Table `tab:observability-boundary`; transition deltas; inflation/saturation crossover.
4. **Answer** — Conditions under which cohort-wide repair reporting converges to detectable-only and participation denominators stabilize.

---

## Expected scientific contribution

1. **Robustness evidence** — Quantifies seed sensitivity vs invariance of the observability confound; separates structural claims from cohort-realization noise.
2. **Boundary characterization** — First systematic ladder showing where saturation inflation and spectral participation artifacts diminish, answering a reviewer “when does this stop mattering?” attack directly.
3. **Operational guidance** — Empirical thresholds for reporting partitions in FSM/MBT repair and localization papers.

---

## Estimated acceptance gain

| Venue | Baseline (frozen manuscript) | With both studies | Rationale |
|-------|------------------------------|-------------------|-----------|
| **IST** | Ready after editorial checks | **+8–15 pp** accept probability | Addresses synthetic/generalizability and single-cohort concerns; strengthens §6–§8 claims with robustness + boundary conditions without new LLM results. |
| **EMSE** | Weaker on generalizability | **+12–20 pp** | EMSE reviewers weight empirical thoroughness; cross-seed + dose–response observability ladder is aligned with EMSE expectations for benchmark papers. |

These are heuristic estimates assuming results confirm qualitative claims (invariant detectable-only floor; inflation tracks saturation; boundary crossover before S3 or documents persistence through S3).
