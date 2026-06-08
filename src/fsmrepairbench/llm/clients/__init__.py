"""Shared LLM clients package."""

from fsmrepairbench.llm.clients.base import ModelBackend, ModelClient, ModelClientError, ModelSpec
from fsmrepairbench.llm.clients.registry import (
    create_model_client,
    parse_model_spec,
    parse_model_specs,
)

__all__ = [
    "ModelBackend",
    "ModelClient",
    "ModelClientError",
    "ModelSpec",
    "create_model_client",
    "parse_model_spec",
    "parse_model_specs",
]
