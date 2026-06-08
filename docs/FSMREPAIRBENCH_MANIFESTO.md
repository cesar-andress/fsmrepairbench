# FSMRepairBench Manifesto

A scientific vision for a long-lived benchmark on LLM-assisted repair of
behavioural finite-state machines.

**Status:** living document  
**Audience:** researchers, benchmark maintainers, artifact reviewers, community contributors  
**Companion docs:** [BENCHMARK_SPEC.md](../BENCHMARK_SPEC.md),
[DATASET_POLICY.md](../DATASET_POLICY.md),
[VERSIONING_POLICY.md](../VERSIONING_POLICY.md),
[CONTRIBUTING.md](../CONTRIBUTING.md)

---

## 1. Why FSMRepairBench exists

Software systems are increasingly specified and implemented as **stateful
behavioural models**: controllers, protocol handlers, UI flows, embedded
supervisors, and generated state machines from requirements or low-code tools.
When these models are wrong, failures are often **semantic** rather than
syntactic: the diagram parses, the code compiles, but the machine accepts the
wrong event sequence or enters an illegal state.

Large language models (LLMs) are now used to edit models, generate code from
specifications, and propose patches from natural language. Yet the research
community lacks a **shared, behavioural, reproducible benchmark** for asking:

> Can an automated method repair a faulty state machine so that it satisfies an
> independent behavioural oracle?

FSMRepairBench exists to answer that question with:

- Explicit **reference** and **faulty** machines
- Machine-executable **oracle suites** (not hidden human judgment)
- **Stable case IDs** and versioned datasets for longitudinal comparison
- **Stratified taxonomies** that expose where methods succeed or fail

We build for the decade, not for a single paper demo.

---

## 2. What scientific gap it addresses

Existing repair and code-generation benchmarks measure adjacent but different
skills:

| Gap | What is missing today | What FSMRepairBench provides |
|-----|------------------------|------------------------------|
| **Behaviour over syntax** | Many benchmarks score text match or test pass on general code | Scores **behavioural pass rate (BPR)** on oracle execution over FSM states |
| **Model-level faults** | Bug benchmarks inject line-level defects in programs | Injects **structural FSM faults**: wrong/missing transitions, guards, timing, nondeterminism |
| **Explicit oracles** | Hidden tests or proprietary evaluation harnesses | Published **oracle suites** per case, inspectable and replayable |
| **Stateful repair** | Single-function patches dominate | Repairs must preserve **reachability, event ordering, and guards** |
| **Stratified analysis** | Aggregate leaderboard scores hide failure modes | Taxonomy-driven **slicing** by machine type, bug class, oracle depth, difficulty |
| **Requirements-to-model loop** | NL benchmarks rarely link text to executable models | Optional **requirements** artefacts and ambiguity injection for NL–FSM studies |

FSMRepairBench does not replace program-repair benchmarks. It fills the gap
between **formal models of behaviour** and **modern generative AI evaluation**.

---

## 3. Benchmark philosophy

### Behaviour is the ground truth

Correctness is defined by executing the candidate FSM against published oracle
scenarios. Reference machines guide construction and analysis, but **oracle
passing** is the primary score.

### Controlled faults, not bug archaeology

Cases are built by **seeded mutation operators** with documented metadata. We
prioritise known fault classes and reproducible difficulty over mining ad hoc
bugs from legacy repositories.

### Stratify before you aggregate

Leaderboard averages are insufficient. Every method should be evaluated across
taxonomy dimensions (machine family, determinism, guard complexity, bug type,
oracle depth, difficulty bucket). Coverage optimizers and gap detectors exist
to improve the dataset, not to flatter a single score.

### Models are first-class artefacts

FSMs are JSON documents with stable IDs, not ephemeral prompt context. Repairs
are **patches** with typed operations (`add_transition`, `replace_guard`, …),
 enabling deterministic replay and failure mining.

