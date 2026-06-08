# Synthetic FSM Examples

These files were generated with the synthetic FSM factory for documentation and
smoke testing.

| File | Complexity | Seed | States | Events |
|------|------------|------|--------|--------|
| `synthetic_small.json` | small | 1 | 5 | 3 |
| `synthetic_medium.json` | medium | 1 | 10 | 5 |

Regenerate examples:

```bash
fsmrepairbench generate-fsm --complexity small --seed 1 --out examples/synthetic_small.json
fsmrepairbench generate-fsm --complexity medium --seed 1 --out examples/synthetic_medium.json
```

Custom generation:

```bash
fsmrepairbench generate-fsm --states 20 --events 10 --seed 42 --out fsm.json
```
