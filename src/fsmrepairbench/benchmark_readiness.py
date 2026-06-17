"""Benchmark readiness assessment for FSMRepairBench (0--5 maturity rubric)."""

from __future__ import annotations

import csv
import json
import statistics
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

RELEASE_LABEL = "v0.2.0-analysis"
ZENODO_DOI = "10.5281/zenodo.20724095"
GITHUB_TAG = "v0.2.1-stvr-polish"
COHORT_SIZE = 1000
MUTATION_OPERATORS_TOTAL = 19

DIMENSION_ORDER: tuple[str, ...] = (
    "coverage",
    "reproducibility",
    "discriminative_power",
    "localization_support",
    "repair_support",
    "artifact_completeness",
)

DIMENSION_LABELS: dict[str, str] = {
    "coverage": "Coverage",
    "reproducibility": "Reproducibility",
    "discriminative_power": "Discriminative power",
    "localization_support": "Localization support",
    "repair_support": "Repair support",
    "artifact_completeness": "Artifact completeness",
}

READINESS_GRADES: tuple[tuple[float, str], ...] = (
    (4.5, "community-ready"),
    (3.5, "maturing"),
    (2.5, "early release"),
    (1.5, "prototype"),
    (0.0, "insufficient"),
)


@dataclass(frozen=True)
class BenchmarkReadinessExportResult:
    """Paths written by :func:`write_benchmark_readiness_exports`."""

    json_path: Path
    tex_path: Path
    report_path: Path
    paper_json_path: Path | None = None
    paper_tex_path: Path | None = None
    paper_report_path: Path | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        msg = f"Missing CSV: {path}"
        raise FileNotFoundError(msg)
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _read_summary(path: Path) -> dict[str, float]:
    summary: dict[str, float] = {}
    for row in _read_csv(path):
        try:
            summary[row["metric"]] = float(row["value"])
        except ValueError:
            continue
    return summary


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        msg = f"Missing JSON: {path}"
        raise FileNotFoundError(msg)
    return json.loads(path.read_text(encoding="utf-8"))


def _score_from_thresholds(value: float, thresholds: tuple[tuple[float, int], ...]) -> int:
    for minimum, score in sorted(thresholds, key=lambda item: item[0], reverse=True):
        if value >= minimum:
            return score
    return 0


def _readiness_grade(mean_score: float) -> str:
    for minimum, label in READINESS_GRADES:
        if mean_score >= minimum:
            return label
    return "insufficient"


def _load_artifact_verification(artifact_dir: Path) -> dict[str, Any]:
    verify_report = artifact_dir / "VERIFY_RESULTS.md"
    manifest = artifact_dir / "benchmark_manifest.json"
    reproducibility = artifact_dir / "REPRODUCIBILITY.md"
    canonical = artifact_dir.parent / "CANONICAL_REPRODUCTION.md"

    manifest_data: dict[str, Any] = {}
    if manifest.is_file():
        manifest_data = _read_json(manifest)

    verification_pass = False
    artifacts_checked = 0
    artifacts_passed = 0
    if verify_report.is_file():
        text = verify_report.read_text(encoding="utf-8")
        verification_pass = "**Status:** PASS" in text
        for line in text.splitlines():
            if "**Artifacts checked:**" in line:
                digits = "".join(ch for ch in line if ch.isdigit())
                if digits:
                    artifacts_checked = int(digits)
            if "**Artifacts passed:**" in line:
                digits = "".join(ch for ch in line if ch.isdigit())
                if digits:
                    artifacts_passed = int(digits)

    return {
        "manifest_present": manifest.is_file(),
        "verify_report_present": verify_report.is_file(),
        "reproducibility_doc_present": reproducibility.is_file(),
        "canonical_reproduction_present": canonical.is_file(),
        "verification_pass": verification_pass,
        "artifacts_checked": artifacts_checked,
        "artifacts_passed": artifacts_passed,
        "artifact_count": int(manifest_data.get("artifact_count", 0)),
        "artifact_counts_by_media_type": manifest_data.get("artifact_counts_by_media_type", {}),
        "zenodo_doi": manifest_data.get("zenodo_doi", ZENODO_DOI),
        "github_tag": manifest_data.get("github_tag", GITHUB_TAG),
    }