### Open artefacts, frozen releases

Datasets ship with manifests, hashes, migration reports, and experiment traces
(`repair_trace.json`, `failure_patterns.csv`). A paper result should be
**re-runnable** without private infrastructure.

---

## 4. Taxonomy philosophy

FSMRepairBench adopts a **practical literature-informed taxonomy**, not a claim
of complete formal coverage.

Principles:

1. **Machine-readable tags** — every case exposes features in `case_features.json`
   and `feature_matrix.csv` for filtering and statistical analysis.
2. **Literature grounding** — tags relate to classical families (DFA, NFA, Mealy,
   Moore, EFSM, timed automata) via `data/literature/literature_taxonomy.yaml`.
3. **Operational semantics over notation** — we tag what the benchmark generator
   and oracle runner actually support, marked as `full`, `partial`, or
   `unsupported` generation support.
4. **Composable dimensions** — machine type, determinism, completeness, arity,
   size, guards, timing, graph structure, oracle depth, and bug type are
   **orthogonal slices**, not a single difficulty label.
5. **Honest scope** — when a formalism is only partially supported, the taxonomy
   says so. Researchers should not confuse benchmark tags with theorem-prover
   expressiveness.

The taxonomy serves three scientific uses:

- **Generation** — stratified dataset plans (`plans/*.yaml`)
- **Evaluation** — fair comparison within slices
- **Diagnosis** — explain *why* a method fails (e.g., guard_flip vs missing_transition)

See [docs/taxonomy.md](taxonomy.md) for tag definitions.

---

## 5. Dataset evolution strategy

Benchmarks that never evolve become obsolete; benchmarks that churn break
science. FSMRepairBench uses a **two-layer version model**:

| Layer | Examples | Purpose |
|-------|----------|---------|
| **Schema version** | v0.1, v1.0, v1.1, v2.0 | JSON on-disk contract |
| **Evolution release** | v0, v1, v2 | Major benchmark era |

Evolution rules:

- **Stable case IDs** (`case_000042`) persist across schema migrations.
- **Additive growth** — new cases and optional metadata in minor releases.
- **Documented removal** — cases removed only in major evolution releases, listed
  in `evolution_report.json` / migration reports (`added_cases`, `removed_cases`,
  `modified_cases`).
- **Gap-driven expansion** — coverage optimizers and gap detection identify
  underrepresented taxonomy cells; generation plans fill them deliberately.
- **Difficulty calibration** — difficulty buckets are recomputed from structural
  and oracle features, not hand-waved.

Tools:

```bash
fsmrepairbench migrate-benchmark SOURCE --target-version v2.0 --output OUT
fsmrepairbench benchmark-evolution compare OLD_DIR NEW_DIR
fsmrepairbench detect-gaps DATASET_DIR
fsmrepairbench calibrate-difficulty DATASET_DIR
```

Target scale: stratified plans toward **10k+ cases** with measurable coverage
metrics, not arbitrary size inflation.

---

## 6. Reproducibility principles

A FSMRepairBench result is reproducible when a third party can:

1. **Identify** the dataset release (`release_manifest.json`, `benchmark_version`)
2. **Load** the same cases by stable ID
3. **Run** the same repair method configuration (model, temperature, iterations)
4. **Score** with the published oracle suites
5. **Verify** outputs against checksums or frozen releases

Concrete commitments:

| Principle | Mechanism |
|-----------|-----------|
| Seeded generation | `seed` in metadata and bug records |
| Frozen releases | `freeze-release`, `hashes.csv`, `environment.json` |
| Experiment configs | YAML experiment files; worker queue with resume |
| Repair trajectories | `repair_trace.json` stores input FSM, prompt, response, patch, score per iteration |
| Failure analysis | `failure_patterns.csv` clusters invalid JSON, wrong patch, regression, oscillation, no-op |
| Paper artifacts | `artifacts/*/artifact.yaml` bundles with pinned versions |
| HuggingFace export | JSONL splits with dataset card for community reuse |

