# Multi-seed stability interpretation

- **detection_rate**: mean 64.00% (std 0.0000, range [0.6400, 0.6400], 95% CI [0.6400, 0.6400]) — **stable**
- **saturation_rate**: mean 36.00% (std 0.0000, range [0.3600, 0.3600], 95% CI [0.3600, 0.3600]) — **stable**
- **detectable_only_crr**: mean 0.00% (std 0.0000, range [0.0000, 0.0000], 95% CI [0.0000, 0.0000]) — **stable**
- **participation_rate**: mean 33.71% (std 0.0038, range [0.3333, 0.3409], 95% CI [0.3333, 0.3409]) — **stable**
- **saturation_inflation_pp**: mean 0.0 pp (std 0.0000, range [0.0000, 0.0000], 95% CI [0.0000, 0.0000]) — **stable**
- **structural_gt_count**: mean 44.5 (std 0.5000, range [44.0000, 45.0000], 95% CI [44.0000, 45.0000]) — **stable**
- **spectrally_participating_count**: mean 15.0 (std 0.0000, range [15.0000, 15.0000], 95% CI [15.0000, 15.0000]) — **stable**

## Notes

- Cohort generation seed varies; stratified cell counts and taxonomy remain fixed.
- Random repair baseline uses fixed repair seed 0 (baseline_random).
- Stable metrics have cross-seed range ≤2 pp (rates) or low dispersion on counts.
- Seed-sensitive metrics should be reported with dispersion, not single-cohort point estimates.
- Detectable-only repair floor near 0% across seeds supports saturation inflation as partition artifact.
