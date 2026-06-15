"""Validate changed_transition_id against behavioral single-transition revert anchors."""

from __future__ import annotations

import csv
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fsmrepairbench.dataset_builder import resolve_coupling_case_file
from fsmrepairbench.models import FSM
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.smoke_test_pipeline import infer_injected_fault_elements
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite, validate_fsm

BEHAVIORAL_ANCHOR_COLUMNS: tuple[str, ...] = (
    "case_id",
    "operator",
    "changed_transition_id",
    "behavioral_anchor_transition",
    "exact_match",
    "notes",
)

OPERATOR_SUMMARY_COLUMNS: tuple[str, ...] = (
    "operator",
    "n_cases",
    "n_exact_match",
    "agreement_rate",
)

DISAGREEMENT_COLUMNS: tuple[str, ...] = (
    "case_id",
    "operator",
    "changed_transition_id",
    "behavioral_anchor_transition",
    "notes",
)

BPR_TOLERANCE = 1e-9


@dataclass(frozen=True)
class BehavioralAnchorRow:
    case_id: str
    operator: str
    changed_transition_id: str
    behavioral_anchor_transition: str
    exact_match: bool
    notes: str

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "operator": self.operator,
            "changed_transition_id": self.changed_transition_id,
            "behavioral_anchor_transition": self.behavioral_anchor_transition,
            "exact_match": self.exact_match,
            "notes": self.notes,
        }


@dataclass(frozen=True)
class OperatorAgreementRow:
    operator: str
    n_cases: int
    n_exact_match: int

    @property
    def agreement_rate(self) -> float:
        if self.n_cases == 0:
            return 0.0
        return self.n_exact_match / self.n_cases

    def to_csv_dict(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "n_cases": self.n_cases,
            "n_exact_match": self.n_exact_match,
            "agreement_rate": round(self.agreement_rate, 6),
        }


@dataclass(frozen=True)
class BehavioralAnchorSummary:
    n_cases: int
    n_exact_match: int
    n_no_anchor: int
    n_multiple_anchors: int

    @property
    def agreement_rate(self) -> float:
        if self.n_cases == 0:
            return 0.0
        return self.n_exact_match / self.n_cases


@dataclass(frozen=True)
class BehavioralAnchorExportResult:
    csv_path: Path
    operator_csv_path: Path
    disagreement_csv_path: Path
    tex_path: Path
    manifest_path: Path
    summary: BehavioralAnchorSummary
    paper_csv_path: Path | None = None
    paper_tex_path: Path | None = None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        msg = f"Missing CSV: {path}"
        raise FileNotFoundError(msg)
    return list(csv.DictReader(path.open(encoding="utf-8")))


def _write_csv(path: Path, columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row[column] for column in columns})


def _bool_from_csv(value: str) -> bool:
    return str(value).strip().lower() == "true"


def load_validatable_audit_rows(audit_path: Path) -> list[dict[str, str]]:
    """Return localized, transition-localizable detectable cases."""
    rows = [
        row
        for row in _read_csv(audit_path)
        if _bool_from_csv(row.get("ground_truth_localizable", ""))
        and _bool_from_csv(row.get("localized", ""))
    ]
    if not rows:
        msg = f"No validatable rows in {audit_path}"
        raise ValueError(msg)
    return rows


def structural_diff_transition_ids(reference: FSM, faulty: FSM) -> tuple[str, ...]:
    """Return transition IDs that differ syntactically between reference and faulty."""
    return tuple(
        sorted(
            element_id
            for element_type, element_id in infer_injected_fault_elements(reference, faulty)
            if element_type == "transition"
        )
    )


