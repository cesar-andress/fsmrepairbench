# Development guide

This document describes how to set up a reproducible FSMRepairBench development
environment and run the test suite.

## Python version

Use **one Python version** consistently (3.11 or 3.12). Mixing user-wide installs
across versions causes broken dependencies (for example, matplotlib missing
`kiwisolver` on 3.12 while packages were installed for another interpreter).

Recommended: a project-local virtual environment.

## Setup

```bash
cd fsmrepairbench
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,analytics]"
```

### Optional extras

| Extra | Purpose |
|-------|---------|
| `dev` | pytest, ruff, mypy |
| `analytics` | matplotlib + kiwisolver for `benchmark-report` and analytics tests |

Core commands (`validate-fsm`, `validate-oracle`, `score`, `mutate`, `generate-fsm`,
`generate-oracles`, `generate-benchmark`, `build-dataset`, etc.) do **not** require the
`analytics` extra.

Install core only:

```bash
python -m pip install -e .
```

Install analytics when generating diversity plots:

```bash
python -m pip install -e ".[analytics]"
```

## Verify the CLI

```bash
fsmrepairbench validate-fsm tests/fixtures/valid_fsm.json
fsmrepairbench validate-oracle tests/fixtures/valid_oracle.json
fsmrepairbench score tests/fixtures/valid_fsm.json tests/fixtures/valid_oracle.json
fsmrepairbench mutate tests/fixtures/valid_fsm.json --operator wrong_target --seed 42 --out /tmp/faulty.json
fsmrepairbench generate-fsm --out /tmp/fsm.json --complexity medium --seed 42
fsmrepairbench generate-oracles /tmp/fsm.json --out /tmp/oracles.json --depth medium
fsmrepairbench generate-benchmark tests/fixtures /tmp/benchmark --bugs-per-fsm 1 --seed 42
```

These commands must work **without** matplotlib installed (base install only).

Analytics commands require the `analytics` extra:

```bash
fsmrepairbench benchmark-report DATASET_DIR
```

If plotting dependencies are missing, the command fails with an explicit message
referencing `pip install -e '.[analytics]'`.

## Run tests

```bash
pytest
```

Run a focused subset:

```bash
pytest tests/test_experiment_executor.py tests/test_leaderboard.py -q
```

## Lint and type-check

```bash
ruff check src tests
mypy src
```

## Regenerate documentation

After changing CLI commands or Pydantic models:

```bash
python scripts/update_docs.py
```

CI verifies that `docs/api.md`, `docs/cli.md`, and `docs/schemas.md` stay in sync.

## Troubleshooting

### `ModuleNotFoundError: No module named 'kiwisolver'`

Your matplotlib install is incomplete for the active Python interpreter.

```bash
source .venv/bin/activate
python -m pip install -e ".[analytics]"
```

Avoid mixing `pip install --user` with a venv.

### `ModuleNotFoundError: No module named 'tests'`

Run pytest from the repository root with the editable install and dev dependencies:

```bash
python -m pip install -e ".[dev]"
pytest
```

Shared test helpers live in `tests/helpers.py`.

### Wrong `fsmrepairbench` on PATH

If an old editable install shadows the project:

```bash
which fsmrepairbench
python -m pip install -e .
```

Prefer running inside the project `.venv`.

## Related documents

- [README.md](../README.md) — project overview
- [CONTRIBUTING.md](../CONTRIBUTING.md) — contribution workflow
- [reproducibility.md](reproducibility.md) — benchmark reproduction
