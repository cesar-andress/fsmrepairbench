# Metamorphic testing

FSMRepairBench supports **metamorphic testing** for benchmark cases: given a
source case (reference FSM, faulty FSM, oracle suite), the tool generates
follow-up cases via behaviour-preserving (or refinement) transformations and
checks whether scoring results satisfy expected relations.

## Motivation

Large benchmark datasets should satisfy structural invariants. Metamorphic
relations encode those invariants as **expected score relations** between a
source case and a transformed follow-up case. Violations highlight inconsistent
scoring, oracle generation, or transformation bugs.

## Supported relations

| Relation | Transformation | Expected score relation |
|----------|----------------|-------------------------|
| `state_renaming_invariance` | Rename states consistently in FSM and oracle | `followup_bpr == source_bpr` |
| `transition_order_invariance` | Reverse transition declaration order | `followup_bpr == source_bpr` |
| `unreachable_state_invariance` | Add an unreachable state and self-loop | `followup_bpr == source_bpr` |
| `equivalent_guard_rewriting` | Rewrite guards to equivalent forms in FSM and oracle | `followup_bpr == source_bpr` |
| `timeout_scaling_relation` | Scale timeout/delay metadata by 2× | `followup_bpr == source_bpr` |
| `event_alias_relation` | Rename events consistently in FSM and oracle | `followup_bpr == source_bpr` |
| `deterministic_refinement_relation` | Block oracle-unreachable transitions | `followup_bpr >= source_bpr` |

Each relation defines:

- **Source case** — the original benchmark case directory
- **Transformed case** — follow-up FSM/oracle artefacts under `--out`
- **Expected score relation** — relation between BPR values (and per-scenario pass status)
- **Violation detector** — compares aggregate BPR and scenario-level outcomes

## Generate follow-up cases

```bash
fsmrepairbench generate-metamorphic-cases CASE_DIR --out OUT_DIR
```

Generate only selected relations:

```bash
fsmrepairbench generate-metamorphic-cases CASE_DIR --out OUT_DIR \
  --relations state_renaming_invariance,event_alias_relation
```

### Input layout

`CASE_DIR` must contain at minimum:

- `reference_fsm.json`
- `faulty_fsm.json`
- `oracle_suite.json`

`bug_metadata.json` is optional but copied when present.

### Output layout

```
OUT_DIR/
├── metamorphic_manifest.json
├── state_renaming_invariance/
│   ├── reference_fsm.json
│   ├── faulty_fsm.json
│   ├── oracle_suite.json
│   ├── bug_metadata.json          # when source had one
│   └── metamorphic_metadata.json
└── event_alias_relation/
    └── ...
```

`metamorphic_metadata.json` records the relation id, transform summary, and
reference/faulty BPR values computed during generation.

## Check a metamorphic relation

Score the source and follow-up FSMs (reference or faulty) against their oracle
suites, then compare the exported score JSON files:

```bash
fsmrepairbench score SOURCE_FSM SOURCE_ORACLE --out-json source_score.json
fsmrepairbench score FOLLOWUP_FSM FOLLOWUP_ORACLE --out-json followup_score.json

fsmrepairbench check-metamorphic source_score.json followup_score.json \
  --relation state_renaming_invariance
```

Optional report export:

```bash
fsmrepairbench check-metamorphic source_score.json followup_score.json \
  --relation event_alias_relation \
  --out metamorphic_check.json
```

Exit code `0` when the relation holds; `1` when a violation is detected.

## Python API

```python
from pathlib import Path
from fsmrepairbench.metamorphic import (
    generate_metamorphic_cases,
    check_metamorphic_relation,
)
from fsmrepairbench.scorer import score_oracle_suite, write_score_json

report = generate_metamorphic_cases(Path("cases/case_000001"), Path("meta_out"))

source = score_oracle_suite(reference, oracle)
followup = score_oracle_suite(followup_reference, followup_oracle)
check = check_metamorphic_relation(source, followup, relation="state_renaming_invariance")
assert check.holds
```

## Notes

- `equivalent_guard_rewriting` applies only when known guard aliases exist in the
  source case (for example `ticket_valid` → `ticket_valid && true`).
- `timeout_scaling_relation` is skipped when the source FSM has no timed
  transitions.
- Per-scenario pass/fail status is also checked for equality (or monotonicity
  for refinement relations).
