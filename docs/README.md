# FSMRepairBench documentation index

Technical specifications, campaign guides, and release audit notes for the
**v0.2.0-analysis** paper release (Zenodo [10.5281/zenodo.20602528](https://doi.org/10.5281/zenodo.20602528)).

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

## Release audit (maintainers)

| Document | Purpose |
|----------|---------|
| [../../docs/release_gap_report.md](../../docs/release_gap_report.md) | STVR implementation gap audit |
| [../../docs/reproducibility_matrix.md](../../docs/reproducibility_matrix.md) | Table/figure → CSV → script traceability |
| [../../docs/zenodo_release_checklist.md](../../docs/zenodo_release_checklist.md) | Pre-Zenodo release checklist |
| [../../docs/coverage_report.md](../../docs/coverage_report.md) | Test coverage of the toolchain |

Paths above are relative to the monorepo root (`~/papers/fsmrepairbench/`). The Python
package git root is this directory (`fsmrepairbench/`).

## v0.3 experimental pilots (not part of Zenodo v0.2.0-analysis)

These modules and exports inform future work; they **do not** replace the frozen
1,000-case paper cohort:

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
