"""A minimal client for any OpenAI-compatible /chat/completions server (llama.cpp, Ollama,
vLLM), over httpx with streaming. No SDK: the API surface used is one POST and its
Server-Sent Events, and an SDK would tie us to one vendor's quirks."""

import json
import logging
from collections.abc import Iterator

import httpx
from django.conf import settings

from copilot.prompt import REQUEST_PARAMS

log = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """The server could not be reached, timed out, or answered with an error."""


def _headers() -> dict:
    h = {"Content-Type": "application/json", "Accept": "text/event-stream"}
    if settings.LLM_API_KEY:
        h["Authorization"] = f"Bearer {settings.LLM_API_KEY}"
    return h


def _timeout() -> httpx.Timeout:
    # Connecting must be quick (a dead server should fall back to extractive answers at
    # once); reading may take as long as a slow CPU needs between tokens.
    return httpx.Timeout(settings.LLM_TIMEOUT_SECONDS, connect=5.0)


def stream_chat(messages: list[dict], *, max_tokens: int | None = None) -> Iterator[str]:
    """Yields content deltas as they arrive. Raises LLMUnavailable on any transport or
    HTTP error, including one in the middle of the stream."""
    body = {
        "model": settings.LLM_MODEL,
        "messages": messages,
        "stream": True,
        **REQUEST_PARAMS,
        "max_tokens": max_tokens or settings.LLM_MAX_TOKENS,
    }
    url = f"{settings.LLM_BASE_URL}/chat/completions"
    try:
        with (
            httpx.Client(timeout=_timeout()) as client,
            client.stream("POST", url, json=body, headers=_headers()) as resp,
        ):
            if resp.status_code != 200:
                resp.read()
                raise LLMUnavailable(f"LLM HTTP {resp.status_code}: {resp.text[:200]}")
            for line in resp.iter_lines():
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    return
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                if event.get("error"):
                    raise LLMUnavailable(f"LLM error: {event['error']}")
                for choice in event.get("choices") or []:
                    # reasoning_content (thinking) is ignored on purpose.
                    text = (choice.get("delta") or {}).get("content")
                    if text:
                        yield text
    except httpx.HTTPError as exc:
        raise LLMUnavailable(f"{type(exc).__name__}: {exc}") from exc


def status() -> dict:
    """{available, model} from GET /models, with a short timeout (for GET /status)."""
    try:
        resp = httpx.get(
            f"{settings.LLM_BASE_URL}/models", headers=_headers(), timeout=httpx.Timeout(3.0)
        )
        ok = resp.status_code == 200
    except httpx.HTTPError:
        ok = False
    return {"available": ok, "model": settings.LLM_MODEL}
