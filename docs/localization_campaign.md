# Ochiai Localization Campaign (RQ3)

Transition-level spectrum-based fault localization using Ochiai suspiciousness on the published 1k localization cohort.

## Cohort

| Item | Value |
|------|-------|
| Default cohort | `data/fsmrepairbench_1k/localization_cohort_1k.txt` ($n=1{,}000$) |
| Ground truth | `changed_transition_id` from `bug_metadata.json` |
| Detectable denominator | Localized cases only (typically $n=495$) |

Skipped cases (negative controls, no-fault, or localization failures) are excluded from top-k and MRR aggregates.

## Metrics

| Metric | Definition |
|--------|------------|
| Top-1 / Top-3 / Top-5 | Fraction of detectable cases where the ground-truth transition appears in the top-$k$ ranked transitions |
| MRR | Mean reciprocal rank over detectable cases |
| Rank distribution | Histogram of ground-truth transition ranks among detectable cases |

## Run

```bash
fsmrepairbench run-localization-campaign data/fsmrepairbench_1k \
  --out results/rq3_localization_1k
```

Explicit cohort:

```bash
fsmrepairbench run-localization-campaign data/fsmrepairbench_1k \
  --out results/rq3_localization_1k \
  --cohort-file data/fsmrepairbench_1k/localization_cohort_1k.txt
```

## Outputs (`results/rq3_localization_1k/`)

| File | Role |
|------|------|
| `per_case_results.csv` | Per-case ranks, top-k hits, reciprocal rank |
| `leaderboard.csv` | Single-row summary for Ochiai (top-k + MRR) |
| `summary.csv` | Flat aggregate metrics with detectable denominator |
| `localization_metrics.csv` | Aggregate metrics plus rank-bucket distribution |
| `confidence_intervals.csv` | Bootstrap CIs for top-k and MRR |
| `report.md` | Narrative report with figures |
| `manifest.json` | Zenodo v0.2.0-analysis freeze metadata |
| `figures/*.png` | Top-k hit rates, rank histograms, operator breakdown |
| `tables/*.tex` | Paper-ready LaTeX tables including `table_leaderboard.tex` |

## Zenodo freeze

`manifest.json` records:

- `release_label`, `campaign_label`, `zenodo_doi`
- `cohort_path`, `cohort_sha256`, `detectable_denominator`
- `metrics`, `output_files`
- `regeneration_commands`, `git_commit_hash`, `generated_at`

## Tests

```bash
pytest tests/test_localization_campaign.py -q
```
