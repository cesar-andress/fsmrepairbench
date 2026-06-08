# Spectrum-based fault localization

FSMRepairBench ranks suspicious FSM elements using **spectrum-based fault
localization (SBFL)** over oracle execution traces. The approach is inspired by
spectrum-based fault localization literature and tools such as GZoltar.

## Idea

Each oracle scenario is executed against the (faulty) FSM. For every scenario we
record:

- whether the scenario **passed** or **failed**
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
  --out results/localization.json
```

Options:

- `--method` — `ochiai`, `tarantula`, or `jaccard`
- `--quiet` — print only the top-ranked element

The command requires at least one **failing** oracle scenario on the supplied FSM.

## JSON output

```json
{
  "fsm_id": "parking_gate_001__faulty__wrong_target__42",
  "oracle_suite_id": "parking_gate_oracles",
  "method": "ochiai",
  "total_passed_scenarios": 1,
  "total_failed_scenarios": 2,
  "rankings": [
    {
      "element_type": "transition",
      "element_id": "t2",
      "score": 1.0,
      "failed_cover_count": 2,
      "passed_cover_count": 0
    }
  ]
}
```

The report also includes per-scenario spectra under `scenario_spectra`.

## Python API

```python
from fsmrepairbench.fault_localization import localize_fault, write_localization_json

report = localize_fault(faulty_fsm, oracle_suite, method="ochiai")
write_localization_json(Path("localization.json"), report)
```

## Typical repair workflow

1. Score the faulty FSM against the reference oracle (`fsmrepairbench score`).
2. Run fault localization to rank suspicious transitions/guards/actions.
3. Feed ranked elements to a repair engine or manual inspection.

## Related documents

- [coverage.md](coverage.md) — specification-based coverage criteria
- [oracle_spec.md](oracle_spec.md) — oracle execution semantics
- [metrics.md](metrics.md) — benchmark evaluation metrics
