"""HuggingFace dataset export for FSMRepairBench."""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from fsmrepairbench.dataset_builder import is_case_complete, load_dataset_cases
from fsmrepairbench.models import FSM, BugMetadata
from fsmrepairbench.validators import load_fsm_json, load_model, load_oracle_suite

HF_DATASET_DIR_NAME = "dataset"
TRAIN_RATIO = 0.8
VALIDATION_RATIO = 0.1
TEST_RATIO = 0.1
DEFAULT_SPLIT_SEED = 42


class HuggingFaceExportError(RuntimeError):
    """Raised when HuggingFace export cannot complete."""


@dataclass(frozen=True)
class HuggingFaceExportResult:
    """Paths written by a HuggingFace export run."""

    dataset_dir: Path
    output_dir: Path
    train_path: Path
    validation_path: Path
    test_path: Path
    dataset_card_path: Path
    split_counts: dict[str, int]


def collect_requirements(fsm: FSM) -> list[str]:
    """Return sorted unique transition requirements declared in *fsm*."""
    seen: set[str] = set()
    requirements: list[str] = []
    for transition in fsm.transitions:
        for requirement in transition.requirements:
            if requirement in seen:
                continue
            seen.add(requirement)
            requirements.append(requirement)
    return sorted(requirements)


def discover_case_directories(dataset_dir: Path) -> list[Path]:
    """Return complete benchmark case directories under *dataset_dir*."""
    cases_root = dataset_dir / "cases"
    if not cases_root.is_dir():
        msg = f"Cases directory not found: {cases_root}"
        raise HuggingFaceExportError(msg)

    case_dirs = [
        case_dir
        for case_dir in sorted(path for path in cases_root.iterdir() if path.is_dir())
        if is_case_complete(case_dir)
    ]
    if not case_dirs:
        msg = f"No complete benchmark cases found under {cases_root}"
        raise HuggingFaceExportError(msg)
    return case_dirs


def load_case_record(case_dir: Path) -> dict[str, Any]:
    """Load one HuggingFace export record from a packaged case directory."""
    reference_fsm = load_fsm_json(case_dir / "reference_fsm.json")
    faulty_fsm = load_fsm_json(case_dir / "faulty_fsm.json")
    bug_metadata = load_model(case_dir / "bug_metadata.json", BugMetadata)
    oracle_suite = load_oracle_suite(case_dir / "oracle_suite.json")

    case_metadata: dict[str, Any] = {}
    metadata_path = case_dir / "case_metadata.json"
    if metadata_path.is_file():
        case_metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    return {
        "case_id": case_dir.name,
        "requirements": collect_requirements(reference_fsm),
        "reference_fsm": reference_fsm.model_dump(),
        "faulty_fsm": faulty_fsm.model_dump(),
        "bug_metadata": bug_metadata.model_dump(),
        "oracle_suite": oracle_suite.model_dump(),
        "metadata": case_metadata,
    }


