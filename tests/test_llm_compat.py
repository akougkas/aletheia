import httpx
import pytest

from aletheia.llm import (
    CompletionResult,
    LLMClient,
    LLMConfig,
    _extract_completion_result,
    _extract_completion_text,
    _strip_think_tags,
)


# ---------------------------------------------------------------------------
# Backward-compatible extraction (returns str)
# ---------------------------------------------------------------------------


def test_extract_completion_text_uses_reasoning_when_content_empty():
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "reasoning_content": '{"indicator":"unemployment rate","confidence":0.8}',
                }
            }
        ]
    }
    assert "indicator" in _extract_completion_text(payload)


def test_extract_completion_text_handles_structured_content_list():
    payload = {
        "choices": [
            {
                "message": {
                    "content": [
                        {"type": "output_text", "text": "first line"},
                        {"type": "output_text", "text": "second line"},
                    ]
                }
            }
        ]
    }
    assert _extract_completion_text(payload) == "first line\nsecond line"


# ---------------------------------------------------------------------------
# CompletionResult extraction — all provider formats
# ---------------------------------------------------------------------------


def test_lmstudio_deepseek_style_reasoning_content():
    """LM Studio with DeepSeek R1: separate reasoning_content field."""
    payload = {
        "choices": [{
            "message": {
                "content": "The answer is 42.",
                "reasoning_content": "Let me think about this carefully...",
            }
        }]
    }
    result = _extract_completion_result(payload)
    assert result.content == "The answer is 42."
    assert "think about this" in result.reasoning


def test_lmstudio_gptoss_style_reasoning():
    """LM Studio with gpt-oss: separate reasoning field."""
    payload = {
        "choices": [{
            "message": {
                "content": "Hello! How can I help?",
                "reasoning": "The user said hello. I should greet them.",
            }
        }]
    }
    result = _extract_completion_result(payload)
    assert result.content == "Hello! How can I help?"
    assert "greet them" in result.reasoning


def test_ollama_openai_compat_reasoning():
    """Ollama /v1/chat/completions: reasoning field (not reasoning_content)."""
    payload = {
        "choices": [{
            "message": {
                "role": "assistant",
                "content": "There are 3 r's in strawberry.",
                "reasoning": "Let me count: s-t-r-a-w-b-e-r-r-y.",
            }
        }]
    }
    result = _extract_completion_result(payload)
    assert "3 r's" in result.content
    assert "count" in result.reasoning


def test_ollama_native_thinking_field():
    """Ollama native /api/chat format uses 'thinking' field name."""
    payload = {
        "choices": [{
            "message": {
                "content": "The capital is Paris.",
                "thinking": "France... the capital is Paris.",
            }
        }]
    }
    result = _extract_completion_result(payload)
    assert result.content == "The capital is Paris."
    assert "Paris" in result.reasoning


def test_inline_think_tags_in_content():
    """Models that put <think> tags inline in content field."""
    payload = {
        "choices": [{
            "message": {
                "content": "<think>I need to reason about this.</think>\nThe answer is 7.",
            }
        }]
    }
    result = _extract_completion_result(payload)
    assert result.content == "The answer is 7."
    assert "reason about this" in result.reasoning
    assert "<think>" not in result.content


def test_content_empty_reasoning_becomes_content():
    """When content is empty, reasoning is promoted to content."""
    payload = {
        "choices": [{
            "message": {
                "content": "",
                "reasoning_content": '{"indicator":"CPI","confidence":0.9}',
            }
        }]
    }
    result = _extract_completion_result(payload)
    assert "indicator" in result.content
    assert result.reasoning == ""


def test_both_fields_empty():
    payload = {"choices": [{"message": {"content": "", "reasoning": ""}}]}
    result = _extract_completion_result(payload)
    assert result.content == ""
    assert result.reasoning == ""


def test_no_choices():
    result = _extract_completion_result({"choices": []})
    assert result.content == ""


# ---------------------------------------------------------------------------
# Inline <think> tag stripping
# ---------------------------------------------------------------------------


def test_strip_think_tags_basic():
    content, reasoning = _strip_think_tags(
        "<think>step 1\nstep 2</think>\nFinal answer."
    )
    assert content == "Final answer."
    assert "step 1" in reasoning
    assert "step 2" in reasoning


def test_strip_think_tags_multiple():
    content, reasoning = _strip_think_tags(
        "<think>first</think>middle<think>second</think>end"
    )
    assert "<think>" not in content
    assert "first" in reasoning
    assert "second" in reasoning


def test_strip_think_tags_none():
    content, reasoning = _strip_think_tags("No thinking here.")
    assert content == "No thinking here."
    assert reasoning == ""


# ---------------------------------------------------------------------------
# CompletionResult behavior
# ---------------------------------------------------------------------------


def test_completion_result_str():
    r = CompletionResult(content="hello", reasoning="thought")
    assert str(r) == "hello"


def test_completion_result_bool():
    assert bool(CompletionResult(content="x", reasoning=""))
    assert not bool(CompletionResult(content="", reasoning="thought"))


class _FakeEmbedClient:
    def __init__(self, response: httpx.Response):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    async def post(self, path: str, json: dict):  # noqa: A002
        self.calls.append((path, json))
        return self.response


@pytest.mark.asyncio
async def test_embed_uses_chat_model_when_embed_model_not_set():
    response = httpx.Response(
        200,
        request=httpx.Request("POST", "http://example/v1/embeddings"),
        json={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
    )
    fake_client = _FakeEmbedClient(response)

    llm = LLMClient(
        config=LLMConfig(
            base_url="http://example",
            embed_base_url="http://example",
            model="chat-model",
            embed_model=None,
        )
    )

    async def _fake_get_embed_client():
        return fake_client

    llm._get_embed_client = _fake_get_embed_client  # type: ignore[method-assign]
    vector = await llm.embed("healthcheck")
    assert vector == [0.1, 0.2, 0.3]
    assert fake_client.calls[0][1]["model"] == "chat-model"


@pytest.mark.asyncio
async def test_embed_raises_actionable_error_when_model_required():
    response = httpx.Response(
        400,
        request=httpx.Request("POST", "http://example/v1/embeddings"),
        json={"error": {"message": "model is required"}},
    )
    fake_client = _FakeEmbedClient(response)

    llm = LLMClient(
        config=LLMConfig(
            base_url="http://example",
            embed_base_url="http://example",
            model=None,
            embed_model=None,
        )
    )

    async def _fake_get_embed_client():
        return fake_client

    llm._get_embed_client = _fake_get_embed_client  # type: ignore[method-assign]
    with pytest.raises(RuntimeError, match="ALETHEIA_EMBED_MODEL"):
        await llm.embed("healthcheck")
