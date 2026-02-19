"""Web search and page extraction utilities for fallback evidence."""

from __future__ import annotations

import asyncio
import html
import os
import re
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str
    provider: str


class WebSearchClient:
    """Resilient web search client with provider fallback."""

    def __init__(self, *, timeout: float = 12.0):
        self.provider = os.environ.get("ALETHEIA_WEB_SEARCH_PROVIDER", "auto").lower()
        chain = os.environ.get(
            "ALETHEIA_WEB_SEARCH_CHAIN",
            "brave,duckduckgo,google",
        )
        self.provider_chain = [item.strip().lower() for item in chain.split(",") if item.strip()]
        self.max_fetch_chars = int(os.environ.get("ALETHEIA_WEB_FETCH_MAX_CHARS", "6000"))
        self.max_fetch_docs = int(os.environ.get("ALETHEIA_WEB_FETCH_DOCS", "3"))
        self.allow_crawl4ai = os.environ.get("ALETHEIA_ENABLE_CRAWL4AI_FALLBACK", "0") == "1"
        self.default_rate_limit_per_min = int(
            os.environ.get("ALETHEIA_WEB_DEFAULT_RATE_LIMIT_PER_MIN", "30")
        )
        self.rate_limits_per_min = self._parse_rate_limits(
            os.environ.get(
                "ALETHEIA_WEB_RATE_LIMIT_PER_MIN",
                "google:20,brave:30,duckduckgo:40,serpapi_google_scholar:15",
            )
        )
        self.circuit_failure_threshold = int(
            os.environ.get("ALETHEIA_WEB_CIRCUIT_FAILURE_THRESHOLD", "3")
        )
        self.circuit_cooldown_seconds = int(
            os.environ.get("ALETHEIA_WEB_CIRCUIT_COOLDOWN_SECONDS", "120")
        )
        self.budget_per_run = self._parse_rate_limits(
            os.environ.get(
                "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN",
                "google:2,brave:2,duckduckgo:2,serpapi_google_scholar:1",
            )
        )
        self._provider_calls: dict[str, deque[float]] = defaultdict(deque)
        self._provider_failures: dict[str, int] = defaultdict(int)
        self._provider_open_until: dict[str, float] = defaultdict(float)
        self._run_provider_calls: dict[str, int] = defaultdict(int)
        self._run_skip_reasons: dict[str, int] = defaultdict(int)
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=5.0),
            headers={
                "User-Agent": "ALETHEIA/0.1 (+https://github.com/aletheia-research)"
            },
            follow_redirects=True,
        )

    async def close(self) -> None:
        await self._client.aclose()

    def start_run(self) -> None:
        """Reset per-run counters used for budget summaries."""
        self._run_provider_calls.clear()
        self._run_skip_reasons.clear()

    def get_run_summary(self) -> dict[str, Any]:
        """Return provider usage/skips for the most recent run."""
        return {
            "calls": dict(self._run_provider_calls),
            "skip_reasons": dict(self._run_skip_reasons),
            "skip_total": int(sum(self._run_skip_reasons.values())),
        }

    async def search(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> list[WebSearchResult]:
        providers = self._resolve_providers()
        for provider in providers:
            allowed, reason = self._provider_gate(provider)
            if not allowed:
                if reason:
                    self._run_skip_reasons[reason] += 1
                continue
            self._register_call(provider)
            if provider == "google":
                fetch = self._search_google_cse
            elif provider == "brave":
                fetch = self._search_brave
            elif provider == "duckduckgo":
                fetch = self._search_duckduckgo
            else:
                continue
            try:
                results = await fetch(query, max_results=max_results)
            except Exception:
                self._register_failure(provider)
                continue
            if results:
                self._register_success(provider)
                return results
        return []

    async def search_scholar(
        self,
        query: str,
        *,
        max_results: int = 5,
    ) -> list[WebSearchResult]:
        """Search scholarly papers via SERP API Google Scholar engine."""
        provider = "serpapi_google_scholar"
        allowed, reason = self._provider_gate(provider)
        if not allowed:
            if reason:
                self._run_skip_reasons[reason] += 1
            return []
        self._register_call(provider)
        try:
            results = await self._search_serpapi_google_scholar(
                query,
                max_results=max_results,
            )
        except Exception:
            self._register_failure(provider)
            return []
        if results:
            self._register_success(provider)
        return results

    def _resolve_providers(self) -> list[str]:
        if self.provider and self.provider != "auto":
            if self.provider in {"google", "brave", "duckduckgo"}:
                return [self.provider]
            return ["duckduckgo"]
        normalized = [p for p in self.provider_chain if p in {"google", "brave", "duckduckgo"}]
        return normalized or ["duckduckgo"]

    def _parse_rate_limits(self, raw: str) -> dict[str, int]:
        limits: dict[str, int] = {}
        for item in raw.split(","):
            entry = item.strip()
            if not entry or ":" not in entry:
                continue
            provider, value = entry.split(":", 1)
            provider_key = provider.strip().lower()
            try:
                limit_value = int(value.strip())
            except ValueError:
                continue
            if provider_key and limit_value >= 0:
                limits[provider_key] = limit_value
        return limits

    def _provider_gate(self, provider: str) -> tuple[bool, str | None]:
        now = time.monotonic()
        if now < self._provider_open_until[provider]:
            return False, f"{provider}:circuit_open"

        calls = self._provider_calls[provider]
        while calls and (now - calls[0]) > 60:
            calls.popleft()

        limit = self.rate_limits_per_min.get(provider, self.default_rate_limit_per_min)
        if limit <= 0:
            return False, f"{provider}:provider_disabled"
        if len(calls) >= limit:
            return False, f"{provider}:rate_limit_per_min"

        run_budget = self.budget_per_run.get(provider)
        if run_budget is not None and run_budget >= 0:
            if self._run_provider_calls.get(provider, 0) >= run_budget:
                return False, f"{provider}:run_budget_exceeded"

        return True, None

    def _register_call(self, provider: str) -> None:
        self._provider_calls[provider].append(time.monotonic())
        self._run_provider_calls[provider] += 1

    def _register_success(self, provider: str) -> None:
        self._provider_failures[provider] = 0
        self._provider_open_until[provider] = 0.0

    def _register_failure(self, provider: str) -> None:
        self._provider_failures[provider] += 1
        if self._provider_failures[provider] >= self.circuit_failure_threshold:
            self._provider_open_until[provider] = time.monotonic() + self.circuit_cooldown_seconds
            self._provider_failures[provider] = 0

    async def _search_google_cse(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[WebSearchResult]:
        api_key = os.environ.get("GOOGLE_CSE_API_KEY")
        cx = os.environ.get("GOOGLE_CSE_CX")
        if not api_key or not cx:
            return []

        response = await self._request_with_retry(
            "GET",
            "https://www.googleapis.com/customsearch/v1",
            params={
                "key": api_key,
                "cx": cx,
                "q": query,
                "num": min(max_results, 10),
                "safe": "active",
            },
        )
        if response is None:
            return []

        payload = response.json()
        items = payload.get("items", [])
        parsed: list[WebSearchResult] = []
        for item in items:
            url = item.get("link")
            title = item.get("title") or "Untitled"
            snippet = item.get("snippet") or ""
            if not url:
                continue
            parsed.append(
                WebSearchResult(
                    title=self._clean_text(title),
                    url=url,
                    snippet=self._clean_text(snippet),
                    provider="google",
                )
            )
        return self._dedupe(parsed, max_results)

    async def _search_serpapi_google_scholar(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[WebSearchResult]:
        api_key = os.environ.get("SERPAPI_API_KEY")
        if not api_key:
            return []

        response = await self._request_with_retry(
            "GET",
            "https://serpapi.com/search.json",
            params={
                "engine": "google_scholar",
                "q": query,
                "api_key": api_key,
                "num": min(max_results, 20),
                "hl": "en",
            },
        )
        if response is None:
            return []

        payload = response.json()
        organic_results = payload.get("organic_results", [])
        parsed: list[WebSearchResult] = []
        for item in organic_results:
            title = item.get("title") or "Untitled"
            link = item.get("link")
            snippet = item.get("snippet") or ""
            pub_summary = (item.get("publication_info") or {}).get("summary")
            combined_snippet = f"{pub_summary or ''} {snippet}".strip()
            if not link:
                continue
            parsed.append(
                WebSearchResult(
                    title=self._clean_text(title),
                    url=link,
                    snippet=self._clean_text(combined_snippet),
                    provider="serpapi_google_scholar",
                )
            )
        return self._dedupe(parsed, max_results)

    async def fetch_pages(self, results: list[WebSearchResult]) -> list[dict[str, Any]]:
        subset = results[: max(1, self.max_fetch_docs)]
        tasks = [self._fetch_one(result) for result in subset]
        rows = await asyncio.gather(*tasks, return_exceptions=True)

        docs: list[dict[str, Any]] = []
        for row in rows:
            if isinstance(row, Exception) or row is None:
                continue
            docs.append(row)
        return docs

    async def _search_brave(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[WebSearchResult]:
        api_key = os.environ.get("BRAVE_SEARCH_API_KEY")
        if not api_key:
            return []

        response = await self._request_with_retry(
            "GET",
            "https://api.search.brave.com/res/v1/web/search",
            params={"q": query, "count": max_results},
            headers={"X-Subscription-Token": api_key},
        )
        if response is None:
            return []

        payload = response.json()
        web_results = payload.get("web", {}).get("results", [])
        parsed: list[WebSearchResult] = []
        for item in web_results:
            url = item.get("url")
            title = item.get("title") or "Untitled"
            description = item.get("description") or ""
            if not url:
                continue
            parsed.append(
                WebSearchResult(
                    title=self._clean_text(title),
                    url=url,
                    snippet=self._clean_text(description),
                    provider="brave",
                )
            )
        return self._dedupe(parsed, max_results)

    async def _search_duckduckgo(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[WebSearchResult]:
        response = await self._request_with_retry(
            "GET",
            "https://api.duckduckgo.com/",
            params={
                "q": query,
                "format": "json",
                "no_html": "1",
                "skip_disambig": "1",
                "no_redirect": "1",
            },
        )
        if response is None:
            return []

        payload = response.json()
        parsed: list[WebSearchResult] = []

        abstract_text = payload.get("AbstractText")
        abstract_url = payload.get("AbstractURL")
        heading = payload.get("Heading") or query
        if abstract_text and abstract_url:
            parsed.append(
                WebSearchResult(
                    title=self._clean_text(heading),
                    url=abstract_url,
                    snippet=self._clean_text(abstract_text),
                    provider="duckduckgo",
                )
            )

        for result in payload.get("Results", []):
            url = result.get("FirstURL")
            text = result.get("Text") or ""
            if not url:
                continue
            parsed.append(
                WebSearchResult(
                    title=self._title_from_url(url),
                    url=url,
                    snippet=self._clean_text(text),
                    provider="duckduckgo",
                )
            )

        for topic in payload.get("RelatedTopics", []):
            if isinstance(topic, dict) and "Topics" in topic:
                for nested in topic["Topics"]:
                    row = self._topic_to_result(nested)
                    if row:
                        parsed.append(row)
            else:
                row = self._topic_to_result(topic)
                if row:
                    parsed.append(row)

        return self._dedupe(parsed, max_results)

    def _topic_to_result(self, topic: dict) -> WebSearchResult | None:
        if not isinstance(topic, dict):
            return None
        url = topic.get("FirstURL")
        text = topic.get("Text")
        if not url or not text:
            return None
        return WebSearchResult(
            title=self._title_from_url(url),
            url=url,
            snippet=self._clean_text(text),
            provider="duckduckgo",
        )

    async def _fetch_one(self, result: WebSearchResult) -> dict[str, Any] | None:
        response = await self._request_with_retry("GET", result.url)
        if response is None:
            if self.allow_crawl4ai:
                return await self._fetch_with_crawl4ai(result)
            return None

        fetched_by = "httpx"
        content_type = (response.headers.get("content-type") or "").lower()
        cleaned = ""
        if "html" in content_type or "text/" in content_type:
            cleaned = self._extract_text(response.text)

        if self.allow_crawl4ai and self._needs_crawl4ai_fallback(cleaned, result.snippet):
            crawl_doc = await self._fetch_with_crawl4ai(result)
            if crawl_doc is not None:
                return crawl_doc

        if not cleaned:
            return None

        return self._format_doc(result, cleaned, fetched_by=fetched_by)

    def _format_doc(
        self,
        result: WebSearchResult,
        cleaned: str,
        *,
        fetched_by: str,
    ) -> dict[str, Any]:
        return {
            "title": result.title,
            "url": result.url,
            "content": cleaned[: self.max_fetch_chars],
            "snippet": result.snippet,
            "provider": result.provider,
            "domain": (urlparse(result.url).netloc or "").lower(),
            "fetched_by": fetched_by,
        }

    def _needs_crawl4ai_fallback(self, cleaned: str, snippet: str) -> bool:
        if not cleaned or len(cleaned) < 600:
            return True
        if snippet and len(cleaned) < max(500, len(snippet) * 2):
            return True
        boilerplate_terms = (
            "cookie",
            "privacy policy",
            "terms of use",
            "sign in",
            "javascript",
            "enable cookies",
        )
        lowered = cleaned.lower()
        hits = sum(1 for term in boilerplate_terms if term in lowered)
        return hits >= 4

    async def _fetch_with_crawl4ai(self, result: WebSearchResult) -> dict[str, Any] | None:
        try:
            from crawl4ai import AsyncWebCrawler  # type: ignore
        except Exception:
            return None

        try:
            async with AsyncWebCrawler() as crawler:
                crawl_result = await crawler.arun(url=result.url, bypass_cache=True)
        except Exception:
            return None

        markdown = ""
        for field in ("markdown", "cleaned_markdown", "fit_markdown", "raw_markdown"):
            value = getattr(crawl_result, field, None)
            if isinstance(value, str) and value.strip():
                markdown = value.strip()
                break

        if not markdown:
            return None
        cleaned = self._clean_text(markdown)
        if not cleaned:
            return None
        return self._format_doc(result, cleaned, fetched_by="crawl4ai")

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        params: dict | None = None,
        headers: dict | None = None,
    ) -> httpx.Response | None:
        for attempt in range(3):
            try:
                response = await self._client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                )
                if response.status_code in {429, 500, 502, 503, 504}:
                    raise httpx.HTTPStatusError(
                        "retryable status",
                        request=response.request,
                        response=response,
                    )
                response.raise_for_status()
                return response
            except Exception:  # noqa: BLE001
                if attempt == 2:
                    return None
                await asyncio.sleep(0.4 * (attempt + 1))
        return None

    def _extract_text(self, html_text: str) -> str:
        text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", html_text)
        text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
        text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
        text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = html.unescape(text)
        return self._clean_text(text)

    def _clean_text(self, value: str) -> str:
        value = re.sub(r"\s+", " ", value or "")
        return value.strip()

    def _title_from_url(self, url: str) -> str:
        parsed = urlparse(url)
        path = parsed.path.strip("/")
        if not path:
            return parsed.netloc or "Untitled"
        return path.split("/")[-1].replace("-", " ").replace("_", " ")[:120]

    def _dedupe(self, rows: list[WebSearchResult], max_results: int) -> list[WebSearchResult]:
        deduped: list[WebSearchResult] = []
        seen_urls: set[str] = set()
        for row in rows:
            normalized = row.url.split("#", 1)[0]
            if normalized in seen_urls:
                continue
            seen_urls.add(normalized)
            deduped.append(row)
            if len(deduped) >= max_results:
                break
        return deduped
