# Spectrum-based fault localization

FSMRepairBench ranks suspicious FSM elements using **spectrum-based fault
localization (SBFL)** over oracle execution traces. Spectra are derived from the
same pass/fail traces used by the oracle scorer (`execute_scenario`,
`trace_scenario_transitions`).

## Idea

Each oracle scenario is executed against the (faulty) FSM. For every scenario we
record:

- whether the scenario **passed** or **failed** (from `execute_scenario`)
- which **states**, **transitions**, **guards**, **actions**, and **timeouts**
  were covered along the execution trace

For each FSM element we then count:

- `failed_cover_count` — failing scenarios that covered the element
- `passed_cover_count` — passing scenarios that covered the element

Suspiciousness coefficients rank elements that appear more often in failing
scenarios than in passing ones.

## Supported coefficients

| Method | Formula (e_f = failed cover, e_p = passed cover, n_f/n_p = non-cover counts) |
|--------|--------------------------------------------------------------------------------|
| **Ochiai** | e_f / sqrt((e_f + e_p)(e_f + n_f)) |
| **Tarantula** | (e_f/(e_f+e_p)) / ((e_f/(e_f+e_p)) + (n_f/(n_f+n_p))) |
| **Jaccard** | e_f / (e_f + e_p + n_f) |

Default method: **Ochiai**.

## CLI

```bash
fsmrepairbench localize-fault examples/demo_faulty.json examples/demo_oracle.json \
  --method ochiai \
  --out results/demo_localization.json
```

Options:

- `--method` — `ochiai`, `tarantula`, or `jaccard`
- `--quiet` — print only the top-ranked element

The command requires at least one **failing** oracle scenario on the supplied FSM.

## JSON output

```json
{
  "fsm_id": "parking_gate_001__faulty__wrong_target__42",
  "method": "ochiai",
  "oracle_suite_id": "parking_gate_oracles",
  "ranked_elements": [
    {
      "element_id": "t2",
      "element_type": "transition",
      "failed_cover_count": 2,
      "passed_cover_count": 0,
      "suspiciousness": 1.0
    }
  ]
}
```

## Python API

```python
from fsmrepairbench.fault_localization import localize_fault, write_localization_json

report = localize_fault(faulty_fsm, oracle_suite, method="ochiai")
write_localization_json(Path("localization.json"), report)
```

## Related documents

- [oracle_spec.md](oracle_spec.md) — oracle execution semantics
- [mutation_spec.md](mutation_spec.md) — ground-truth fault sites in `bug_metadata.json`
- [higher_order_mutation.md](higher_order_mutation.md) — coupling analysis
