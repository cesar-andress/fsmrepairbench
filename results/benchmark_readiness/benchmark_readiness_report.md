# FSMRepairBench Benchmark Readiness Assessment

**Release:** `v0.2.0-analysis`  
**Generated:** 2026-06-16T14:30:49.379781+00:00  
**Mean readiness score:** 2.67/5 (early release)  

## Purpose

Transparent maturity audit, not a promotional score. Scores characterise the v0.2.0-analysis plain_fsm/shallow-oracle slice only.

This report applies a six-dimension rubric commonly invoked in benchmark science
(diversity/coverage, reproducibility, discriminative utility, localization support,
repair-task infrastructure, artifact completeness). Scores are **not** marketing claims;
they document where the v0.2.0-analysis release is strong, limited, or incomplete.

## Rubric

- **Scale:** 0=absent, 1=minimal, 2=limited, 3=adequate prototype, 4=strong, 5=community-ready
- **Evidence ratio:** internal 0–1 composite from published exports (documented per dimension).
- **Score caps:** conservative caps apply when single-family coverage, oracle saturation,
  or missing replication artefacts are observed.

## Dimension scores

| Dimension | Score | Evidence | Key strength | Primary limitation |
|-----------|------:|---------:|--------------|-------------------|
| Coverage | 2/5 | 0.49 | Four balanced complexity tiers and near-uniform operator quotas on the realised cohort. | Only plain_fsm instances are realised (machine-type coverage 12.5%). |
| Reproducibility | 3/5 | 1.00 | Frozen Zenodo deposit, pinned cohort manifests, and checksum-backed manuscript exports. | No fully pinned container image or hardware digest is reported in the manuscript. |
| Discriminative power | 3/5 | 0.73 | All three deterministic C1 baselines are statistically distinguishable on detectable-only repair. | Only three deterministic engines plus one random control are evaluated. |
| Localization support | 2/5 | 0.43 | Transition-level Ochiai hook, localizability audit export, and dual-partition reporting exist. | 119 detectable faults lack transition-localizable ground truth. |
| Repair support | 2/5 | 0.86 | Deterministic C1 baselines, detectable-only leaderboard columns, and regression tracking are shipped. | Only single-pass deterministic engines are characterised; search/LLM repair tracks are absent. |
| Artifact completeness | 4/5 | 1.00 | 329 manuscript exports tracked with SHA-256 digests and campaign manifests. | No sealed held-out evaluation split or perennial leaderboard host is bundled. |

## Literature comparison

| Source / practice | Criterion | Typical mature benchmark | FSMRepairBench v0.2.0 | Score |
|-------------------|-----------|--------------------------|------------------------|------:|
| Siegmund et al. (2015); Borg et al. (2017) | Feature-space diversity / representativeness | Multi-project or multi-family strata with audited coverage gaps | Single plain_fsm family; 54.8% mean dimension coverage | 2/5 |
| Fucci et al. (2018); Hook \& Kelly (2003) | Reproducible packaging and independent replay | Frozen artefacts + scripted replay + independent replication | Zenodo deposit, verified exports, CLI docs; no container vignette | 3/5 |
| Gazzola et al. (2019); Just et al. (2014) | Discriminative utility among repair methods | Multiple techniques separable with stable rankings | Three deterministic baselines separable on detectable-only repair | 3/5 |
| Kanewala \& Bieman (2014) | Fault-localization benchmark support | Broad, construct-valid ground truth and informative spectra | 376/1,000 localizable GT; weak default top-1 under shallow oracles | 2/5 |
| Jimenez et al. (2016) | Repair-task infrastructure | Multiple repair approaches with community submission path | Deterministic C1 lane only; saturation confounds cohort-wide repair | 2/5 |
| ACM artifact evaluation; SV-COMP practice | Artifact completeness and verification | Verified bundle, perennial tracks, held-out splits | 107 verified CSV/PNG/TeX exports; no held-out community track | 4/5 |

## Priority gaps

- **[HIGH] coverage (2/5):** Only plain_fsm instances are realised (machine-type coverage 12.5%).
- **[HIGH] localization_support (2/5):** 119 detectable faults lack transition-localizable ground truth.
- **[HIGH] repair_support (2/5):** Only single-pass deterministic engines are characterised; search/LLM repair tracks are absent.
- **[MEDIUM] discriminative_power (3/5):** Only three deterministic engines plus one random control are evaluated.
- **[MEDIUM] reproducibility (3/5):** No fully pinned container image or hardware digest is reported in the manuscript.

## Regeneration

```bash
python paper1/scripts/generate_benchmark_readiness_outputs.py
```

Inputs: taxonomy summary, C1 utility summary, localization metrics, C1 leaderboard,
benchmark health JSON (optional), and artifact verification bundle under `paper1/artifact/`.
