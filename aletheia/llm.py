"""LLM client for OpenAI-compatible endpoints."""

import json
import os
import re
from dataclasses import dataclass
from typing import AsyncGenerator, Optional

import httpx
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Reasoning / thinking token handling
# ---------------------------------------------------------------------------
# Different providers use different field names for reasoning tokens:
#   LM Studio (DeepSeek-style): reasoning_content  (message & delta)
#   LM Studio (gpt-oss style): reasoning           (message & delta)
#   Ollama native /api/chat:   thinking             (message)
#   Ollama OpenAI-compat /v1:  reasoning            (message & delta)
#   OpenAI o-series:           reasoning_content    (message & delta)
#
# Some models also emit inline <think>...</think> tags inside the content
# field (Qwen3, DeepSeek-R1 when LM Studio reasoning extraction is off).
# ---------------------------------------------------------------------------

_THINK_TAG_RE = re.compile(
    r"<think>(.*?)</think>",
    re.DOTALL,
)

_REASONING_KEYS = ("reasoning_content", "reasoning", "thinking")


def _strip_think_tags(text: str) -> tuple[str, str]:
    """Split inline <think> blocks from content.

    Returns (clean_content, reasoning_text).
    """
    reasoning_parts: list[str] = []
    clean = text
    for match in _THINK_TAG_RE.finditer(text):
        reasoning_parts.append(match.group(1).strip())
    if reasoning_parts:
        clean = _THINK_TAG_RE.sub("", text).strip()
    return clean, "\n".join(reasoning_parts)


@dataclass(frozen=True)
class CompletionResult:
    """LLM response with separated content and reasoning."""

    content: str
    reasoning: str

    def __str__(self) -> str:
        return self.content

    def __bool__(self) -> bool:
        return bool(self.content)


class LLMConfig(BaseModel):
    """Configuration for OpenAI-compatible chat + embedding services."""

    base_url: str = Field(
        default_factory=lambda: os.environ.get("ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234")
    )
    embed_base_url: str = Field(
        default_factory=lambda: os.environ.get(
            "ALETHEIA_EMBED_BASE_URL",
            os.environ.get("ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234"),
        )
    )
    model: str | None = Field(default_factory=lambda: os.environ.get("ALETHEIA_LLM_MODEL"))
    embed_model: str | None = Field(default_factory=lambda: os.environ.get("ALETHEIA_EMBED_MODEL"))
    api_key: str | None = Field(default_factory=lambda: os.environ.get("ALETHEIA_LLM_API_KEY"))
    embed_api_key: str | None = Field(
        default_factory=lambda: os.environ.get("ALETHEIA_EMBED_API_KEY")
    )
    timeout: float = 120.0


