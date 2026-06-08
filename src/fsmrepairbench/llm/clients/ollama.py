"""Ollama model client."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from fsmrepairbench.llm.clients.base import ModelBackend, ModelClientError, ModelSpec

OllamaHttpRunner = Callable[[str, str, float, str], str]
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"


class OllamaClient:
    """Client for the local Ollama generate API."""

    backend = ModelBackend.OLLAMA

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        http_runner: OllamaHttpRunner | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._http_runner = http_runner

    def generate(self, *, model: str, prompt: str, temperature: float) -> str:
        runner = self._http_runner or _default_http_runner
        try:
            return runner(model, prompt, temperature, self.base_url)
        except urllib.error.URLError as exc:
            msg = f"Failed to reach Ollama at {self.base_url}: {exc}"
            raise ModelClientError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = "Ollama returned a non-JSON response body"
            raise ModelClientError(msg) from exc


def _default_http_runner(model: str, prompt: str, temperature: float, base_url: str) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    request = urllib.request.Request(
        f"{base_url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))
    if "response" not in body:
        raise ModelClientError(f"Unexpected Ollama response: {body!r}")
    return str(body["response"])


def client_from_spec(spec: ModelSpec) -> OllamaClient:
    """Build an Ollama client from *spec*."""
    base_url = spec.base_url or DEFAULT_OLLAMA_BASE_URL
    return OllamaClient(base_url=base_url)