def revert_single_transition(
    faulty: FSM,
    reference: FSM,
    transition_id: str,
) -> FSM | None:
    """Revert one transition in *faulty* to its reference definition."""
    reference_by_id = {transition.id: transition for transition in reference.transitions}
    faulty_by_id = {transition.id: transition for transition in faulty.transitions}
    reference_transition = reference_by_id.get(transition_id)
    faulty_transition = faulty_by_id.get(transition_id)

    if reference_transition is None and faulty_transition is None:
        return None

    patched = faulty.model_copy(deep=True)
    if reference_transition is None and faulty_transition is not None:
        patched.transitions = [
            transition for transition in patched.transitions if transition.id != transition_id
        ]
    elif reference_transition is not None and faulty_transition is None:
        patched.transitions.append(reference_transition.model_copy())
    else:
        assert reference_transition is not None
        index = next(
            idx for idx, transition in enumerate(patched.transitions) if transition.id == transition_id
        )
        patched.transitions[index] = reference_transition.model_copy()

    if validate_fsm(patched):
        return None
    return patched


def restoring_transition_ids(
    faulty: FSM,
    reference: FSM,
    oracle,
    *,
    candidate_transition_ids: Sequence[str] | None = None,
) -> tuple[str, ...]:
    """Return transitions whose single revert restores reference oracle behaviour."""
    candidates = (
        tuple(candidate_transition_ids)
        if candidate_transition_ids is not None
        else structural_diff_transition_ids(reference, faulty)
    )
    restoring: list[str] = []
    for transition_id in candidates:
        patched = revert_single_transition(faulty, reference, transition_id)
        if patched is None:
            continue
        if score_oracle_suite(patched, oracle).bpr >= 1.0 - BPR_TOLERANCE:
            restoring.append(transition_id)
    return tuple(restoring)


def select_behavioral_anchor(
    changed_transition_id: str,
    restoring: Sequence[str],
) -> tuple[str, bool, str]:
    """Pick the behavioral anchor and record whether it matches metadata ground truth."""
    target = (changed_transition_id or "").strip()
    if not restoring:
        return "", False, "no single-transition revert restores reference behavior"

    if len(restoring) == 1:
        anchor = restoring[0]
        return anchor, anchor == target, ""

    if target and target in restoring:
        return target, True, f"multiple behavioral anchors; selected metadata target among {restoring}"

    anchor = restoring[0]
    return (
        anchor,
        anchor == target,
        f"multiple behavioral anchors {restoring}; selected lexicographically first",
    )


def validate_case_behavioral_anchor(case_dir: Path, audit_row: dict[str, str]) -> BehavioralAnchorRow | None:
    """Validate one case when reference, faulty, and oracle files are available."""
    reference_path = resolve_coupling_case_file(case_dir, "reference_fsm.json")
    faulty_path = resolve_coupling_case_file(case_dir, "faulty_fsm.json")
    oracle_path = resolve_coupling_case_file(case_dir, "oracle_suite.json")
    if reference_path is None or faulty_path is None or oracle_path is None:
        return None

    reference = load_fsm_json(reference_path)
    faulty = load_fsm_json(faulty_path)
    oracle = load_oracle_suite(oracle_path)

    if score_oracle_suite(faulty, oracle).bpr >= 1.0 - BPR_TOLERANCE:
        return BehavioralAnchorRow(
            case_id=audit_row["case_id"],
            operator=audit_row["mutation_operator"],
            changed_transition_id=audit_row.get("changed_transition_id", "") or "",
            behavioral_anchor_transition="",
            exact_match=False,
            notes="oracle-saturated; validation skipped",
        )

    restoring = restoring_transition_ids(faulty, reference, oracle)
    anchor, exact_match, notes = select_behavioral_anchor(
        audit_row.get("changed_transition_id", "") or "",
        restoring,
    )
    return BehavioralAnchorRow(
        case_id=audit_row["case_id"],
        operator=audit_row["mutation_operator"],
        changed_transition_id=audit_row.get("changed_transition_id", "") or "",
        behavioral_anchor_transition=anchor,
        exact_match=exact_match,
        notes=notes,
    )


