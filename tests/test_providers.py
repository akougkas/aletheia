"""Unit tests for AI provider abstraction layer."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aletheia.providers import (
    Capability,
    Endpoint,
    ModelInfo,
    get_provider,
    detect_provider,
    probe_endpoint,
)
from aletheia.providers.ollama import OllamaProvider
from aletheia.providers.lmstudio import LMStudioProvider
from aletheia.providers.openai_compat import OpenAICompatProvider


# ---------------------------------------------------------------------------
# Endpoint + get_provider
# ---------------------------------------------------------------------------


def test_get_provider_ollama():
    ep = Endpoint(name="test", url="http://localhost:11434", provider_type="ollama", roles=["chat"])
    provider = get_provider(ep)
    assert isinstance(provider, OllamaProvider)
    assert provider.endpoint is ep


def test_get_provider_lmstudio():
    ep = Endpoint(name="test", url="http://localhost:1234", provider_type="lmstudio", roles=["chat"])
    provider = get_provider(ep)
    assert isinstance(provider, LMStudioProvider)


def test_get_provider_openai_compat():
    ep = Endpoint(name="test", url="http://localhost:8080", provider_type="openai_compat", roles=["chat"])
    provider = get_provider(ep)
    assert isinstance(provider, OpenAICompatProvider)


def test_get_provider_unknown_raises():
    ep = Endpoint(name="test", url="http://localhost:8080", provider_type="banana", roles=["chat"])
    with pytest.raises(ValueError, match="Unknown provider type"):
        get_provider(ep)


# ---------------------------------------------------------------------------
# Ollama provider
# ---------------------------------------------------------------------------


def _make_ollama(roles=None) -> OllamaProvider:
    ep = Endpoint(
        name="test-ollama",
        url="http://localhost:11434",
        provider_type="ollama",
        roles=roles or ["chat", "embed"],
        default_chat_model="llama3",
        default_embed_model="qwen3-embedding:8b",
    )
    return OllamaProvider(ep)


def test_ollama_capabilities():
    provider = _make_ollama()
    caps = provider.capabilities()
    assert Capability.CHAT in caps
    assert Capability.EMBED in caps
    assert Capability.MODEL_PULL in caps
    assert Capability.MODEL_DELETE in caps
    assert Capability.MODEL_LOAD in caps
    assert Capability.MODEL_UNLOAD in caps
    assert Capability.MODEL_INFO in caps
    assert Capability.MODEL_LIST in caps


def test_ollama_capabilities_chat_only():
    provider = _make_ollama(roles=["chat"])
    caps = provider.capabilities()
    assert Capability.CHAT in caps
    assert Capability.EMBED not in caps
    assert Capability.MODEL_PULL in caps


@pytest.mark.asyncio
async def test_ollama_health_check_ok():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"models": [{"name": "llama3"}]}
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    result = await provider.health_check()
    assert result["ok"] is True
    assert result["provider"] == "ollama"
    assert result["model_count"] == 1


@pytest.mark.asyncio
async def test_ollama_health_check_fail():
    provider = _make_ollama()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    provider._client = mock_client

    result = await provider.health_check()
    assert result["ok"] is False
    assert "connection refused" in result["error"]


@pytest.mark.asyncio
async def test_ollama_list_models():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "models": [
            {
                "name": "llama3:latest",
                "size": 4_000_000_000,
                "details": {
                    "family": "llama",
                    "parameter_size": "8B",
                    "quantization_level": "Q4_K_M",
                },
            },
            {
                "name": "qwen3-embedding:8b",
                "size": 2_000_000_000,
                "details": {
                    "family": "qwen3",
                    "parameter_size": "8B",
                    "quantization_level": "Q8_0",
                },
            },
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    models = await provider.list_models()
    assert len(models) == 2
    assert models[0].name == "llama3:latest"
    assert models[0].size_bytes == 4_000_000_000
    assert models[0].quantization == "Q4_K_M"
    assert models[0].provider == "ollama"
    assert models[0].endpoint_name == "test-ollama"
    assert "chat" in models[0].capabilities
    assert models[1].name == "qwen3-embedding:8b"
    assert "embed" in models[1].capabilities


@pytest.mark.asyncio
async def test_ollama_chat():
    provider = _make_ollama()
    expected = {
        "choices": [{"message": {"content": "Hello!"}}],
    }
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = expected
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    result = await provider.chat(
        [{"role": "user", "content": "hi"}],
        model=None,
    )
    assert result["choices"][0]["message"]["content"] == "Hello!"
    # Verify model was set from endpoint default
    call_args = mock_client.post.call_args
    payload = call_args[1]["json"]
    assert payload["model"] == "llama3"


@pytest.mark.asyncio
async def test_ollama_embed():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [{"embedding": [0.1, 0.2, 0.3]}],
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    result = await provider.embed("test text")
    assert result == [[0.1, 0.2, 0.3]]


@pytest.mark.asyncio
async def test_ollama_delete_model():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.request = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    result = await provider.delete_model("old-model")
    assert result["ok"] is True
    assert result["deleted"] == "old-model"


@pytest.mark.asyncio
async def test_ollama_load_model():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    result = await provider.load_model("llama3")
    assert result["ok"] is True
    call_args = mock_client.post.call_args
    payload = call_args[1]["json"]
    assert payload["keep_alive"] == -1


@pytest.mark.asyncio
async def test_ollama_unload_model():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    result = await provider.unload_model("llama3")
    assert result["ok"] is True
    call_args = mock_client.post.call_args
    payload = call_args[1]["json"]
    assert payload["keep_alive"] == 0


@pytest.mark.asyncio
async def test_ollama_model_info():
    provider = _make_ollama()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "details": {
            "family": "llama",
            "parameter_size": "8B",
            "quantization_level": "Q4_K_M",
        },
        "model_info": {},
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    info = await provider.model_info("llama3")
    assert info.name == "llama3"
    assert info.family == "llama"
    assert info.quantization == "Q4_K_M"


# ---------------------------------------------------------------------------
# LM Studio provider
# ---------------------------------------------------------------------------


def _make_lmstudio(roles=None) -> LMStudioProvider:
    ep = Endpoint(
        name="test-lmstudio",
        url="http://localhost:1234",
        provider_type="lmstudio",
        roles=roles or ["chat"],
    )
    return LMStudioProvider(ep)


def test_lmstudio_capabilities():
    provider = _make_lmstudio()
    caps = provider.capabilities()
    assert Capability.CHAT in caps
    assert Capability.MODEL_LIST in caps
    assert Capability.MODEL_LOAD in caps
    assert Capability.MODEL_UNLOAD in caps
    assert Capability.MODEL_PULL not in caps


@pytest.mark.asyncio
async def test_lmstudio_list_models():
    provider = _make_lmstudio()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {
        "data": [
            {"id": "deepseek-r1-distill-qwen-7b"},
            {"id": "granite-3.1-8b-instruct"},
        ]
    }
    mock_response.raise_for_status = MagicMock()
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)
    provider._client = mock_client

    models = await provider.list_models()
    assert len(models) == 2
    assert models[0].name == "deepseek-r1-distill-qwen-7b"
    assert models[0].loaded is True  # LM Studio only shows loaded
    assert models[0].provider == "lmstudio"


# ---------------------------------------------------------------------------
# OpenAI-compat provider
# ---------------------------------------------------------------------------


def _make_compat(roles=None) -> OpenAICompatProvider:
    ep = Endpoint(
        name="test-compat",
        url="http://localhost:8080",
        provider_type="openai_compat",
        roles=roles or ["chat", "embed"],
    )
    return OpenAICompatProvider(ep)


def test_openai_compat_capabilities():
    provider = _make_compat()
    caps = provider.capabilities()
    assert Capability.CHAT in caps
    assert Capability.EMBED in caps
    assert Capability.MODEL_LIST in caps
    assert Capability.MODEL_PULL not in caps
    assert Capability.MODEL_DELETE not in caps


# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_detect_provider_ollama():
    """Ollama detected when /api/tags returns models key."""
    async def _mock_get(url, **kwargs):
        resp = MagicMock()
        if "/api/tags" in url:
            resp.status_code = 200
            resp.json.return_value = {"models": []}
            return resp
        resp.status_code = 404
        return resp

    with patch("aletheia.providers.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        result = await detect_provider("http://localhost:11434")
        assert result == "ollama"


@pytest.mark.asyncio
async def test_detect_provider_generic_fallback():
    """Falls back to openai_compat when nothing identifies."""
    async def _mock_get(url, **kwargs):
        resp = MagicMock()
        if "/api/tags" in url:
            resp.status_code = 404
            return resp
        # Check /lmstudio BEFORE /v1/models (more specific match first)
        if "/lmstudio" in url:
            raise httpx.ConnectError("nope")
        if "/v1/models" in url:
            resp.status_code = 200
            resp.text = '{"data": []}'
            resp.json.return_value = {"data": []}
            return resp
        resp.status_code = 404
        return resp

    with patch("aletheia.providers.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get = _mock_get
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_cls.return_value = mock_client

        result = await detect_provider("http://localhost:8080")
        assert result == "openai_compat"


# ---------------------------------------------------------------------------
# ModelInfo dataclass
# ---------------------------------------------------------------------------


def test_model_info_defaults():
    info = ModelInfo(name="test-model")
    assert info.name == "test-model"
    assert info.size_bytes is None
    assert info.loaded is False
    assert info.capabilities == []
    assert info.provider == ""


def test_model_info_with_details():
    info = ModelInfo(
        name="llama3:latest",
        size_bytes=4_000_000_000,
        quantization="Q4_K_M",
        family="llama",
        parameter_count="8B",
        loaded=True,
        capabilities=["chat"],
        provider="ollama",
        endpoint_name="zbook-ollama",
    )
    assert info.size_bytes == 4_000_000_000
    assert info.loaded is True
    assert info.provider == "ollama"


# ---------------------------------------------------------------------------
# Endpoint resolve_model
# ---------------------------------------------------------------------------


def test_resolve_model_explicit():
    provider = _make_ollama()
    assert provider._resolve_model("custom-model", role="chat") == "custom-model"


def test_resolve_model_from_endpoint_default():
    provider = _make_ollama()
    assert provider._resolve_model(None, role="chat") == "llama3"
    assert provider._resolve_model(None, role="embed") == "qwen3-embedding:8b"


def test_resolve_model_none_when_no_default():
    ep = Endpoint(name="bare", url="http://localhost:1234", provider_type="ollama", roles=["chat"])
    provider = OllamaProvider(ep)
    assert provider._resolve_model(None, role="chat") is None


# ---------------------------------------------------------------------------
# LLMClient with provider delegation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_llm_client_delegates_to_chat_provider():
    """LLMClient.complete() delegates to chat_provider when given."""
    from aletheia.llm import LLMClient

    mock_provider = AsyncMock()
    mock_provider.chat = AsyncMock(return_value={
        "choices": [{"message": {"content": "delegated!"}}],
    })
    mock_provider.close = AsyncMock()

    client = LLMClient(chat_provider=mock_provider)
    result = await client.complete("test prompt")
    assert result == "delegated!"
    mock_provider.chat.assert_called_once()
    await client.close()


@pytest.mark.asyncio
async def test_llm_client_delegates_to_embed_provider():
    """LLMClient.embed() delegates to embed_provider when given."""
    from aletheia.llm import LLMClient

    mock_provider = AsyncMock()
    mock_provider.embed = AsyncMock(return_value=[[0.1, 0.2, 0.3]])
    mock_provider.close = AsyncMock()

    client = LLMClient(embed_provider=mock_provider)
    result = await client.embed("test text")
    assert result == [0.1, 0.2, 0.3]
    mock_provider.embed.assert_called_once()
    await client.close()
