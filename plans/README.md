# FSMRepairBench Dataset Plans

This directory contains stratified dataset generation plans for FSMRepairBench. Each plan is a YAML file that declares taxonomy cells (`GenerationCell`) with explicit counts so benchmark construction is reproducible rather than accidental.

## Plans

| File | Cases | Seed | Purpose |
|------|------:|-----:|---------|
| `fsmrepairbench_v0_smoke_plan.yaml` | 100 | 42 | Fast smoke-test stratified build for CI and local validation |
| `fsmrepairbench_v0_10k_plan.yaml` | 10,000 | 42 | Balanced v0 benchmark across machine families, guards, timing, graph topology, and bug types |

## Smoke plan (100 cases)

The smoke plan covers `plain_fsm`, `mealy`, `moore`, `efsm`, and `timed_fsm` with deterministic and nondeterministic cells, complete and partial completeness, low/medium/high arity, and fifteen mutation operators. All cells use the `tiny` size class with `shallow` oracle depth to keep generation fast.

```bash
fsmrepairbench build-stratified-dataset \
  plans/fsmrepairbench_v0_smoke_plan.yaml \
  data/fsmrepairbench_v0_smoke
```

Validate locally:

```bash
python -c "
from pathlib import Path
from fsmrepairbench.generators.stratified_specs import load_dataset_plan, total_planned_cases
plan = load_dataset_plan(Path('plans/fsmrepairbench_v0_smoke_plan.yaml'))
print(plan.name, total_planned_cases(plan), plan.seed)
"
```

Expected output: `fsmrepairbench_v0_smoke 100 42`

## Initial 10k plan

The plan is organised into commented blocks:

1. Plain FSM baseline
2. Mealy / Moore output semantics
3. EFSM and timed families
4. Nondeterministic and partial completeness stress
5. Guard complexity, time features, and graph topology portfolios
6. Arity rebalancing and a full bug-type sweep

See `docs/taxonomy.md` for feature definitions and filtering examples.

## Build the dataset

From the repository root:

```bash
fsmrepairbench build-stratified-dataset \
  plans/fsmrepairbench_v0_10k_plan.yaml \
  data/fsmrepairbench_v0_10k
```

This writes:

```
data/fsmrepairbench_v0_10k/
  cases/case_XXXXXX/
    reference_fsm.json
    faulty_fsm.json
    oracle_suite.json
    bug_metadata.json
    case_features.json
  case_index.csv
  feature_matrix.csv
  dataset_plan.json
  README.md
```

Building all 10,000 cases is CPU-intensive. Use sufficient workers indirectly via repeated runs/resume patterns, or start with a smaller experimental plan derived from the same schema.

## Filter and analyse subsets

After building, slice the dataset by taxonomy features:

```bash
fsmrepairbench filter-cases data/fsmrepairbench_v0_10k \
  --machine-type efsm \
  --determinism deterministic \
  --out subsets/efsm_deterministic.csv

fsmrepairbench subset-overlap data/fsmrepairbench_v0_10k \
  --a "machine_type=efsm,guard_complexity=compound" \
  --b "bug_type=guard_flip,arity_class=high" \
  --out subsets/overlap.json
```

## Validate a plan locally

```bash
python -c "
from pathlib import Path
from fsmrepairbench.generators.stratified_specs import load_dataset_plan, total_planned_cases
plan = load_dataset_plan(Path('plans/fsmrepairbench_v0_10k_plan.yaml'))
print(plan.name, total_planned_cases(plan), plan.seed)
"
```

Expected output: `fsmrepairbench_v0_10k 10000 42`
