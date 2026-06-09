# FSMRepairBench dataset policy

This policy governs how benchmark datasets are constructed, published, and
maintained over time.

See also:

- [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md) — structural specification
- [VERSIONING_POLICY.md](VERSIONING_POLICY.md) — versioning and release rules
- [CONTRIBUTING.md](CONTRIBUTING.md) — contribution process

## Principles

1. **Stable case IDs** — once published, a case ID always refers to the same
   benchmark intent.
2. **Behavioural ground truth** — reference FSM + oracle define correctness;
   faulty FSM defines the repair task.
3. **Reproducibility** — seeds, plan versions, and manifests must be recorded.
4. **Traceability** — every release links to predecessor releases and migration
   artefacts.

## Frozen Zenodo release (`v0.2.0-analysis`)

**The empirical dataset and paper metrics remain frozen at
[v0.2.0-analysis](https://doi.org/10.5281/zenodo.20602528) / Zenodo DOI
[10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528).**

The STVR paper release is archived at Zenodo with release label **`v0.2.0-analysis`**.

| Item | Policy |
|------|--------|
| **Canonical dataset** | `data/fsmrepairbench_1k/` |
| **Analysis cohort** | First 1,000 completed cases; pinned in `analysis_cohort_1k.txt` (+ JSON manifest with SHA-256) |
| **Campaign cohorts** | Separate pinned manifests for RQ3, RQ4, and C3 (see dataset README) |
| **Frozen exports** | `results/taxonomy_coverage/`, `results/analysis/`, `results/rq3_localization_1k/`, `results/rq4_coupling_250/`, `results/baseline_repair_C1/`, `results/oracle_depth_ablation/` each ship `manifest.json` recording cohort SHA and DOI |
| **Silent edits** | **Forbidden** — do not in-place edit case JSON, oracle suites, or frozen CSV exports referenced by the manuscript without a new release label and Zenodo version |
| **Regeneration** | Allowed when reproducing from pinned cohorts + documented CLI commands; outputs must match frozen checksums/metrics before replacing paper exports |

Verify cohort integrity:

```bash
python ../paper1/scripts/verify_cohort_manifests.py
```

## GitHub tooling release (`v0.2.1-stvr-polish`)

GitHub release:
**[v0.2.1-stvr-polish](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.2.1-stvr-polish)**

| Item | Policy |
|------|--------|
| **Scope** | Documentation, reproducibility audits, manifest metadata — not new benchmark content |
| **Dataset** | Still **`data/fsmrepairbench_1k`** as frozen by Zenodo **`v0.2.0-analysis`** |
| **Empirical metrics** | Unchanged — **v0.2.1-stvr-polish does not modify benchmark cases, oracle suites, mutation operators, campaign cohorts, or reported empirical metrics** |
| **Citation** | Paper tables/figures → Zenodo DOI **`10.5281/zenodo.20602528`**; tooling → GitHub tag **`v0.2.1-stvr-polish`** |

### v0.3.x pilot datasets (non-authoritative for the paper)

Pilot trees such as `data/fsmrepairbench_multifamily_v0_3_smoke/` and
`data/fsmrepairbench_negative_controls/` are **not** part of the Zenodo
`v0.2.0-analysis` deposit. They must not be substituted for `fsmrepairbench_1k` in
paper tables without an explicit new release.

## Stable ID policy

### Case IDs

- Format: `case_{index:06d}` (six-digit zero-padded index)
- Assigned at dataset build time via `format_case_id(case_number)`
- Directory name must equal case ID
- **Never reassign** a case ID to different FSM content, bug type, or oracle

### FSM and bug IDs

- FSM `id` fields are stable within a case
- `bug_metadata.bug_id` must uniquely identify the fault instance
- Transition-level requirement IDs (`R1`, `R2`, …) must not change meaning after
  publication

### Dataset IDs

| Dataset ID | Evolution release | Default schema |
|------------|-------------------|----------------|
| `fsmrepairbench_v0` | v0 | v0.1 |
| `fsmrepairbench_v1` | v1 | v1.0 / v1.1 |
| `fsmrepairbench_v2` | v2 | v2.0 |

## Allowed changes

### Patch release (same schema minor bump, e.g. v1.0 → v1.1)

- Add optional metadata fields
- Fix documentation or non-semantic typos in descriptions
- Add derived analysis files (`feature_matrix.csv`, analytics plots)
- Backfill difficulty or requirements metadata without altering FSM behaviour

### Migration (same case IDs)

- Add new required sidecar files via `migrate-benchmark`
- Normalize metadata to a newer schema version
- Record changes in `migration_report.json` (`added_cases`, `removed_cases`,
  `modified_cases`)

## Forbidden changes

- Reusing a case ID for different reference/faulty/oracle behaviour
- Silently editing `reference_fsm.json` or `oracle_suite.json` in a frozen release
- Removing cases without documenting them in an evolution report
- Changing mutation operator or bug semantics under an existing case ID
- Publishing a dataset without `benchmark_version` in `metadata.json`

## Dataset construction paths

### Mass generation

```bash
fsmrepairbench build-dataset --size N --seed S --benchmark-version v2.0
```

Produces `cases/`, `metadata.json`, `index.csv`, `release_manifest.json`.

### Stratified generation

```bash
fsmrepairbench build-stratified-dataset PLAN.yaml OUTPUT_DIR
```

Produces taxonomy-aligned cases plus `case_index.csv` and `feature_matrix.csv`.

Plans live under `plans/` and must declare `name`, `version`, and `seed`.

## Quality gates before publication

A dataset is publishable when:

1. All cases pass `validate-fsm` and `validate-oracle`
2. `detect_benchmark_version` matches the intended schema
3. `release_manifest.json` is present and accurate
4. Case count in manifest matches `cases/` directory
5. For stratified sets, `feature_matrix.csv` covers all cases
6. Frozen releases pass `freeze-release` checksum validation

## Deprecation of cases

Cases are deprecated, not deleted silently:

1. Mark deprecated cases in release notes and evolution report
2. Keep case directories read-only for one major evolution release when possible
3. Remove cases only in a new major evolution release (`v1` → `v2`) with
   explicit `removed_cases` entries

Deprecated cases must remain parseable by compatibility loaders until the
documented sunset version.

## Metadata schema policy

### Dataset-level (`metadata.json`)

Required fields depend on schema version (see `VERSION_SPECS` in
`versioning.py`). Every published dataset must include:

- `dataset_id`
- `benchmark_version`
- `seed`
- `cases_dir`

v2.0+ also requires `schema_version`.

### Case-level (`case_metadata.json`)

Required from v1.0 onward. Must include:

- `case_id` matching directory name
- `benchmark_version`
- Difficulty fields (`difficulty_score` or `difficulty` block)

New fields must be **additive** within a major evolution release.

### Index files

- `index.csv` / `case_index.csv` are derived inventories, not authoritative
  over case JSON
- Regenerating index files is allowed if row content remains consistent with
  case artefacts

## Analysis artefacts

Derived files do not change benchmark semantics:

- `coverage_report.json`, `missing_cells.csv`, `gap_fill_plan.yaml`
- `difficulty_calibration.csv`
- `failure_patterns.csv`, `repair_trace.json`

They may be regenerated from canonical case data.

## Long-term archival

Frozen releases should include:

- `release_manifest.json`
- `hashes.csv` (from freeze workflow)
- `environment.json`
- Complete `cases/` tree

Store seeds and plan YAML alongside the dataset for full regeneration audits.
