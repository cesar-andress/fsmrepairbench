# Implementation audit — v0.3 empirical robustness improvements

**Date:** 2026-06-09  
**Package root:** `fsmrepairbench/` (Python package under `~/papers/fsmrepairbench/fsmrepairbench`)  
**Paper export root:** `../paper1/results/`  
**Scope:** Post-implementation verification of C1 manifest, multi-seed exports, confidence intervals, campaign partitions, RQ4 random-secondary sensitivity, C3 depth-forced ablation, multifamily pilot, and negative controls.

---

## 1. Test suite

```text
$ cd fsmrepairbench && python -m pytest -q
589 passed, 1 skipped in 20.63s
```

All unit and CLI integration tests for the v0.3 robustness features pass (`test_coupling_random_secondary.py`, `test_oracle_depth_ablation_v2.py`, `test_multifamily_pilot.py`, `test_negative_control_campaign.py`, `test_campaign_partitions.py`, etc.).

---

## 2. Smoke command log

Commands executed from `fsmrepairbench/` on 2026-06-09. Fixture dataset: `tests/fixtures/stratified_coupling_dataset` unless noted.

| # | Command | Exit | Notes |
|---|---------|-----:|-------|
| 1 | `fsmrepairbench validate-fsm tests/fixtures/valid_fsm.json` | 0 | OK — valid FSM |
| 2 | `fsmrepairbench validate-oracle tests/fixtures/valid_oracle.json` | 0 | OK — valid oracle suite |
| 3 | `fsmrepairbench score tests/fixtures/simple_fsm.json tests/fixtures/simple_oracle.json` | 0 | BPR 100%, 2/2 scenarios |
| 4 | `fsmrepairbench analyze-benchmark tests/fixtures/stratified_coupling_dataset --out /tmp/audit_smoke_out/analyze` | 0 | 1 case analyzed |
| 5 | `fsmrepairbench run-tools tests/fixtures/stratified_coupling_dataset tools/baselines_c1 --out /tmp/audit_smoke_out/tools --workers 1 --max-cases 1` | 2 | **Invalid flag** — `--max-cases` is not a `run-tools` option |
| 5′ | `fsmrepairbench run-tools tests/fixtures/stratified_coupling_dataset tools/baselines_c1 --out /tmp/audit_smoke_out/tools --workers 1 --quiet` | 0 | 3 baseline runs on 1-case fixture |
| 6 | `fsmrepairbench run-localization-campaign tests/fixtures/stratified_coupling_dataset --out /tmp/audit_smoke_out/localization --cohort-file /tmp/audit_cohort.txt` | 0 | 1 localized case |
| 7 | `fsmrepairbench run-oracle-depth-ablation tests/fixtures/stratified_coupling_dataset --out /tmp/audit_smoke_out/oracle_depth --cohort-file /tmp/audit_cohort.txt --no-write-cohort --scenario-policy depth-forced` | 0 | Depth-forced ablation on 1 case; **also writes default paper export** |
| 8 | `fsmrepairbench summarize-campaign-partitions --dataset data/fsmrepairbench_1k --out /tmp/audit_smoke_out/partitions --paper-export-dir /tmp/audit_smoke_out/partitions_paper --quiet` | 0 | 5 campaign rows |

**Smoke artefact warning:** Command 7 defaults to `--paper-export-dir ../paper1/results/oracle_depth_ablation_v2`. The audit smoke run overwrote that untracked directory with a 1-case fixture manifest. Regenerate the full 200-case campaign before citing C3 v2 numbers in the manuscript (see §5).

---

## 3. Output verification matrix

Legend: **OK** = required artefacts present at production scale; **PARTIAL** = present but incomplete naming, scale, or location; **MISSING** = directory or core artefact absent.

Expected core trio where applicable: `manifest.json`, `report.md`, and a primary CSV (`summary.csv` or campaign-specific equivalent). Paper-ready LaTeX under `tables/` where the export pipeline supports it.

### 3.1 C1 baseline manifest

| Location | Status | manifest | report | summary CSV | tables | CI |
|----------|--------|:--------:|:------:|:-----------:|:------:|:--:|
| `results/repair_baseline_1k_c1/` | **OK** | ✓ | ✓ | ✓ `summary.csv` | — (paper only) | ✓ `confidence_intervals.csv` |
| `../paper1/results/baseline_repair_C1/` | **OK** | ✓ | ✓ | ✓ | ✓ 8 `.tex` | ✓ |

Additional C1 exports verified:

