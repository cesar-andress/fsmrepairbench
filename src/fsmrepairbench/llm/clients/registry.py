"""Model client registry and model spec parsing."""

from __future__ import annotations

from typing import Any

from fsmrepairbench.llm.clients.base import ModelBackend, ModelClient, ModelSpec
from fsmrepairbench.llm.clients.ollama import client_from_spec as ollama_from_spec
from fsmrepairbench.llm.clients.openai_compat import (
    client_from_spec as openai_from_spec,
)
from fsmrepairbench.llm.clients.vllm import client_from_spec as vllm_from_spec

DEFAULT_BACKEND = ModelBackend.OLLAMA


class ModelRegistryError(ValueError):
    """Raised when a model specification cannot be resolved."""


def parse_model_spec(value: str | dict[str, Any], *, default_backend: ModelBackend) -> ModelSpec:
    """Parse a YAML model entry or plain model name."""
    if isinstance(value, str):
        return ModelSpec(name=value, backend=default_backend)

    if not isinstance(value, dict):
        msg = "Model entries must be strings or mappings"
        raise ModelRegistryError(msg)

    name = value.get("name")
    if not isinstance(name, str) or not name:
        msg = "Model mapping must include a non-empty 'name'"
        raise ModelRegistryError(msg)

    backend_raw = value.get("backend", default_backend.value)
    try:
        backend = ModelBackend(str(backend_raw))
    except ValueError as exc:
        msg = f"Unsupported model backend: {backend_raw!r}"
        raise ModelRegistryError(msg) from exc

    base_url = value.get("base_url")
    api_key = value.get("api_key")
    return ModelSpec(
        name=name,
        backend=backend,
        base_url=str(base_url) if base_url is not None else None,
        api_key=str(api_key) if api_key is not None else None,
    )


def parse_model_specs(
    models: list[str | dict[str, Any]],
    *,
    default_backend: ModelBackend = DEFAULT_BACKEND,
) -> list[ModelSpec]:
    """Parse all model entries from experiment configuration."""
    return [parse_model_spec(model, default_backend=default_backend) for model in models]


def create_model_client(spec: ModelSpec) -> ModelClient:
    """Instantiate the client for *spec*."""
    if spec.backend is ModelBackend.OLLAMA:
        return ollama_from_spec(spec)
    if spec.backend is ModelBackend.OPENAI:
        return openai_from_spec(spec)
    if spec.backend is ModelBackend.VLLM:
        return vllm_from_spec(spec)
    msg = f"Unsupported backend: {spec.backend}"
    raise ModelRegistryError(msg)


def client_label(spec: ModelSpec) -> str:
    """Return a stable label used for result filenames."""
    if spec.backend is ModelBackend.OLLAMA and spec.base_url is None:
        return spec.name
    return f"{spec.backend.value}::{spec.name}"
