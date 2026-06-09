# FSMRepairBench

[![CI](https://img.shields.io/badge/CI-placeholder-lightgrey)](https://github.com/cesar-andress/fsmrepairbench/actions)
[![Docs](https://img.shields.io/badge/docs-auto--generated-lightgrey)](https://github.com/cesar-andress/fsmrepairbench/actions/workflows/docs.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Version](https://img.shields.io/badge/version-0.1.0-blue)](pyproject.toml)

**Behavioural finite-state machine repair benchmark — toolkit, generators, and experiment pipeline.**

FSMRepairBench evaluates whether automated methods can restore correct behaviour in
faulty state machines using **oracle-based scoring**, not textual diff against a hidden
reference. The repository ships a working Python implementation: JSON schemas, validation,
seeded mutation, dataset builders, LLM/baseline repair experiments, and governance tooling.

> **Status:** under active development (v0.1.0). The implementation is substantial and
> tested, but there is **no official frozen public release or peer-reviewed paper yet**.
> APIs, dataset contents, and leaderboard protocols may change before v2.0.

---

## Table of contents

- [Project pitch](#project-pitch)
- [Current capabilities](#current-capabilities)
- [Installation](#installation)
- [Quick start](#quick-start)
- [CLI command overview](#cli-command-overview)
- [Taxonomy-driven dataset generation](#taxonomy-driven-dataset-generation)
- [Literature taxonomy](#literature-taxonomy)
- [Synthetic FSM generation](#synthetic-fsm-generation)
- [Oracle generation](#oracle-generation)
- [Mutation operators](#mutation-operators)
- [Benchmark generation](#benchmark-generation)
- [Artifact reproducibility](#artifact-reproducibility)
- [Tests](#tests)
- [Roadmap](#roadmap)
- [Documentation](#documentation)
- [Citation](#citation)
- [Contributing](#contributing)

---

## Project pitch

Controllers, protocols, and embedded systems are often modelled as **finite-state
machines**. Repairing those models means fixing **behaviour** — which states are reached
under which events — not merely editing JSON or diagram syntax.

Most repair benchmarks instead target **source code** (Defects4J, SWE-Bench, HumanEval) or
**smart contracts** (SmartBugs). FSMRepairBench targets **explicit behavioural FSMs** with:

- a published **oracle suite** as the correctness criterion;
- **controlled, seeded faults** with documented mutation metadata;
- a **ten-dimensional taxonomy** for stratified generation and reporting;
- a reproducible toolchain from dataset build through experiment freeze.

Primary metric: **Behavioural Pass Rate (BPR)** — fraction of oracle steps passed by a
candidate FSM. See [docs/oracle_spec.md](docs/oracle_spec.md).

---

## Current capabilities

The following is **implemented and covered by tests** in this repository:

| Area | What works today |
|------|------------------|
| **Core model** | Pydantic FSM, oracle, bug metadata, patch, and score schemas |
| **Validation** | `validate-fsm`, `validate-oracle`, semantic FSM checks |
| **Scoring** | Oracle execution, BPR, repair result aggregation |
| **Generation** | Synthetic FSMs, oracle suites, requirements, ambiguity injection |
| **Fault injection** | 15 seeded mutation operators with reproducible metadata |
| **Datasets** | Mass build (`build-dataset`), stratified build from YAML plans, feature matrix |
| **Experiments** | Parallel executor, LLM backends (Ollama, vLLM, OpenAI-compat), baselines |
| **Analytics** | Difficulty calibration, coverage/gap analysis, quality & novelty reports |
| **Governance** | Schema versioning, migration, evolution diff, release manifests, freeze |
| **Artifacts** | Paper-style bundles with `reproduce` command |
| **Docs** | Technical specs under `docs/`, auto-generated API/CLI/schema reference |

Not yet available as a **published benchmark product**: frozen leaderboard track, held-out
evaluation split, Zenodo DOI, or community-maintained reference dataset at scale.

---

## Installation

**Requirements:** Python 3.11+ (3.12 recommended). Use a project virtual environment.

```bash
git clone https://github.com/ORG/FSMRepairBench.git
cd FSMRepairBench
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[dev,analytics]"
```

| Extra | Command | Purpose |
|-------|---------|---------|
| Core | `pip install -e .` | Validation, scoring, mutation, dataset build (no matplotlib) |
| `analytics` | `pip install -e ".[analytics]"` | Diversity plots (`benchmark-report`) |
| `dev` | `pip install -e ".[dev]"` | pytest, ruff, mypy |

Setup troubleshooting: [docs/development.md](docs/development.md)

---

## Quick start

```bash
# Validate fixtures
fsmrepairbench validate-fsm tests/fixtures/valid_fsm.json
fsmrepairbench validate-oracle tests/fixtures/valid_oracle.json

# Score reference FSM against oracle (BPR = 1.0 expected)
fsmrepairbench score tests/fixtures/valid_fsm.json tests/fixtures/valid_oracle.json

# Export machine-readable score results
fsmrepairbench score examples/demo_faulty.json examples/demo_oracle.json \
  --out-json results/demo_score.json \
  --out-csv results/demo_score.csv \
  --quiet

# SOTA analysis: specification coverage, coupling, constrained inputs
fsmrepairbench coverage tests/fixtures/simple_fsm.json tests/fixtures/simple_oracle.json \
  --out results/coverage.json
fsmrepairbench spec-coverage tests/fixtures/simple_fsm.json tests/fixtures/simple_oracle.json \
  --out-json results/spec_coverage.json --out-csv results/spec_coverage.csv --quiet
fsmrepairbench generate-constrained-inputs tests/fixtures/simple_fsm.json \
  --out-json results/constrained_inputs.json --out-csv results/constrained_inputs.csv --quiet
fsmrepairbench flatten-hierarchical tests/fixtures/hierarchical_web.json --out results/flat_web.json

# Generate benchmark cases from reference FSMs (skips non-FSM JSON in input dir)
fsmrepairbench generate-benchmark tests/fixtures data/generated_smoke \
  --bugs-per-fsm 3 --seed 42

# Build a synthetic dataset
fsmrepairbench build-dataset --size 10 --seed 42 --output data/my_benchmark
fsmrepairbench validate-dataset data/my_benchmark

# Stratified build from a plan
fsmrepairbench build-stratified-dataset plans/fsmrepairbench_v0_10k_plan.yaml data/stratified
```

Repair and experiment workflow:

```bash
fsmrepairbench baseline-repair faulty.json oracle.json --out patch.json
fsmrepairbench apply-patch faulty.json patch.json --out repaired.json
fsmrepairbench run-experiment configs/experiment.yaml
fsmrepairbench leaderboard results/
fsmrepairbench freeze-release results/ --release-dir releases/run_001
```

---

## CLI command overview

Entry point: `fsmrepairbench`. Full reference: [docs/cli.md](docs/cli.md) (auto-generated).

| Group | Commands |
|-------|----------|
| **Validation** | `validate-fsm`, `validate-oracle`, `validate-dataset` |
| **Scoring & repair** | `score`, `mutate`, `apply-patch`, `baseline-repair`, `llm-repair` |
| **FSM / oracle tools** | `generate-fsm`, `generate-oracles`, `generate-requirements`, `inject-ambiguity` |
| **Dataset build** | `build-dataset`, `build-stratified-dataset`, `generate-benchmark` |
| **Analysis** | `estimate-difficulty`, `calibrate-difficulty`, `benchmark-report`, `coverage-optimizer`, `detect-gaps`, `analyze-novelty`, `mine-failure-patterns` |
| **Filtering** | `filter-cases`, `subset-overlap` |
| **Experiments & release** | `run-experiment`, `leaderboard`, `freeze-release`, `export-hf`, `reproduce` |
| **Versioning** | `benchmark-version`, `migrate-benchmark`, `release-manifest`, `benchmark-evolution compare`, `benchmark-evolution trace` |
| **Literature** | `literature-index` |

Core commands (`validate-fsm`, `validate-oracle`, `score`, `mutate`, `generate-fsm`,
`generate-oracles`, `generate-benchmark`, `build-dataset`) do **not** require the
`analytics` extra.

---

## Taxonomy-driven dataset generation

FSMRepairBench classifies cases along **ten dimensions** for stratified generation,
filtering, and slice-aware evaluation:

`machine_type`, `determinism`, `completeness`, `arity_class`, `size_class`,
`guard_complexity`, `time_features`, `graph_structure`, `oracle_depth`, `bug_type`

Stratified builds consume a YAML **plan** (`plans/`) declaring cells and counts. Output
includes `cases/`, `feature_matrix.csv`, and taxonomy-aligned metadata.

```bash
fsmrepairbench build-stratified-dataset plans/fsmrepairbench_v0_10k_plan.yaml OUTPUT_DIR
fsmrepairbench filter-cases OUTPUT_DIR --machine-type efsm --out subset.csv
fsmrepairbench detect-gaps OUTPUT_DIR
```

Reference: [docs/taxonomy.md](docs/taxonomy.md) · Plan format: [plans/README.md](plans/README.md)

---

## Literature taxonomy

A literature-informed taxonomy maps classic FSM families and testing concepts to benchmark
tags. The index is built from `data/literature/literature_taxonomy.yaml` and supports
grounding stratification choices in published automata and model-based testing literature.

```bash
fsmrepairbench literature-index --out data/literature/index.json
```

See [docs/literature/README.md](docs/literature/README.md) and
[data/literature/literature_taxonomy.yaml](data/literature/literature_taxonomy.yaml).

---

## Synthetic FSM generation

The synthetic factory generates parameterised FSMs with configurable size, branching,
determinism, and complexity presets (`small` → `very_large`). Used by mass and stratified
builders with deterministic seeds.

```bash
fsmrepairbench generate-fsm --out fsm.json --complexity medium --seed 42
fsmrepairbench build-dataset --size 100 --seed 42 --output data/benchmark_v1
```

Machine families supported in the taxonomy include plain FSM, Mealy, Moore, EFSM, and
timed variants (practical subset — see [docs/benchmark_spec.md](docs/benchmark_spec.md)).

---

## Oracle generation

Oracle suites are generated from reference FSMs via bounded scenario walks. Depth presets
control scenario length and coverage ambition:

| Depth | Max steps (approx.) |
|-------|---------------------|
| `shallow` | 5 |
| `medium` | 12 |
| `deep` | 25 |
| `exhaustive_like` | 40 |

```bash
fsmrepairbench generate-oracles reference_fsm.json --out oracle_suite.json --depth medium
```

Reference FSMs are validated to achieve BPR = 1.0 on generated suites before mutation.
Semantics: [docs/oracle_spec.md](docs/oracle_spec.md)

---

## Mutation operators

Fifteen **seeded** operators inject controlled faults with documented `bug_metadata.json`:

`missing_transition`, `wrong_target`, `wrong_source`, `wrong_event`, `wrong_initial_state`,
`duplicate_transition`, `dead_state_intro`, `guard_flip`, `guard_weaken`, `guard_strengthen`,
`action_corruption`, `timeout_corruption`, `delay_corruption`, `nondeterminism_intro`,
`unreachable_state_intro`

```bash
fsmrepairbench mutate reference.json --operator missing_transition --seed 42 \
  --out faulty.json --meta bug_metadata.json
```

Full fault models: [docs/mutation_spec.md](docs/mutation_spec.md)

---

## Benchmark generation

Build repair cases from a directory of **reference FSM JSON files**. Non-FSM files
(oracle suites, invalid JSON) are discovered and **skipped** automatically.

```
INPUT_DIR/
├── reference_fsm.json      # loaded
├── oracles/                # optional oracle suites keyed by fsm_id
│   └── reference_oracle.json
└── other.json              # skipped if not a valid FSM
```

```bash
fsmrepairbench generate-benchmark INPUT_DIR OUTPUT_DIR --bugs-per-fsm 10 --seed 123
```

Each case under `OUTPUT_DIR/cases/case_NNNNNN/` contains `reference_fsm.json`,
`faulty_fsm.json`, `bug_metadata.json`, and optionally `oracle_suite.json`, plus
`summary.csv`.

---

## Artifact reproducibility

Paper-style artifact bundles pin dataset seeds, experiment configs, prompts, and models.
The `reproduce` command rebuilds datasets (when configured), runs experiments, and can
freeze results with SHA-256 checksums.

```bash
fsmrepairbench reproduce artifacts/icse2027/
fsmrepairbench freeze-release results/ --release-dir releases/frozen_run
```

Bundled example artifacts ship under `artifacts/` (ICSE/EMSE/TSE placeholder tracks).
Details: [docs/reproducibility.md](docs/reproducibility.md) · Policies:
[VERSIONING_POLICY.md](VERSIONING_POLICY.md), [DATASET_POLICY.md](DATASET_POLICY.md)

---

## Tests

```bash
pytest
```

The suite covers validation, scoring, mutation, generation, stratified builds,
experiments, leaderboard, versioning, quality/novelty analysis, and CLI smoke tests.
Shared helpers live in `tests/helpers.py`.

For development:

```bash
pip install -e ".[dev,analytics]"
ruff check src tests
python scripts/update_docs.py   # refresh docs/api.md, docs/cli.md, docs/schemas.md
```

---

## Roadmap

FSMRepairBench is evolving toward a community-maintained reference benchmark. Highlights:

| Phase | Direction |
|-------|-----------|
| **Implemented** | Core toolchain, 15 mutators, stratified builder, LLM experiments, governance, docs |
| **Next** | Frozen v2.0 release, public leaderboard protocol, held-out evaluation split |
| **Later** | Timed oracle execution, curated industrial cases, multi-oracle consensus |

Full roadmap: [docs/roadmap.md](docs/roadmap.md) · Vision:
[docs/FSMREPAIRBENCH_MANIFESTO.md](docs/FSMREPAIRBENCH_MANIFESTO.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/architecture.md](docs/architecture.md) | System architecture |
| [docs/benchmark_spec.md](docs/benchmark_spec.md) | Goals, scope, limitations |
| [docs/dataset_format.md](docs/dataset_format.md) | On-disk JSON contract |
| [docs/oracle_spec.md](docs/oracle_spec.md) | Oracle execution & BPR |
| [docs/mutation_spec.md](docs/mutation_spec.md) | Mutation operators |
| [docs/metrics.md](docs/metrics.md) | Evaluation metrics |
| [docs/reproducibility.md](docs/reproducibility.md) | Seeds, versioning, freeze |
| [docs/c1_baseline_repair.md](docs/c1_baseline_repair.md) | C1 campaign manifests and regeneration |
| [docs/development.md](docs/development.md) | Developer setup |
| [docs/cli.md](docs/cli.md) | Auto-generated CLI reference |
| [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md) | Normative contract |

---

## Citation

If you use this repository in research, please cite the software (paper citation TBD):

```bibtex
@software{fsmrepairbench2026,
  title        = {FSMRepairBench: A Benchmark for Behavioural Finite-State Machine Repair},
  author       = {FSMRepairBench Contributors},
  year         = {2026},
  url          = {https://github.com/cesar-andress/fsmrepairbench},
  version      = {0.1.0},
  note         = {Under active development; not yet a published benchmark release}
}
```

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Before submitting changes:

```bash
pytest -q
ruff check src tests
```

Do not silently edit frozen cases or reuse case IDs for different semantics.

---

## License

MIT License — see [LICENSE](LICENSE).
