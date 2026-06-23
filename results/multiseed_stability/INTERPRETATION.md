# Multi-seed stability interpretation

- **detection_rate**: mean 65.00% (std 0.0000, range [0.6500, 0.6500], 95% CI [0.6500, 0.6500]) — **stable**
- **saturation_rate**: mean 35.00% (std 0.0000, range [0.3500, 0.3500], 95% CI [0.3500, 0.3500]) — **stable**
- **detectable_only_crr**: mean 0.00% (std 0.0000, range [0.0000, 0.0000], 95% CI [0.0000, 0.0000]) — **stable**
- **participation_rate**: mean 33.33% (std 0.0000, range [0.3333, 0.3333], 95% CI [0.3333, 0.3333]) — **stable**
- **saturation_inflation_pp**: mean 35.0 pp (std 0.0000, range [35.0000, 35.0000], 95% CI [35.0000, 35.0000]) — **stable**
- **structural_gt_count**: mean 450.0 (std 0.0000, range [450.0000, 450.0000], 95% CI [450.0000, 450.0000]) — **stable**
- **spectrally_participating_count**: mean 150.0 (std 0.0000, range [150.0000, 150.0000], 95% CI [150.0000, 150.0000]) — **stable**

## Notes

- Cohort generation seed varies; stratified cell counts and taxonomy remain fixed.
- Random repair baseline uses fixed repair seed 0 (baseline_random).
- Stable metrics have cross-seed range ≤2 pp (rates) or low dispersion on counts.
- Seed-sensitive metrics should be reported with dispersion, not single-cohort point estimates.
- Detectable-only repair floor near 0% across seeds supports saturation inflation as partition artifact.