Reproducibility is **non-negotiable** for leaderboard entries and official release
tags.

---

## 7. Benchmark governance

FSMRepairBench is governed as **community infrastructure**, not as a private
lab dataset.

Governance pillars:

1. **Normative specs** — [BENCHMARK_SPEC.md](../BENCHMARK_SPEC.md)
2. **Dataset policy** — immutability of published case semantics
   ([DATASET_POLICY.md](../DATASET_POLICY.md))
3. **Versioning policy** — migration, deprecation, metadata schema
   ([VERSIONING_POLICY.md](../VERSIONING_POLICY.md))
4. **Contribution rules** — [CONTRIBUTING.md](../CONTRIBUTING.md)

Decision hierarchy:

- **Patch release** — additive metadata, tooling, derived analytics
- **Schema minor** — backward-compatible migration with reports
- **Evolution major** — may add/remove cases with traceability

Maintainers enforce:

- No silent edits to frozen cases
- No reuse of case IDs
- Migration paths for deprecated schema versions
- Tests (`pytest`) before merge

Community contributors propose changes through documented review; schema-breaking
changes require explicit migration design.

---

## 8. Threats to validity

Any benchmark claim must acknowledge limitations. Primary threats:

### Construct validity

- **Oracle incompleteness** — passing all published scenarios does not prove
  equivalence to the reference FSM.
- **Mutation realism** — seeded faults may not match industrial defect distributions.
- **Taxonomy heuristics** — graph and guard tags are approximate.

### Internal validity

- **Oracle-generator coupling** — oracles are generated from the same reference
  model used to define ground truth; subtle overfitting to generator artefacts
  is possible.
- **Patch operator bias** — repair methods may exploit the patch DSL rather than
  general model editing.
- **LLM non-determinism** — unless temperature and prompts are fixed, scores vary
  between runs.

### External validity

- **Domain transfer** — results on synthetic/stratified FSMs may not predict
  performance on proprietary SCADE, Simulink, or protocol specs.
- **NL requirements gap** — optional requirement text may not reflect real
  requirements engineering practice.
- **Model scale** — size classes may underrepresent very large industrial state spaces.

### Conclusion validity

- **Leaderboard overfitting** — tuning to public cases without held-out frozen
  releases inflates scores.
- **Slice shopping** — reporting only favourable taxonomy cells.

Mitigations we commit to:

- Held-out or frozen release tracks for official comparison
- Stratified reporting mandatory in leaderboard design
- Trajectory and failure-pattern mining for diagnosing *how* methods fail
- Transparent threat documentation (this section) in papers using the benchmark

---

## 9. Long-term roadmap

FSMRepairBench is intended to evolve over multiple research cycles.

### Near term (current era: v1 → v2)

- [x] Core FSM/oracle validation and mutation operators
- [x] Stratified dataset builder and 10k plan scaffolding
- [x] Versioning, migration, and evolution reports
- [x] Difficulty calibration and gap detection
- [x] Requirement generation and ambiguity injection
- [x] Repair trajectories and failure pattern mining
- [ ] Community frozen release v2.0 with public leaderboard
- [ ] Held-out evaluation split with sealed checksums

### Medium term

- Richer **timed and probabilistic** families where oracles remain executable
- **Industrial case studies** contributed under stable IDs (curated, not scraped)
- **Multi-oracle** consensus scoring and mutation testing of oracles themselves
- Integration with **model-driven engineering** interchange formats (where licensing permits)
- Cross-benchmark protocols linking NL requirements → FSM → repair → re-verification

### Long term

- Standing **community steering** process for evolution releases
- **Perennial artifact track** at major venues (similar to SV-COMP / JAPEX traditions)
- Benchmark variants for **human-in-the-loop** repair and **certified** patch classes
- Open corpus linking FSMRepairBench cases to formal proofs (optional, not required for base score)

