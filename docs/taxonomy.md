# FSMRepairBench Taxonomy

FSMRepairBench uses an explicit, machine-readable taxonomy so benchmark cases can be generated, filtered, and analysed by structural and semantic features. The taxonomy is inspired by classic automata literature and practical model-based testing practice, but FSMRepairBench intentionally implements a **practical subset** rather than every formalism in full theoretical detail.

## Machine families

| Tag | Meaning |
|-----|---------|
| `plain_fsm` | Classic Moore/Mealy-style transition system without extensions |
| `mealy` | Transitions may carry an `output` field (Mealy-style) |
| `moore` | States may carry a `state_output` field (Moore-style) |
| `efsm` | Extended FSM with a `variables` dictionary and guard expressions |
| `timed_fsm` | Transitions may include `timeout` and/or `delay` fields |
| `timed_efsm` | EFSM plus timed fields |

Related formal families such as interface automata and register automata share guarded transitions and richer state spaces, but are not fully modelled here.

## Determinism and completeness

- **Deterministic** machines do not expose multiple transitions with the same `(source, event, guard)` key.
- **Nondeterministic** machines may expose multiple matching transitions for the same input context.
- **Complete** machines provide at least one transition for every reachable `(state, event)` pair.
- **Partial** machines omit some transitions from reachable states.

These notions follow standard treatments of deterministic vs nondeterministic automata and complete vs partial transition systems.

## Arity, size, and guards

- **Arity class** summarises branching (`avg_out_degree`, `max_out_degree`).
- **Size class** summarises reachable state count.
- **Guard complexity** distinguishes absent guards, simple predicates, compound boolean expressions, and nested expressions.

Extended FSMs in the literature often attach guards to transitions; FSMRepairBench stores guards as optional strings on transitions.

## Timed features

Timed automata and timed FSMs extend transitions with timing constraints. FSMRepairBench tags cases with:

- `timeout`
- `timed_guard`
- `output_delay`
- `timed_guard_and_timeout`

These are inferred from optional `timeout`, `delay`, and time-like guard strings.

## Graph structure

Graph tags summarise coarse topology:

- `acyclic`, `cyclic`, `strongly_connected`
- `sparse`, `dense`
- `hub_and_spoke`, `layered`

Tags are heuristic and may co-occur (for example, a graph can be cyclic and dense).

## Oracle depth

Oracle suites are tagged by scenario depth:

- `shallow`, `medium`, `deep`, `exhaustive_like`

These correspond to generation limits on oracle path length and coverage ambition.

## Bug types

Bug types align with mutation operators used to construct faulty FSMs, including structural edits (missing/wrong transitions), guard edits, timed-field corruption, and introduced nondeterminism or unreachable states.

## Practical scope

FSMRepairBench does **not** claim exhaustive coverage of every FSM variant in the literature. The taxonomy is designed for reproducible stratified generation, filtering, and experiment slicing—not for formal verification of complete automata classes.

## Reproducible subsets

Every generated case stores a `case_features.json` document. Use:

```bash
fsmrepairbench filter-cases DATASET_DIR --determinism deterministic --machine-type efsm --out subset.csv
fsmrepairbench subset-overlap DATASET_DIR --a "determinism=deterministic,machine_type=efsm" --b "arity_class=high,bug_type=wrong_target" --out overlap.json
```

Stratified datasets are declared with YAML/JSON plans and built via:

```bash
fsmrepairbench build-stratified-dataset PLAN_PATH OUTPUT_DIR
```
