# FSMRepairBench

[![CI](https://img.shields.io/badge/CI-placeholder-lightgrey)](https://github.com/cesar-andress/fsmrepairbench/actions)
[![Docs](https://img.shields.io/badge/docs-auto--generated-lightgrey)](https://github.com/cesar-andress/fsmrepairbench/actions/workflows/docs.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-3776ab?logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Package](https://img.shields.io/badge/package-0.1.0-blue)](pyproject.toml)
[![Release](https://img.shields.io/badge/release-v0.3.0-blue)](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)
[![Dataset](https://img.shields.io/badge/dataset-v0.3.0-green)](https://doi.org/10.5281/zenodo.20602528)
[![DOI](https://zenodo.org/badge/DOI/10.5281/zenodo.20602528.svg)](https://doi.org/10.5281/zenodo.20602528)

**Behavioural finite-state machine repair benchmark — toolkit, generators, and experiment pipeline.**

FSMRepairBench evaluates whether automated methods can restore correct behaviour in
faulty state machines using **oracle-based scoring**, not textual diff against a hidden
reference. The repository ships a working Python implementation: JSON schemas, validation,
seeded mutation, dataset builders, LLM/baseline repair experiments, and governance tooling.

> **Canonical release for the STVR manuscript:**
> **[v0.3.0 — Benchmark Demonstration Release](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)**
> (Zenodo DOI [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528)).
>
> The release archives the frozen thousand-case cohort, construct-labelled demonstration
> exports (repair, localisation, oracle-depth/surface studies, SBFL comparison, coupling),
> reproducibility scripts, and manuscript assets. Headline empirical metrics are unchanged
> from prior frozen exports.
>
> **Package version** `0.1.0` (`pyproject.toml`) is the installable Python semver; it is
> independent of GitHub release labels.
>
> **Historical labels:** `v0.2.0-analysis` and `v0.2.1-stvr-polish` refer to earlier
> packaging of the same frozen cohort and metrics; see [`VERSIONING_POLICY.md`](VERSIONING_POLICY.md).

### Release labels

| Label | Role | Cite / use |
|-------|------|------------|
| **[v0.3.0](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)** | Benchmark demonstration release | **Cite in the STVR paper** (GitHub release + Zenodo DOI `10.5281/zenodo.20602528`) |
| **`v0.2.0-analysis`** | Historical export label on early campaign bundles | Provenance only; superseded by v0.3.0 |
| **`v0.2.1-stvr-polish`** | Historical tooling tag | Provenance only; superseded by v0.3.0 |

---

## Table of contents

- [Project pitch](#project-pitch)
- [Paper release (v0.2.0-analysis)](#paper-release-v020-analysis)
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

## Paper release (v0.3.0)

Empirical campaigns reported in the STVR manuscript use release label **`v0.3.0`**
([GitHub](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0);
Zenodo [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528)).

| Item | Value |
|------|-------|
| **Dataset** | `data/fsmrepairbench_1k/` (1,024 completed builds; **1,000** pinned analysis cases) |
| **Build plan** | `plans/fsmrepairbench_v0_1k_plan.yaml` (plan seed 44) |
| **Cohort manifests** | `analysis_cohort_1k.txt`, `localization_cohort_1k.txt`, `coupling_campaign_250.txt`, `oracle_depth_ablation_200.txt` |
| **Mutation operators** | **19 registered**, **17 realised** in the analysis cohort (`timed_selective_mutation`, `variable_intra_class`: 0 cases) |
| **Frozen exports** | `results/taxonomy_coverage/`, `results/analysis/`, `results/rq3_localization_1k/`, `results/rq4_coupling_250/`, `results/baseline_repair_C1/`, `results/oracle_depth_ablation/` |
| **Reproduction guide** | [`../paper1/CANONICAL_REPRODUCTION.md`](../paper1/CANONICAL_REPRODUCTION.md) (GitHub `v0.3.0`) |
| **Paper mirror** | `../paper1/results/` (LaTeX/PNG copies; see monorepo layout) |

Verify pinned cohort SHA-256 digests:

```bash
python ../paper1/scripts/verify_cohort_manifests.py
```

### Reproduce published campaigns

Run from this directory (`fsmrepairbench/`) with the package installed
(`pip install -e ".[dev,analytics]"`). Skip dataset build if `data/fsmrepairbench_1k/`
is already present (Zenodo download or prior build).

**Validate dataset artefacts**

```bash
fsmrepairbench validate-dataset data/fsmrepairbench_1k
fsmrepairbench validate-fsm data/fsmrepairbench_1k/cases/case_000001/reference_fsm.json
fsmrepairbench validate-oracle data/fsmrepairbench_1k/cases/case_000001/oracle_suite.json
```

**RQ1 — taxonomy coverage**

```bash
fsmrepairbench generate-taxonomy-coverage data/fsmrepairbench_1k \
  --out results/taxonomy_coverage \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt
```

**RQ2 — mutation detectability (v0.2.0-analysis analysis export)**

```bash
fsmrepairbench analyze-benchmark data/fsmrepairbench_1k --out results/analysis
```

**C1 — baseline repair**

```bash
fsmrepairbench run-c1-baseline-repair data/fsmrepairbench_1k \
  --out results/repair_baseline_1k_c1 \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt \
  --tools-dir tools/baselines_c1 \
  --paper-export-dir ../paper1/results/baseline_repair_C1 \
  --workers 4 \
  --skip-multi-seed
```

Canonical commands and SHA-256 digests: [`../paper1/CANONICAL_REPRODUCTION.md`](../paper1/CANONICAL_REPRODUCTION.md).

**RQ3 — Ochiai localization**

```bash
fsmrepairbench run-localization-campaign data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/localization_cohort_1k.txt \
  --out results/rq3_localization_1k
fsmrepairbench audit-rq3-localization-localizability data/fsmrepairbench_1k \
  --out results/rq3_localization_1k
python ../paper1/scripts/generate_rq3_localization_outputs.py
```

**RQ4 — higher-order coupling**

```bash
fsmrepairbench run-coupling-campaign data/fsmrepairbench_1k \
  --cohort-file data/fsmrepairbench_1k/coupling_campaign_250.txt \
  --out results/rq4_coupling_250 \
  --subset-dir results/rq4_coupling_subset \
  --seed 44
python ../paper1/scripts/generate_rq4_coupling_outputs.py
```

**C3 — oracle depth ablation**

```bash
fsmrepairbench run-oracle-depth-ablation data/fsmrepairbench_1k \
  --out results/oracle_depth_ablation \
  --cohort-file data/fsmrepairbench_1k/oracle_depth_ablation_200.txt \
  --no-write-cohort
python ../paper1/scripts/generate_oracle_depth_ablation_outputs.py
```

**Campaign partition summary (cross-campaign denominators)**

```bash
fsmrepairbench summarize-campaign-partitions \
  --dataset data/fsmrepairbench_1k \
  --out results/campaign_partitions \
  --paper-export-dir ../paper1/results/campaign_partitions
```

Campaign guides: [docs/README.md](docs/README.md) · Dataset README:
[data/fsmrepairbench_1k/README.md](data/fsmrepairbench_1k/README.md)

### Multi-family extension cohorts (v0.3.x)

Ten-dimensional stratified cohorts covering **five machine families** (`plain_fsm`, `mealy`,
`moore`, `efsm`, `timed_fsm`). These complement—not replace—the frozen Zenodo deposit.

| Track | Release label | Dataset |
|-------|---------------|---------|
| 1k-plan (seed 44) | `v0.3.0-1k-plan-multifamily` | `data/fsmrepairbench_1k_multifamily/` |
| v0.3 external-validity (seed 46) | `v0.3.0-multifamily-cohort` | `data/fsmrepairbench_multifamily_v0_3/` |

```bash
# Build, pin, validate (1k-plan track)
python ../paper1/scripts/build_multifamily_cohorts.py --track 1k-plan
fsmrepairbench validate-multifamily-cohort data/fsmrepairbench_1k_multifamily

# RQ2 analysis on pinned cohort
fsmrepairbench analyze-benchmark data/fsmrepairbench_1k_multifamily \
  --cohort-file data/fsmrepairbench_1k_multifamily/analysis_cohort_1k.txt \
  --out results/analysis_1k_multifamily
```

Full guide: [`../docs/multifamily_cohorts.md`](../docs/multifamily_cohorts.md) · GitHub
[`v0.3.0`](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)

---

## Historical tooling release (v0.2.1-stvr-polish)

GitHub release:
**[v0.2.1-stvr-polish](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.2.1-stvr-polish)**

Historical pre-v0.3.0 tag for reproducibility documentation and submission polish.
Superseded by **`v0.3.0`** for manuscript citation. It **does not** change benchmark cases,
oracle suites, mutation operators, cohort manifests, or headline empirical metrics.

---

## Canonical release (v0.3.0)

GitHub release:
**[v0.3.0](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)**
(*FSMRepairBench v0.3.0 — Benchmark Demonstration Release*)

Clone or check out **`v0.3.0`** for the STVR manuscript bundle; cite Zenodo
**`10.5281/zenodo.20602528`** for dataset bytes and headline metrics.

---

## Current capabilities

The following is **implemented and covered by tests** in this repository:

| Area | What works today |
|------|------------------|
| **Core model** | Pydantic FSM, oracle, bug metadata, patch, and score schemas |
| **Validation** | `validate-fsm`, `validate-oracle`, semantic FSM checks |
| **Scoring** | Oracle execution, BPR, repair result aggregation |
| **Generation** | Synthetic FSMs, oracle suites, requirements, ambiguity injection |
| **Fault injection** | **19** registered mutation operators (**17** realised in `v0.2.0-analysis`); seeded metadata |
| **Paper campaigns** | RQ1 taxonomy, RQ2 analysis, RQ3 localization, RQ4 coupling, C1 baselines, C3 oracle depth |
| **Frozen exports** | CSV/LaTeX/PNG + `manifest.json` per campaign; Zenodo DOI on manifests |
| **Datasets** | Mass build (`build-dataset`), stratified build from YAML plans, feature matrix |
| **Experiments** | Parallel executor, LLM backends (Ollama, vLLM, OpenAI-compat), baselines |
| **Analytics** | Difficulty calibration, coverage/gap analysis, quality & novelty reports |
| **Governance** | Schema versioning, migration, evolution diff, release manifests, freeze |
| **Artifacts** | Paper-style bundles with `reproduce` command |
| **Docs** | Technical specs under `docs/`, auto-generated API/CLI/schema reference |

Experimental **v0.3** pilots (multi-family, negative controls, depth-forced ablation) ship
in the repository but are **not** part of the Zenodo `v0.2.0-analysis` deposit. Future work
includes public leaderboard tracks and held-out evaluation splits beyond the frozen paper cohort.

---

## Installation

**Requirements:** Python 3.11+ (3.12 recommended). Use a project virtual environment.

```bash
git clone https://github.com/cesar-andress/fsmrepairbench.git
cd fsmrepairbench/fsmrepairbench
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
| **Analysis** | `analyze-benchmark`, `analyze-multifamily-cohort`, `validate-multifamily-cohort`, `generate-taxonomy-coverage`, `run-localization-campaign`, `run-coupling-campaign`, `run-oracle-depth-ablation`, `summarize-campaign-partitions`, `estimate-difficulty`, `calibrate-difficulty`, `benchmark-report`, `coverage-optimizer`, `detect-gaps`, `analyze-novelty`, `mine-failure-patterns` |
| **Paper repair baselines** | `run-tools`, `export-c1-baseline-repair`, `run-c1-baseline-repair`, `write-c1-manifest` |
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

**Nineteen** operators are registered in the mutation catalogue (`MUTATION_OPERATORS` in
`mutators.py` + `mutation_advanced.py`). The **`v0.2.0-analysis`** cohort realises **17**
operators; `timed_selective_mutation` and `variable_intra_class` have zero cases because
build failures excluded them from the stratified 1k export.

Core operators:

`missing_transition`, `wrong_target`, `wrong_source`, `wrong_event`, `wrong_initial_state`,
`duplicate_transition`, `dead_state_intro`, `guard_flip`, `guard_weaken`, `guard_strengthen`,
`action_corruption`, `timeout_corruption`, `delay_corruption`, `nondeterminism_intro`,
`unreachable_state_intro`

Advanced operators:

`guard_inter_class`, `action_full_mutation`, `variable_intra_class`, `timed_selective_mutation`

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
Campaign exports for **`v0.2.0-analysis`** additionally record cohort SHA-256, Zenodo DOI, and
regeneration commands in each `manifest.json`.

```bash
fsmrepairbench reproduce artifacts/icse2027/
fsmrepairbench freeze-release results/ --release-dir releases/frozen_run
python ../paper1/scripts/verify_cohort_manifests.py
```

Bundled example artifacts ship under `artifacts/` (ICSE/EMSE/TSE placeholder tracks).
Details: [docs/reproducibility.md](docs/reproducibility.md) · Policies:
[VERSIONING_POLICY.md](VERSIONING_POLICY.md), [DATASET_POLICY.md](DATASET_POLICY.md) ·
Release audits (monorepo): [../docs/release_gap_report.md](../docs/release_gap_report.md),
[../docs/reproducibility_matrix.md](../docs/reproducibility_matrix.md),
[../docs/zenodo_release_checklist.md](../docs/zenodo_release_checklist.md)
(polish release **[v0.2.1-stvr-polish](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.2.1-stvr-polish)**;
frozen dataset remains Zenodo **`v0.2.0-analysis`**)

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

FSMRepairBench continues to evolve beyond the frozen paper release:

| Phase | Direction |
|-------|-----------|
| **Shipped (v0.2.0-analysis)** | 1k stratified cohort, Zenodo DOI, RQ1–RQ4 + C1 + C3 exports, manifests |
| **Polish (v0.2.1-stvr-polish)** | Public docs, reproducibility matrix, manifest alignment — no new empirical data |
| **Experimental (v0.3.x)** | Multi-family smoke, negative controls, depth-forced ablation — not paper evidence |
| **Next** | Public leaderboard protocol, held-out evaluation split, schema v2.0 scale-up |
| **Later** | Timed oracle execution, curated industrial cases, multi-oracle consensus |

Full roadmap: [docs/roadmap.md](docs/roadmap.md) · Vision:
[docs/FSMREPAIRBENCH_MANIFESTO.md](docs/FSMREPAIRBENCH_MANIFESTO.md)

---

## Documentation

| Document | Description |
|----------|-------------|
| [docs/README.md](docs/README.md) | **Documentation index** (campaigns, specs, release audits) |
| [docs/architecture.md](docs/architecture.md) | System architecture |
| [docs/benchmark_spec.md](docs/benchmark_spec.md) | Goals, scope, limitations |
| [docs/dataset_format.md](docs/dataset_format.md) | On-disk JSON contract |
| [docs/oracle_spec.md](docs/oracle_spec.md) | Oracle execution & BPR |
| [docs/mutation_spec.md](docs/mutation_spec.md) | Mutation operators |
| [docs/metrics.md](docs/metrics.md) | Evaluation metrics |
| [docs/reproducibility.md](docs/reproducibility.md) | Seeds, versioning, freeze |
| [docs/taxonomy_coverage.md](docs/taxonomy_coverage.md) | RQ1 taxonomy coverage campaign |
| [docs/multifamily_cohorts.md](docs/multifamily_cohorts.md) | Multi-family 10D cohorts (package index) |
| [../docs/multifamily_cohorts.md](../docs/multifamily_cohorts.md) | Multi-family cohorts (full guide) |
| [docs/localization_campaign.md](docs/localization_campaign.md) | RQ3 Ochiai localization |
| [docs/coupling_campaign.md](docs/coupling_campaign.md) | RQ4 higher-order coupling |
| [docs/c1_baseline_repair.md](docs/c1_baseline_repair.md) | C1 baseline repair exports |
| [docs/oracle_depth_ablation.md](docs/oracle_depth_ablation.md) | C3 oracle depth ablation |
| [docs/development.md](docs/development.md) | Developer setup |
| [docs/cli.md](docs/cli.md) | Auto-generated CLI reference |
| [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md) | Normative contract |
| [data/fsmrepairbench_1k/README.md](data/fsmrepairbench_1k/README.md) | Frozen 1k dataset & cohort pins |

---

## Citation

If you use the **empirical dataset, demonstration exports, or paper metrics**, cite
**`v0.3.0`** and Zenodo DOI **`10.5281/zenodo.20602528`**. If you use the **software
toolchain**, cite the GitHub repository at tag **`v0.3.0`**:

```bibtex
@misc{fsmrepairbench2026_v030,
  title        = {{FSMRepairBench v0.3.0: Benchmark Demonstration Release}},
  author       = {Andr{\'e}s, C{\'e}sar},
  year         = {2026},
  howpublished = {\url{https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0}},
  doi          = {10.5281/zenodo.20602528},
  note         = {Version v0.3.0}
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
