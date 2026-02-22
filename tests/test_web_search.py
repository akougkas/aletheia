import pytest

from aletheia.web_search import WebSearchClient, WebSearchResult


@pytest.fixture(autouse=True)
def _clear_web_search_env(monkeypatch):
    keys = [
        "ALETHEIA_WEB_SEARCH_PROVIDER",
        "ALETHEIA_WEB_SEARCH_CHAIN",
        "ALETHEIA_WEB_FETCH_MAX_CHARS",
        "ALETHEIA_WEB_FETCH_DOCS",
        "ALETHEIA_WEB_DEFAULT_RATE_LIMIT_PER_MIN",
        "ALETHEIA_WEB_RATE_LIMIT_PER_MIN",
        "ALETHEIA_WEB_CIRCUIT_FAILURE_THRESHOLD",
        "ALETHEIA_WEB_CIRCUIT_COOLDOWN_SECONDS",
        "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN",
        "SERPAPI_API_KEY",
        "GOOGLE_CSE_API_KEY",
        "GOOGLE_CSE_CX",
        "BRAVE_SEARCH_API_KEY",
    ]
    for key in keys:
        monkeypatch.delenv(key, raising=False)


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


@pytest.mark.asyncio
async def test_search_auto_provider_chain_falls_through(monkeypatch):
    client = WebSearchClient()
    client.provider = "auto"
    client.provider_chain = ["google", "brave", "duckduckgo"]

    async def _google(query: str, *, max_results: int):  # noqa: ARG001
        return []

    async def _brave(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Brave result",
                url="https://example.org/a",
                snippet="snippet",
                provider="brave",
            )
        ]

    async def _ddg(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="DDG result",
                url="https://example.org/b",
                snippet="snippet",
                provider="duckduckgo",
            )
        ]

    monkeypatch.setattr(client, "_search_google_cse", _google)
    monkeypatch.setattr(client, "_search_brave", _brave)
    monkeypatch.setattr(client, "_search_duckduckgo", _ddg)

    results = await client.search("test query", max_results=3)
    assert results
    assert results[0].provider == "brave"
    await client.close()


@pytest.mark.asyncio
async def test_search_honors_explicit_provider(monkeypatch):
    client = WebSearchClient()
    client.provider = "duckduckgo"

    async def _ddg(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="DDG only",
                url="https://example.org/ddg",
                snippet="snippet",
                provider="duckduckgo",
            )
        ]

    async def _google(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Google",
                url="https://example.org/google",
                snippet="snippet",
                provider="google",
            )
        ]

    monkeypatch.setattr(client, "_search_duckduckgo", _ddg)
    monkeypatch.setattr(client, "_search_google_cse", _google)

    results = await client.search("test query", max_results=3)
    assert results
    assert results[0].provider == "duckduckgo"
    await client.close()


@pytest.mark.asyncio
async def test_search_scholar_uses_serpapi_google_scholar(monkeypatch):
    client = WebSearchClient()
    monkeypatch.setenv("SERPAPI_API_KEY", "test-key")

    async def _request(method: str, url: str, *, params=None, headers=None):  # noqa: ARG001
        return _Response(
            {
                "organic_results": [
                    {
                        "title": "Labor paper",
                        "link": "https://doi.org/10.9999/test",
                        "snippet": "Snippet",
                        "publication_info": {"summary": "Author 2024"},
                    }
                ]
            }
        )

    monkeypatch.setattr(client, "_request_with_retry", _request)
    results = await client.search_scholar("labor methodology", max_results=3)
    assert results
    assert results[0].provider == "serpapi_google_scholar"
    assert "Author" in results[0].snippet
    await client.close()


