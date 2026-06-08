# Specification-based coverage

FSMRepairBench computes **specification-based coverage** from an FSM and an oracle
suite. Coverage is derived by tracing oracle scenarios against the FSM and measuring
which structural elements of the specification are exercised.

## Criteria

| Criterion | Description |
|-----------|-------------|
| **State** | Reachable states visited by oracle scenarios |
| **Transition** | Reachable transitions fired by oracle scenarios |
| **Transition pair** | Adjacent transition pairs along executed paths |
| **Transition sequence** | Contiguous transition sequences up to configurable depth |
| **Guard** | Guarded transitions (EFSM) covered by scenarios |
| **Timeout** | Timed transitions with `timeout` fields covered by scenarios |

Denominators use **reachable** states and transitions from the FSM initial state.

## CLI

```bash
fsmrepairbench coverage tests/fixtures/simple_fsm.json tests/fixtures/simple_oracle.json \
  --out results/coverage.json
```

Optional flags:

- `--sequence-depth N` — maximum length for transition-sequence coverage (default: 3)
- `--quiet` — print a short summary instead of detailed output

## JSON output

The report is written as JSON with top-level metadata and a `criteria` object:

```json
{
  "fsm_id": "toggle_001",
  "oracle_suite_id": "toggle_oracles",
  "machine_type": "plain_fsm",
  "sequence_depth": 3,
  "criteria": {
    "state": {"covered": 2, "total": 2, "coverage": 1.0, "covered_items": ["off", "on"]},
    "transition": {"covered": 2, "total": 2, "coverage": 1.0, "covered_items": ["t1", "t2"]}
  }
}
```

## Python API

```python
from fsmrepairbench.coverage import compute_coverage_report, write_coverage_json

report = compute_coverage_report(fsm, suite, sequence_depth=3)
write_coverage_json(Path("coverage.json"), report)
```

The legacy `spec-coverage` CLI command remains available and delegates to the same
implementation via `fsmrepairbench.spec_coverage`.

## Related documents

- [metrics.md](metrics.md) — oracle and taxonomy metrics
- [oracle_spec.md](oracle_spec.md) — oracle execution semantics
