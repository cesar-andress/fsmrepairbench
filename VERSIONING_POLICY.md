# FSMRepairBench versioning policy

This policy defines how benchmark schema versions, evolution releases, migrations,
deprecations, and metadata evolve over time.

See also:

- [BENCHMARK_SPEC.md](BENCHMARK_SPEC.md)
- [DATASET_POLICY.md](DATASET_POLICY.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

## Version layers

FSMRepairBench uses **three** complementary version axes:

| Layer | Examples | Meaning |
|-------|----------|---------|
| **Schema version** | `v0.1`, `v1.0`, `v1.1`, `v2.0` | On-disk JSON contract |
| **Evolution release** | `v0`, `v1`, `v2` | Major benchmark generation era |
| **Paper / GitHub release label** | `v0.3.0` | Canonical benchmark demonstration release (STVR manuscript) |
| **Historical Zenodo campaign label** | `v0.2.0-analysis` | Earlier export metadata on the same frozen cohort |
| **Historical GitHub tooling label** | `v0.2.1-stvr-polish` | Pre-v0.3.0 reproducibility tag |
| **Python package version** | `0.1.0` (`pyproject.toml`) | Installable CLI/library semver |

**Canonical release for the STVR manuscript:**
**[v0.3.0 — Benchmark Demonstration Release](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)**
with Zenodo DOI [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528).

### Release labels (summary)

| Label | Role |
|-------|------|
| **`v0.3.0`** | Benchmark demonstration release — cite in the STVR paper |
| **`v0.2.0-analysis`** | Historical export label — provenance only |
| **`v0.2.1-stvr-polish`** | Historical tooling tag — provenance only |

### v0.3.0 (canonical benchmark demonstration release)

GitHub release:
**[v0.3.0](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.3.0)**
(*FSMRepairBench v0.3.0 — Benchmark Demonstration Release*).

This label identifies:

- Dataset `data/fsmrepairbench_1k/` (1,024 completed builds; **1,000** pinned analysis cases)
- Pinned cohort manifests (`analysis_cohort_1k.txt`, `localization_cohort_1k.txt`,
  `coupling_campaign_250.txt`, `oracle_depth_ablation_200.txt`)
- Frozen demonstration exports under `paper1/results/` and `results/` (RQ1–RQ4, C1, C3,
  oracle-surface sensitivity, SBFL comparison, open-weight repair baseline)
- Reproducibility scripts, manuscript exports, and artifact manifests

Cite **GitHub release `v0.3.0` and Zenodo DOI `10.5281/zenodo.20602528`** for empirical
results and archived demonstration readouts. Cite **package version + git tag** for software
reproducibility.

### v0.2.0-analysis (historical export label)

The label **`v0.2.0-analysis`** appears on early frozen export metadata for the same
 thousand-case cohort. It does **not** supersede **`v0.3.0`** for manuscript citation.

Zenodo deposit [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528) hosts
dataset bytes referenced by all release labels above.

The Python package may remain at **`0.1.0`** while GitHub release labels evolve.
Cite the **Zenodo DOI and v0.3.0 release label** for empirical results;
cite **package version + git tag** for software reproducibility.

### v0.2.1-stvr-polish (historical tooling release)

GitHub release:
**[v0.2.1-stvr-polish](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.2.1-stvr-polish)**

Historical tag for pre-v0.3.0 reproducibility polish. Superseded by **`v0.3.0`** for
manuscript citation. **Does not modify benchmark cases, oracle suites, mutation operators,
campaign cohorts, or reported empirical metrics** relative to the frozen cohort.

### Experimental pilots (not the primary release)

Features under `results/multifamily_v0_3_smoke/`, `results/negative_controls/`,
`results/oracle_depth_ablation_v2/`, and `results/rq4_coupling_250_random_secondary/`
are **experimental** robustness pilots. They:

- Do **not** supersede headline metrics on the primary thousand-case cohort
- May change without a release bump until promoted into a future release label

See [docs/implementation_audit_v0_3.md](docs/implementation_audit_v0_3.md) and
[docs/README.md](docs/README.md).

Mapping (implemented in `benchmark_evolution.py`):

| Evolution release | Schema versions | Dataset ID |
|-------------------|-----------------|------------|
| v0 | v0.1 | `fsmrepairbench_v0` |
| v1 | v1.0, v1.1 | `fsmrepairbench_v1` |
| v2 | v2.0 | `fsmrepairbench_v2` |

## Supported schema versions

Current supported versions (`BenchmarkVersion`):

| Version | Required case files | Notable additions |
|---------|---------------------|-------------------|
| v0.1 | reference, faulty, bug, oracle | Legacy minimal layout |
| v1.0 | + `case_metadata.json` | Difficulty metadata |
| v1.1 | same as v1.0 | `statistics` in dataset metadata |
| v2.0 | + optional `requirements.json` | `schema_version: 2`, requirements |

Default for new builds: **v1.0** (`DEFAULT_BENCHMARK_VERSION`). New publications
should target **v2.0** when requirements are in scope.

## Release policy

### Release types

1. **Schema patch** (v1.0 → v1.1)
   - Additive metadata only
   - No case ID changes
   - Migration optional but recommended

2. **Schema minor within evolution release** (tooling / metadata backfill)
   - Automated via `migrate-benchmark`
   - Must emit `migration_report.json`

3. **Evolution release** (v1 → v2)
   - May add/remove cases with documented diffs
   - Requires `evolution_report.json` when comparing releases
   - New `dataset_id`

### Release artefacts

Every published dataset release must ship:

| Artefact | Purpose |
|----------|---------|
| `release_manifest.json` | Version, case count, required files, compatibility |
| `metadata.json` | Authoritative `benchmark_version` and `dataset_id` |
| `migration_report.json` | Present when migrated from an older schema |

Generate or refresh manifests:

```bash
fsmrepairbench release-manifest DATASET_DIR
```

### Release checklist

- [ ] `benchmark_version` detected correctly
- [ ] `evolution_release` recorded in manifest
- [ ] All case IDs stable and unique
- [ ] Migration or evolution report attached for upgrades
- [ ] Tests pass (`pytest`)
- [ ] Changelog entry documents added/removed/modified cases

## Migration policy

### Supported operations

- **Upgrade** to a newer schema via `migrate-benchmark`
- **Dry-run analysis** via `migrate-benchmark --dry-run`
- **Evolution diff** via `benchmark-evolution compare OLD NEW`

### Unsupported operations

- Downgrading schema versions
- In-place migration without output directory
- Migration that renames case IDs

### Migration reports

`migration_report.json` includes:

- `source_version`, `target_version`
- `source_release`, `target_release`
- `added_cases`, `removed_cases`, `modified_cases`
- Per-case `status` and `changes`

Stable case IDs must be preserved (`stable_case_ids_preserved: true`).

## Deprecation policy

### Schema fields

1. **Active** — documented and written by current builders
2. **Deprecated** — still readable; writers emit replacement fields
3. **Removed** — only after one major evolution release past deprecation notice

Deprecated fields must be listed in release notes and handled by
`ensure_backward_compatible_metadata()` for at least one compatibility release.

### Schema versions

- **v0.1** — deprecated; readable, migratable to v1.0+
- **v1.0** — maintained for compatibility; new datasets should prefer v2.0
- **v1.1** — current v1-line maintenance target
- **v2.0** — current recommended publication target

Sunset timeline for deprecated schema versions is announced in release notes at
least **one major evolution release** in advance.

### CLI commands and modules

Experimental commands may change without a schema bump. Stable commands used in
paper artifacts (`build-dataset`, `migrate-benchmark`, `run-experiment`,
`freeze-release`) follow semver in the Python package and require deprecation
notice in `CONTRIBUTING.md` before removal.

## Metadata schema policy

### General rules

1. **Additive by default** — new optional fields in minor/patch releases
2. **Breaking changes** — require schema version increment and migration path
3. **No silent renames** — use new field names; keep readers accepting old names
4. **Single source of truth** — case JSON over CSV/index derivatives

### Field authority

| Concern | Authoritative file |
|---------|-------------------|
| FSM behaviour | `reference_fsm.json`, `oracle_suite.json` |
| Fault definition | `bug_metadata.json`, `faulty_fsm.json` |
| Case identity | directory name + `case_metadata.case_id` |
| Dataset version | `metadata.json` → `benchmark_version` |
| Requirements | `requirements.json` (v2.0) + transition IDs |

### Schema version integer

`schema_version` in metadata maps to benchmark version:

| benchmark_version | schema_version |
|-------------------|----------------|
| v0.1 | 0 |
| v1.0, v1.1 | 1 |
| v2.0 | 2 |

### Validation

Loaders use Pydantic models in `models.py`. Changes to models require:

1. Updated fixtures in `tests/fixtures/`
2. Version spec update in `VERSION_SPECS`
3. Migration logic in `normalize_case_metadata()` when backfill is needed

## Traceability chain

```
plan YAML (name, version, seed)
    → case_id (stable)
        → case artefacts
            → dataset metadata (benchmark_version)
                → release_manifest.json (evolution_release)
                    → migration_report.json / evolution_report.json
```

Verify trace for a local dataset:

```bash
fsmrepairbench benchmark-evolution trace DATASET_DIR
fsmrepairbench benchmark-version DATASET_DIR
```

## Version numbering for the Python package

The PyPI/package version (`pyproject.toml`, e.g. `0.1.0`) is independent of
benchmark schema versions. Package releases document compatible benchmark schema
versions in release notes.
