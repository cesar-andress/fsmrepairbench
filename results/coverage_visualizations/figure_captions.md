# Coverage visualisation captions (v0.2.0-analysis)

## heatmap_dimension_plan_vs_realised.png

Dual heatmap comparing declared YAML plan values (left) with realised cohort
counts (right) across all ten stratification dimensions. Orange cells mark values
present in the plan; green cells mark realised/planned ratios near 1.0. Gaps appear
for four non-`plain_fsm` machine families, `size_class=tiny` (cohort uses balanced
small/medium/large/very_large tiers instead), and several time-feature and oracle-depth
values declared in the plan but absent from the built cohort.

## heatmap_family_operator_plan_vs_realised.png

Plan-cell realisation ratio heatmap (`machine_type` × mutation operator). Only
`plain_fsm` rows register realised cases; 20/20 YAML cells remain
unrepresented at full cell granularity (`plan_cell_gaps.csv`).

## heatmap_operator_complexity_tier.png

Realised cohort density heatmap (mutation operator × structural complexity tier).
Seventeen operators appear with near-uniform tier balance (~246–252 cases per tier);
`timed_selective_mutation` and `variable_intra_class` remain absent.

## heatmap_family_complexity_tier.png

Realised cohort density heatmap (FSM family × complexity tier). The v0.2.0-analysis
release contains only `plain_fsm` (1/5 planned
families realised) with balanced tier counts.

## heatmap_dimension_coverage_summary.png

Observed-to-universe coverage ratio per taxonomy dimension (mean 54.8% across ten
axes). Highlights partial coverage: machine_type 12.5%, time_features 20%,
bug_type 89.5%, size_class 80% (cohort tiers differ from plan `tiny` quota).