def _evaluate_coverage(
    *,
    taxonomy_summary: dict[str, float],
    health_report: dict[str, Any] | None,
) -> dict[str, Any]:
    mean_dim = taxonomy_summary.get("mean_dimension_coverage_ratio", 0.0)
    operator_ratio = taxonomy_summary.get("mutation_operator_coverage_ratio", 0.0)
    triple_ratio = taxonomy_summary.get("triple_feature_coverage_ratio", 0.0)
    fsm_families_present = taxonomy_summary.get("fsm_families_present", 1.0)
    fsm_families_total = taxonomy_summary.get("fsm_families_total", 8.0)
    machine_type_ratio = fsm_families_present / fsm_families_total if fsm_families_total else 0.0

    tier_balance = 0.0
    if health_report:
        tier_balance = float(health_report["pillars"]["complexity_tier_balance"]["score"])

    evidence_ratio = (
        0.30 * mean_dim
        + 0.25 * machine_type_ratio
        + 0.20 * operator_ratio
        + 0.15 * triple_ratio
        + 0.10 * tier_balance
    )
    rubric_score = _score_from_thresholds(
        evidence_ratio,
        (
            (0.80, 5),
            (0.65, 4),
            (0.50, 3),
            (0.35, 2),
            (0.20, 1),
        ),
    )
    if machine_type_ratio <= 0.20:
        rubric_score = min(rubric_score, 2)
    if mean_dim < 0.60:
        rubric_score = min(rubric_score, 3)

    return {
        "score": rubric_score,
        "evidence_ratio": round(evidence_ratio, 6),
        "metrics": {
            "mean_dimension_coverage_ratio": round(mean_dim, 6),
            "machine_type_coverage_ratio": round(machine_type_ratio, 6),
            "mutation_operator_coverage_ratio": round(operator_ratio, 6),
            "triple_feature_coverage_ratio": round(triple_ratio, 6),
            "complexity_tier_balance_score": round(tier_balance, 6),
            "fsm_families_present": int(fsm_families_present),
            "fsm_families_total": int(fsm_families_total),
        },
        "strengths": [
            "Four balanced complexity tiers and near-uniform operator quotas on the realised cohort.",
            "Seventeen of nineteen mutation operators appear with documented build-failure exclusions.",
        ],
        "limitations": [
            "Only plain_fsm instances are realised (machine-type coverage 12.5%).",
            "Mean dimension value coverage is 54.8%; triple-feature coverage is 10.0%.",
            "The declared ten-dimensional stratification plan remains partially populated.",
        ],
        "literature_alignment": [
            "Siegmund et al. / Borg et al. diversity criterion: partial feature-space coverage.",
            "Jimenez et al. representativeness: synthetic single-family slice, not multi-domain.",
        ],
    }


