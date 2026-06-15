# C1 Extended Baseline Repair

Additional deterministic repair engines on the pinned 1{,}000-case analysis cohort,
complementing the original C1 trio (`missing-transition`, `wrong-target`, `random`).

## Engines

| CLI command | tool_id | Strategy |
|-------------|---------|----------|
| `search-bpr` | `baseline_search_bpr` | Greedy oracle-guided search over patch candidates to maximize BPR |
| `oracle-composite` | `baseline_oracle_composite` | Single-pass structural alignment: missing transition, wrong target/source/event, initial state |
| `llm-template` | `baseline_llm_template` | Deterministic LLM-style template baseline (reproducible without model API) |

All engines consume only `faulty_fsm.json` and `oracle_suite.json` (same construct as C1).

## Run

```bash
fsmrepairbench run-c1-extended-baseline-repair data/fsmrepairbench_1k \
  --out results/baseline_repair_C1_extended \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --workers 4

python ../paper1/scripts/generate_baseline_repair_C1_extended_outputs.py
```

Export-only from existing runs:

```bash
fsmrepairbench export-c1-extended-baseline-repair data/fsmrepairbench_1k \
  --out results/baseline_repair_C1_extended
```

## Metrics

Per tool and partition (cohort-wide / detectable-only):

- complete repair (`final_bpr == 1.0`)
- effective repair (`final_bpr > initial_bpr`)
- mean ΔBPR

Bootstrap 95% CIs: `confidence_intervals.csv` (campaign label `C1-extended-baseline-repair`).

## Localization coupling

`repair_localization_coupling.csv` joins each repair outcome with structural-diff
localization top-k ranks (RQ3 upper-bound method) where reference FSM is available
for evaluation context. Repair engines do not consume reference FSM; the coupling
export is for analysis only.

## Manifest

Release label: `C1-extended-baseline-repair`

Frozen paper export: `paper1/results/baseline_repair_C1_extended/manifest.json`

Required fields match C1 (`campaign_label`, `cohort_sha256`, `tool_names`, `regeneration_commands`, …)
plus `extended_engines`.

## Tests

```bash
pytest tests/test_c1_extended_baselines.py tests/test_baselines.py -q
```
