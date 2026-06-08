# Advanced FSM semantics

FSMRepairBench supports benchmark slices inspired by testing theory for
**nondeterministic**, **probabilistic**, **refusal/quiescence**, **cyclic**, and
**discrete-time** systems.

## Schema extensions

### Transitions

| Field | Purpose |
|-------|---------|
| `probability` | Branch probability for probabilistic machines |
| `is_nondeterministic` | Explicit nondeterminism marker |
| `refusal` | Refusal transition marker |
| `quiescence` | Quiescence/silent-step marker |
| `discrete_time` | Discrete time-step index |

### States

| Field | Purpose |
|-------|---------|
| `refusal` | Refusal-state marker |
| `quiescence` | Quiescent-state marker |

### FSM metadata

| Field | Purpose |
|-------|---------|
| `discrete_time_step` | Global discrete time unit |
| `semantics_mode` | Default oracle semantics mode |
| `cyclic_metadata` | Optional persisted cycle/SCC metadata |

Special refusal/quiescence events are also recognised:
`$refusal`, `$quiescence`, `refusal`, `quiescence`, `delta`, `tau`.

## Structural feature inference

`infer_structural_features(fsm)` returns:

| Feature | Meaning |
|---------|---------|
| `has_nondeterminism` | Ambiguous `(source, event, guard)` choices |
| `has_probabilities` | At least one probabilistic transition |
| `has_cycles` | Positive cycle count in reachable graph |
| `has_refusals` | Refusal/quiescence markers present |
| `has_discrete_time` | Discrete-time step metadata present |
| `cycle_count` | Number of simple cycles |
| `strongly_connected_component_count` | SCC count on reachable subgraph |

These fields are also propagated into taxonomy `CaseFeatures` for stratified
benchmark slicing.

## Oracle semantics modes

| Mode | Intended use |
|------|--------------|
| `deterministic` | Classic deterministic FSMs |
| `nondeterministic_accepting` | Accepting-set oracle steps over ambiguous transitions |
| `probabilistic_threshold` | Probability-threshold oracle steps |
| `refusal_aware` | Refusal and quiescence testing |
| `timed_discrete` | Discrete-time timed transitions |

Set `OracleSuite.semantics_mode` (or `FSM.semantics_mode`) to activate mode-aware
oracle execution in `score_oracle_suite`.

Oracle step extensions:

- `accepting_states` — allowed post-step states under nondeterministic semantics
- `probability_threshold` — cumulative probability cutoff
- `refusal_expected` / `quiescence_expected` — refusal-aware checks
- `discrete_time` — discrete-time step alignment

## CLI

```bash
fsmrepairbench validate-semantics FSM_PATH --mode probabilistic_threshold
```

Optional oracle validation:

```bash
fsmrepairbench validate-semantics FSM_PATH ORACLE.json \
  --mode nondeterministic_accepting \
  --out semantics_report.json
```

Exit code `0` when semantics are valid; `1` otherwise.

## Python API

```python
from fsmrepairbench.semantics import infer_structural_features, validate_semantics

features = infer_structural_features(fsm)
report = validate_semantics(fsm, mode="probabilistic_threshold")
assert report.valid
```

## Taxonomy integration

`compute_case_features()` now exports semantics-oriented flags and
`semantics_features` tags (`nondeterminism`, `probability`, `refusal`,
`quiescence`, `discrete_time`, `cycles`) for stratified dataset planning.

Machine types `probabilistic_fsm` and `nondeterministic_fsm` are inferred when
corresponding structural features are present.