def _evaluate_reproducibility(*, artifact_audit: dict[str, Any]) -> dict[str, Any]:
    checks = {
        "zenodo_deposit": bool(artifact_audit.get("zenodo_doi")),
        "github_tooling_tag": bool(artifact_audit.get("github_tag")),
        "benchmark_manifest": artifact_audit.get("manifest_present", False),
        "artifact_verification_pass": artifact_audit.get("verification_pass", False),
        "reproducibility_doc": artifact_audit.get("reproducibility_doc_present", False),
        "canonical_reproduction_doc": artifact_audit.get("canonical_reproduction_present", False),
    }
    passed = sum(1 for value in checks.values() if value)
    evidence_ratio = passed / len(checks)
    rubric_score = _score_from_thresholds(
        evidence_ratio,
        (
            (0.95, 5),
            (0.80, 4),
            (0.65, 3),
            (0.45, 2),
            (0.25, 1),
        ),
    )
    if checks["artifact_verification_pass"] and checks["canonical_reproduction_doc"] and checks["zenodo_deposit"]:
        rubric_score = max(rubric_score, 3)
    rubric_score = min(rubric_score, 3)

    return {
        "score": rubric_score,
        "evidence_ratio": round(evidence_ratio, 6),
        "checks": checks,
        "metrics": {
            "artifacts_checked": artifact_audit.get("artifacts_checked", 0),
            "artifacts_passed": artifact_audit.get("artifacts_passed", 0),
            "artifact_count": artifact_audit.get("artifact_count", 0),
        },
        "strengths": [
            "Frozen Zenodo deposit, pinned cohort manifests, and checksum-backed manuscript exports.",
            "Canonical CLI regeneration path documented in CANONICAL_REPRODUCTION.md.",
        ],
        "limitations": [
            "No fully pinned container image or hardware digest is reported in the manuscript.",
            "Independent third-party replication runs are not yet published.",
            "Tooling GitHub tag and empirical Zenodo deposit use separate release labels.",
        ],
        "literature_alignment": [
            "Fucci et al. / Hook & Kelly replication packaging: strong static artefacts, weak independent replay.",
            "ACM artifact evaluation checklist: available, verified exports; execution pinning incomplete.",
        ],
    }


def _evaluate_discriminative_power(*, utility_summary: dict[str, Any]) -> dict[str, Any]:
    detectable_index = float(
        utility_summary.get("benchmark_discrimination_index", {})
        .get("complete_repair", {})
        .get("detectable_only", 0.0)
    )
    utility_index = float(
        utility_summary.get("benchmark_utility_index", {}).get(
            "detectable_only_complete_repair",
            0.0,
        )
    )
    rank_stability = float(
        utility_summary.get("rank_stability", {})
        .get("complete_repair_detectable_only", {})
        .get("kendall_tau_mean", 0.0)
    )
    cohort_index = float(
        utility_summary.get("benchmark_discrimination_index", {})
        .get("complete_repair", {})
        .get("cohort_wide", 0.0)
    )

    evidence_ratio = (
        0.45 * detectable_index + 0.35 * min(utility_index, 1.0) + 0.20 * max(rank_stability, 0.0)
    )
    rubric_score = _score_from_thresholds(
        evidence_ratio,
        (
            (0.85, 5),
            (0.70, 4),
            (0.55, 3),
            (0.40, 2),
            (0.20, 1),
        ),
    )
    rubric_score = min(rubric_score, 4)
    if rank_stability < 0.25:
        rubric_score = min(rubric_score, 3)
    if cohort_index > detectable_index:
        rubric_score = min(rubric_score, 3)

    return {
        "score": rubric_score,
        "evidence_ratio": round(evidence_ratio, 6),
        "metrics": {
            "detectable_only_discrimination_index": round(detectable_index, 6),
            "detectable_only_utility_index": round(utility_index, 6),
            "detectable_only_rank_stability_kendall_tau": round(rank_stability, 6),
            "cohort_wide_discrimination_index": round(cohort_index, 6),
            "tool_count": len(utility_summary.get("tools", [])),
        },
        "strengths": [
            "All three deterministic C1 baselines are statistically distinguishable on detectable-only repair.",
            "Large Cohen's h effect sizes separate missing-transition from random controls.",
        ],
        "limitations": [
            "Only three deterministic engines plus one random control are evaluated.",
            "Operator-level rank stability is low on the detectable-only partition (Kendall tau ~ 0.11).",
            "Cohort-wide discrimination is inflated by 505/1,000 oracle-saturated cases.",
        ],
        "literature_alignment": [
            "Gazzola et al.\\ APR survey utility criterion: strong baseline separation, limited method diversity.",
            "Just et al.\\ Defects4J practice: paired per-case disagreement and effect sizes are implemented.",
        ],
    }


