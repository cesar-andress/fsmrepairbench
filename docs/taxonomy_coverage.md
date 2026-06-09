# Taxonomy Coverage Report (RQ1)

Empirical audit of FSMRepairBench taxonomy coverage on the published analysis cohort.

## Cohort

| Item | Value |
|------|-------|
| Default cohort | `data/fsmrepairbench_1k/analysis_cohort_1k.txt` ($n=1{,}000$) |
| Feature source | `feature_matrix.csv` when present, else `case_features.json`, else inferred from packaged cases |
| Coverage engine | `build_feature_coverage_report()` in `coverage_optimizer.py` |

## Metrics

| Area | Output |
|------|--------|
| Taxonomy dimensions | `dimension_summary.csv`, `coverage_by_dimension.csv` |
| FSM family | `coverage_by_fsm_family.csv`, `table_fsm_family_coverage.tex` |
| Mutation operator | `coverage_by_mutation_operator.csv`, `table_mutation_operator_coverage.tex` |
| Complexity tier | `coverage_by_complexity_tier.csv`, `table_complexity_tier_coverage.tex` |
| Unique combinations | `unique_combinations_summary.csv`, `coverage_by_unique_combinations.csv`, `feature_space_report.json` |
| Cohort summary | `summary.csv` |

## Run

```bash
fsmrepairbench generate-taxonomy-coverage data/fsmrepairbench_1k \
  --out results/taxonomy_coverage
```

Explicit cohort:

```bash
fsmrepairbench generate-taxonomy-coverage data/fsmrepairbench_1k \
  --out results/taxonomy_coverage \
  --cohort-file data/fsmrepairbench_1k/analysis_cohort_1k.txt
```

## Outputs (`results/taxonomy_coverage/`)

| File | Role |
|------|------|
| `taxonomy_coverage_report.md` | Narrative support statement for taxonomy claims |
| `summary.csv` | Flat cohort metrics |
| `dimension_summary.csv` | Per-dimension observed/universe coverage + entropy |
| `coverage_by_dimension.csv` | Value-level counts per dimension |
| `coverage_by_fsm_family.csv` | FSM family coverage |
| `coverage_by_mutation_operator.csv` | Mutation operator coverage |
| `coverage_by_complexity_tier.csv` | Complexity tier coverage |
| `unique_combinations_summary.csv` | Feature-space saturation metrics |
| `coverage_by_unique_combinations.csv` | Top taxonomy combinations by case count |
| `feature_space_report.json` | Full `build_feature_coverage_report()` payload |
| `feature_matrix_snapshot.csv` | Cohort feature matrix when dataset lacks one |
| `manifest.json` | Zenodo v0.2.0-analysis freeze metadata |
| `figures/*.png` | Dimension, family, operator, tier, and saturation figures |
| `tables/*.tex` | Paper-ready LaTeX tables |

## Zenodo freeze

`manifest.json` records:

- `release_label`, `campaign_label`, `zenodo_doi`
- `cohort_path`, `cohort_sha256`, `case_count`
- `feature_source`, `summary`, `output_files`
- `regeneration_commands`, `git_commit_hash`, `generated_at`

## Tests

```bash
pytest tests/test_taxonomy_coverage.py -q
```