@pytest.mark.asyncio
async def test_search_respects_rate_limit_budget_and_falls_through(monkeypatch):
    client = WebSearchClient()
    client.provider = "auto"
    client.provider_chain = ["google", "brave"]
    client.default_rate_limit_per_min = 100
    client.rate_limits_per_min["google"] = 1

    async def _google(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Google result",
                url="https://example.org/google",
                snippet="snippet",
                provider="google",
            )
        ]

    async def _brave(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Brave result",
                url="https://example.org/brave",
                snippet="snippet",
                provider="brave",
            )
        ]

    monkeypatch.setattr(client, "_search_google_cse", _google)
    monkeypatch.setattr(client, "_search_brave", _brave)

    first = await client.search("test query", max_results=3)
    second = await client.search("test query 2", max_results=3)
    assert first and first[0].provider == "google"
    assert second and second[0].provider == "brave"
    await client.close()


@pytest.mark.asyncio
async def test_search_respects_per_run_budget_and_resets_on_start_run(monkeypatch):
    client = WebSearchClient()
    client.provider = "auto"
    client.provider_chain = ["google", "brave"]
    client.default_rate_limit_per_min = 100
    client.budget_per_run["google"] = 1
    client.start_run()

    async def _google(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Google result",
                url="https://example.org/google",
                snippet="snippet",
                provider="google",
            )
        ]

    async def _brave(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Brave fallback",
                url="https://example.org/brave",
                snippet="snippet",
                provider="brave",
            )
        ]

    monkeypatch.setattr(client, "_search_google_cse", _google)
    monkeypatch.setattr(client, "_search_brave", _brave)

    first = await client.search("query one", max_results=3)
    second = await client.search("query two", max_results=3)
    run_summary = client.get_run_summary()
    assert first and first[0].provider == "google"
    assert second and second[0].provider == "brave"
    assert run_summary["skip_total"] >= 1

    client.start_run()
    third = await client.search("query three", max_results=3)
    assert third and third[0].provider == "google"
    await client.close()


@pytest.mark.asyncio
async def test_search_uses_circuit_breaker_on_provider_failures(monkeypatch):
    client = WebSearchClient()
    client.provider = "auto"
    client.provider_chain = ["google", "brave"]
    client.circuit_failure_threshold = 1
    client.circuit_cooldown_seconds = 999

    calls = {"google": 0}

    async def _google(query: str, *, max_results: int):  # noqa: ARG001
        calls["google"] += 1
        raise RuntimeError("provider down")

    async def _brave(query: str, *, max_results: int):  # noqa: ARG001
        return [
            WebSearchResult(
                title="Brave fallback",
                url="https://example.org/fallback",
                snippet="snippet",
                provider="brave",
            )
        ]

    monkeypatch.setattr(client, "_search_google_cse", _google)
    monkeypatch.setattr(client, "_search_brave", _brave)

    first = await client.search("query one", max_results=3)
    second = await client.search("query two", max_results=3)
    assert first and first[0].provider == "brave"
    assert second and second[0].provider == "brave"
    assert calls["google"] == 1
    await client.close()


@pytest.mark.asyncio
async def test_fetch_page_uses_crawl4ai_fallback_when_html_quality_low(monkeypatch):
    client = WebSearchClient()
    client.allow_crawl4ai = True

    class _HttpResp:
        headers = {"content-type": "text/html"}
        text = "<html><body>cookie policy sign in terms of use</body></html>"

    async def _request(method: str, url: str, *, params=None, headers=None):  # noqa: ARG001
        return _HttpResp()

    async def _crawl(result):  # noqa: ANN001
        return {
            "title": result.title,
            "url": result.url,
            "content": "Clean markdown content from crawl4ai.",
            "snippet": result.snippet,
            "provider": result.provider,
            "domain": "example.org",
            "fetched_by": "crawl4ai",
        }

    monkeypatch.setattr(client, "_request_with_retry", _request)
    monkeypatch.setattr(client, "_fetch_with_crawl4ai", _crawl)
    row = await client._fetch_one(
        WebSearchResult(
            title="Low quality page",
            url="https://example.org/page",
            snippet="A short snippet",
            provider="duckduckgo",
        )
    )
    assert row is not None
    assert row["fetched_by"] == "crawl4ai"
    await client.close()
