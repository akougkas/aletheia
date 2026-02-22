"""Ollama provider — full model management via REST API."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator, Callable

import httpx

from .base import AIProvider, Capability, Endpoint, ModelInfo


class OllamaProvider(AIProvider):
    """Provider for Ollama endpoints with full model lifecycle support."""

    def __init__(self, endpoint: Endpoint) -> None:
        super().__init__(endpoint)
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            base = self.endpoint.url.rstrip("/")
            headers: dict[str, str] = {}
            if self.endpoint.api_key:
                headers["Authorization"] = f"Bearer {self.endpoint.api_key}"
            self._client = httpx.AsyncClient(
                base_url=base,
                timeout=120.0,
                headers=headers,
            )
        return self._client

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def capabilities(self) -> set[Capability]:
        caps = {
            Capability.MODEL_LIST,
            Capability.MODEL_PULL,
            Capability.MODEL_DELETE,
            Capability.MODEL_LOAD,
            Capability.MODEL_UNLOAD,
            Capability.MODEL_INFO,
        }
        if "chat" in self.endpoint.roles:
            caps.add(Capability.CHAT)
        if "embed" in self.endpoint.roles:
            caps.add(Capability.EMBED)
        return caps

    async def health_check(self) -> dict[str, Any]:
        client = self._get_client()
        try:
            resp = await client.get("/api/tags")
            resp.raise_for_status()
            data = resp.json()
            models = data.get("models", [])
            return {
                "ok": True,
                "provider": "ollama",
                "model_count": len(models),
                "endpoint": self.endpoint.url,
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": "ollama",
                "error": str(exc),
                "endpoint": self.endpoint.url,
            }

    async def list_models(self) -> list[ModelInfo]:
        client = self._get_client()
        resp = await client.get("/api/tags")
        resp.raise_for_status()
        data = resp.json()
        result: list[ModelInfo] = []
        for m in data.get("models", []):
            details = m.get("details", {})
            result.append(
                ModelInfo(
                    name=m.get("name", ""),
                    size_bytes=m.get("size"),
                    quantization=details.get("quantization_level"),
                    family=details.get("family"),
                    parameter_count=details.get("parameter_size"),
                    loaded=False,  # Ollama /api/tags doesn't indicate loaded state
                    capabilities=_infer_capabilities(m.get("name", ""), details),
                    provider="ollama",
                    endpoint_name=self.endpoint.name,
                )
            )
        return result

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
        client = self._get_client()
        resolved = self._resolve_model(model, role="chat")
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if resolved:
            payload["model"] = resolved
        if stop:
            payload["stop"] = stop
        resp = await client.post("/v1/chat/completions", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: list[str] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        client = self._get_client()
        resolved = self._resolve_model(model, role="chat")
        payload: dict[str, Any] = {
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if resolved:
            payload["model"] = resolved
        if stop:
            payload["stop"] = stop
        async with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    yield json.loads(data)

    async def embed(self, text: str | list[str], *, model: str | None = None) -> list[list[float]]:
        client = self._get_client()
        resolved = self._resolve_model(model, role="embed")
        inputs = [text] if isinstance(text, str) else text
        payload: dict[str, Any] = {"input": inputs}
        if resolved:
            payload["model"] = resolved
        resp = await client.post("/v1/embeddings", json=payload)
        resp.raise_for_status()
        data = resp.json()
        return [item["embedding"] for item in data["data"]]

    async def pull_model(
        self,
        name: str,
        *,
        progress_callback: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        client = self._get_client()
        async with client.stream(
            "POST",
            "/api/pull",
            json={"name": name, "stream": True},
            timeout=600.0,
        ) as resp:
            resp.raise_for_status()
            last_status: dict[str, Any] = {}
            async for line in resp.aiter_lines():
                if not line.strip():
                    continue
                chunk = json.loads(line)
                last_status = chunk
                if progress_callback:
                    progress_callback(chunk)
            return last_status

    async def delete_model(self, name: str) -> dict[str, Any]:
        client = self._get_client()
        resp = await client.request("DELETE", "/api/delete", json={"name": name})
        resp.raise_for_status()
        return {"ok": True, "deleted": name}

    async def load_model(self, name: str) -> dict[str, Any]:
        """Load model into memory using keep_alive=-1 (stay loaded)."""
        client = self._get_client()
        resp = await client.post(
            "/api/generate",
            json={"model": name, "keep_alive": -1, "prompt": ""},
            timeout=300.0,
        )
        resp.raise_for_status()
        return {"ok": True, "loaded": name}

    async def unload_model(self, name: str) -> dict[str, Any]:
        """Unload model from memory using keep_alive=0."""
        client = self._get_client()
        resp = await client.post(
            "/api/generate",
            json={"model": name, "keep_alive": 0, "prompt": ""},
        )
        resp.raise_for_status()
        return {"ok": True, "unloaded": name}

    async def model_info(self, name: str) -> ModelInfo:
        client = self._get_client()
        resp = await client.post("/api/show", json={"name": name})
        resp.raise_for_status()
        data = resp.json()
        details = data.get("details", {})
        model_info = data.get("model_info", {})
        return ModelInfo(
            name=name,
            size_bytes=None,  # /api/show doesn't return size directly
            quantization=details.get("quantization_level"),
            family=details.get("family"),
            parameter_count=details.get("parameter_size"),
            loaded=False,
            capabilities=_infer_capabilities(name, details),
            provider="ollama",
            endpoint_name=self.endpoint.name,
        )


def _infer_capabilities(name: str, details: dict[str, Any]) -> list[str]:
    """Best-effort capability inference from model name and details."""
    lower = name.lower()
    caps: list[str] = []
    if "embed" in lower:
        caps.append("embed")
    else:
        caps.append("chat")
    return caps