Roadmap items are aspirational until shipped with tests, docs, and migration paths.

---

## 10. Positioning relative to other benchmarks

FSMRepairBench is complementary. We compare by **task**, **artefact**, and
**evaluation signal**.

### Defects4J

| | Defects4J | FSMRepairBench |
|---|-----------|----------------|
| **Unit** | Java classes/methods | Finite-state machines |
| **Faults** | Real mined bugs | Controlled mutations |
| **Oracles** | Developer test suites | Published behavioural scenarios |
| **Target methods** | APR tools, LLM patchers | LLM/model repair, synthesis |

*Relation:* Defects4J remains the gold standard for **real-world Java APR**.
FSMRepairBench targets **explicit behavioural models** where state and events
are primary—not line-level Java semantics.

### BugsInPy

| | BugsInPy | FSMRepairBench |
|---|----------|----------------|
| **Language** | Python | Language-agnostic JSON FSMs |
| **Scope** | Real bug/fix pairs | Synthetic/stratified model faults |
| **Evaluation** | Test suite pass | Oracle BPR on state traces |

*Relation:* BugsInPy supports **Python repair** research with authentic bugs.
FSMRepairBench supports **model-based** behaviour repair independent of
implementation language.

### SWE-Bench

| | SWE-Bench | FSMRepairBench |
|---|-----------|----------------|
| **Task** | Resolve GitHub issues in repos | Repair faulty FSM to pass oracles |
| **Context** | Full codebase + CI | Compact machine + oracle suite |
| **Signal** | Real integration tests | Controlled behavioural scenarios |
| **Cost** | Expensive, environment-heavy | Lightweight, replayable JSON |

*Relation:* SWE-Bench measures **software engineering agents** in the wild.
FSMRepairBench isolates **stateful behavioural reasoning** without repository
noise—useful for ablation and controlled comparison.

### HumanEval

| | HumanEval | FSMRepairBench |
|---|-----------|----------------|
| **Task** | Synthesize function from docstring | Repair structured machine |
| **Output** | Code string | Patch over typed FSM operations |
| **Correctness** | Hidden unit tests on functions | Published oracle scenarios |
| **Structure** | Stateless I/O | Stateful transitions, guards, timing |

*Relation:* HumanEval benchmarks **code generation from NL**. FSMRepairBench
benchmarks **behaviour-preserving repair of an existing model** with explicit
state space—closer to controller/protocol design than to single-function synthesis.

### SmartBugs

| | SmartBugs | FSMRepairBench |
|---|-----------|----------------|
| **Domain** | Smart contract vulnerabilities | Finite-state behavioural models |
| **Faults** | Security weakness patterns | Structural/state-machine mutations |
| **Artefact** | Solidity programs | JSON FSMs + oracles |
| **Goal** | Find/exploit/analysis tools | Repair to restore behaviour |

*Relation:* SmartBugs drives **blockchain security** tool comparison.
FSMRepairBench drives **behavioural model repair** for controllers, protocols,
and MDE workflows—not contract vulnerability detection per se.

### Summary positioning statement

> **FSMRepairBench is the behavioural state-machine repair benchmark**: it
> occupies the space between formal models and LLM evaluation, where correctness
> means satisfying observable state-oracle scenarios, not merely producing
> plausible code or passing opaque tests.

---

## Closing commitment

If FSMRepairBench succeeds as a community benchmark, it will be because we
prioritised:

- **Stable science** over flashy leaderboard numbers
- **Transparent faults and oracles** over hidden evaluation
- **Stratified honesty** over aggregate hype
- **Governed evolution** over silent dataset drift

We invite researchers to use FSMRepairBench, challenge its threats to validity,
contribute cases and taxonomies, and hold maintainers to the policies in this
manifesto and the companion governance documents.

**FSMRepairBench is behavioural repair science—in the open, for the long run.**
