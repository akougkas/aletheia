"""LM Studio provider — chat, embed, model list/load/unload."""

from __future__ import annotations

import json
from typing import Any, AsyncGenerator

import httpx

from .base import AIProvider, Capability, Endpoint, ModelInfo


class LMStudioProvider(AIProvider):
    """Provider for LM Studio endpoints."""

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
        caps: set[Capability] = {Capability.MODEL_LIST}
        if "chat" in self.endpoint.roles:
            caps.add(Capability.CHAT)
        if "embed" in self.endpoint.roles:
            caps.add(Capability.EMBED)
        # LM Studio supports load/unload via its own API
        caps.add(Capability.MODEL_LOAD)
        caps.add(Capability.MODEL_UNLOAD)
        return caps

    async def health_check(self) -> dict[str, Any]:
        client = self._get_client()
        try:
            resp = await client.get("/v1/models")
            resp.raise_for_status()
            data = resp.json()
            models = data.get("data", [])
            return {
                "ok": True,
                "provider": "lmstudio",
                "model_count": len(models),
                "endpoint": self.endpoint.url,
            }
        except Exception as exc:
            return {
                "ok": False,
                "provider": "lmstudio",
                "error": str(exc),
                "endpoint": self.endpoint.url,
            }

    async def list_models(self) -> list[ModelInfo]:
        client = self._get_client()
        resp = await client.get("/v1/models")
        resp.raise_for_status()
        data = resp.json()
        result: list[ModelInfo] = []
        for m in data.get("data", []):
            model_id = m.get("id", "")
            result.append(
                ModelInfo(
                    name=model_id,
                    size_bytes=None,
                    quantization=None,
                    family=None,
                    parameter_count=None,
                    loaded=True,  # LM Studio /v1/models only shows loaded models
                    capabilities=_infer_capabilities(model_id),
                    provider="lmstudio",
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

    async def load_model(self, name: str) -> dict[str, Any]:
        """Load model via LM Studio API."""
        client = self._get_client()
        try:
            resp = await client.post(
                "/lmstudio/v1/models/load",
                json={"model": name},
                timeout=300.0,
            )
            resp.raise_for_status()
            return {"ok": True, "loaded": name}
        except httpx.HTTPStatusError:
            return {"ok": False, "error": "LM Studio load endpoint not available"}

    async def unload_model(self, name: str) -> dict[str, Any]:
        """Unload model via LM Studio API."""
        client = self._get_client()
        try:
            resp = await client.post(
                "/lmstudio/v1/models/unload",
                json={"model": name},
            )
            resp.raise_for_status()
            return {"ok": True, "unloaded": name}
        except httpx.HTTPStatusError:
            return {"ok": False, "error": "LM Studio unload endpoint not available"}


def _infer_capabilities(model_id: str) -> list[str]:
    lower = model_id.lower()
    if "embed" in lower:
        return ["embed"]
    return ["chat"]
