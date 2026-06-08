"""Queue-based scheduling for repair experiment tasks."""

from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from threading import Lock

from fsmrepairbench.experiment.tasks import RepairTask


@dataclass
class TaskQueue:
    """Thread-safe FIFO queue with optional on-disk persistence."""

    _pending: deque[RepairTask]
    _lock: Lock
    queue_dir: Path | None = None

    @classmethod
    def from_tasks(cls, tasks: list[RepairTask], *, queue_dir: Path | None = None) -> TaskQueue:
        queue = cls(_pending=deque(tasks), _lock=Lock(), queue_dir=queue_dir)
        if queue_dir is not None:
            queue.persist_pending()
        return queue

    def __len__(self) -> int:
        with self._lock:
            return len(self._pending)

    def enqueue(self, task: RepairTask) -> None:
        with self._lock:
            self._pending.append(task)
        self.persist_pending()

    def dequeue(self) -> RepairTask | None:
        with self._lock:
            if not self._pending:
                return None
            return self._pending.popleft()

    def persist_pending(self) -> None:
        if self.queue_dir is None:
            return
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        pending_path = self.queue_dir / "pending.jsonl"
        with self._lock:
            tasks = list(self._pending)
        with pending_path.open("w", encoding="utf-8") as handle:
            for task in tasks:
                handle.write(json.dumps(_task_to_dict(task), ensure_ascii=False) + "\n")


def _task_to_dict(task: RepairTask) -> dict[str, object]:
    return {
        "task_id": task.task_id,
        "case_id": task.case_id,
        "model_label": task.model_label,
        "model_name": task.model_name,
        "backend": task.backend,
        "case_dir": task.case_dir,
        "mutation_operator": task.mutation_operator,
        "iterations": task.iterations,
        "temperature": task.temperature,
        "base_url": task.base_url,
        "api_key": task.api_key,
    }


def load_task_queue(path: Path) -> TaskQueue:
    """Load a pending task queue from ``pending.jsonl``."""
    tasks: list[RepairTask] = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            payload = json.loads(line)
            tasks.append(
                RepairTask(
                    task_id=str(payload["task_id"]),
                    case_id=str(payload["case_id"]),
                    model_label=str(payload["model_label"]),
                    model_name=str(payload["model_name"]),
                    backend=str(payload["backend"]),
                    case_dir=str(payload["case_dir"]),
                    mutation_operator=str(payload["mutation_operator"]),
                    iterations=int(payload["iterations"]),
                    temperature=float(payload["temperature"]),
                    base_url=payload.get("base_url"),
                    api_key=payload.get("api_key"),
                )
            )
    return TaskQueue.from_tasks(tasks, queue_dir=path.parent)
