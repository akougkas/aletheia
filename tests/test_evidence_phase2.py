import pytest

from aletheia.evidence import (
    ClaimRouter,
    ClaimType,
    EvidenceAggregator,
    EvidencePipeline,
    RoutingPlan,
    ScholarPaperEvidenceSource,
    SourceOutput,
    WebSearchEvidenceSource,
)
from aletheia.web_search import WebSearchResult
from aletheia.schema import Direction, PolicyClaim
from aletheia.source_registry import SourceRegistry


def _claim(dataset: str | None, indicator: str, text: str) -> PolicyClaim:
    return PolicyClaim(
        original_text=text,
        indicator=indicator,
        dataset=dataset,
        geography="EU",
        period_start=2020,
        period_end=2021,
        direction=Direction.UNKNOWN,
    )


def test_claim_router_prioritizes_methodology_strategy_for_seed_dataset():
    router = ClaimRouter()
    plan = router.route(
        _claim(
            "EU-LFS",
            "unemployment rate",
            "EU unemployment fell sharply in 2021.",
        )
    )
    assert plan.claim_type == ClaimType.METHODOLOGY_AWARE
    assert plan.source_ids[:2] == ["methodology_kb", "data_api"]
    assert plan.fallback_source_id == "web_fallback"
    assert "paper_scholar" in plan.deep_research_source_ids


def test_evidence_aggregator_ranks_relevant_items_with_scores():
    claim = _claim(
        "EU-LFS",
        "unemployment rate",
        "EU unemployment fell sharply in 2021.",
    )
    aggregator = EvidenceAggregator(SourceRegistry.default())
    plan = RoutingPlan(
        claim_type=ClaimType.METHODOLOGY_AWARE,
        source_ids=["methodology_kb", "web_fallback"],
        fallback_source_id="web_fallback",
    )
    outputs = [
        SourceOutput(
            source_id="methodology_kb",
            evidence_docs=[
                {
                    "title": "EU-LFS methodology note",
                    "content": "Definition change in 2021 lowered unemployment by 0.3-0.4pp.",
                    "url": "https://ec.europa.eu/eurostat/web/lfs/methodology",
                },
                {
                    "title": "Unrelated housing bulletin",
                    "content": "Housing indicators for 2015.",
                    "url": "https://example.org/housing",
                },
            ],
        ),
        SourceOutput(
            source_id="web_fallback",
            evidence_docs=[
                {
                    "title": "General web commentary",
                    "content": "Opinion piece without clear methods.",
                    "url": "https://random-blog.test/post",
                }
            ],
        ),
    ]

    aggregated = aggregator.aggregate(claim, plan, outputs)
    assert aggregated.evidence_docs[0]["title"] == "EU-LFS methodology note"
    assert all("relevance_score" in row for row in aggregated.evidence_docs)
    assert all("confidence_score" in row for row in aggregated.evidence_docs)
    assert (
        aggregated.evidence_docs[0]["confidence_score"]
        >= aggregated.evidence_docs[-1]["confidence_score"]
    )


def test_evidence_aggregator_penalizes_geography_mismatch():
    """BLS docs should score lower than Eurostat docs for EU claims."""
    claim = _claim(
        "EU-LFS",
        "unemployment rate",
        "EU unemployment fell sharply in 2021.",
    )
    aggregator = EvidenceAggregator(SourceRegistry.default())
    plan = RoutingPlan(
        claim_type=ClaimType.STATISTICAL_FACT,
        source_ids=["data_api", "methodology_kb"],
    )
    outputs = [
        SourceOutput(
            source_id="data_api",
            evidence_docs=[
                {
                    "title": "EUROSTAT connector evidence",
                    "content": "EUROSTAT returned 312 points for unemployment rate.",
                    "url": None,
                },
                {
                    "title": "BLS connector evidence",
                    "content": "BLS returned 48 points for unemployment rate.",
                    "url": None,
                },
            ],
        ),
    ]

    aggregated = aggregator.aggregate(claim, plan, outputs)
    eurostat_doc = next(d for d in aggregated.evidence_docs if "EUROSTAT" in d["title"])
    bls_doc = next(d for d in aggregated.evidence_docs if "BLS" in d["title"])
    assert eurostat_doc["relevance_score"] > bls_doc["relevance_score"]


