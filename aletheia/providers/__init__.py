"""Provider registry — factory, detection, endpoint probing."""

from __future__ import annotations

from typing import Any

import httpx

from .base import AIProvider, Capability, Endpoint, ModelInfo
from .lmstudio import LMStudioProvider
from .ollama import OllamaProvider
from .openai_compat import OpenAICompatProvider

__all__ = [
    "AIProvider",
    "Capability",
    "Endpoint",
    "LMStudioProvider",
    "ModelInfo",
    "OllamaProvider",
    "OpenAICompatProvider",
    "detect_provider",
    "get_provider",
    "probe_endpoint",
    "register_endpoints",
    "get_configured_endpoints",
]

# --- Endpoint registry (populated by runtime_profiles YAML config) ---
_configured_endpoints: dict[str, Endpoint] = {}
_chat_endpoint_name: str | None = None
_embed_endpoint_name: str | None = None


def register_endpoints(
    endpoints: dict[str, Endpoint],
    *,
    chat_endpoint: str | None = None,
    embed_endpoint: str | None = None,
) -> None:
    """Register endpoint configs from YAML/profile resolution."""
    _configured_endpoints.clear()
    _configured_endpoints.update(endpoints)
    global _chat_endpoint_name, _embed_endpoint_name
    _chat_endpoint_name = chat_endpoint
    _embed_endpoint_name = embed_endpoint


def get_configured_endpoints() -> dict[str, Endpoint]:
    """Return all registered endpoints."""
    return dict(_configured_endpoints)


def _active_chat_endpoint() -> Endpoint | None:
    """Return the currently configured chat endpoint, if any."""
    if _chat_endpoint_name and _chat_endpoint_name in _configured_endpoints:
        return _configured_endpoints[_chat_endpoint_name]
    return None


def _active_embed_endpoint() -> Endpoint | None:
    """Return the currently configured embed endpoint, if any."""
    if _embed_endpoint_name and _embed_endpoint_name in _configured_endpoints:
        return _configured_endpoints[_embed_endpoint_name]
    return None


_PROVIDER_CLASSES: dict[str, type[AIProvider]] = {
    "ollama": OllamaProvider,
    "lmstudio": LMStudioProvider,
    "openai_compat": OpenAICompatProvider,
}


def get_provider(endpoint: Endpoint) -> AIProvider:
    """Return a concrete provider instance for the given endpoint config."""
    cls = _PROVIDER_CLASSES.get(endpoint.provider_type)
    if cls is None:
        raise ValueError(
            f"Unknown provider type '{endpoint.provider_type}'. "
            f"Valid types: {', '.join(_PROVIDER_CLASSES)}"
        )
    return cls(endpoint)


async def detect_provider(url: str, *, timeout: float = 5.0) -> str:
    """Probe a URL to determine provider type.

    Detection order:
    1. Ollama — responds to GET /api/tags
    2. LM Studio — responds to GET /v1/models with LM Studio markers
    3. Generic OpenAI-compat fallback
    """
    base = url.rstrip("/")
    async with httpx.AsyncClient(timeout=timeout) as client:
        # Try Ollama native API
        try:
            resp = await client.get(f"{base}/api/tags")
            if resp.status_code == 200:
                data = resp.json()
                if "models" in data:
                    return "ollama"
        except Exception:
            pass

        # Try /v1/models and look for LM Studio markers
        try:
            resp = await client.get(f"{base}/v1/models")
            if resp.status_code == 200:
                data = resp.json()
                # LM Studio includes specific markers in its response
                raw_text = resp.text.lower()
                if "lmstudio" in raw_text or "lm studio" in raw_text:
                    return "lmstudio"
                # Also check if /lmstudio path responds
                try:
                    lms_resp = await client.get(f"{base}/lmstudio/v1/models")
                    if lms_resp.status_code == 200:
                        return "lmstudio"
                except Exception:
                    pass
                # Has /v1/models but not identifiable — generic
                return "openai_compat"
        except Exception:
            pass

    return "openai_compat"


async def probe_endpoint(url: str, *, timeout: float = 8.0) -> dict[str, Any]:
    """Full endpoint probe: detect type, list models, check health."""
    provider_type = await detect_provider(url, timeout=timeout)
    endpoint = Endpoint(
        name="probe",
        url=url,
        provider_type=provider_type,
        roles=["chat", "embed"],
    )
    provider = get_provider(endpoint)
    try:
        health = await provider.health_check()
        models: list[dict[str, Any]] = []
        try:
            model_list = await provider.list_models()
            models = [
                {
                    "name": m.name,
                    "size_bytes": m.size_bytes,
                    "quantization": m.quantization,
                    "family": m.family,
                    "parameter_count": m.parameter_count,
                    "capabilities": m.capabilities,
                }
                for m in model_list
            ]
        except Exception as exc:
            health["model_list_error"] = str(exc)

        return {
            "url": url,
            "provider_type": provider_type,
            "health": health,
            "models": models,
        }
    finally:
        await provider.close()