def _evaluate_localization_support(
    *,
    localization_metrics_path: Path,
    health_report: dict[str, Any] | None,
) -> dict[str, Any]:
    loc_rows = {
        (row["partition"], row["metric"]): row for row in _read_csv(localization_metrics_path)
    }
    localizable_cases = int(float(loc_rows[("transition_localizable_gt", "localized_cases")]["value"]))
    top1 = float(loc_rows[("transition_localizable_gt", "top1_hit_rate")]["value"])
    detectable_cases = int(float(loc_rows[("all_detectable", "localized_cases")]["value"]))
    not_ranked = detectable_cases - localizable_cases

    gt_fraction = localizable_cases / COHORT_SIZE
    detectable_fraction = detectable_cases / COHORT_SIZE
    evidence_ratio = 0.45 * gt_fraction + 0.25 * detectable_fraction + 0.20 * top1 + 0.10

    rubric_score = _score_from_thresholds(
        evidence_ratio,
        (
            (0.75, 5),
            (0.60, 4),
            (0.45, 3),
            (0.30, 2),
            (0.15, 1),
        ),
    )
    if gt_fraction < 0.45:
        rubric_score = min(rubric_score, 2)
    if top1 < 0.30:
        rubric_score = min(rubric_score, 3)

    return {
        "score": rubric_score,
        "evidence_ratio": round(evidence_ratio, 6),
        "metrics": {
            "transition_localizable_cases": localizable_cases,
            "detectable_cases": detectable_cases,
            "not_ranked_detectable_cases": not_ranked,
            "localizable_gt_fraction": round(gt_fraction, 6),
            "top1_hit_rate_localizable_gt": round(top1, 6),
        },
        "strengths": [
            "Transition-level Ochiai hook, localizability audit export, and dual-partition reporting exist.",
            "Primary headline metrics use a construct-valid 376-case localizable subset.",
        ],
        "limitations": [
            "119 detectable faults lack transition-localizable ground truth.",
            "Default shallow-oracle spectra yield weak top-1 guidance (19.68% on localizable GT).",
            "Localization coverage is 376/1,000 cases (37.6%).",
        ],
        "literature_alignment": [
            "Kanewala \\& Bieman testing-benchmark criterion: evaluation hook present, ground truth partial.",
            "Code-centric FL benchmarks (e.g.\\ Defects4J line faults): richer GT coverage and stronger default spectra.",
        ],
    }


def _evaluate_repair_support(
    *,
    leaderboard_path: Path,
    health_report: dict[str, Any] | None,
) -> dict[str, Any]:
    rows = _read_csv(leaderboard_path)
    tool_count = len(rows)
    detectable_rates = [float(row["complete_repair_rate_detectable_only"]) for row in rows]
    regression_rates = [
        float(row.get("regression_rate", row.get("regression_rate_cohort_wide", 0)))
        for row in rows
    ]
    saturation_rate = 0.505
    if health_report:
        saturation_rate = float(health_report["pillars"]["oracle_health"]["saturation_rate"])

    spread = max(detectable_rates) - min(detectable_rates) if detectable_rates else 0.0
    evidence_ratio = (
        0.30 * min(tool_count / 5.0, 1.0)
        + 0.30 * spread
        + 0.20 * (1.0 - saturation_rate)
        + 0.20 * (1.0 if any(rate > 0 for rate in regression_rates) else 0.5)
    )
    rubric_score = _score_from_thresholds(
        evidence_ratio,
        (
            (0.80, 5),
            (0.65, 4),
            (0.50, 3),
            (0.35, 2),
            (0.20, 1),
        ),
    )
    rubric_score = min(rubric_score, 3)
    if tool_count <= 4:
        rubric_score = min(rubric_score, 2)
    if saturation_rate >= 0.45:
        rubric_score = min(rubric_score, 2)

    return {
        "score": rubric_score,
        "evidence_ratio": round(evidence_ratio, 6),
        "metrics": {
            "repair_tool_count": tool_count,
            "detectable_only_complete_repair_spread": round(spread, 6),
            "oracle_saturation_rate": round(saturation_rate, 6),
            "max_regression_rate": round(max(regression_rates), 6),
        },
        "strengths": [
            "Deterministic C1 baselines, detectable-only leaderboard columns, and regression tracking are shipped.",
            "Per-case exports support paired statistical comparison following APR benchmark practice.",
        ],
        "limitations": [
            "Only single-pass deterministic engines are characterised; search/LLM repair tracks are absent.",
            "505/1,000 oracle-saturated faults confound cohort-wide repair numerators.",
            "No community tool submission workflow or held-out repair split is published.",
        ],
        "literature_alignment": [
            "Jimenez et al.\\ SBSE benchmark task support: baseline repair lane exists, advanced techniques unevaluated.",
            "Defects4J repair track maturity: fewer tools, narrower fault model, but mature community adoption.",
        ],
    }


