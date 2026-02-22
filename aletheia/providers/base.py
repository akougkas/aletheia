"""Provider abstraction layer for AI endpoints."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, Callable


class Capability(enum.Enum):
    """Operations an AI provider can support."""

    CHAT = "chat"
    EMBED = "embed"
    MODEL_LIST = "model_list"
    MODEL_PULL = "model_pull"
    MODEL_DELETE = "model_delete"
    MODEL_LOAD = "model_load"
    MODEL_UNLOAD = "model_unload"
    MODEL_INFO = "model_info"


@dataclass
class Endpoint:
    """A configured AI endpoint."""

    name: str  # e.g. "zbook-ollama"
    url: str  # e.g. "http://127.0.0.1:11434"
    provider_type: str  # "ollama" | "lmstudio" | "openai_compat"
    roles: list[str]  # ["chat", "embed"]
    api_key: str | None = None
    default_chat_model: str | None = None
    default_embed_model: str | None = None


@dataclass
class ModelInfo:
    """Metadata about a model available on an endpoint."""

    name: str
    size_bytes: int | None = None
    quantization: str | None = None
    family: str | None = None
    parameter_count: str | None = None
    loaded: bool = False
    capabilities: list[str] = field(default_factory=list)
    provider: str = ""
    endpoint_name: str = ""


@dataclass
class ChatResponse:
    """Raw response from a provider chat call (pre-reasoning-extraction)."""

    raw_data: dict[str, Any]


class AIProvider(ABC):
    """Abstract base for AI provider backends."""

    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint

    @abstractmethod
    async def health_check(self) -> dict[str, Any]:
        """Check endpoint connectivity. Returns dict with 'ok' bool + details."""

    @abstractmethod
    def capabilities(self) -> set[Capability]:
        """Return the set of operations this provider supports."""

    @abstractmethod
    async def list_models(self) -> list[ModelInfo]:
        """List models available on this endpoint."""

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        """Send a chat completion request. Returns raw response dict."""
        raise NotImplementedError(f"{type(self).__name__} does not support chat")

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Stream chat completion. Yields raw SSE chunk dicts."""
        raise NotImplementedError(f"{type(self).__name__} does not support streaming")
        # Make this a generator for type-checking
        yield {}  # pragma: no cover

    async def embed(self, text: str | list[str], *, model: str | None = None) -> list[list[float]]:
        """Get embedding vectors. Returns list of vectors (one per input)."""
        raise NotImplementedError(f"{type(self).__name__} does not support embeddings")

    async def pull_model(
        self,
        name: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """Pull/download a model. Returns status dict."""
        raise NotImplementedError(f"{type(self).__name__} does not support model pulling")

    async def delete_model(self, name: str) -> dict[str, Any]:
        """Delete a model. Returns status dict."""
        raise NotImplementedError(f"{type(self).__name__} does not support model deletion")

    async def load_model(self, name: str) -> dict[str, Any]:
        """Load a model into memory. Returns status dict."""
        raise NotImplementedError(f"{type(self).__name__} does not support model loading")

    async def unload_model(self, name: str) -> dict[str, Any]:
        """Unload a model from memory. Returns status dict."""
        raise NotImplementedError(f"{type(self).__name__} does not support model unloading")

    async def model_info(self, name: str) -> ModelInfo:
        """Get detailed info about a specific model."""
        raise NotImplementedError(f"{type(self).__name__} does not support model info")

    async def close(self) -> None:
        """Clean up resources."""

    def _resolve_model(self, model: str | None, *, role: str) -> str | None:
        """Resolve model name from explicit arg or endpoint defaults."""
        if model:
            return model
        if role == "chat":
            return self.endpoint.default_chat_model
        if role == "embed":
            return self.endpoint.default_embed_model
        return None