class _StaticSource:
    def __init__(self, source_id: str, output: SourceOutput):
        self.source_id = source_id
        self._output = output

    async def collect(
        self,
        claim: PolicyClaim,  # noqa: ARG002
        *,
        plan: RoutingPlan | None = None,  # noqa: ARG002
    ) -> SourceOutput:
        return self._output


class _StaticRouter:
    def route(self, claim: PolicyClaim) -> RoutingPlan:  # noqa: ARG002
        return RoutingPlan(
            claim_type=ClaimType.GENERAL,
            source_ids=["primary_empty"],
            fallback_source_id="web_fallback",
            deep_research_source_ids=[],
        )


class _BudgetRouter:
    def route(self, claim: PolicyClaim) -> RoutingPlan:  # noqa: ARG002
        return RoutingPlan(
            claim_type=ClaimType.GENERAL,
            source_ids=["primary_empty", "primary_empty"],
            fallback_source_id=None,
            deep_research_source_ids=[],
        )


class _DeepResearchRouter:
    def route(self, claim: PolicyClaim) -> RoutingPlan:  # noqa: ARG002
        return RoutingPlan(
            claim_type=ClaimType.GENERAL,
            source_ids=["primary_empty"],
            fallback_source_id=None,
            deep_research_source_ids=["paper_scholar"],
        )


class _TrackingSource(_StaticSource):
    def __init__(self, source_id: str, output: SourceOutput):
        super().__init__(source_id, output)
        self.called = False

    async def collect(
        self,
        claim: PolicyClaim,  # noqa: ARG002
        *,
        plan: RoutingPlan | None = None,  # noqa: ARG002
    ) -> SourceOutput:
        self.called = True
        return self._output


@pytest.mark.asyncio
async def test_pipeline_uses_fallback_when_primary_sources_are_empty():
    claim = _claim(None, "employment", "Employment changed over time.")
    pipeline = EvidencePipeline(
        router=_StaticRouter(),  # type: ignore[arg-type]
        sources={
            "primary_empty": _StaticSource(
                "primary_empty",
                SourceOutput(source_id="primary_empty"),
            ),
            "web_fallback": _StaticSource(
                "web_fallback",
                SourceOutput(
                    source_id="web_fallback",
                    evidence_docs=[
                        {
                            "title": "Fallback evidence",
                            "content": "Recovered from fallback retrieval.",
                            "url": "https://fallback.example/doc",
                        }
                    ],
                ),
            ),
        },
        aggregator=EvidenceAggregator(SourceRegistry.default()),
    )

    aggregated = await pipeline.collect(claim)
    assert aggregated.fallback_used is True
    assert any(
        output.source_id == "web_fallback" for output in aggregated.source_outputs
    )
    assert aggregated.evidence_docs[0]["source_id"] == "web_fallback"


class _FakeSearchClient:
    def __init__(self):
        self.search_called = False

    async def search(self, query: str, *, max_results: int = 5):  # noqa: ARG002
        self.search_called = True
        return []

    async def fetch_pages(self, results):  # noqa: ANN001, ARG002
        return []

    async def close(self):
        return None