def _evaluate_artifact_completeness(*, artifact_audit: dict[str, Any]) -> dict[str, Any]:
    artifact_count = int(artifact_audit.get("artifact_count", 0))
    verification_pass = artifact_audit.get("verification_pass", False)
    media_counts = artifact_audit.get("artifact_counts_by_media_type", {})
    media_total = sum(int(value) for value in media_counts.values())

    coverage_ratio = min(artifact_count / 100.0, 1.0) if artifact_count else 0.0
    verification_ratio = 1.0 if verification_pass else 0.0
    media_diversity = min(len(media_counts) / 3.0, 1.0)
    evidence_ratio = 0.45 * coverage_ratio + 0.35 * verification_ratio + 0.20 * media_diversity

    rubric_score = _score_from_thresholds(
        evidence_ratio,
        (
            (0.90, 5),
            (0.75, 4),
            (0.60, 3),
            (0.40, 2),
            (0.20, 1),
        ),
    )
    if not verification_pass:
        rubric_score = min(rubric_score, 2)
    if artifact_count < 80:
        rubric_score = min(rubric_score, 3)
    rubric_score = min(rubric_score, 4)

    return {
        "score": rubric_score,
        "evidence_ratio": round(evidence_ratio, 6),
        "metrics": {
            "artifact_count": artifact_count,
            "artifact_media_total": media_total,
            "artifact_counts_by_media_type": media_counts,
            "verification_pass": verification_pass,
        },
        "strengths": [
            f"{artifact_count} manuscript exports tracked with SHA-256 digests and campaign manifests.",
            "ACM-style artifact package includes verification report and reproducibility instructions.",
        ],
        "limitations": [
            "No sealed held-out evaluation split or perennial leaderboard host is bundled.",
            "Container image and independent replication vignette remain roadmap items.",
        ],
        "literature_alignment": [
            "ACM artifact evaluation badging: strong available/functional static package.",
            "SV-COMP / JAPEX-style perennial tracks: not yet realised.",
        ],
    }


def compute_benchmark_readiness(
    *,
    taxonomy_summary_path: Path,
    utility_summary_path: Path,
    localization_metrics_path: Path,
    leaderboard_path: Path,
    artifact_dir: Path,
    health_report_path: Path | None = None,
) -> dict[str, Any]:
    """Compute six-dimension readiness assessment with transparent 0--5 scores."""
    taxonomy_summary = _read_summary(taxonomy_summary_path)
    utility_summary = _read_json(utility_summary_path)
    artifact_audit = _load_artifact_verification(artifact_dir)
    health_report = _read_json(health_report_path) if health_report_path and health_report_path.is_file() else None

    dimensions: dict[str, Any] = {
        "coverage": _evaluate_coverage(
            taxonomy_summary=taxonomy_summary,
            health_report=health_report,
        ),
        "reproducibility": _evaluate_reproducibility(artifact_audit=artifact_audit),
        "discriminative_power": _evaluate_discriminative_power(utility_summary=utility_summary),
        "localization_support": _evaluate_localization_support(
            localization_metrics_path=localization_metrics_path,
            health_report=health_report,
        ),
        "repair_support": _evaluate_repair_support(
            leaderboard_path=leaderboard_path,
            health_report=health_report,
        ),
        "artifact_completeness": _evaluate_artifact_completeness(artifact_audit=artifact_audit),
    }

    scores = [dimensions[name]["score"] for name in DIMENSION_ORDER]
    mean_score = round(statistics.mean(scores), 3)

    literature_comparison = _build_literature_comparison(dimensions)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "release_label": RELEASE_LABEL,
        "zenodo_doi": ZENODO_DOI,
        "github_tag": GITHUB_TAG,
        "cohort_size": COHORT_SIZE,
        "assessment_goal": (
            "Transparent maturity audit, not a promotional score. "
            "Scores characterise the v0.2.0-analysis plain_fsm/shallow-oracle slice only."
        ),
        "rubric": {
            "scale": "0=absent, 1=minimal, 2=limited, 3=adequate prototype, 4=strong, 5=community-ready",
            "dimensions": list(DIMENSION_ORDER),
        },
        "dimensions": dimensions,
        "dimension_scores": {name: dimensions[name]["score"] for name in DIMENSION_ORDER},
        "mean_readiness_score": mean_score,
        "readiness_grade": _readiness_grade(mean_score),
        "literature_comparison": literature_comparison,
        "priority_gaps": _build_priority_gaps(dimensions),
    }


