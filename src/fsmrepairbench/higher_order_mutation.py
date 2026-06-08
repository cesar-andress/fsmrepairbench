"""Higher-order FSM mutation and dataset coupling analysis."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from fsmrepairbench.dataset_builder import is_case_complete
from fsmrepairbench.models import BugMetadata, FSM, OracleSuite
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import load_fsm_json, load_oracle_suite


class HigherOrderMutationError(ValueError):
    """Raised when a higher-order mutation cannot be applied."""


@dataclass(frozen=True)
class ComponentFault:
    """One first-order fault injected as part of a higher-order mutant."""

    operator: str
    seed: int
    bug_id: str
    changed_transition_id: str | None
    description: str

    def to_dict(self) -> dict[str, str | int | None]:
        return {
            "operator": self.operator,
            "seed": self.seed,
            "bug_id": self.bug_id,
            "changed_transition_id": self.changed_transition_id,
            "description": self.description,
        }


def parse_operators(operators: str | list[str]) -> list[str]:
    """Parse comma-separated or list operator identifiers."""
    if isinstance(operators, str):
        parsed = [item.strip() for item in operators.split(",") if item.strip()]
    else:
        parsed = [item.strip() for item in operators if item.strip()]
    if not parsed:
        msg = "At least one mutation operator is required"
        raise HigherOrderMutationError(msg)
    unknown = [operator for operator in parsed if operator not in MUTATION_OPERATORS]
    if unknown:
        msg = f"Unknown mutation operator(s): {', '.join(unknown)}"
        raise HigherOrderMutationError(msg)
    return parsed


def _step_seed(base_seed: int, step_index: int) -> int:
    return base_seed + step_index * 1000


def _higher_order_tag(operators: list[str]) -> str:
    return "__".join(operators)


def _higher_order_bug_id(reference_fsm_id: str, operators: list[str], seed: int) -> str:
    return f"{reference_fsm_id}__hom__{_higher_order_tag(operators)}__{seed}"


def _higher_order_faulty_id(reference_fsm_id: str, operators: list[str], seed: int) -> str:
    return f"{reference_fsm_id}__faulty__hom__{_higher_order_tag(operators)}__{seed}"


def component_fault_from_metadata(metadata: BugMetadata) -> ComponentFault:
    """Build a component fault record from first-order metadata."""
    return ComponentFault(
        operator=metadata.mutation_operator,
        seed=metadata.seed,
        bug_id=metadata.bug_id,
        changed_transition_id=metadata.changed_transition_id,
        description=metadata.description,
    )


def is_first_order_mutant(metadata: BugMetadata) -> bool:
    """Return whether *metadata* describes a first-order mutant."""
    if metadata.is_higher_order:
        return False
    order = metadata.mutation_order or 1
    return order == 1


def is_higher_order_mutant(metadata: BugMetadata) -> bool:
    """Return whether *metadata* describes a higher-order mutant."""
    if metadata.is_higher_order:
        return True
    order = metadata.mutation_order or 1
    return order >= 2 or len(metadata.component_faults) >= 2


def mutate_higher_order(
    reference: FSM,
    operators: str | list[str],
    seed: int,
) -> tuple[FSM, BugMetadata]:
    """Apply one or more mutation operators to build a first- or higher-order mutant."""
    operator_list = parse_operators(operators)

    if len(operator_list) == 1:
        faulty, metadata = mutate(reference, operator_list[0], seed)
        component = component_fault_from_metadata(metadata)
        return faulty, metadata.model_copy(
            update={
                "mutation_order": 1,
                "component_faults": [component.to_dict()],
                "is_higher_order": False,
                "coupled_to_simple_faults": None,
            }
        )

    current = reference
    components: list[ComponentFault] = []
    coupled_simple: list[str] = []

    for index, operator in enumerate(operator_list):
        step_seed = _step_seed(seed, index)
        try:
            next_fsm, step_metadata = mutate(current, operator, step_seed)
        except MutatorError as exc:
            msg = (
                f"Failed to apply operator '{operator}' at step {index + 1} "
                f"of {len(operator_list)}: {exc}"
            )
            raise HigherOrderMutationError(msg) from exc
        component = component_fault_from_metadata(step_metadata)
        components.append(component)
        coupled_simple.append(component.bug_id)
        current = next_fsm

    faulty_id = _higher_order_faulty_id(reference.id, operator_list, seed)
    faulty = current.model_copy(
        update={
            "id": faulty_id,
            "name": f"{reference.name} (higher-order: {', '.join(operator_list)})",
            "reference_fsm_id": reference.id,
            "parent_fsm_id": reference.id,
        }
    )

    metadata = BugMetadata(
        bug_id=_higher_order_bug_id(reference.id, operator_list, seed),
        reference_fsm_id=reference.id,
        faulty_fsm_id=faulty_id,
        mutation_operator=",".join(operator_list),
        changed_transition_id=components[-1].changed_transition_id,
        description=(
            f"Higher-order mutant applying {len(operator_list)} operators: "
            f"{', '.join(operator_list)}"
        ),
        seed=seed,
        mutation_order=len(operator_list),
        component_faults=[component.to_dict() for component in components],
        is_higher_order=True,
        coupled_to_simple_faults=coupled_simple,
    )
    return faulty, metadata


def _is_fault_detected(reference: FSM, faulty: FSM, oracle: OracleSuite) -> bool:
    reference_score = score_oracle_suite(reference, oracle)
    faulty_score = score_oracle_suite(faulty, oracle)
    return faulty_score.bpr < reference_score.bpr


def _reproduce_component_fault(reference: FSM, component: dict[str, str | int | None]) -> FSM:
    operator = str(component["operator"])
    step_seed = int(component["seed"])
    faulty, _ = mutate(reference, operator, step_seed)
    return faulty


@dataclass(frozen=True)
class CaseCouplingRecord:
    """Coupling analysis for one benchmark case."""

    case_id: str
    reference_fsm_id: str
    mutation_order: int
    is_higher_order: bool
    higher_order_detected: bool
    first_order_components_detected: int
    first_order_components_total: int
    all_first_order_detected: bool
    coupled_to_simple_faults: tuple[str, ...]


@dataclass(frozen=True)
class DatasetCouplingReport:
    """Dataset-level coupling-effect estimate."""

    dataset_dir: Path
    case_count: int
    first_order_case_count: int
    higher_order_case_count: int
    first_order_detection_rate: float
    higher_order_detection_rate: float
    coupling_effect_estimate: float
    cases: tuple[CaseCouplingRecord, ...]


def analyze_case_coupling(case_dir: Path) -> CaseCouplingRecord | None:
    """Analyze coupling for one complete benchmark case directory."""
    if not is_case_complete(case_dir):
        return None

    reference = load_fsm_json(case_dir / "reference_fsm.json")
    faulty = load_fsm_json(case_dir / "faulty_fsm.json")
    oracle = load_oracle_suite(case_dir / "oracle_suite.json")
    metadata = BugMetadata.model_validate(
        json.loads((case_dir / "bug_metadata.json").read_text(encoding="utf-8"))
    )

    mutation_order = metadata.mutation_order or 1
    higher_order = is_higher_order_mutant(metadata)
    higher_order_detected = _is_fault_detected(reference, faulty, oracle)

    components = metadata.component_faults
    if higher_order and components:
        detected_components = 0
        for component in components:
            component_faulty = _reproduce_component_fault(reference, component)
            if _is_fault_detected(reference, component_faulty, oracle):
                detected_components += 1
        total_components = len(components)
    elif higher_order:
        total_components = mutation_order
        detected_components = 0
    else:
        total_components = 1
        detected_components = 1 if higher_order_detected else 0

    all_first_order_detected = (
        detected_components == total_components if total_components else False
    )
    coupled = tuple(metadata.coupled_to_simple_faults or ())

    return CaseCouplingRecord(
        case_id=case_dir.name,
        reference_fsm_id=reference.id,
        mutation_order=mutation_order,
        is_higher_order=higher_order,
        higher_order_detected=higher_order_detected,
        first_order_components_detected=detected_components,
        first_order_components_total=total_components,
        all_first_order_detected=all_first_order_detected,
        coupled_to_simple_faults=coupled,
    )


def analyze_dataset_coupling(dataset_dir: Path) -> DatasetCouplingReport:
    """Estimate coupling between first-order and higher-order fault detection."""
    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"No cases/ directory found in {dataset_dir}"
        raise HigherOrderMutationError(msg)

    records: list[CaseCouplingRecord] = []
    for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir()):
        record = analyze_case_coupling(case_dir)
        if record is not None:
            records.append(record)

    if not records:
        msg = f"No complete benchmark cases found under {cases_root}"
        raise HigherOrderMutationError(msg)

    first_order_cases = [record for record in records if not record.is_higher_order]
    higher_order_cases = [record for record in records if record.is_higher_order]

    fo_detected = sum(1 for record in first_order_cases if record.higher_order_detected)
    ho_detected = sum(1 for record in higher_order_cases if record.higher_order_detected)

    fo_rate = fo_detected / len(first_order_cases) if first_order_cases else 0.0
    ho_rate = ho_detected / len(higher_order_cases) if higher_order_cases else 0.0

    eligible = [
        record
        for record in higher_order_cases
        if record.all_first_order_detected
    ]
    coupled_detected = sum(1 for record in eligible if record.higher_order_detected)
    coupling_estimate = coupled_detected / len(eligible) if eligible else 0.0

    return DatasetCouplingReport(
        dataset_dir=dataset_dir,
        case_count=len(records),
        first_order_case_count=len(first_order_cases),
        higher_order_case_count=len(higher_order_cases),
        first_order_detection_rate=fo_rate,
        higher_order_detection_rate=ho_rate,
        coupling_effect_estimate=coupling_estimate,
        cases=tuple(records),
    )


def dataset_coupling_report_to_dict(report: DatasetCouplingReport) -> dict[str, object]:
    """Convert a dataset coupling report to JSON."""
    return {
        "dataset_dir": str(report.dataset_dir),
        "case_count": report.case_count,
        "first_order_case_count": report.first_order_case_count,
        "higher_order_case_count": report.higher_order_case_count,
        "first_order_detection_rate": report.first_order_detection_rate,
        "higher_order_detection_rate": report.higher_order_detection_rate,
        "coupling_effect_estimate": report.coupling_effect_estimate,
        "cases": [
            {
                "case_id": record.case_id,
                "reference_fsm_id": record.reference_fsm_id,
                "mutation_order": record.mutation_order,
                "is_higher_order": record.is_higher_order,
                "higher_order_detected": record.higher_order_detected,
                "first_order_components_detected": record.first_order_components_detected,
                "first_order_components_total": record.first_order_components_total,
                "all_first_order_detected": record.all_first_order_detected,
                "coupled_to_simple_faults": list(record.coupled_to_simple_faults),
            }
            for record in report.cases
        ],
    }


def write_dataset_coupling_report(path: Path, report: DatasetCouplingReport) -> None:
    """Write dataset coupling analysis to JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dataset_coupling_report_to_dict(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
