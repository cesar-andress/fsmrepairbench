# FSM Literature Knowledge Base

FSMRepairBench maintains a machine-readable literature taxonomy that links benchmark families to classical FSM formalisms. The canonical source file is:

```
data/literature/literature_taxonomy.yaml
```

Each entry documents:

| Field | Purpose |
|-------|---------|
| `id` | Stable machine-readable identifier |
| `name` | Human-readable family name |
| `category` | High-level grouping (automata, timed, hierarchical, …) |
| `description` | Short prose summary |
| `formal_definition` | Compact formal characterisation |
| `references` | Key literature citations |
| `features` | Structural tags used for cross-indexing |
| `repair_relevance` | Why the family matters for repair benchmarking |
| `generation_support` | Current FSMRepairBench generation coverage |

## Generation support values

| Value | Meaning |
|-------|---------|
| `full` | Actively generated in stratified benchmark plans |
| `partial` | Approximated or only partially generated |
| `planned` | Documented for future benchmark support |
| `reference_only` | Literature reference without native generation yet |
| `none` | Not targeted for generation |

These values describe the **current toolkit**, not theoretical expressiveness.

## Index the knowledge base

```bash
fsmrepairbench literature-index
fsmrepairbench literature-index --category timed
fsmrepairbench literature-index --id efsm
fsmrepairbench literature-index --json --out data/literature/index.json
```

## Relationship to benchmark taxonomy

The operational benchmark taxonomy lives in `docs/taxonomy.md` and `src/fsmrepairbench/taxonomy.py`. The literature knowledge base provides external grounding: for example, benchmark `machine_type=efsm` corresponds to the literature entry `efsm`, while `interface_automata` is currently reference-only.

Do not overclaim full support for every formalism listed here. FSMRepairBench implements a practical subset suitable for oracle-driven repair experiments.
