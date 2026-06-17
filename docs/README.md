# FSMRepairBench documentation index

Technical specifications, campaign guides, and release audit notes.

**The empirical dataset and paper metrics remain frozen at
[v0.2.0-analysis](https://doi.org/10.5281/zenodo.20602577) / Zenodo DOI
[10.5281/zenodo.20602577](https://doi.org/10.5281/zenodo.20602577).**

**[v0.2.1-stvr-polish](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.2.1-stvr-polish)**
is the latest GitHub release for reproducibility, documentation, manifests, and submission
polish. **v0.2.1-stvr-polish does not modify benchmark cases, oracle suites, mutation
operators, campaign cohorts, or reported empirical metrics.**

## Release labels

| Label | Role | Cite / use |
|-------|------|------------|
| **[v0.2.0-analysis](https://doi.org/10.5281/zenodo.20602577)** | Frozen dataset and empirical campaign release | **Cite this in the STVR paper** |
| **[v0.2.1-stvr-polish](https://github.com/cesar-andress/fsmrepairbench/releases/tag/v0.2.1-stvr-polish)** | Reproducibility and submission-polish release | **Use this for latest tooling and docs** |
| **v0.3.x** | Future pilots and extensions | Not paper evidence |

All reproduction commands below use dataset **`data/fsmrepairbench_1k`**.

## Paper empirical campaigns (STVR)

| Campaign | Doc | CLI | Frozen export |
|----------|-----|-----|---------------|
| RQ1 taxonomy coverage | [taxonomy_coverage.md](taxonomy_coverage.md) | `generate-taxonomy-coverage` | `results/taxonomy_coverage/` |
| RQ2 mutation detectability | [metrics.md](metrics.md) · [reproducibility.md](reproducibility.md) | `analyze-benchmark` | `results/analysis/` |
| RQ3 Ochiai localization | [localization_campaign.md](localization_campaign.md) · [fault_localization.md](fault_localization.md) | `run-localization-campaign` | `results/rq3_localization_1k/` |
| RQ4 higher-order coupling | [coupling_campaign.md](coupling_campaign.md) · [higher_order_mutation.md](higher_order_mutation.md) | `run-coupling-campaign` | `results/rq4_coupling_250/` |
| C1 baseline repair | [c1_baseline_repair.md](c1_baseline_repair.md) | `run-tools` · `export-c1-baseline-repair` | `results/baseline_repair_C1/` |
| C3 oracle depth ablation | [oracle_depth_ablation.md](oracle_depth_ablation.md) | `run-oracle-depth-ablation` | `results/oracle_depth_ablation/` |
| Campaign partitions | *(CLI only)* | `summarize-campaign-partitions` | `results/campaign_partitions/` |

Dataset and cohort pins: [../data/fsmrepairbench_1k/README.md](../data/fsmrepairbench_1k/README.md)

## Multi-family extension cohorts (v0.3.x)

Five machine families (`plain_fsm`, `mealy`, `moore`, `efsm`, `timed_fsm`) on ten-dimensional
stratification plans. **Not part of the Zenodo `v0.2.0-analysis` deposit.**

| Track | Doc | Build CLI | Dataset |
|-------|-----|-----------|---------|
| 1k-plan multi-family | [multifamily_cohorts.md](multifamily_cohorts.md) | `build-stratified-dataset` + `validate-multifamily-cohort` | `data/fsmrepairbench_1k_multifamily/` |
| v0.3 external-validity | [multifamily_cohorts.md](multifamily_cohorts.md) · [multifamily_pilot.md](multifamily_pilot.md) | `analyze-multifamily-cohort` | `data/fsmrepairbench_multifamily_v0_3/` |

Monorepo guide: [`../../docs/multifamily_cohorts.md`](../../docs/multifamily_cohorts.md)

## Release audit (maintainers)

| Document | Purpose |
|----------|---------|
| [../../docs/release_gap_report.md](../../docs/release_gap_report.md) | STVR implementation gap audit |
| [../../docs/reproducibility_matrix.md](../../docs/reproducibility_matrix.md) | Table/figure → CSV → script traceability |
| [../../docs/zenodo_release_checklist.md](../../docs/zenodo_release_checklist.md) | Pre-Zenodo release checklist (`v0.2.0-analysis`) |

Paths above are relative to the monorepo root (`~/papers/fsmrepairbench/`). The Python
package git root is this directory (`fsmrepairbench/`).

## v0.3.x experimental pilots (not part of paper evidence)

These modules and exports inform future work; they **do not** replace the frozen
1,000-case paper cohort or Zenodo **`v0.2.0-analysis`**:

| Pilot | Doc |
|-------|-----|
| Multi-family stratification | [multifamily_pilot.md](multifamily_pilot.md) |
| Negative controls | [negative_controls.md](negative_controls.md) |
| Implementation audit v0.3 | [implementation_audit_v0_3.md](implementation_audit_v0_3.md) |

## Core specifications

| Document | Description |
|----------|-------------|
| [architecture.md](architecture.md) | System architecture |
| [benchmark_spec.md](benchmark_spec.md) | Goals, scope, limitations |
| [dataset_format.md](dataset_format.md) | On-disk JSON contract |
| [oracle_spec.md](oracle_spec.md) | Oracle execution and BPR |
| [mutation_spec.md](mutation_spec.md) | Mutation operators |
| [taxonomy.md](taxonomy.md) | Ten-dimensional stratification |
| [metrics.md](metrics.md) | Evaluation metrics |
| [reproducibility.md](reproducibility.md) | Seeds, versioning, freeze |
| [development.md](development.md) | Developer setup |

## Auto-generated reference

| Document | Description |
|----------|-------------|
| [cli.md](cli.md) | CLI command reference |
| [api.md](api.md) | Python API reference |
| [schemas.md](schemas.md) | JSON schema summary |

Regenerate with `python scripts/update_docs.py` from the repository root.

## Policies

| Document | Description |
|----------|-------------|
| [../VERSIONING_POLICY.md](../VERSIONING_POLICY.md) | Schema vs release vs package versioning |
| [../DATASET_POLICY.md](../DATASET_POLICY.md) | Stable IDs and frozen release rules |
| [../BENCHMARK_SPEC.md](../BENCHMARK_SPEC.md) | Normative benchmark contract |