def _build_literature_comparison(dimensions: dict[str, Any]) -> list[dict[str, str]]:
    rows = [
        {
            "source": "Siegmund et al. (2015); Borg et al. (2017)",
            "criterion": "Feature-space diversity / representativeness",
            "typical_mature_benchmark": "Multi-project or multi-family strata with audited coverage gaps",
            "fsmrepairbench_v0_2": "Single plain_fsm family; 54.8% mean dimension coverage",
            "readiness_score": str(dimensions["coverage"]["score"]),
        },
        {
            "source": "Fucci et al. (2018); Hook \\& Kelly (2003)",
            "criterion": "Reproducible packaging and independent replay",
            "typical_mature_benchmark": "Frozen artefacts + scripted replay + independent replication",
            "fsmrepairbench_v0_2": "Zenodo deposit, verified exports, CLI docs; no container vignette",
            "readiness_score": str(dimensions["reproducibility"]["score"]),
        },
        {
            "source": "Gazzola et al. (2019); Just et al. (2014)",
            "criterion": "Discriminative utility among repair methods",
            "typical_mature_benchmark": "Multiple techniques separable with stable rankings",
            "fsmrepairbench_v0_2": "Three deterministic baselines separable on detectable-only repair",
            "readiness_score": str(dimensions["discriminative_power"]["score"]),
        },
        {
            "source": "Kanewala \\& Bieman (2014)",
            "criterion": "Fault-localization benchmark support",
            "typical_mature_benchmark": "Broad, construct-valid ground truth and informative spectra",
            "fsmrepairbench_v0_2": "376/1,000 localizable GT; weak default top-1 under shallow oracles",
            "readiness_score": str(dimensions["localization_support"]["score"]),
        },
        {
            "source": "Jimenez et al. (2016)",
            "criterion": "Repair-task infrastructure",
            "typical_mature_benchmark": "Multiple repair approaches with community submission path",
            "fsmrepairbench_v0_2": "Deterministic C1 lane only; saturation confounds cohort-wide repair",
            "readiness_score": str(dimensions["repair_support"]["score"]),
        },
        {
            "source": "ACM artifact evaluation; SV-COMP practice",
            "criterion": "Artifact completeness and verification",
            "typical_mature_benchmark": "Verified bundle, perennial tracks, held-out splits",
            "fsmrepairbench_v0_2": "107 verified CSV/PNG/TeX exports; no held-out community track",
            "readiness_score": str(dimensions["artifact_completeness"]["score"]),
        },
    ]
    return rows


def _build_priority_gaps(dimensions: dict[str, Any]) -> list[dict[str, str]]:
    ordered = sorted(
        ((name, dimensions[name]["score"]) for name in DIMENSION_ORDER),
        key=lambda item: (item[1], item[0]),
    )
    gaps: list[dict[str, str]] = []
    for name, score in ordered:
        if score >= 4:
            continue
        limitation = dimensions[name]["limitations"][0]
        gaps.append(
            {
                "dimension": name,
                "score": str(score),
                "priority": "high" if score <= 2 else "medium",
                "gap": limitation,
            }
        )
    return gaps


