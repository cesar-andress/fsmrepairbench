# No-fault negative control cohort

Construct-validity controls for repair-tool evaluation on **already-correct** FSMs.
Reviewers may ask whether repair tools introduce false changes or false improvements when
no mutation is present.

## Purpose

Negative controls copy reference FSMs and oracle suites from the frozen
`v0.2.0-analysis` cohort without injecting faults. They measure:

- false repair rate (spurious patches or regressions)
- regression rate
- mean ΔBPR
- number of tool runs that modify correct FSMs

Localization is **not applicable** and is skipped for `no_fault` cases.

## Important scope note

| Aspect | v0.2.0-analysis (Zenodo) | Negative controls |
|--------|--------------------------|-------------------|
| Frozen release | Yes | No (local pilot) |
| Injected faults | Yes | **No** (`mutation_operator=no_fault`) |
| Use in RQ2/C1 headline metrics | Yes | **No** — separate construct-validity check |

Do not merge negative controls into `data/fsmrepairbench_1k/` or re-point existing campaign manifests.

## Case layout

Each case directory contains:

| File | Role |
|------|------|
| `reference_fsm.json` | Correct reference machine |
| `faulty_fsm.json` | Identical copy of reference |
| `oracle_suite.json` | Copied from source v0.2.0-analysis case |
| `bug_metadata.json` | `mutation_operator=no_fault`, `is_negative_control=true` |
| `case_metadata.json` | Updated index metadata with BPR=1.0, `bpr_delta=0` |
| `source_case_id.txt` | Provenance link to source case |

Oracle generation policy matches v0.2.0-analysis because suites are **copied**, not regenerated.

## Run

```bash
fsmrepairbench run-negative-control-campaign \
  --source-dataset data/fsmrepairbench_1k \
  --source-cohort data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --dataset-dir data/fsmrepairbench_negative_controls \
  --out results/negative_controls \
  --cohort-size 100 \
  --seed 44
```

Reuse an existing built dataset:

```bash
fsmrepairbench run-negative-control-campaign --reuse-dataset
```

## Exports

`results/negative_controls/`:

| File | Description |
|------|-------------|
| `summary.csv` | Overall and per-tool false repair / regression metrics |
| `per_case_results.csv` | Scoring and baseline repair rows per case/tool |
| `report.md` | Narrative summary |
| `manifest.json` | Provenance (`replaces_v0_2_analysis: false`) |
| `tables/table_negative_control_summary.tex` | LaTeX table |

Paper export: `../paper1/results/negative_controls/`

## Tests

```bash
pytest tests/test_negative_control_campaign.py -q
```

## API

```python
from pathlib import Path
from fsmrepairbench.negative_control_campaign import run_negative_control_campaign

result = run_negative_control_campaign(
    Path("data/fsmrepairbench_1k"),
    output_dir=Path("results/negative_controls"),
)
print(result.report_path)
```