- Raw multi-seed: `random_multiseed_summary.csv`, `random_multiseed_per_seed.csv`, `random_multiseed_summary.json`
- Paper multi-seed: `random_multi_seed_summary.csv`, `random_multi_seed_aggregate.csv`, `tables/table_random_multi_seed_aggregate.tex`

### 3.2 Confidence intervals

| Campaign | Raw (`results/`) | Paper (`../paper1/results/`) |
|----------|------------------|------------------------------|
| v0.2 analysis | ✓ `analysis/confidence_intervals.csv` | ✓ `v0_2_analysis/confidence_intervals.csv` + LaTeX |
| C1 baseline | ✓ `repair_baseline_1k_c1/confidence_intervals.csv` | ✓ `baseline_repair_C1/confidence_intervals.csv` + LaTeX |
| RQ3 localization | — | ✓ `rq3_localization_1k/confidence_intervals.csv` + LaTeX |
| RQ4 coupling (primary) | ✓ `rq4_coupling_250/confidence_intervals.csv` + LaTeX | (mirrored in primary export) |
| C3 oracle depth (original) | ✓ `oracle_depth_ablation/confidence_intervals.csv` + LaTeX | ✓ `oracle_depth_ablation/tables/table_confidence_intervals.tex` |

Analysis cohort exports intentionally omit `manifest.json`; C1/RQ4/C3 manifests record CI file paths in `output_files`.

### 3.3 Campaign partition table

| Location | Status | Primary CSV | report | manifest | LaTeX |
|----------|--------|-------------|--------|----------|-------|
| `results/campaign_partitions/` | **OK** | ✓ `partition_summary.csv` | ✓ | — (by design) | — |
| `../paper1/results/campaign_partitions/` | **PARTIAL** | ✓ | — | — | ✓ `tables/table_campaign_partitions.tex` |

The partition exporter uses `partition_summary.{csv,json}` rather than `summary.csv`. Raw `report.md` documents five campaigns with denominators (analysis 1000, C1 1000/495, RQ3 495, RQ4 250, C3 200).

### 3.4 RQ4 random-secondary sensitivity

| Location | Status | Notes |
|----------|--------|-------|
| `results/rq4_coupling_250_random_secondary/` | **MISSING** | Raw mirror directory not populated |
| `../paper1/results/rq4_coupling_250_random_secondary/` | **PARTIAL** | Untracked smoke export: 2 seeds, pytest/tmp cohort in `report.md`; no `manifest.json` |

Present in paper tree: `random_secondary_summary.csv`, `random_secondary_summary.json`, `report.md`, `tables/table_random_secondary_summary.tex`.

### 3.5 C3 depth-forced ablation (v2)

| Location | Status | Notes |
|----------|--------|-------|
| `results/oracle_depth_ablation_v2/` | **MISSING** | Raw mirror directory not populated |
| `../paper1/results/oracle_depth_ablation_v2/` | **PARTIAL** | Smoke-scale (1 case) after audit CLI run; uses `depth_summary.csv` not `summary.csv` |

Present: `manifest.json`, `report.md`, `depth_summary.csv`, `coverage_by_depth.csv`, `paired_detection_changes.csv`, `per_case_results.csv`, 2 LaTeX tables.

Original C3 (`results/oracle_depth_ablation/`) remains unchanged at 200-case scale with shortest-path policy.

### 3.6 Multifamily external-validity pilot

| Location | Status | Scale |
|----------|--------|-------|
| `results/multifamily_v0_3_smoke/` | **OK** | 500 cases (100 × 5 families) |
| `../paper1/results/multifamily_v0_3_smoke/` | **OK** | Mirrored |

All core artefacts plus `family_summary.csv`, `detection_by_family.csv`, `operator_by_family.csv`, and 2 LaTeX tables.

### 3.7 Negative controls (no-fault)

| Location | Status | Scale |
|----------|--------|-------|
| `results/negative_controls/` | **OK** | 100 no-fault cases, seed 44 |
| `../paper1/results/negative_controls/` | **OK** | Mirrored |

0% false repair and 0% regression on C1 baselines (see `docs/negative_controls.md`).

---

## 4. Missing outputs (summary)

| Item | Gap |
|------|-----|
| RQ4 random-secondary raw tree | `results/rq4_coupling_250_random_secondary/` never created |
| C3 depth-forced raw tree | `results/oracle_depth_ablation_v2/` never created |
| RQ4 random-secondary manifest | No `manifest.json` in paper export (CLI gap for this campaign) |
| RQ4 / C3 v2 production scale | Paper exports currently reflect test/smoke runs (2 seeds / 1 case), not pinned 250 / 200 cohorts |
| C1 raw LaTeX tables | Tables live under paper export only (`export-c1-baseline-repair` / paper script) |
| Campaign partitions paper report | `report.md` written to raw dir only; paper dir has CSV + LaTeX |
| Naming convention | Some campaigns use domain CSV names (`depth_summary.csv`, `random_secondary_summary.csv`, `partition_summary.csv`) instead of generic `summary.csv` |

