"""Repair task definitions for scalable experiment execution."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fsmrepairbench.llm.clients.base import ModelSpec
from fsmrepairbench.llm.clients.registry import client_label

if TYPE_CHECKING:
    from fsmrepairbench.experiments import ExperimentCase


@dataclass(frozen=True)
class RepairTask:
    """One queued repair execution."""

    task_id: str
    case_id: str
    model_label: str
    model_name: str
    backend: str
    case_dir: str
    mutation_operator: str
    iterations: int
    temperature: float
    base_url: str | None = None
    api_key: str | None = None

    @property
    def model_spec(self) -> ModelSpec:
        from fsmrepairbench.llm.clients.base import ModelBackend

        return ModelSpec(
            name=self.model_name,
            backend=ModelBackend(self.backend),
            base_url=self.base_url,
            api_key=self.api_key,
        )


def build_repair_tasks(
    cases: list[ExperimentCase],
    model_specs: list[ModelSpec],
    *,
    iterations: int,
    temperature: float,
) -> list[RepairTask]:
    """Build the Cartesian product of cases and model specs."""
    tasks: list[RepairTask] = []
    for case in cases:
        for spec in model_specs:
            label = client_label(spec)
            task_id = f"{case.case_id}__{label.replace('/', '_').replace(':', '__')}"
            tasks.append(
                RepairTask(
                    task_id=task_id,
                    case_id=case.case_id,
                    model_label=label,
                    model_name=spec.name,
                    backend=spec.backend.value,
                    case_dir=str(case.case_dir),
                    mutation_operator=case.mutation_operator,
                    iterations=iterations,
                    temperature=temperature,
                    base_url=spec.base_url,
                    api_key=spec.api_key,
                )
            )
    return tasks
