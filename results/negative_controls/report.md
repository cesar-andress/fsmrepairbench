# Negative Control Cohort (No-Fault)

Construct-validity controls for repair tools on already-correct FSMs. These cases copy reference machines and oracle suites from the frozen v0.2.0-analysis cohort without injecting mutations.

**Important:** This pilot does not replace the Zenodo `v0.2.0-analysis` release.

## Cohort

- Dataset: `data/fsmrepairbench_negative_controls`
- Manifest: `negative_control_cohort_100.txt`
- Cases: 100
- Selection seed: 44

## Overall metrics

- False repair rate: **0.00%**
- Regression rate: **0.00%**
- Mean ΔBPR: **0.0000**
- Tool runs modifying correct FSMs: **0**
- Localization skipped (not applicable): **100/100**

## Metrics by repair tool

| Tool | Cases | False repair | Regression | Mean ΔBPR | Patches applied |
|---|---:|---:|---:|---:|---:|
| `baseline_missing_transition` | 100 | 0.00% | 0.00% | 0.0000 | 0 |
| `baseline_random` | 100 | 0.00% | 0.00% | 0.0000 | 0 |
| `baseline_wrong_target` | 100 | 0.00% | 0.00% | 0.0000 | 0 |

## Artifacts

- Summary: `results/negative_controls/summary.csv`
- Per-case results: `results/negative_controls/per_case_results.csv`
- LaTeX tables: `results/negative_controls/tables/`

