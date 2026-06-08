# Higher-order mutation and coupling analysis

FSMRepairBench supports **first-order** and **higher-order** mutants for mutation
testing experiments inspired by the coupling effect literature.

## Definitions

| Term | Meaning |
|------|---------|
| **First-order mutant** | One mutation operator applied once |
| **Higher-order mutant** | Two or more mutation operators applied sequentially |
| **mutation_order** | Number of injected faults (operators applied) |

Extended `BugMetadata` fields:

- `mutation_order`
- `component_faults` — list of first-order fault records
- `is_higher_order`
- `coupled_to_simple_faults` — optional list of constituent first-order bug IDs

## CLI: higher-order mutation

```bash
fsmrepairbench mutate-higher-order tests/fixtures/valid_fsm.json \
  --operators wrong_target,guard_flip,missing_transition \
  --seed 42 \
  --out faulty.json \
  --meta bug.json
```

Operators are applied **in order** to the evolving FSM. A single operator produces
a first-order mutant with `mutation_order=1`.

## CLI: coupling analysis

```bash
fsmrepairbench coupling-analysis data/my_benchmark \
  --out results/coupling_report.json
```

The report scans complete cases under `DATASET_DIR/cases/` and estimates:

- first-order vs higher-order oracle detection rates
- **coupling_effect_estimate** — among higher-order cases where all constituent
  first-order faults are detected, the fraction where the higher-order fault is
  also detected

## Python API

```python
from fsmrepairbench.higher_order_mutation import (
    analyze_dataset_coupling,
    mutate_higher_order,
)

faulty, metadata = mutate_higher_order(reference, "wrong_target,guard_flip", seed=42)
report = analyze_dataset_coupling(Path("data/my_benchmark"))
```

## Related documents

- [fault_localization.md](fault_localization.md) — spectrum-based suspiciousness ranking
- [mutation_spec.md](mutation_spec.md) — mutation operator catalogue
