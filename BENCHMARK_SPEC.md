# FSMRepairBench specification

This document defines the stable contract for FSMRepairBench as a long-lived
behavioural FSM repair benchmark. It is normative for dataset authors, tool
maintainers, and paper artifact reviewers.

Related governance documents:

- [DATASET_POLICY.md](DATASET_POLICY.md) — dataset construction and change rules
- [VERSIONING_POLICY.md](VERSIONING_POLICY.md) — schema versions, releases, deprecation
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution workflow

## Purpose

FSMRepairBench evaluates automated repair of **behavioural finite-state machines**
using:

1. A **reference FSM** (ground truth behaviour)
2. A **faulty FSM** (buggy instance)
3. An **oracle suite** (behavioural test scenarios)
4. Optional **requirements** and **metadata** for stratified analysis

Repair methods are scored by behavioural pass rate (BPR) over oracle execution.

## Stable identifiers

Stable IDs are immutable once assigned to a published benchmark case or release.
They must not be reused for different semantics.

| Identifier | Format | Example | Scope |
|------------|--------|---------|-------|
| Case ID | `case_{index:06d}` | `case_000042` | One benchmark instance |
| FSM ID | string in FSM JSON | `toggle_001` | Reference/faulty machine |
| Bug ID | string in bug metadata | `toggle_001__missing_transition__42` | One injected fault |
| Dataset ID | `fsmrepairbench_v{n}` | `fsmrepairbench_v2` | Major dataset lineage |
| Schema version | `v0.1`, `v1.0`, `v1.1`, `v2.0` | `v2.0` | On-disk JSON contract |
| Evolution release | `v0`, `v1`, `v2` | `v1` | Major benchmark generation |

Rules:

- Case directories must be named exactly by case ID.
- Case IDs are assigned sequentially at build time and preserved across schema
  migrations.
- FSM IDs must match between `reference_fsm.json`, `faulty_fsm.json`, and
  `oracle_suite.fsm_id` when present.
- Requirement IDs (`R1`, `R2`, …) are stable within a case once published.

Detect stable case IDs with:

```bash
fsmrepairbench benchmark-version DATASET_DIR
```

## Benchmark case layout

Each case lives under `cases/<case_id>/`.

### Required files (v1.0+)

| File | Role |
|------|------|
| `reference_fsm.json` | Correct behavioural FSM |
| `faulty_fsm.json` | Buggy FSM to repair |
| `bug_metadata.json` | Mutation operator, seed, description |
| `oracle_suite.json` | Behavioural oracle scenarios |
| `case_metadata.json` | Case-level metadata and difficulty |

### Optional files (v2.0+)

| File | Role |
|------|------|
| `requirements.json` | Requirement IDs linked to transitions |

### Derived dataset files

| File | Role |
|------|------|
| `metadata.json` | Dataset-level version, seed, size |
| `index.csv` / `case_index.csv` | Case inventory |
| `feature_matrix.csv` | Stratified taxonomy features |
| `release_manifest.json` | Release traceability |
| `migration_report.json` | Schema migration summary |

## Core JSON models

Authoritative schemas live in `src/fsmrepairbench/models.py`.

### FSM

- `id`, `name`, `states`, `initial_state`, `events`, `transitions`
- Transitions may include `guard`, `action`, `timeout`, `requirements`
- Reachability from `initial_state` is required for valid benchmark cases

### Oracle suite

- `id`, optional `fsm_id`, `scenarios[]`
- Each scenario has ordered `steps[]` with `event` and `expected_state`

### Repair artefacts

Experiment outputs may include:

- `repair_trace.json` — full repair trajectory per iteration
- `failure_patterns.csv` — mined recurring failure clusters
- Result JSON under `case_id__model.json`

## Taxonomy dimensions

Stratified datasets classify cases along:

- `machine_type`, `determinism`, `completeness`, `arity_class`, `size_class`
- `guard_complexity`, `time_features`, `graph_structure`, `oracle_depth`
- `bug_type`

See `docs/taxonomy.md` and `data/literature/literature_taxonomy.yaml`.

## Tooling contract

The CLI entry point is `fsmrepairbench`. Key maintenance commands:

```bash
# Validation
fsmrepairbench validate-fsm PATH
fsmrepairbench validate-oracle PATH

# Versioning and evolution
fsmrepairbench benchmark-version DATASET_DIR
fsmrepairbench migrate-benchmark SOURCE --target-version v2.0 --output OUT
fsmrepairbench benchmark-evolution trace DATASET_DIR
fsmrepairbench benchmark-evolution compare OLD_DIR NEW_DIR

# Release integrity
fsmrepairbench release-manifest DATASET_DIR
```

## Compatibility

Readers must honour `benchmark_version` and `schema_version` in dataset
metadata. Older datasets remain readable through forward-compatible loaders and
explicit migration (`migrate-benchmark`).

Downgrading schema versions is not supported.

## Change control

Changes to this specification require:

1. A versioned schema bump (see [VERSIONING_POLICY.md](VERSIONING_POLICY.md))
2. Migration support or a documented breaking release
3. Updated tests under `tests/`
4. Entry in release notes / migration report

Semantic changes to an existing case ID are forbidden; publish a new case
instead.
