# Contributing to FSMRepairBench

Thank you for helping maintain FSMRepairBench as a long-lived research benchmark.

## Governance documents

Read these before proposing benchmark or schema changes:

| Document | Topic |
|----------|-------|
| [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md) | Case layout, stable IDs, tooling contract |
| [DATASET_POLICY.md](DATASET_POLICY.md) | Dataset construction and immutability rules |
| [VERSIONING_POLICY.md](VERSIONING_POLICY.md) | Releases, migration, deprecation, metadata |

## Development setup

Requirements: **Python 3.11+**

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
mypy src
```

## What to contribute

### Safe without schema review

- Bug fixes in validators, scorers, or CLI
- New analysis commands that emit **derived** artefacts only
- Tests and documentation
- Performance improvements that do not change benchmark semantics

### Requires governance review

- Changes to case JSON schemas or required files
- New taxonomy dimensions or bug types
- Case ID format or assignment logic
- Migration behaviour or version detection
- Removal or renaming of stable CLI commands used in artifacts

Open a discussion describing:

1. Motivation and research impact
2. Schema version bump (if any)
3. Migration/backward compatibility plan
4. Effect on stable case IDs (must be **none** for in-place changes)

## Coding conventions

- Match existing module layout under `src/fsmrepairbench/`
- Use Typer for CLI commands; Rich for user output
- Raise domain-specific errors (`*Error` subclasses of `ValueError` or
  `RuntimeError`)
- Prefer pure functions and dataclasses for report payloads
- Keep CLI modules thin; put logic in dedicated modules

### Module patterns

| Concern | Example module |
|---------|------------------|
| Analysis / reports | `coverage_optimizer.py`, `gap_detection.py` |
| Dataset builders | `dataset_builder.py`, `stratified_builder.py` |
| Versioning | `versioning.py`, `benchmark_evolution.py` |
| Repair experiments | `experiments.py`, `repair_trajectory.py` |

Each new analysis module should include tests in `tests/test_<module>.py`.

## Stable identifiers — contributor rules

**Do not:**

- Reassign published `case_*` IDs
- Change reference/oracle behaviour under an existing case ID
- Reuse requirement IDs (`R1`, …) for different semantics

**Do:**

- Assign new case IDs for new benchmark instances
- Record seeds and plan versions in metadata
- Run `release-manifest` after dataset changes

See [DATASET_POLICY.md](DATASET_POLICY.md).

## Testing requirements

All contributions must pass:

```bash
python3.11 -m pytest -q
```

Add tests when you change:

- Validators or models
- Migration / versioning logic
- Dataset builders
- CLI commands

Use fixtures in `tests/fixtures/` or minimal inline datasets in `tmp_path`.

## Documentation requirements

- User-facing behaviour: update relevant governance doc or `docs/`
- New CLI commands: docstring + example in commit message or PR description
- Schema changes: update [VERSIONING_POLICY.md](VERSIONING_POLICY.md) and
  `VERSION_SPECS` in code

## Commit messages

Use concise, conventional prefixes:

```
feat: add ...
fix: correct ...
docs: update ...
test: add ...
refactor: ...
chore: ...
```

Benchmark governance changes should use `docs:` or `feat:` with a clear
migration note in the body.

## Release and deprecation process

1. Implement code + tests + migration (if needed)
2. Update governance docs
3. Run full test suite
4. For dataset releases: generate `release_manifest.json` and migration/evolution
   reports
5. Announce deprecated fields or commands in release notes

Follow [VERSIONING_POLICY.md](VERSIONING_POLICY.md) for schema bumps.

## Metadata schema changes

Before adding or renaming metadata fields:

1. Confirm the authoritative file (see metadata schema policy)
2. Prefer optional fields first
3. Add normalization in `normalize_case_metadata()` for upgrades
4. Extend `VERSION_SPECS.metadata_fields`
5. Add detection/migration tests in `tests/test_versioning.py`

Breaking renames require a new `benchmark_version`, not an silent edit.

## Paper artifacts

Reproducible paper bundles live under `artifacts/`. When changing commands or
schemas that artifacts depend on:

- Update the affected `artifact.yaml` pins
- Verify with `fsmrepairbench reproduce ARTIFACT_PATH` (or project-specific flow)
- Document compatibility in the artifact README

## Questions

For benchmark semantics (what counts as a valid case, oracle, or repair success),
refer to [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md).

For whether a dataset change is allowed, refer to [DATASET_POLICY.md](DATASET_POLICY.md).

For version numbers and migration, refer to [VERSIONING_POLICY.md](VERSIONING_POLICY.md).