def build_behavioral_anchor_rows(
    dataset_dir: Path,
    audit_path: Path,
) -> list[BehavioralAnchorRow]:
    rows: list[BehavioralAnchorRow] = []
    for audit_row in load_validatable_audit_rows(audit_path):
        case_dir = dataset_dir / "cases" / audit_row["case_id"]
        case_row = validate_case_behavioral_anchor(case_dir, audit_row)
        if case_row is not None:
            rows.append(case_row)
    if not rows:
        msg = "No behavioral-anchor validation rows could be computed"
        raise ValueError(msg)
    return rows


def summarize_behavioral_anchor_rows(rows: Sequence[BehavioralAnchorRow]) -> BehavioralAnchorSummary:
    validated = [row for row in rows if row.notes != "oracle-saturated; validation skipped"]
    return BehavioralAnchorSummary(
        n_cases=len(validated),
        n_exact_match=sum(1 for row in validated if row.exact_match),
        n_no_anchor=sum(
            1
            for row in validated
            if row.notes == "no single-transition revert restores reference behavior"
        ),
        n_multiple_anchors=sum(1 for row in validated if row.notes.startswith("multiple behavioral anchors")),
    )


def build_operator_agreement_rows(rows: Sequence[BehavioralAnchorRow]) -> list[OperatorAgreementRow]:
    validated = [row for row in rows if row.notes != "oracle-saturated; validation skipped"]
    grouped: dict[str, list[BehavioralAnchorRow]] = {}
    for row in validated:
        grouped.setdefault(row.operator, []).append(row)
    return [
        OperatorAgreementRow(
            operator=operator,
            n_cases=len(bucket),
            n_exact_match=sum(1 for row in bucket if row.exact_match),
        )
        for operator, bucket in sorted(grouped.items())
    ]


def disagreement_examples(rows: Sequence[BehavioralAnchorRow]) -> list[BehavioralAnchorRow]:
    return [
        row
        for row in rows
        if row.notes != "oracle-saturated; validation skipped" and not row.exact_match
    ]


