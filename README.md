# FSMRepairBench

Benchmark for evaluating LLM-based repair of behavioural finite-state machines (FSMs).

## Current status

This repository contains the **initial implementation skeleton** for FSMRepairBench. The focus is on project structure, JSON schemas, validation, and a minimal CLI — not on full benchmark logic yet.

### Implemented

- **Pydantic models** for FSM definitions, oracle suites, bug metadata, and repair results (`src/fsmrepairbench/models.py`).
- **JSON loading and validation** for FSM and oracle documents (`src/fsmrepairbench/validators.py`).
- **Typer CLI** with two commands:
  - `fsmrepairbench validate-fsm PATH` — validate an FSM JSON file
  - `fsmrepairbench validate-oracle PATH` — validate an oracle suite JSON file
- **Skeleton modules** for future work: `oracle.py`, `mutators.py`, `scorer.py`.
- **Pytest suite** with fixture-based tests under `tests/`.

### Not yet implemented

- FSM simulation and oracle execution
- Bug injection / mutators
- Repair scoring against reference FSMs
- Benchmark dataset packaging and LLM integration

## Requirements

- Python 3.11+

## Installation

```bash
pip install -e .
```

Optional development tools:

```bash
pip install -e ".[dev]"
```

## Usage

Validate an FSM definition:

```bash
fsmrepairbench validate-fsm tests/fixtures/valid_fsm.json
```

Validate an oracle suite:

```bash
fsmrepairbench validate-oracle tests/fixtures/valid_oracle.json
```

## JSON schemas (informal)

### FSM

```json
{
  "name": "example",
  "states": [
    {"id": "s0", "name": "Start", "is_initial": true, "is_final": false}
  ],
  "transitions": [
    {"source": "s0", "target": "s1", "event": "go"}
  ]
}
```

Rules enforced at load time:

- At least one state
- Exactly one initial state (`is_initial: true`)
- Transition `source` and `target` must reference defined state IDs

### Oracle suite

```json
{
  "name": "example_oracle",
  "fsm_name": "example",
  "scenarios": [
    {
      "name": "happy_path",
      "steps": [
        {"event": "go", "expected_state": "s1"}
      ]
    }
  ]
}
```

## Development

Run tests:

```bash
pytest
```

Lint and type-check (with dev dependencies):

```bash
ruff check src tests
mypy src
```

## Project layout

```
src/fsmrepairbench/
  models.py      # Pydantic schemas
  validators.py  # JSON load/validate helpers
  oracle.py      # Oracle helpers (stub)
  mutators.py    # Bug injection (stub)
  scorer.py      # Repair scoring (stub)
  cli.py         # Typer CLI
tests/
  fixtures/      # Sample JSON files
  test_*.py
```
