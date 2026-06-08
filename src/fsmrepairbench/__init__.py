"""FSMRepairBench: benchmark for LLM-based repair of behavioural FSMs."""

from fsmrepairbench.generator import generate_benchmark
from fsmrepairbench.models import (
    FSM,
    BugMetadata,
    OracleScenario,
    OracleStep,
    OracleSuite,
    RepairResult,
    ScenarioResult,
    ScoreResult,
    State,
    StepResult,
    Transition,
)
from fsmrepairbench.mutators import MUTATION_OPERATORS, MutatorError, mutate
from fsmrepairbench.oracle import execute_scenario
from fsmrepairbench.patch import FSMPatch, PatchError, apply_patch, load_patch_json, validate_patch
from fsmrepairbench.scorer import score_oracle_suite
from fsmrepairbench.validators import is_valid_fsm, load_fsm_json, validate_fsm

__all__ = [
    "BugMetadata",
    "FSM",
    "FSMPatch",
    "MUTATION_OPERATORS",
    "MutatorError",
    "PatchError",
    "OracleScenario",
    "OracleStep",
    "OracleSuite",
    "RepairResult",
    "ScenarioResult",
    "ScoreResult",
    "State",
    "StepResult",
    "Transition",
    "apply_patch",
    "execute_scenario",
    "generate_benchmark",
    "is_valid_fsm",
    "load_fsm_json",
    "load_patch_json",
    "mutate",
    "score_oracle_suite",
    "validate_fsm",
    "validate_patch",
]
__version__ = "0.1.0"