class _FakeStore:
    def __init__(self):
        self.persist_called = False
        self.completed_called = False
        self.begin_called = False
        self.last_metadata = None

    async def cached_documents(
        self,
        claim: PolicyClaim,  # noqa: ARG002
        plan: RoutingPlan,  # noqa: ARG002
        *,
        source_id: str,  # noqa: ARG002
        max_age_hours: int = 24,  # noqa: ARG002
        limit: int = 5,  # noqa: ARG002
    ):
        return [
            {
                "title": "Cached source",
                "url": "https://cached.example/doc",
                "content": "Previously discovered evidence.",
                "metadata": {"cached": True},
            }
        ]

    async def begin_run(
        self,
        claim: PolicyClaim,
        plan: RoutingPlan,
        *,
        case_id: str | None = None,  # noqa: ARG002
    ):
        self.begin_called = True
        return 123

    async def persist_aggregated(self, run_id: int | None, aggregated):  # noqa: ANN001, ARG002
        self.persist_called = True

    async def complete_run(
        self,
        run_id: int | None,  # noqa: ARG002
        *,
        status: str = "completed",  # noqa: ARG002
        metadata=None,  # noqa: ANN001
        error_text: str | None = None,  # noqa: ARG002
    ):
        self.completed_called = True
        self.last_metadata = metadata


@pytest.mark.asyncio
async def test_web_fallback_uses_cached_documents_before_network():
    claim = _claim("EU-LFS", "unemployment", "EU unemployment changed in 2021.")
    plan = RoutingPlan(
        claim_type=ClaimType.METHODOLOGY_AWARE,
        source_ids=["methodology_kb"],
        fallback_source_id="web_fallback",
    )
    fake_client = _FakeSearchClient()
    fake_store = _FakeStore()
    source = WebSearchEvidenceSource(
        search_client=fake_client,
        retrieval_store=fake_store,  # type: ignore[arg-type]
    )

    output = await source.collect(claim, plan=plan)
    assert output.evidence_docs
    assert output.evidence_docs[0]["metadata"]["cached"] is True
    assert fake_client.search_called is False


@pytest.mark.asyncio
async def test_pipeline_persists_aggregated_results_with_store():
    claim = _claim(None, "employment", "Employment changed over time.")
    fake_store = _FakeStore()
    pipeline = EvidencePipeline(
        router=_StaticRouter(),  # type: ignore[arg-type]
        sources={
            "primary_empty": _StaticSource(
                "primary_empty",
                SourceOutput(source_id="primary_empty"),
            ),
            "web_fallback": _StaticSource(
                "web_fallback",
                SourceOutput(
                    source_id="web_fallback",
                    evidence_docs=[
                        {
                            "title": "Fallback evidence",
                            "content": "Recovered from fallback retrieval.",
                            "url": "https://fallback.example/doc",
                        }
                    ],
                ),
            ),
        },
        aggregator=EvidenceAggregator(SourceRegistry.default()),
        retrieval_store=fake_store,  # type: ignore[arg-type]
    )

    await pipeline.collect(claim)
    assert fake_store.begin_called is True
    assert fake_store.persist_called is True
    assert fake_store.completed_called is True
    assert isinstance(fake_store.last_metadata, dict)
    assert "provider_budget_skips" in fake_store.last_metadata


@pytest.mark.asyncio
async def test_pipeline_runs_deep_research_for_ambiguous_evidence(monkeypatch):
    monkeypatch.setenv("ALETHEIA_ENABLE_DEEP_RESEARCH", "1")
    claim = _claim(None, "employment", "Employment changed over time.")
    primary = _TrackingSource("primary_empty", SourceOutput(source_id="primary_empty"))
    scholar = _TrackingSource(
        "paper_scholar",
        SourceOutput(
            source_id="paper_scholar",
            evidence_docs=[
                {
                    "title": "Scholar evidence",
                    "content": "Methodology impact paper for labor claims.",
                    "url": "https://doi.org/10.1234/example",
                }
            ],
        ),
    )

    pipeline = EvidencePipeline(
        router=_DeepResearchRouter(),  # type: ignore[arg-type]
        sources={
            "primary_empty": primary,
            "paper_scholar": scholar,
        },
        aggregator=EvidenceAggregator(SourceRegistry.default()),
    )

    aggregated = await pipeline.collect(claim)
    assert primary.called is True
    assert scholar.called is True
    assert aggregated.analysis["deep_research_used"] is True
    assert any(doc["source_id"] == "paper_scholar" for doc in aggregated.evidence_docs)