def split_records(
    records: list[dict[str, Any]],
    *,
    seed: int = DEFAULT_SPLIT_SEED,
    train_ratio: float = TRAIN_RATIO,
    validation_ratio: float = VALIDATION_RATIO,
    test_ratio: float = TEST_RATIO,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Split export records into train, validation, and test sets."""
    total_ratio = train_ratio + validation_ratio + test_ratio
    if abs(total_ratio - 1.0) > 1e-6:
        msg = "Split ratios must sum to 1.0"
        raise HuggingFaceExportError(msg)

    count = len(records)
    if count == 0:
        return [], [], []

    shuffled = sorted(records, key=lambda record: str(record["case_id"]))
    rng = random.Random(seed)
    rng.shuffle(shuffled)

    train_count = max(1, round(count * train_ratio)) if count >= 3 else max(1, count - 1)
    remaining = count - train_count
    validation_count = round(remaining * (validation_ratio / (validation_ratio + test_ratio)))
    validation_count = min(remaining, max(0, validation_count))
    test_count = count - train_count - validation_count

    train_records = shuffled[:train_count]
    validation_records = shuffled[train_count : train_count + validation_count]
    test_records = shuffled[train_count + validation_count :]
    assert len(test_records) == test_count
    return train_records, validation_records, test_records


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    """Write *records* to a JSON Lines file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _load_split_seed(dataset_dir: Path) -> int:
    metadata_path = dataset_dir / "metadata.json"
    if not metadata_path.is_file():
        return DEFAULT_SPLIT_SEED
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        return int(payload.get("seed", DEFAULT_SPLIT_SEED))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return DEFAULT_SPLIT_SEED


def generate_dataset_card(
    *,
    dataset_id: str,
    case_count: int,
    split_counts: dict[str, int],
    seed: int,
) -> str:
    """Return a HuggingFace dataset card in Markdown with YAML front matter."""
    front_matter = {
        "language": "en",
        "license": "mit",
        "task_categories": ["text2text-generation"],
        "tags": ["fsm", "code-repair", "benchmark", "finite-state-machine"],
        "pretty_name": "FSMRepairBench",
        "size_categories": _size_category(case_count),
        "dataset_info": {
            "features": [
                {"name": "case_id", "dtype": "string"},
                {"name": "requirements", "dtype": "list"},
                {"name": "reference_fsm", "dtype": "dict"},
                {"name": "faulty_fsm", "dtype": "dict"},
                {"name": "bug_metadata", "dtype": "dict"},
                {"name": "oracle_suite", "dtype": "dict"},
                {"name": "metadata", "dtype": "dict"},
            ],
            "splits": [
                {"name": "train", "num_examples": split_counts["train"]},
                {"name": "validation", "num_examples": split_counts["validation"]},
                {"name": "test", "num_examples": split_counts["test"]},
            ],
        },
    }
    yaml_block = yaml.safe_dump(front_matter, sort_keys=False).strip()
    return f"""---
{yaml_block}
---

# FSMRepairBench

FSMRepairBench is a benchmark for evaluating repair of behavioural finite-state machines (FSMs).
Each example contains a reference FSM, a faulty FSM produced by controlled mutation, bug metadata,
behavioural oracle scenarios, and declared transition requirements.

## Dataset summary

- Dataset id: `{dataset_id}`
- Total cases: {case_count}
- Split seed: {seed}
- Train: {split_counts["train"]}
- Validation: {split_counts["validation"]}
- Test: {split_counts["test"]}

## Fields

- `requirements`: unique requirement identifiers referenced by the reference FSM transitions
- `reference_fsm`: ground-truth behavioural FSM
- `faulty_fsm`: mutated FSM to be repaired
- `bug_metadata`: mutation operator, seed, and bug description
- `oracle_suite`: behavioural scenarios used to score repairs
- `metadata`: benchmark case metadata such as difficulty and oracle coverage

## Usage

```python
from datasets import load_dataset

dataset = load_dataset(
    "json",
    data_files={{
        "train": "train.jsonl",
        "validation": "validation.jsonl",
        "test": "test.jsonl",
    }},
)
```

## Citation

If you use this dataset, please cite the FSMRepairBench benchmark toolkit.
"""


def _size_category(case_count: int) -> str:
    if case_count < 1000:
        return "n<1K"
    if case_count < 10000:
        return "1K<n<10K"
    if case_count < 100000:
        return "10K<n<100K"
    if case_count < 1000000:
        return "100K<n<1M"
    return "n>1M"


def export_huggingface_dataset(
    dataset_dir: Path,
    *,
    output_dir: Path | None = None,
) -> HuggingFaceExportResult:
    """Export a benchmark dataset directory to HuggingFace JSONL splits."""
    if not dataset_dir.is_dir():
        msg = f"Dataset directory not found: {dataset_dir}"
        raise HuggingFaceExportError(msg)

    case_dirs = discover_case_directories(dataset_dir)
    index_rows = load_dataset_cases(dataset_dir)
    if len(index_rows) != len(case_dirs):
        msg = (
            f"Index/case mismatch: {len(index_rows)} indexed rows vs "
            f"{len(case_dirs)} complete case directories"
        )
        raise HuggingFaceExportError(msg)

    records = [load_case_record(case_dir) for case_dir in case_dirs]
    seed = _load_split_seed(dataset_dir)
    train_records, validation_records, test_records = split_records(records, seed=seed)

    export_dir = output_dir or (dataset_dir / HF_DATASET_DIR_NAME)
    train_path = export_dir / "train.jsonl"
    validation_path = export_dir / "validation.jsonl"
    test_path = export_dir / "test.jsonl"
    dataset_card_path = export_dir / "README.md"

    write_jsonl(train_path, train_records)
    write_jsonl(validation_path, validation_records)
    write_jsonl(test_path, test_records)

    split_counts = {
        "train": len(train_records),
        "validation": len(validation_records),
        "test": len(test_records),
    }
    dataset_id = dataset_dir.name
    metadata_path = dataset_dir / "metadata.json"
    if metadata_path.is_file():
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
            dataset_id = str(payload.get("dataset_id", dataset_id))
        except (OSError, json.JSONDecodeError):
            pass

    dataset_card_path.write_text(
        generate_dataset_card(
            dataset_id=dataset_id,
            case_count=len(records),
            split_counts=split_counts,
            seed=seed,
        ),
        encoding="utf-8",
    )

    return HuggingFaceExportResult(
        dataset_dir=dataset_dir,
        output_dir=export_dir,
        train_path=train_path,
        validation_path=validation_path,
        test_path=test_path,
        dataset_card_path=dataset_card_path,
        split_counts=split_counts,
    )