def _write_benchmark_readiness_tex(path: Path, report: dict[str, Any]) -> None:
    rows: list[str] = []
    for name in DIMENSION_ORDER:
        dimension = report["dimensions"][name]
        detail = (
            dimension["limitations"][0]
            .replace("plain_fsm", "\\texttt{plain\\_fsm}")
            .replace("1,000", "1{,}000")
            .replace("505/1,000", "505/1{,}000")
            .replace("376/1,000", "376/1{,}000")
            .replace("%", "\\%")
        )
        rows.append(
            f"{DIMENSION_LABELS[name]} & {dimension['score']}/5 & "
            f"{dimension['evidence_ratio']:.2f} & {detail} \\\\"
        )

    literature_rows = []
    for row in report["literature_comparison"]:
        current = (
            row["fsmrepairbench_v0_2"]
            .replace("plain_fsm", "\\texttt{plain\\_fsm}")
            .replace("1,000", "1{,}000")
            .replace("%", "\\%")
        )
        literature_rows.append(
            f"{row['criterion']} & {row['typical_mature_benchmark']} & "
            f"{current} & {row['readiness_score']}/5 \\\\"
        )

    tex = f"""\\begin{{table}}[t]
\\caption{{Benchmark readiness assessment for the \\texttt{{v0.2.0-analysis}} release (0--5 rubric).
Mean readiness score $={report['mean_readiness_score']:.2f}$ ({report['readiness_grade']}).
This audit is intentionally conservative: high scores require breadth beyond the current \\texttt{{plain\\_fsm}}/shallow-oracle slice.}}
\\label{{tab:benchmark-readiness}}
\\footnotesize
\\setlength{{\\tabcolsep}}{{4pt}}
\\begin{{tabular}}{{@{{}}lrrp{{0.42\\linewidth}}@{{}}}}
\\toprule
Dimension & Score & Evidence & Primary limitation \\\\
\\midrule
{chr(10).join(rows)}
\\midrule
\\textbf{{Mean readiness}} & \\textbf{{{report['mean_readiness_score']:.2f}}} & --- & Grade: \\textbf{{{report['readiness_grade']}}} \\\\
\\bottomrule
\\end{{tabular}}
\\end{{table}}

\\begin{{table}}[t]
\\caption{{Literature-aligned benchmark readiness comparison (selected criteria from benchmark science and APR surveys).
Scores refer to the FSMRepairBench v0.2.0-analysis column only; they are not cross-benchmark merit rankings.}}
\\label{{tab:benchmark-readiness-literature}}
\\scriptsize
\\setlength{{\\tabcolsep}}{{3pt}}
\\begin{{tabular}}{{@{{}}p{{0.18\\linewidth}}p{{0.24\\linewidth}}p{{0.24\\linewidth}}r@{{}}}}
\\toprule
Criterion & Typical mature practice & FSMRepairBench v0.2.0 & Score \\\\
\\midrule
{chr(10).join(literature_rows)}
\\bottomrule
\\end{{tabular}}
\\end{{table}}
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(tex, encoding="utf-8")


def _write_benchmark_readiness_report(path: Path, report: dict[str, Any]) -> None:
    lines = [
        "# FSMRepairBench Benchmark Readiness Assessment",
        "",
        f"**Release:** `{report['release_label']}`  ",
        f"**Generated:** {report['generated_at']}  ",
        f"**Mean readiness score:** {report['mean_readiness_score']:.2f}/5 ({report['readiness_grade']})  ",
        "",
        "## Purpose",
        "",
        report["assessment_goal"],
        "",
        "This report applies a six-dimension rubric commonly invoked in benchmark science",
        "(diversity/coverage, reproducibility, discriminative utility, localization support,",
        "repair-task infrastructure, artifact completeness). Scores are **not** marketing claims;",
        "they document where the v0.2.0-analysis release is strong, limited, or incomplete.",
        "",
        "## Rubric",
        "",
        f"- **Scale:** {report['rubric']['scale']}",
        "- **Evidence ratio:** internal 0–1 composite from published exports (documented per dimension).",
        "- **Score caps:** conservative caps apply when single-family coverage, oracle saturation,",
        "  or missing replication artefacts are observed.",
        "",
        "## Dimension scores",
        "",
        "| Dimension | Score | Evidence | Key strength | Primary limitation |",
        "|-----------|------:|---------:|--------------|-------------------|",
    ]
    for name in DIMENSION_ORDER:
        dimension = report["dimensions"][name]
        strength = dimension["strengths"][0]
        limitation = dimension["limitations"][0]
        lines.append(
            f"| {DIMENSION_LABELS[name]} | {dimension['score']}/5 | "
            f"{dimension['evidence_ratio']:.2f} | {strength} | {limitation} |"
        )

    lines.extend(
        [
            "",
            "## Literature comparison",
            "",
            "| Source / practice | Criterion | Typical mature benchmark | FSMRepairBench v0.2.0 | Score |",
            "|-------------------|-----------|--------------------------|------------------------|------:|",
        ]
    )
    for row in report["literature_comparison"]:
        lines.append(
            f"| {row['source']} | {row['criterion']} | {row['typical_mature_benchmark']} | "
            f"{row['fsmrepairbench_v0_2']} | {row['readiness_score']}/5 |"
        )

    lines.extend(["", "## Priority gaps", ""])
    for gap in report["priority_gaps"]:
        lines.append(
            f"- **[{gap['priority'].upper()}] {gap['dimension']} ({gap['score']}/5):** {gap['gap']}"
        )

    lines.extend(
        [
            "",
            "## Regeneration",
            "",
            "```bash",
            "python paper1/scripts/generate_benchmark_readiness_outputs.py",
            "```",
            "",
            "Inputs: taxonomy summary, C1 utility summary, localization metrics, C1 leaderboard,",
            "benchmark health JSON (optional), and artifact verification bundle under `paper1/artifact/`.",
            "",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_benchmark_readiness_exports(
    *,
    taxonomy_summary_path: Path,
    utility_summary_path: Path,
    localization_metrics_path: Path,
    leaderboard_path: Path,
    artifact_dir: Path,
    out_dir: Path,
    health_report_path: Path | None = None,
    paper_export_dir: Path | None = None,
) -> BenchmarkReadinessExportResult:
    """Write readiness JSON, LaTeX tables, and Markdown report."""
    report = compute_benchmark_readiness(
        taxonomy_summary_path=taxonomy_summary_path,
        utility_summary_path=utility_summary_path,
        localization_metrics_path=localization_metrics_path,
        leaderboard_path=leaderboard_path,
        artifact_dir=artifact_dir,
        health_report_path=health_report_path,
    )

    json_path = out_dir / "benchmark_readiness.json"
    tex_path = out_dir / "tables" / "benchmark_readiness.tex"
    report_path = out_dir / "benchmark_readiness_report.md"

    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _write_benchmark_readiness_tex(tex_path, report)
    _write_benchmark_readiness_report(report_path, report)

    paper_json_path = paper_tex_path = paper_report_path = None
    if paper_export_dir is not None and paper_export_dir.resolve() != out_dir.resolve():
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        paper_json_path = paper_export_dir / json_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_report_path = paper_export_dir / report_path.name
        paper_json_path.write_text(json_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_tex_path.parent.mkdir(parents=True, exist_ok=True)
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        paper_report_path.write_text(report_path.read_text(encoding="utf-8"), encoding="utf-8")

    return BenchmarkReadinessExportResult(
        json_path=json_path,
        tex_path=tex_path,
        report_path=report_path,
        paper_json_path=paper_json_path,
        paper_tex_path=paper_tex_path,
        paper_report_path=paper_report_path,
    )