class LLMClient:
    """Async client for llama.cpp server's OpenAI-compatible API."""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config
        self._client: Optional[httpx.AsyncClient] = None
        self._embed_client: Optional[httpx.AsyncClient] = None

    def _effective_config(self) -> LLMConfig:
        # Lazily resolve env-backed config so profile selection can happen before first request.
        if self.config is None:
            self.config = LLMConfig()
        return self.config

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            config = self._effective_config()
            headers = {}
            if config.api_key:
                headers["Authorization"] = f"Bearer {config.api_key}"
            self._client = httpx.AsyncClient(
                base_url=config.base_url,
                timeout=config.timeout,
                headers=headers,
            )
        return self._client

    async def _get_embed_client(self) -> httpx.AsyncClient:
        if self._embed_client is None:
            config = self._effective_config()
            headers = {}
            if config.embed_api_key:
                headers["Authorization"] = f"Bearer {config.embed_api_key}"
            self._embed_client = httpx.AsyncClient(
                base_url=config.embed_base_url,
                timeout=config.timeout,
                headers=headers,
            )
        return self._embed_client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._embed_client:
            await self._embed_client.aclose()
            self._embed_client = None

    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list[str]] = None,
    ) -> str:
        """Generate a completion (non-streaming). Returns content only."""
        result = await self.complete_with_reasoning(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
        )
        return result.content

    async def complete_with_reasoning(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list[str]] = None,
    ) -> CompletionResult:
        """Generate a completion with separated reasoning tokens."""
        client = await self._get_client()
        config = self._effective_config()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop": stop,
            "stream": False,
        }
        if config.model:
            payload["model"] = config.model

        response = await client.post("/v1/chat/completions", json=payload)
        response.raise_for_status()
        data = response.json()
        return _extract_completion_result(data)

    async def stream(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list[str]] = None,
    ) -> AsyncGenerator[tuple[str, str], None]:
        """Generate a completion with streaming.

        Yields ``(kind, token)`` tuples where *kind* is ``"content"`` or
        ``"reasoning"``.  Callers that only care about final text can ignore
        the tag or use :meth:`stream_content`.
        """
        client = await self._get_client()
        config = self._effective_config()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stop": stop,
            "stream": True,
        }
        if config.model:
            payload["model"] = config.model

        async with client.stream("POST", "/v1/chat/completions", json=payload) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    chunk = json.loads(data)
                    delta = chunk.get("choices", [{}])[0].get("delta", {})

                    # Content token
                    content_token = delta.get("content")
                    if content_token:
                        yield ("content", content_token)

                    # Reasoning token — check all provider field names
                    for key in _REASONING_KEYS:
                        reasoning_token = delta.get(key)
                        if reasoning_token:
                            yield ("reasoning", reasoning_token)
                            break

    async def stream_content(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """Convenience streaming that yields only content tokens (no reasoning)."""
        async for kind, token in self.stream(
            prompt,
            system=system,
            temperature=temperature,
            max_tokens=max_tokens,
            stop=stop,
        ):
            if kind == "content":
                yield token

    async def embed(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        client = await self._get_embed_client()
        config = self._effective_config()
        payload = {"input": text}
        model = config.embed_model or config.model
        if model:
            payload["model"] = model

        response = await client.post("/v1/embeddings", json=payload)
        if response.status_code >= 400:
            detail = _extract_error_detail(response)
            if "model" in detail.lower() and "required" in detail.lower():
                raise RuntimeError(
                    "Embedding endpoint requires an explicit model; set ALETHEIA_EMBED_MODEL."
                )
            raise httpx.HTTPStatusError(
                f"Embedding request failed: {response.status_code} {detail}",
                request=response.request,
                response=response,
            )
        data = response.json()
        return data["data"][0]["embedding"]


# Default client instance
llm = LLMClient()


async def test_llm() -> dict:
    """Test LLM connection."""
    client = LLMClient()
    try:
        # Test completion
        response = await client.complete(
            "Say 'hello' and nothing else.",
            max_tokens=10,
        )

        # Test embedding (may not be available on all setups)
        try:
            embedding = await client.embed("test")
            embed_dim = len(embedding)
        except Exception:
            embed_dim = None

        return {
            "completion_ok": True,
            "response_sample": response[:50],
            "embedding_dim": embed_dim,
        }
    finally:
        await client.close()


def _extract_error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return (response.text or "").strip()[:200]

    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            message = err.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return (response.text or "").strip()[:200]


def _extract_completion_result(payload: dict) -> CompletionResult:
    """Extract content and reasoning from a chat completion response."""
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return CompletionResult(content="", reasoning="")

    first_choice = choices[0] if isinstance(choices[0], dict) else {}
    message = first_choice.get("message")
    if isinstance(message, dict):
        return _extract_message_parts(message)

    # Legacy: plain text field on choice
    text_field = first_choice.get("text")
    if isinstance(text_field, str):
        return CompletionResult(content=text_field.strip(), reasoning="")
    return CompletionResult(content="", reasoning="")


def _extract_completion_text(payload: dict) -> str:
    """Backward-compatible: extract only the content string."""
    return _extract_completion_result(payload).content


def _extract_message_parts(message: dict) -> CompletionResult:
    """Extract both content and reasoning from a message dict.

    Handles all known provider formats:
    - Separate fields: reasoning_content, reasoning, thinking
    - Inline tags: <think>...</think> inside content
    - Structured content (list of text items)
    """
    # --- Gather raw content ---
    raw_content = ""
    content = message.get("content")
    if isinstance(content, str):
        raw_content = content.strip()
    elif isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str) and item.strip():
                parts.append(item.strip())
            elif isinstance(item, dict):
                text = item.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text.strip())
        raw_content = "\n".join(parts)

    # --- Gather reasoning from dedicated fields ---
    reasoning_parts: list[str] = []
    for key in _REASONING_KEYS:
        value = message.get(key)
        text = _value_as_text(value)
        if text:
            reasoning_parts.append(text)

    # --- Handle inline <think> tags in content ---
    clean_content, inline_reasoning = _strip_think_tags(raw_content)
    if inline_reasoning:
        reasoning_parts.append(inline_reasoning)

    reasoning = "\n".join(reasoning_parts).strip()

    # If content is empty but reasoning has what looks like the actual answer
    # (some models put everything in reasoning_content when content is blank),
    # use reasoning as content.
    if not clean_content and reasoning:
        return CompletionResult(content=reasoning, reasoning="")

    return CompletionResult(content=clean_content, reasoning=reasoning)


def _extract_message_text(message: dict) -> str:
    """Backward-compatible: extract only the content string."""
    return _extract_message_parts(message).content


def _value_as_text(value: object) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        return json.dumps(value)
    if isinstance(value, list):
        items: list[str] = []
        for entry in value:
            if isinstance(entry, str) and entry.strip():
                items.append(entry.strip())
            elif isinstance(entry, dict):
                text = entry.get("text")
                if isinstance(text, str) and text.strip():
                    items.append(text.strip())
        return "\n".join(items).strip()
    return ""


if __name__ == "__main__":
    import asyncio

    result = asyncio.run(test_llm())
    print(json.dumps(result, indent=2))
