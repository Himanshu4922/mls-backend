"""Minimal OpenAI REST client (chat + embeddings) over ``requests``.

The SDK is deliberately not used: the Vercel bundle is size-capped and the
three calls we make are plain JSON POSTs. Everything is configured from env:

- ``OPENAI_API_KEY`` (required to enable any AI feature)
- ``OPENAI_BASE_URL`` (default ``https://api.openai.com/v1``)
- ``OPENAI_SEARCH_MODEL`` — model that turns a search sentence into filters
- ``OPENAI_SUMMARY_MODEL`` — comma-separated, tried in order for summaries
- ``OPENAI_EMBEDDING_MODEL`` / ``OPENAI_EMBEDDING_DIMENSIONS`` — listing vectors

No ``temperature`` is sent: newer reasoning models reject non-default values,
and the structured-output schema already pins the shape of every answer.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import requests

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_CHAT_MODEL = "gpt-4.1-mini"
DEFAULT_EMBEDDING_MODEL = "text-embedding-3-small"
DEFAULT_EMBEDDING_DIMENSIONS = 512


class OpenAIError(Exception):
    """Any failure talking to OpenAI: not configured, HTTP error, bad payload."""


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


def api_key() -> str:
    return os.environ.get("OPENAI_API_KEY", "").strip()


def is_configured() -> bool:
    return bool(api_key())


def search_model() -> str:
    return os.environ.get("OPENAI_SEARCH_MODEL", "").strip() or DEFAULT_CHAT_MODEL


def summary_models() -> list[str]:
    raw = os.environ.get("OPENAI_SUMMARY_MODEL", "").strip() or DEFAULT_CHAT_MODEL
    return [m.strip() for m in raw.split(",") if m.strip()]


def embedding_model() -> str:
    return os.environ.get("OPENAI_EMBEDDING_MODEL", "").strip() or DEFAULT_EMBEDDING_MODEL


def embedding_dimensions() -> int:
    try:
        return int(os.environ.get("OPENAI_EMBEDDING_DIMENSIONS", DEFAULT_EMBEDDING_DIMENSIONS))
    except ValueError:
        return DEFAULT_EMBEDDING_DIMENSIONS


def _post(path: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
    key = api_key()
    if not key:
        raise OpenAIError("OPENAI_API_KEY is not configured on the backend.")
    base = os.environ.get("OPENAI_BASE_URL", "").strip().rstrip("/") or DEFAULT_BASE_URL
    try:
        response = requests.post(
            f"{base}{path}",
            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
            json=payload,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise OpenAIError(f"network error: {exc}") from exc
    if not response.ok:
        try:
            message = response.json().get("error", {}).get("message") or response.text
        except ValueError:
            message = response.text
        raise OpenAIError(f"[HTTP {response.status_code}] {message[:500]}")
    try:
        return response.json()
    except ValueError as exc:
        raise OpenAIError("OpenAI returned a non-JSON response.") from exc


def chat(
    messages: list[dict[str, str]],
    *,
    model: str,
    json_schema: dict[str, Any] | None = None,
    schema_name: str = "result",
    max_tokens: int = 800,
    timeout: float = 20,
) -> ChatResult:
    """One chat completion. With ``json_schema`` the reply is strict JSON."""
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_tokens,
    }
    if json_schema is not None:
        payload["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": schema_name, "strict": True, "schema": json_schema},
        }
    data = _post("/chat/completions", payload, timeout)
    try:
        choice = data["choices"][0]
        message = choice["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise OpenAIError("OpenAI response had no choices.") from exc
    if message.get("refusal"):
        raise OpenAIError(f"model refused: {message['refusal'][:200]}")
    content = (message.get("content") or "").strip()
    if not content:
        reason = choice.get("finish_reason") or "unknown"
        raise OpenAIError(f"empty completion (finish_reason={reason}).")
    usage = data.get("usage") or {}
    return ChatResult(
        content=content,
        model=data.get("model") or model,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        raw=data,
    )


def embed(texts: list[str], *, timeout: float = 30) -> list[list[float]]:
    """Embeddings for ``texts``, in input order."""
    if not texts:
        return []
    data = _post(
        "/embeddings",
        {
            "model": embedding_model(),
            "input": texts,
            "dimensions": embedding_dimensions(),
        },
        timeout,
    )
    try:
        rows = sorted(data["data"], key=lambda row: row["index"])
        vectors = [row["embedding"] for row in rows]
    except (KeyError, TypeError) as exc:
        raise OpenAIError("OpenAI embeddings response was malformed.") from exc
    if len(vectors) != len(texts):
        raise OpenAIError("OpenAI returned a different number of embeddings than inputs.")
    return vectors
