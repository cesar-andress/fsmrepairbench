# Multi-Family External-Validity Pilot (v0.3.0)

Pilot mini-cohort to reduce the **plain_fsm-only** external-validity weakness in the
frozen `v0.2.0-analysis` release. This dataset informs future benchmark releases; it
does **not** replace the Zenodo `v0.2.0-analysis` deposit or modify
`data/fsmrepairbench_1k/analysis_cohort_1k.txt`.

## Small pilot (20 cases)

| Field | Value |
|-------|-------|
| Plan file | `plans/fsmrepairbench_multifamily_pilot_plan.yaml` |
| Dataset | `data/fsmrepairbench_multifamily_pilot/` |
| Cases | 20 (4 stratification cells × 5 families) |
| Seed | 46 |
| Release label | `v0.3.0-multifamily-pilot` |

Each non-`plain_fsm` family (Mealy, Moore, EFSM, timed FSM) has at least four cases;
`plain_fsm` cells provide a local reference without replacing the frozen 1k cohort.

### Regeneration (from `fsmrepairbench/`)

```bash
python ../paper1/scripts/build_multifamily_pilot_dataset.py
python ../paper1/scripts/pin_multifamily_pilot_cohorts.py
python ../paper1/scripts/generate_multifamily_pilot_outputs.py
```

### Exports

| Location | Contents |
|----------|----------|
| `results/multifamily_pilot/` | Repo-local analysis outputs |
| `../paper1/results/multifamily_pilot/` | Paper-ready copy |

Coverage ratios (dimension, mutation operator, complexity tier, machine type) live under
`coverage/` and are indexed in `manifest.json` with per-file SHA-256 digests.

## Smoke pilot (500 cases)


STVR reviewers may challenge taxonomy and title claims when empirical campaigns use a
1,000-case cohort containing only `plain_fsm` machines. The v0.3.0 pilot generates a
balanced 500-case sample across five machine families with the same stratified builder
used for larger releases.

## Plan

| Field | Value |
|-------|-------|
| Plan file | `plans/fsmrepairbench_multifamily_v0_3_smoke_plan.yaml` |
| Dataset | `data/fsmrepairbench_multifamily_v0_3_smoke/` |
| Cases | 500 (100 per family) |
| Seed | 46 |
| Size class | `tiny` (fast smoke-scale generation) |
| Oracle depth | `shallow` |

Target families:

- `plain_fsm`
- `mealy`
- `moore`
- `efsm`
- `timed_fsm`

## Build dataset

```bash
fsmrepairbench build-stratified-dataset \
  plans/fsmrepairbench_multifamily_v0_3_smoke_plan.yaml \
  data/fsmrepairbench_multifamily_v0_3_smoke
```

Each case directory contains:

- `reference_fsm.json`
- `faulty_fsm.json`
- `oracle_suite.json`
- `bug_metadata.json`
- `case_features.json`

## Analyze pilot cohort

```bash
fsmrepairbench analyze-multifamily-cohort \
  data/fsmrepairbench_multifamily_v0_3_smoke \
  --out results/multifamily_v0_3_smoke
```

### Exports (`results/multifamily_v0_3_smoke/`)

| File | Description |
|------|-------------|
| `summary.csv` | Overall metrics plus per-family planned/built/failure counts |
| `family_summary.csv` | Detection, BPR, coverage, build failures by family |
| `operator_by_family.csv` | Mutation operator distribution within each family |
| `detection_by_family.csv` | Detection metrics keyed by machine family |
| `report.md` | Narrative pilot report |
| `manifest.json` | Provenance (`replaces_v0_2_analysis: false`) |
| `figures/` | Family counts, detection, BPR delta, operator bars |
| `tables/` | LaTeX tables for paper export |

Paper-ready copy: `../paper1/results/multifamily_v0_3_smoke/`

## Relationship to v0.2.0-analysis

| Aspect | v0.2.0-analysis (frozen) | v0.3.0 pilot |
|--------|--------------------------|--------------|
| Zenodo release | Yes (`v0.2.0-analysis`) | No (local pilot) |
| Machine families | `plain_fsm` only | Five families |
| Size | 1,000 cases | 500 cases |
| Campaign cohorts | RQ2, C1, etc. | External-validity sensitivity only |

Do **not** merge this pilot into `data/fsmrepairbench_1k/` or re-point existing
campaign manifests.

## Tests

```bash
pytest tests/test_multifamily_pilot.py -q
```

## API

```python
from pathlib import Path
from fsmrepairbench.multifamily_analysis import analyze_multifamily_cohort

result = analyze_multifamily_cohort(
    Path("data/fsmrepairbench_multifamily_v0_3_smoke"),
    output_dir=Path("results/multifamily_v0_3_smoke"),
)
print(result.report_path)
```
