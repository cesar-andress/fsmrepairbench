# Stratified Dataset: fsmrepairbench_1k

- **Dataset:** fsmrepairbench_1k
- **Version:** 0.2.0-analysis
- **Number of completed FSM cases:** 1,024
- **Number of analyzed FSM cases:** 1,000 (pinned cohort)
- **Files:** reference_fsm.json, faulty_fsm.json, oracle_suite.json, bug_metadata.json, case_features.json
- **Seed:** 43 (Zenodo metadata); build plan uses seed **44** — see `plans/fsmrepairbench_v0_1k_plan.yaml`
- **DOI:** [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528)
- **Notes:** some candidate cases failed due to unsupported mutation operators

Build plan: `plans/fsmrepairbench_v0_1k_plan.yaml`. Per-case metrics and build status: `progress.csv`.

## Pinned analysis cohort (1,000 cases)

Paper experiments use the first **1,000** `completed` rows in `progress.csv` order:

| File | Role |
|------|------|
| `analysis_cohort_1k.txt` | One case ID per line (canonical order) |
| `analysis_cohort_1k.json` | Manifest with SHA-256, DOI, plan seed, timestamps |

Regenerate from paper workspace:

```bash
python ../paper1/scripts/pin_analysis_cohort.py
```

## Implemented campaigns on this dataset

| Campaign | CLI | Results (code repo) | Paper export |
|----------|-----|---------------------|--------------|
| v0.2.0-analysis | `analyze-benchmark` | `results/analysis/` | `paper1/results/v0_2_analysis/` |
| RQ1 taxonomy coverage | `generate-taxonomy-coverage` | `results/taxonomy_coverage/` (`manifest.json`) | (pending) |
| C1 baseline repair | `run-c1-baseline-repair` / `run-tools` + `tools/baselines_c1/` | `results/baseline_repair_C1/` (`manifest.json`) | `paper1/results/baseline_repair_C1/` (`manifest.json`) |
| C3 oracle depth ablation | `run-oracle-depth-ablation` | `results/oracle_depth_ablation/` | (pending) |
| RQ3 localization | `run-localization-campaign` / `paper1/scripts/run_rq3_localization.py` | `results/rq3_localization_1k/` | `paper1/results/rq3_localization_1k/` |
| RQ4 coupling | `run-coupling-campaign` / `paper1/scripts/run_rq4_coupling_campaign.py` | `results/rq4_coupling_250/` | `paper1/results/rq4_coupling_250/` |

## Pinned experiment cohorts

| Cohort | Cases | Manifest |
|--------|------:|----------|
| Analysis | 1,000 | `analysis_cohort_1k.txt` |
| RQ3 localization | 1,000 | `localization_cohort_1k.txt` |
| RQ4 coupling | 250 | `coupling_campaign_250.txt` |
| C3 oracle depth | 200 | `oracle_depth_ablation_200.txt` |

Regenerate all pinned manifests and verify SHA-256 digests:

```bash
python ../paper1/scripts/pin_all_cohort_manifests.py
```

Individual pins: `pin_analysis_cohort.py`, `pin_rq3_rq4_cohorts.py`, `pin_oracle_depth_cohort.py`.
Verify only: `python ../paper1/scripts/verify_cohort_manifests.py`.

Each completed case directory under `cases/` contains reference and faulty FSM serialisations, oracle suite, and bug metadata.
