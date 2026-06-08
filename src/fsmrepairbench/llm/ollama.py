"""Ollama-based LLM repair runner."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from fsmrepairbench.llm.prompts import (
    build_repair_prompt,
    extract_json_object,
    parse_patch_response,
)
from fsmrepairbench.llm.repair import run_llm_repair_with_client
from fsmrepairbench.models import FSM, OracleSuite, RepairResult

OllamaRunner = Callable[[str, str, float], str]

OLLAMA_GENERATE_URL = "http://localhost:11434/api/generate"


class OllamaError(RuntimeError):
    """Raised when Ollama cannot be reached or returns an invalid response."""


def run_ollama(
    model: str,
    prompt: str,
    temperature: float = 0.0,
    *,
    runner: OllamaRunner | None = None,
) -> str:
    """Call a local Ollama model and return the response text."""
    call = runner or _call_ollama_http
    return call(model, prompt, temperature)


def _call_ollama_http(model: str, prompt: str, temperature: float) -> str:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature},
    }
    request = urllib.request.Request(
        OLLAMA_GENERATE_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as exc:
        msg = f"Failed to reach Ollama at {OLLAMA_GENERATE_URL}: {exc}"
        raise OllamaError(msg) from exc
    except json.JSONDecodeError as exc:
        msg = "Ollama returned a non-JSON response body"
        raise OllamaError(msg) from exc

    if "response" not in body:
        raise OllamaError(f"Unexpected Ollama response: {body!r}")
    return str(body["response"])


def run_llm_repair_case(
    faulty_fsm: FSM,
    oracle_suite: OracleSuite,
    model: str,
    max_iterations: int,
    temperature: float = 0.0,
    *,
    ollama_runner: OllamaRunner | None = None,
) -> RepairResult:
    """Iteratively ask Ollama for repair patches and re-score the FSM."""
    if ollama_runner is not None:
        return run_llm_repair_with_client(
            faulty_fsm,
            oracle_suite,
            model=model,
            max_iterations=max_iterations,
            temperature=temperature,
            generate_fn=ollama_runner,
        )

    return run_llm_repair_with_client(
        faulty_fsm,
        oracle_suite,
        model=model,
        max_iterations=max_iterations,
        temperature=temperature,
        generate_fn=run_ollama,
    )


__all__ = [
    "OllamaError",
    "OllamaRunner",
    "build_repair_prompt",
    "extract_json_object",
    "parse_patch_response",
    "run_llm_repair_case",
    "run_ollama",
]