def _write_behavioral_anchor_tex(
    path: Path,
    summary: BehavioralAnchorSummary,
    operator_rows: Sequence[OperatorAgreementRow],
    disagreements: Sequence[BehavioralAnchorRow],
) -> None:
    lines = [
        "% Auto-generated from fsmrepairbench.behavioral_anchor_validation",
        "\\begin{table}[htbp]",
        "  \\centering",
        "  \\caption{Agreement between metadata \\texttt{changed\\_transition\\_id} and "
        f"behavioral-anchor transitions on $n={summary.n_cases}$ transition-localizable detectable cases. "
        f"Overall exact-match rate: {100.0 * summary.agreement_rate:.1f}\\%."
        "}",
        "  \\label{tab:behavioral-anchor-validation}",
        "  \\begin{tabular}{lrrr}",
        "    \\toprule",
        "    Operator & $n$ & Exact matches & Agreement \\\\",
        "    \\midrule",
    ]
    for row in operator_rows:
        lines.append(
            f"    \\texttt{{{row.operator.replace('_', '\\_')}}} & {row.n_cases} & "
            f"{row.n_exact_match} & {100.0 * row.agreement_rate:.1f}\\% \\\\"
        )
    lines.extend(
        [
            "    \\midrule",
            f"    \\textbf{{Overall}} & {summary.n_cases} & {summary.n_exact_match} & "
            f"\\textbf{{{100.0 * summary.agreement_rate:.1f}\\%}} \\\\",
            "    \\bottomrule",
            "  \\end{tabular}",
            "\\end{table}",
            "",
        ]
    )
    if disagreements:
        lines.extend(
            [
                "\\begin{table}[htbp]",
                "  \\centering",
                "  \\caption{Disagreement examples between syntactic and behavioral fault anchors.}",
                "  \\label{tab:behavioral-anchor-disagreements}",
                "  \\small",
                "  \\begin{tabular}{llll}",
                "    \\toprule",
                "    Case & Operator & Metadata GT & Behavioral anchor \\\\",
                "    \\midrule",
            ]
        )
        for row in disagreements[:10]:
            lines.append(
                f"    {row.case_id} & \\texttt{{{row.operator.replace('_', '\\_')}}} & "
                f"{row.changed_transition_id} & {row.behavioral_anchor_transition} \\\\"
            )
        lines.extend(["    \\bottomrule", "  \\end{tabular}", "\\end{table}", ""])

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def write_behavioral_anchor_exports(
    dataset_dir: Path,
    rq3_dir: Path,
    *,
    out_dir: Path | None = None,
    paper_export_dir: Path | None = None,
) -> BehavioralAnchorExportResult:
    """Write behavioral-anchor validation CSV, summaries, and LaTeX table."""
    audit_path = rq3_dir / "localizability_audit.csv"
    export_root = out_dir or rq3_dir
    tables_dir = export_root / "tables"

    rows = build_behavioral_anchor_rows(dataset_dir, audit_path)
    summary = summarize_behavioral_anchor_rows(rows)
    operator_rows = build_operator_agreement_rows(rows)
    disagreements = disagreement_examples(rows)

    csv_path = export_root / "behavioral_anchor_validation.csv"
    _write_csv(csv_path, BEHAVIORAL_ANCHOR_COLUMNS, [row.to_csv_dict() for row in rows])

    operator_csv_path = export_root / "behavioral_anchor_agreement_by_operator.csv"
    _write_csv(
        operator_csv_path,
        OPERATOR_SUMMARY_COLUMNS,
        [row.to_csv_dict() for row in operator_rows],
    )

    disagreement_csv_path = export_root / "behavioral_anchor_disagreements.csv"
    _write_csv(
        disagreement_csv_path,
        DISAGREEMENT_COLUMNS,
        [row.to_csv_dict() for row in disagreements],
    )

    tex_path = tables_dir / "table_behavioral_anchor_validation.tex"
    _write_behavioral_anchor_tex(tex_path, summary, operator_rows, disagreements)

    manifest = {
        "release_label": "RQ3-localization-ochiai-1k",
        "dataset_dir": str(dataset_dir),
        "source_audit": str(audit_path),
        "partition": "localized_transition_localizable_gt",
        "summary": {
            "n_cases": summary.n_cases,
            "n_exact_match": summary.n_exact_match,
            "agreement_rate": round(summary.agreement_rate, 6),
            "n_no_anchor": summary.n_no_anchor,
            "n_multiple_anchors": summary.n_multiple_anchors,
        },
        "operator_agreement": [row.to_csv_dict() for row in operator_rows],
        "disagreement_count": len(disagreements),
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    manifest_path = export_root / "behavioral_anchor_validation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    paper_csv_path = paper_tex_path = None
    if paper_export_dir is not None:
        paper_export_dir.mkdir(parents=True, exist_ok=True)
        (paper_export_dir / "tables").mkdir(parents=True, exist_ok=True)
        paper_csv_path = paper_export_dir / csv_path.name
        paper_tex_path = paper_export_dir / "tables" / tex_path.name
        paper_csv_path.write_text(csv_path.read_text(encoding="utf-8"), encoding="utf-8")
        (paper_export_dir / operator_csv_path.name).write_text(
            operator_csv_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        (paper_export_dir / disagreement_csv_path.name).write_text(
            disagreement_csv_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        paper_tex_path.write_text(tex_path.read_text(encoding="utf-8"), encoding="utf-8")
        (paper_export_dir / manifest_path.name).write_text(
            manifest_path.read_text(encoding="utf-8"),
            encoding="utf-8",
        )

    return BehavioralAnchorExportResult(
        csv_path=csv_path,
        operator_csv_path=operator_csv_path,
        disagreement_csv_path=disagreement_csv_path,
        tex_path=tex_path,
        manifest_path=manifest_path,
        summary=summary,
        paper_csv_path=paper_csv_path,
        paper_tex_path=paper_tex_path,
    )
