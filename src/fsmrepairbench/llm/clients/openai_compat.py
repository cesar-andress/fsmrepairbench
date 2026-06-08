"""OpenAI-compatible chat completion client."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Callable

from fsmrepairbench.llm.clients.base import ModelBackend, ModelClientError, ModelSpec

OpenAIHttpRunner = Callable[[str, str, float, str, str | None], str]
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


class OpenAICompatibleClient:
    """Client for OpenAI-compatible ``/v1/chat/completions`` APIs."""

    backend = ModelBackend.OPENAI

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        api_key: str | None = None,
        http_runner: OpenAIHttpRunner | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self._http_runner = http_runner

    def generate(self, *, model: str, prompt: str, temperature: float) -> str:
        runner = self._http_runner or _default_http_runner
        try:
            return runner(model, prompt, temperature, self.base_url, self.api_key)
        except urllib.error.URLError as exc:
            msg = f"Failed to reach OpenAI-compatible API at {self.base_url}: {exc}"
            raise ModelClientError(msg) from exc
        except json.JSONDecodeError as exc:
            msg = "OpenAI-compatible API returned a non-JSON response body"
            raise ModelClientError(msg) from exc


def _default_http_runner(
    model: str,
    prompt: str,
    temperature: float,
    base_url: str,
    api_key: str | None,
) -> str:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
    }
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=120) as response:
        body = json.loads(response.read().decode("utf-8"))

    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ModelClientError(f"Unexpected OpenAI-compatible response: {body!r}")

    message = choices[0].get("message", {})
    content = message.get("content")
    if not isinstance(content, str):
        raise ModelClientError(f"Missing message content in response: {body!r}")
    return content


def client_from_spec(spec: ModelSpec) -> OpenAICompatibleClient:
    """Build an OpenAI-compatible client from *spec*."""
    base_url = spec.base_url or DEFAULT_OPENAI_BASE_URL
    return OpenAICompatibleClient(base_url=base_url, api_key=spec.api_key)