class _ScholarClient:
    def __init__(self):
        self.fetched_urls: list[str] = []

    async def search_scholar(self, query: str, *, max_results: int):  # noqa: ARG002
        return [
            WebSearchResult(
                title="Allowed paper",
                url="https://doi.org/10.1000/test",
                snippet="Paper snippet",
                provider="serpapi_google_scholar",
            ),
            WebSearchResult(
                title="Blocked paper",
                url="https://spam.example.com/paper",
                snippet="spam",
                provider="serpapi_google_scholar",
            ),
        ]

    async def fetch_pages(self, results):  # noqa: ANN001
        self.fetched_urls = [row.url for row in results]
        return [
            {
                "title": row.title,
                "url": row.url,
                "content": "Fetched paper content",
                "provider": row.provider,
                "domain": "doi.org",
            }
            for row in results
        ]

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_scholar_source_enforces_allowlist(monkeypatch):
    monkeypatch.setenv("ALETHEIA_SCHOLAR_ALLOW_DOMAINS", "doi.org,nber.org")
    monkeypatch.setenv("ALETHEIA_SCHOLAR_ALLOWLIST_MODE", "strict")
    source = ScholarPaperEvidenceSource(search_client=_ScholarClient())
    output = await source.collect(
        _claim("EU-LFS", "unemployment", "Need paper evidence"),
        plan=RoutingPlan(
            claim_type=ClaimType.METHODOLOGY_AWARE,
            source_ids=["methodology_kb"],
            fallback_source_id="web_fallback",
        ),
    )
    assert output.evidence_docs
    assert all("doi.org" in (doc.get("url") or "") for doc in output.evidence_docs)


@pytest.mark.asyncio
async def test_scholar_source_balanced_mode_keeps_non_allowlisted_with_metadata(
    monkeypatch,
):
    monkeypatch.setenv("ALETHEIA_SCHOLAR_ALLOW_DOMAINS", "doi.org")
    monkeypatch.setenv("ALETHEIA_SCHOLAR_ALLOWLIST_MODE", "balanced")
    source = ScholarPaperEvidenceSource(search_client=_ScholarClient())
    output = await source.collect(
        _claim("EU-LFS", "unemployment", "Need paper evidence"),
        plan=RoutingPlan(
            claim_type=ClaimType.METHODOLOGY_AWARE,
            source_ids=["methodology_kb"],
        ),
    )
    assert len(output.evidence_docs) == 2
    statuses = {
        (doc.get("metadata") or {}).get("allowlist_status")
        for doc in output.evidence_docs
    }
    assert "allowlisted" in statuses
    assert "untrusted" in statuses


@pytest.mark.asyncio
async def test_pipeline_source_budget_skips_extra_calls(monkeypatch):
    monkeypatch.setenv("ALETHEIA_SOURCE_BUDGET_PER_RUN", "primary_empty:1")
    claim = _claim(None, "employment", "Employment changed over time.")
    primary = _TrackingSource(
        "primary_empty",
        SourceOutput(
            source_id="primary_empty",
            evidence_docs=[
                {"title": "One", "content": "doc", "url": "https://example.org"}
            ],
        ),
    )
    pipeline = EvidencePipeline(
        router=_BudgetRouter(),  # type: ignore[arg-type]
        sources={"primary_empty": primary},
        aggregator=EvidenceAggregator(SourceRegistry.default()),
    )

    aggregated = await pipeline.collect(claim)
    assert aggregated.analysis["provider_budget_skips"] >= 1
    assert any(
        "source run budget exceeded" in err
        for output in aggregated.source_outputs
        for err in output.errors
    )
