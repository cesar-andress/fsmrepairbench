"""vLLM model client (OpenAI-compatible serving endpoint)."""

from __future__ import annotations

from fsmrepairbench.llm.clients.base import ModelBackend, ModelSpec
from fsmrepairbench.llm.clients.openai_compat import OpenAICompatibleClient

DEFAULT_VLLM_BASE_URL = "http://localhost:8000/v1"


class VLLMClient(OpenAICompatibleClient):
    """Client for vLLM's OpenAI-compatible REST API."""

    backend = ModelBackend.VLLM


def client_from_spec(spec: ModelSpec) -> VLLMClient:
    """Build a vLLM client from *spec*."""
    base_url = spec.base_url or DEFAULT_VLLM_BASE_URL
    return VLLMClient(base_url=base_url, api_key=spec.api_key)