---

## 5. Known limitations

1. **Dual-tree layout.** Production numbers for manuscript tables live under `../paper1/results/`; raw `results/` mirrors are incomplete for the two newest campaigns (RQ4 random-secondary, C3 v2).
2. **Smoke overwrite of C3 v2 paper export.** Default `--paper-export-dir` on `run-oracle-depth-ablation` makes fixture-scale CLI/tests risky for frozen exports. Prefer explicit `--paper-export-dir` to a temp path in CI/smoke, or `--no-paper-export` if added later.
3. **RQ4 random-secondary cost.** Full run: 250-case cohort × 10 random secondary seeds × HO generation — expect long runtime; only smoke-scale artefacts exist today.
4. **C3 original vs v2.** `oracle_depth_ablation/` (shortest-path) shows identical shallow/medium/deep detection under original generation; v2 (`depth-forced`) is the intended ablation but needs full 200-case regeneration before paper claims.
5. **Multifamily / negative controls are v0.3 pilots.** Not part of Zenodo `v0.2.0-analysis`; document as sensitivity / validity supplements, not primary cohort replacements.
6. **Partition exporter schema.** By design omits `manifest.json`; metadata is in `partition_summary.json`.
7. **Untracked paper dirs.** `paper1/results/rq4_coupling_250_random_secondary/` and `oracle_depth_ablation_v2/` are not yet committed to git (`??`).

---

## 6. Suggested next steps for paper integration

### 6.1 Regenerate production-scale exports

```bash
# RQ4 random-secondary (250 cases, seeds 0–9)
fsmrepairbench run-coupling-campaign data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/coupling_campaign_250.txt \
  --no-write-cohort \
  --secondary-operator-policy random \
  --out results/rq4_coupling_250_random_secondary \
  --paper-export-dir ../paper1/results/rq4_coupling_250_random_secondary

# C3 depth-forced (200 cases)
fsmrepairbench run-oracle-depth-ablation data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_200.txt \
  --no-write-cohort \
  --scenario-policy depth-forced \
  --out results/oracle_depth_ablation_v2 \
  --paper-export-dir ../paper1/results/oracle_depth_ablation_v2

# Refresh campaign partition table (already OK at raw scale)
fsmrepairbench summarize-campaign-partitions --dataset data/fsmrepairbench_1k
```

### 6.2 Manuscript wiring (`../paper1/main.tex` — not modified in this audit)

- **Table: campaign partitions** — `\input{results/campaign_partitions/tables/table_campaign_partitions.tex}`
- **C1 robustness** — CI table + random multi-seed aggregate from `baseline_repair_C1/tables/`
- **RQ4 sensitivity** — `table_random_secondary_summary.tex`; cite alongside primary RQ4 CI table
- **C3 ablation** — prefer v2 `table_depth_forced_summary.tex` and `table_paired_detection_changes.tex`; retain footnote that original C3 used shortest-path generation
- **Supplements** — multifamily family/detection tables; negative-control summary (0% false repair)

### 6.3 Hardening before Zenodo v0.3

- Add `manifest.json` emission to RQ4 random-secondary export pipeline
- Mirror raw + paper trees for RQ4 random-secondary and C3 v2
- Pin regeneration commands in `docs/reproducibility.md`
- Consider CLI flag to disable paper export during tests/smoke
- Commit frozen paper exports after full regeneration

---

## 7. Audit conclusion

| Area | Implementation | Production artefacts |
|------|:--------------:|:--------------------:|
| C1 manifest + multi-seed + CI | ✓ | ✓ |
| Analysis / RQ3 / RQ4 / C3 CI | ✓ | ✓ (RQ3/C1/analysis paper) |
| Campaign partitions | ✓ | ✓ raw; paper missing `report.md` |
| RQ4 random-secondary | ✓ code & tests | ✗ raw; smoke-scale paper only |
| C3 depth-forced v2 | ✓ code & tests | ✗ raw; smoke-scale paper only |
| Multifamily pilot | ✓ | ✓ |
| Negative controls | ✓ | ✓ |
| pytest + CLI smoke | ✓ | — |

**Overall:** v0.3 robustness features are implemented and tested. Primary empirical gaps are **full-scale regeneration** of RQ4 random-secondary and C3 depth-forced exports in both `results/` and `../paper1/results/` before manuscript numbers are final.
