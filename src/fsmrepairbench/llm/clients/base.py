"""Model client abstractions for LLM repair backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class ModelBackend(StrEnum):
    """Supported LLM inference backends."""

    OLLAMA = "ollama"
    OPENAI = "openai"
    VLLM = "vllm"


@dataclass(frozen=True)
class ModelSpec:
    """Configuration for one model endpoint."""

    name: str
    backend: ModelBackend = ModelBackend.OLLAMA
    base_url: str | None = None
    api_key: str | None = None


class ModelClient(Protocol):
    """Protocol implemented by all LLM inference clients."""

    backend: ModelBackend

    def generate(self, *, model: str, prompt: str, temperature: float) -> str:
        """Generate text from *prompt* using *model*."""


class ModelClientError(RuntimeError):
    """Raised when an LLM client request fails."""
