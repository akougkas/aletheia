"""LLM client for llama.cpp server."""

import httpx
from typing import AsyncGenerator, Optional
from pydantic import BaseModel


class LLMConfig(BaseModel):
    """Configuration for llama.cpp server connection."""
    base_url: str = "http://mini:8080"
    timeout: float = 120.0


class LLMClient:
    """Async client for llama.cpp server's OpenAI-compatible API."""

    def __init__(self, config: Optional[LLMConfig] = None):
        self.config = config or LLMConfig()
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                timeout=self.config.timeout,
            )
        return self._client

    async def close(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    async def complete(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list[str]] = None,
    ) -> str:
        """Generate a completion (non-streaming)."""
        client = await self._get_client()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = await client.post(
            "/v1/chat/completions",
            json={
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stop": stop,
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content", "")
        # Handle reasoning models: if content empty but reasoning exists, extract JSON from reasoning
        if not content and msg.get("reasoning_content"):
            import re
            json_match = re.search(r'\{[^{}]*\}', msg["reasoning_content"])
            if json_match:
                content = json_match.group(0)
        return content

    async def stream(
        self,
        prompt: str,
        *,
        system: Optional[str] = None,
        temperature: float = 0.7,
        max_tokens: int = 2048,
        stop: Optional[list[str]] = None,
    ) -> AsyncGenerator[str, None]:
        """Generate a completion with streaming."""
        client = await self._get_client()

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        async with client.stream(
            "POST",
            "/v1/chat/completions",
            json={
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stop": stop,
                "stream": True,
            },
        ) as response:
            response.raise_for_status()
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    data = line[6:]
                    if data.strip() == "[DONE]":
                        break
                    import json
                    chunk = json.loads(data)
                    if delta := chunk["choices"][0].get("delta", {}).get("content"):
                        yield delta

    async def embed(self, text: str) -> list[float]:
        """Get embedding vector for text."""
        client = await self._get_client()
        response = await client.post(
            "/v1/embeddings",
            json={"input": text},
        )
        response.raise_for_status()
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


if __name__ == "__main__":
    import asyncio
    import json

    result = asyncio.run(test_llm())
    print(json.dumps(result, indent=2))
