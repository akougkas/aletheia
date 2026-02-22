"""Phase 2 evidence routing and aggregation primitives."""

from __future__ import annotations

import asyncio
from collections import defaultdict
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Protocol
from urllib.parse import urlparse

from aletheia.retrieval_store import RetrievalStore
from aletheia.schema import MethodologyChange, PolicyClaim
from aletheia.source_registry import SourceRegistry
from aletheia.web_search import WebSearchClient


class ClaimType(str, Enum):
    """Coarse claim categories used for routing strategy."""

    METHODOLOGY_AWARE = "methodology_aware"
    STATISTICAL_FACT = "statistical_fact"
    GENERAL = "general"


@dataclass(frozen=True)
class RoutingPlan:
    """Ordered evidence retrieval strategy."""

    claim_type: ClaimType
    source_ids: list[str]
    fallback_source_id: str | None = "web_fallback"
    deep_research_source_ids: list[str] = field(default_factory=list)


@dataclass
class SourceOutput:
    """Normalized result from one evidence source plugin."""

    source_id: str
    breaks: list[MethodologyChange] = field(default_factory=list)
    analysis: dict[str, Any] | None = None
    evidence_docs: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class AggregatedEvidence:
    """Merged, scored evidence fed into Editor synthesis."""

    plan: RoutingPlan
    source_outputs: list[SourceOutput]
    breaks: list[MethodologyChange]
    analysis: dict[str, Any]
    evidence_docs: list[dict[str, Any]]
    aggregate_confidence: float
    fallback_used: bool


class EvidenceSource(Protocol):
    """Interface for pluggable evidence sources."""

    source_id: str

    async def collect(
        self,
        claim: PolicyClaim,
        *,
        plan: RoutingPlan | None = None,
    ) -> SourceOutput:
        ...


class ArchivistLike(Protocol):
    async def find_breaks(self, claim: PolicyClaim) -> list[MethodologyChange]:
        ...

    async def find_evidence(self, claim: PolicyClaim, limit: int = 5) -> list[dict[str, Any]]:
        ...

    async def semantic_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        ...


class AnalystLike(Protocol):
    async def analyze(self, claim: PolicyClaim) -> dict[str, Any]:
        ...


class MethodologyEvidenceSource:
    """Primary source for methodology breaks + related snippets."""

    source_id = "methodology_kb"

    def __init__(self, archivist: ArchivistLike, *, limit: int = 5):
        self.archivist = archivist
        self.limit = limit

    async def collect(
        self,
        claim: PolicyClaim,
        *,
        plan: RoutingPlan | None = None,  # noqa: ARG002
    ) -> SourceOutput:
        output = SourceOutput(source_id=self.source_id)
        breaks_result, docs_result = await asyncio.gather(
            self.archivist.find_breaks(claim),
            self.archivist.find_evidence(claim, limit=self.limit),
            return_exceptions=True,
        )

        if isinstance(breaks_result, Exception):
            output.errors.append(str(breaks_result))
        else:
            output.breaks = breaks_result

        if isinstance(docs_result, Exception):
            output.errors.append(str(docs_result))
        else:
            output.evidence_docs = docs_result
        output.analysis = {
            "break_search_mode": getattr(self.archivist, "last_break_search_mode", "unknown"),
            "doc_search_mode": getattr(self.archivist, "last_doc_search_mode", "unknown"),
        }

        return output


class DocumentIndexEvidenceSource:
    """Document-only retrieval source (papers/notes from index)."""

    source_id = "document_index"

    def __init__(self, archivist: ArchivistLike, *, limit: int = 6):
        self.archivist = archivist
        self.limit = limit

    async def collect(
        self,
        claim: PolicyClaim,
        *,
        plan: RoutingPlan | None = None,  # noqa: ARG002
    ) -> SourceOutput:
        output = SourceOutput(source_id=self.source_id)
        try:
            output.evidence_docs = await self.archivist.find_evidence(claim, limit=self.limit)
            output.analysis = {
                "doc_search_mode": getattr(self.archivist, "last_doc_search_mode", "unknown"),
            }
        except Exception as exc:  # noqa: BLE001
            output.errors.append(str(exc))
        return output


class DataApiEvidenceSource:
    """Live API evidence source using Analyst connectors."""

    source_id = "data_api"

    def __init__(self, analyst: AnalystLike):
        self.analyst = analyst

    async def collect(
        self,
        claim: PolicyClaim,
        *,
        plan: RoutingPlan | None = None,  # noqa: ARG002
    ) -> SourceOutput:
        output = SourceOutput(source_id=self.source_id)
        try:
            analysis = await self.analyst.analyze(claim)
            output.analysis = analysis
            output.evidence_docs = self._analysis_to_docs(claim, analysis)
        except Exception as exc:  # noqa: BLE001
            output.errors.append(str(exc))
        return output

    def _analysis_to_docs(
        self, claim: PolicyClaim, analysis: dict[str, Any]
    ) -> list[dict[str, Any]]:
        raw_data = analysis.get("raw_data") or {}
        source = raw_data.get("source")
        points = raw_data.get("points") or []
        if not source or not points:
            return []

        first_point = points[0]
        last_point = points[-1]
        summary = (
            f"{source} returned {len(points)} points for {claim.indicator}. "
            f"Latest value: {last_point.get('value')} ({last_point.get('date')}); "
            f"earliest value: {first_point.get('value')} ({first_point.get('date')})."
        )
        return [
            {
                "title": f"{source} connector evidence",
                "content": summary,
                "url": None,
                "metadata": {
                    "dataset": raw_data.get("dataset"),
                    "series_id": raw_data.get("series_id"),
                    "evidence_type": "api_observation",
                },
            }
        ]


class WebSearchEvidenceSource:
    """Live web fallback with cache support and robust fetching."""

    source_id = "web_fallback"

    def __init__(
        self,
        *,
        max_results: int = 5,
        search_client: WebSearchClient | None = None,
        retrieval_store: RetrievalStore | None = None,
    ):
        self.max_results = max_results
        self.search_client = search_client or WebSearchClient()
        self.retrieval_store = retrieval_store
        self.cache_hours = int(os.environ.get("ALETHEIA_WEB_CACHE_HOURS", "24"))

    async def collect(
        self,
        claim: PolicyClaim,
        *,
        plan: RoutingPlan | None = None,
    ) -> SourceOutput:
        output = SourceOutput(source_id=self.source_id)
        if self.retrieval_store and plan and self.cache_hours > 0:
            cached = await self.retrieval_store.cached_documents(
                claim,
                plan,
                source_id=self.source_id,
                max_age_hours=self.cache_hours,
                limit=self.max_results,
            )
            if cached:
                output.evidence_docs = cached
                return output

        query = (
            f"{claim.original_text}\n"
            f"Dataset: {claim.dataset or 'unknown'}\n"
            f"Indicator: {claim.indicator}"
        )

        try:
            results = await self.search_client.search(query, max_results=self.max_results)
            pages = await self.search_client.fetch_pages(results)
            if pages:
                output.evidence_docs = [
                    {
                        "title": row.get("title") or "Web evidence",
                        "url": row.get("url"),
                        "content": row.get("content") or row.get("snippet") or "",
                        "metadata": {
                            "provider": row.get("provider"),
                            "domain": row.get("domain"),
                            "evidence_type": "web_search",
                        },
                    }
                    for row in pages
                ]
            else:
                output.evidence_docs = [
                    {
                        "title": result.title,
                        "url": result.url,
                        "content": result.snippet,
                        "metadata": {
                            "provider": result.provider,
                            "evidence_type": "web_search_snippet",
                        },
                    }
                    for result in results
                ]
        except Exception as exc:  # noqa: BLE001
            output.errors.append(str(exc))
        return output

    async def close(self) -> None:
        await self.search_client.close()

    def start_run(self) -> None:
        start = getattr(self.search_client, "start_run", None)
        if callable(start):
            start()

    def get_run_summary(self) -> dict[str, Any]:
        getter = getattr(self.search_client, "get_run_summary", None)
        if callable(getter):
            return getter()
        return {}


class ScholarPaperEvidenceSource:
    """Google Scholar paper retrieval via SERP API."""

    source_id = "paper_scholar"

    def __init__(
        self,
        *,
        max_results: int = 5,
        search_client: WebSearchClient | None = None,
        retrieval_store: RetrievalStore | None = None,
    ):
        self.max_results = max_results
        self.search_client = search_client or WebSearchClient()
        self.retrieval_store = retrieval_store
        self.cache_hours = int(os.environ.get("ALETHEIA_PAPER_CACHE_HOURS", "48"))
        self.allowlist_mode = os.environ.get(
            "ALETHEIA_SCHOLAR_ALLOWLIST_MODE",
            "balanced",
        ).strip().lower()
        self.allowed_domains = self._parse_allow_domains(
            os.environ.get(
                "ALETHEIA_SCHOLAR_ALLOW_DOMAINS",
                (
                    "doi.org,nber.org,arxiv.org,ssrn.com,oecd.org,imf.org,worldbank.org,"
                    "nature.com,science.org,sciencedirect.com,springer.com,wiley.com,"
                    "oup.com,cambridge.org"
                ),
            )
        )

    async def collect(
        self,
        claim: PolicyClaim,
        *,
        plan: RoutingPlan | None = None,
    ) -> SourceOutput:
        output = SourceOutput(source_id=self.source_id)
        if self.retrieval_store and plan and self.cache_hours > 0:
            cached = await self.retrieval_store.cached_documents(
                claim,
                plan,
                source_id=self.source_id,
                max_age_hours=self.cache_hours,
                limit=self.max_results,
            )
            if cached:
                output.evidence_docs = cached
                return output

        query = (
            f"{claim.indicator} {claim.original_text} "
            f"{claim.dataset or ''} methodology evidence paper"
        )

        try:
            results = await self.search_client.search_scholar(query, max_results=self.max_results)
            selected_results, filtered_count = self._select_results(results)
            if filtered_count > 0:
                output.errors.append(
                    f"Scholar allowlist filtered {filtered_count} result(s) in {self.allowlist_mode} mode"
                )
            pages = await self.search_client.fetch_pages(selected_results)
            if pages:
                output.evidence_docs = [
                    {
                        "title": row.get("title") or "Scholarly paper",
                        "url": row.get("url"),
                        "content": row.get("content") or row.get("snippet") or "",
                        "metadata": {
                            "provider": row.get("provider"),
                            "domain": row.get("domain"),
                            "fetched_by": row.get("fetched_by"),
                            "evidence_type": "google_scholar_paper",
                            "allowlist_status": self._allowlist_status(row.get("url")),
                            "allowlist_mode": self.allowlist_mode,
                        },
                    }
                    for row in pages
                ]
            else:
                output.evidence_docs = [
                    {
                        "title": result.title,
                        "url": result.url,
                        "content": result.snippet,
                        "metadata": {
                            "provider": result.provider,
                            "evidence_type": "google_scholar_snippet",
                            "allowlist_status": self._allowlist_status(result.url),
                            "allowlist_mode": self.allowlist_mode,
                        },
                    }
                    for result in selected_results
                ]
        except Exception as exc:  # noqa: BLE001
            output.errors.append(str(exc))
        return output

    async def close(self) -> None:
        await self.search_client.close()

    def start_run(self) -> None:
        start = getattr(self.search_client, "start_run", None)
        if callable(start):
            start()

    def get_run_summary(self) -> dict[str, Any]:
        getter = getattr(self.search_client, "get_run_summary", None)
        if callable(getter):
            return getter()
        return {}

    def _parse_allow_domains(self, raw: str) -> tuple[str, ...]:
        domains = []
        for item in raw.split(","):
            value = item.strip().lower()
            if value:
                domains.append(value)
        return tuple(domains)

    def _is_allowlisted(self, url: str | None) -> bool:
        if not url:
            return False
        try:
            domain = (urlparse(url).netloc or "").lower()
        except Exception:  # noqa: BLE001
            return False
        if not domain:
            return False
        return any(domain == allowed or domain.endswith(f".{allowed}") for allowed in self.allowed_domains)

    def _allowlist_status(self, url: str | None) -> str:
        if not url:
            return "unknown"
        return "allowlisted" if self._is_allowlisted(url) else "untrusted"

    def _select_results(
        self,
        results: list,
    ) -> tuple[list, int]:
        if self.allowlist_mode == "open":
            return results, 0

        allowlisted = [result for result in results if self._is_allowlisted(result.url)]
        if self.allowlist_mode == "strict":
            return allowlisted, max(0, len(results) - len(allowlisted))

        # balanced mode keeps all results but downstream scoring downranks untrusted domains.
        return results, 0


class ClaimRouter:
    """Deterministic strategy router for evidence retrieval."""

    _methodology_datasets = {
        "NHIS",
        "CPS",
        "ACS",
        "CPI",
        "EU-LFS",
        "HICP",
        "EU-MORTALITY",
        "ESA2010",
        "EU-SILC",
    }
    _statistical_datasets = {"BLS", "ECB", "FRED", "CENSUS"}
    _methodology_terms = (
        "methodology",
        "redesign",
        "revision",
        "series break",
        "classification",
        "definition",
        "comparability",
    )
    _statistical_terms = ("rate", "gdp", "inflation", "unemployment", "poverty")

    def route(self, claim: PolicyClaim) -> RoutingPlan:
        dataset = (claim.dataset or "").strip().upper().replace("_", "-")
        combined_text = f"{claim.indicator} {claim.original_text}".lower()

        if dataset in self._methodology_datasets or any(
            term in combined_text for term in self._methodology_terms
        ):
            return RoutingPlan(
                claim_type=ClaimType.METHODOLOGY_AWARE,
                source_ids=["methodology_kb", "data_api", "document_index"],
                fallback_source_id="web_fallback",
                deep_research_source_ids=["paper_scholar"],
            )

        if dataset in self._statistical_datasets or any(
            term in combined_text for term in self._statistical_terms
        ):
            return RoutingPlan(
                claim_type=ClaimType.STATISTICAL_FACT,
                source_ids=["data_api", "methodology_kb", "document_index"],
                fallback_source_id="web_fallback",
                deep_research_source_ids=["paper_scholar"],
            )

        return RoutingPlan(
            claim_type=ClaimType.GENERAL,
            source_ids=["document_index", "methodology_kb"],
            fallback_source_id="web_fallback",
            deep_research_source_ids=["paper_scholar"],
        )


class EvidenceAggregator:
    """Aggregate and rank evidence with explicit relevance/confidence scores."""

    def __init__(self, registry: SourceRegistry):
        self.registry = registry

    def aggregate(
        self,
        claim: PolicyClaim,
        plan: RoutingPlan,
        source_outputs: list[SourceOutput],
    ) -> AggregatedEvidence:
        breaks = self._dedupe_breaks(source_outputs)
        analysis = self._merge_analysis(source_outputs)
        evidence_docs = self._score_and_rank_docs(claim, source_outputs, analysis)
        aggregate_confidence = self._aggregate_confidence(evidence_docs, analysis)
        fallback_used = any(
            plan.fallback_source_id and output.source_id == plan.fallback_source_id
            for output in source_outputs
        )
        return AggregatedEvidence(
            plan=plan,
            source_outputs=source_outputs,
            breaks=breaks,
            analysis=analysis,
            evidence_docs=evidence_docs,
            aggregate_confidence=aggregate_confidence,
            fallback_used=fallback_used,
        )

    def _dedupe_breaks(self, source_outputs: list[SourceOutput]) -> list[MethodologyChange]:
        by_key: dict[tuple[int | None, str | None], MethodologyChange] = {}
        for output in source_outputs:
            for change in output.breaks:
                key = (change.id, change.benchmark_case_id)
                by_key[key] = change
        return list(by_key.values())

    def _merge_analysis(self, source_outputs: list[SourceOutput]) -> dict[str, Any]:
        chosen: dict[str, Any] = {}
        for output in source_outputs:
            if output.analysis and output.analysis.get("data_retrieved"):
                chosen = dict(output.analysis)
                break
        if not chosen:
            for output in source_outputs:
                if output.analysis:
                    chosen = dict(output.analysis)
                    break

        source_analysis = {
            output.source_id: output.analysis
            for output in source_outputs
            if output.analysis
        }
        if source_analysis:
            chosen["source_analysis"] = source_analysis

        source_errors = {
            output.source_id: output.errors
            for output in source_outputs
            if output.errors
        }
        if source_errors:
            chosen["source_errors"] = source_errors
        return chosen

    def _score_and_rank_docs(
        self,
        claim: PolicyClaim,
        source_outputs: list[SourceOutput],
        analysis: dict[str, Any],
    ) -> list[dict[str, Any]]:
        scored: list[dict[str, Any]] = []
        for output in source_outputs:
            for raw_doc in output.evidence_docs:
                doc = dict(raw_doc)
                doc["source_id"] = output.source_id
                relevance = self._score_relevance(claim, doc)
                confidence = self._score_confidence(
                    output.source_id,
                    doc,
                    relevance,
                    analysis,
                )
                doc["relevance_score"] = round(relevance, 3)
                doc["confidence_score"] = round(confidence, 3)
                scored.append(doc)

        scored.sort(
            key=lambda item: (
                float(item.get("confidence_score", 0.0)),
                float(item.get("relevance_score", 0.0)),
            ),
            reverse=True,
        )
        return scored

    def _claim_tokens(self, claim: PolicyClaim) -> set[str]:
        base = f"{claim.dataset or ''} {claim.indicator} {claim.original_text}"
        tokens = re.findall(r"[a-z0-9-]+", base.lower())
        return {token for token in tokens if len(token) >= 4}

    _us_markers = {"bls", "census", "fred", "american", "united states"}
    _eu_markers = {"eurostat", "euro area", "eurozone", "european", "hicp", "eu-lfs", "eu-silc", "ecb"}

    def _claim_geography(self, claim: PolicyClaim) -> str:
        """Return 'us', 'eu', or '' based on claim context."""
        text = f"{claim.geography or ''} {claim.original_text} {claim.dataset or ''}".lower()
        if any(m in text for m in self._eu_markers) or any(
            m in text for m in {"eu ", "eu-"}
        ):
            return "eu"
        if any(m in text for m in self._us_markers) or any(
            m in text for m in {"usa", "u.s."}
        ):
            return "us"
        return ""

    def _score_relevance(self, claim: PolicyClaim, doc: dict[str, Any]) -> float:
        claim_tokens = self._claim_tokens(claim)
        if not claim_tokens:
            return 0.0

        payload = " ".join(
            [
                str(doc.get("title", "")),
                str(doc.get("content", "")),
                str(doc.get("url", "")),
            ]
        ).lower()
        doc_tokens = {token for token in re.findall(r"[a-z0-9-]+", payload) if len(token) >= 4}
        if not doc_tokens:
            return 0.0

        overlap = len(claim_tokens & doc_tokens)
        overlap_score = overlap / max(1, min(len(claim_tokens), 8))

        indicator_phrase = claim.indicator.lower().strip()
        indicator_bonus = 0.15 if indicator_phrase and indicator_phrase in payload else 0.0
        dataset = (claim.dataset or "").lower().strip()
        dataset_bonus = 0.1 if dataset and dataset in payload else 0.0

        # Geography mismatch penalty: penalize US docs for EU claims and vice versa.
        geo_penalty = 0.0
        claim_geo = self._claim_geography(claim)
        if claim_geo == "eu" and any(m in payload for m in self._us_markers):
            geo_penalty = 0.25
        elif claim_geo == "us" and any(m in payload for m in self._eu_markers):
            geo_penalty = 0.25

        return max(0.0, min(1.0, overlap_score + indicator_bonus + dataset_bonus - geo_penalty))

    def _score_confidence(
        self,
        source_id: str,
        doc: dict[str, Any],
        relevance_score: float,
        analysis: dict[str, Any],
    ) -> float:
        base = self.registry.base_confidence(source_id)
        trust_bonus = 0.1 if self.registry.is_trusted_url(source_id, doc.get("url")) else 0.0
        fallback_penalty = 0.1 if source_id == "web_fallback" else 0.0
        allowlist_penalty = 0.0
        if source_id == "paper_scholar":
            metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
            status = metadata.get("allowlist_status")
            if status in {"untrusted", "unknown"}:
                allowlist_penalty = 0.12

        data_consistency_adjust = 0.0
        value_check = analysis.get("claim_value_check")
        if source_id == "data_api" and isinstance(value_check, dict):
            if value_check.get("within_tolerance") is True:
                data_consistency_adjust += 0.08
            elif value_check.get("within_tolerance") is False:
                data_consistency_adjust -= 0.12

        structure_signal = analysis.get("structural_break_detected")
        break_signal_adjust = 0.0
        if isinstance(structure_signal, dict) and structure_signal.get("detected"):
            math_confidence = float(structure_signal.get("confidence", 0.5))
            if source_id in {"data_api", "methodology_kb"}:
                break_signal_adjust += 0.15 * math_confidence

        score = (
            (0.55 * base)
            + (0.45 * relevance_score)
            + trust_bonus
            - fallback_penalty
            - allowlist_penalty
            + data_consistency_adjust
            + break_signal_adjust
        )
        return max(0.0, min(1.0, score))

    def _aggregate_confidence(self, evidence_docs: list[dict[str, Any]], analysis: dict[str, Any]) -> float:
        if not evidence_docs:
            return 0.0
        top_scores = [
            float(doc.get("confidence_score", 0.0))
            for doc in evidence_docs[:3]
            if isinstance(doc.get("confidence_score"), (int, float))
        ]
        if not top_scores:
            return 0.0
        score = sum(top_scores) / len(top_scores)
        value_check = analysis.get("claim_value_check")
        if isinstance(value_check, dict):
            if value_check.get("within_tolerance") is True:
                score += 0.04
            elif value_check.get("within_tolerance") is False:
                score -= 0.08
        return round(max(0.0, min(1.0, score)), 3)


class EvidencePipeline:
    """Run routing plan, execute source plugins, and aggregate results."""

    def __init__(
        self,
        router: ClaimRouter,
        sources: dict[str, EvidenceSource],
        aggregator: EvidenceAggregator,
        retrieval_store: RetrievalStore | None = None,
    ):
        self.router = router
        self.sources = sources
        self.aggregator = aggregator
        self.retrieval_store = retrieval_store
        self.deep_research_enabled = (
            os.environ.get("ALETHEIA_ENABLE_DEEP_RESEARCH", "0") == "1"
        )
        self.deep_research_threshold = float(
            os.environ.get("ALETHEIA_DEEP_RESEARCH_CONF_THRESHOLD", "0.62")
        )
        self.source_budget_per_run = self._parse_budget_map(
            os.environ.get(
                "ALETHEIA_SOURCE_BUDGET_PER_RUN",
                "methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1",
            )
        )
        self._run_source_calls: dict[str, int] = defaultdict(int)
        self._run_source_skips: dict[str, int] = defaultdict(int)

    async def collect(self, claim: PolicyClaim) -> AggregatedEvidence:
        return await self.collect_with_progress(claim, progress_callback=None)

    async def collect_with_progress(
        self,
        claim: PolicyClaim,
        *,
        progress_callback: Callable[[dict[str, Any]], Any] | None,
    ) -> AggregatedEvidence:
        self._refresh_runtime_flags()
        self._reset_run_state()
        plan = self.router.route(claim)
        await self._emit_progress(
            progress_callback,
            {
                "event": "routing_selected",
                "claim_type": plan.claim_type.value,
                "source_ids": list(plan.source_ids),
                "fallback_source_id": plan.fallback_source_id,
            },
        )
        run_id: str | None = None
        if self.retrieval_store:
            run_id = await self.retrieval_store.begin_run(claim, plan)

        outputs = await self._collect_sources(
            plan.source_ids,
            claim,
            plan=plan,
            progress_callback=progress_callback,
        )

        if plan.fallback_source_id and not self._has_substantive_evidence(outputs):
            if plan.fallback_source_id in self.sources and all(
                output.source_id != plan.fallback_source_id for output in outputs
            ):
                outputs.extend(
                    await self._collect_sources(
                        [plan.fallback_source_id],
                        claim,
                        plan=plan,
                        progress_callback=progress_callback,
                    )
                )

        aggregated = self.aggregator.aggregate(claim, plan, outputs)
        deep_research_used = False
        if self.deep_research_enabled and self._is_ambiguous(aggregated):
            deep_outputs = await self._collect_sources(
                plan.deep_research_source_ids,
                claim,
                plan=plan,
                progress_callback=progress_callback,
            )
            if deep_outputs:
                outputs.extend(deep_outputs)
                aggregated = self.aggregator.aggregate(claim, plan, outputs)
                deep_research_used = True

        aggregated.analysis["deep_research_used"] = deep_research_used
        aggregated.analysis["ambiguous_evidence"] = self._is_ambiguous(aggregated)
        provider_budget_summary, provider_budget_skips = self._collect_provider_budget_report()
        source_budget_summary = {
            "calls": dict(self._run_source_calls),
            "skips": dict(self._run_source_skips),
            "skip_total": int(sum(self._run_source_skips.values())),
        }
        aggregated.analysis["provider_budget_summary"] = {
            "sources": source_budget_summary,
            "providers": provider_budget_summary,
        }
        aggregated.analysis["provider_budget_skips"] = (
            source_budget_summary["skip_total"] + provider_budget_skips
        )

        if self.retrieval_store:
            await self.retrieval_store.persist_aggregated(run_id, aggregated)
            await self.retrieval_store.complete_run(
                run_id,
                status="completed",
                metadata={
                    "fallback_used": aggregated.fallback_used,
                    "deep_research_used": deep_research_used,
                    "aggregate_confidence": aggregated.aggregate_confidence,
                    "evidence_count": len(aggregated.evidence_docs),
                    "break_count": len(aggregated.breaks),
                    "provider_budget_skips": aggregated.analysis.get("provider_budget_skips", 0),
                    "provider_budget_summary": aggregated.analysis.get("provider_budget_summary"),
                },
            )
        await self._emit_progress(
            progress_callback,
            {
                "event": "collection_completed",
                "break_count": len(aggregated.breaks),
                "evidence_count": len(aggregated.evidence_docs),
                "aggregate_confidence": aggregated.aggregate_confidence,
            },
        )
        return aggregated

    async def _collect_sources(
        self,
        source_ids: list[str],
        claim: PolicyClaim,
        *,
        plan: RoutingPlan,
        progress_callback: Callable[[dict[str, Any]], Any] | None,
    ) -> list[SourceOutput]:
        tasks = []
        task_source_ids: list[str] = []
        outputs: list[SourceOutput] = []
        for source_id in source_ids:
            source = self.sources.get(source_id)
            if source is None:
                continue

            budget = self.source_budget_per_run.get(source_id)
            current_calls = self._run_source_calls.get(source_id, 0)
            if budget is not None and budget >= 0 and current_calls >= budget:
                self._run_source_skips[f"{source_id}:run_budget_exceeded"] += 1
                await self._emit_progress(
                    progress_callback,
                    {
                        "event": "source_skipped",
                        "source_id": source_id,
                        "reason": "run_budget_exceeded",
                    },
                )
                outputs.append(
                    SourceOutput(
                        source_id=source_id,
                        errors=["source run budget exceeded"],
                    )
                )
                continue

            self._run_source_calls[source_id] = current_calls + 1
            await self._emit_progress(
                progress_callback,
                {"event": "source_started", "source_id": source_id},
            )
            try:
                task = source.collect(claim, plan=plan)  # type: ignore[call-arg]
            except TypeError:
                task = source.collect(claim)  # type: ignore[call-arg]
            tasks.append(task)
            task_source_ids.append(source_id)

        if not tasks:
            return outputs

        results = await asyncio.gather(*tasks, return_exceptions=True)
        for source_id, result in zip(task_source_ids, results, strict=True):
            if isinstance(result, Exception):
                payload = SourceOutput(source_id=source_id, errors=[str(result)])
                outputs.append(payload)
                await self._emit_progress(
                    progress_callback,
                    {
                        "event": "source_completed",
                        "source_id": source_id,
                        "break_count": 0,
                        "doc_count": 0,
                        "error_count": 1,
                    },
                )
            else:
                outputs.append(result)
                await self._emit_progress(
                    progress_callback,
                    {
                        "event": "source_completed",
                        "source_id": source_id,
                        "break_count": len(result.breaks),
                        "doc_count": len(result.evidence_docs),
                        "error_count": len(result.errors),
                    },
                )
        return outputs

    def _has_substantive_evidence(self, outputs: list[SourceOutput]) -> bool:
        for output in outputs:
            if output.breaks:
                return True
            if output.evidence_docs:
                return True
            if output.analysis and output.analysis.get("data_retrieved"):
                return True
        return False

    def _is_ambiguous(self, aggregated: AggregatedEvidence) -> bool:
        if aggregated.aggregate_confidence < self.deep_research_threshold:
            return True
        if not aggregated.breaks and not aggregated.analysis.get("data_retrieved"):
            return True
        if not aggregated.evidence_docs:
            return True
        top_doc_conf = aggregated.evidence_docs[0].get("confidence_score")
        if isinstance(top_doc_conf, (int, float)) and float(top_doc_conf) < 0.65:
            return True
        if aggregated.fallback_used and len(aggregated.evidence_docs) < 2:
            return True
        return False

    async def close(self) -> None:
        for source in self.sources.values():
            close = getattr(source, "close", None)
            if close is None:
                continue
            try:
                maybe = close()
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception:
                continue

    def _parse_budget_map(self, raw: str) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for item in raw.split(","):
            entry = item.strip()
            if not entry or ":" not in entry:
                continue
            key, value = entry.split(":", 1)
            source_id = key.strip()
            try:
                budget = int(value.strip())
            except ValueError:
                continue
            if source_id:
                mapping[source_id] = budget
        return mapping

    def _reset_run_state(self) -> None:
        self._run_source_calls.clear()
        self._run_source_skips.clear()
        for source in self.sources.values():
            start_run = getattr(source, "start_run", None)
            if callable(start_run):
                try:
                    start_run()
                except Exception:
                    continue

    def _refresh_runtime_flags(self) -> None:
        self.deep_research_enabled = os.environ.get("ALETHEIA_ENABLE_DEEP_RESEARCH", "0") == "1"
        self.deep_research_threshold = float(
            os.environ.get("ALETHEIA_DEEP_RESEARCH_CONF_THRESHOLD", "0.62")
        )
        self.source_budget_per_run = self._parse_budget_map(
            os.environ.get(
                "ALETHEIA_SOURCE_BUDGET_PER_RUN",
                "methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1",
            )
        )

    def _collect_provider_budget_report(self) -> tuple[dict[str, dict[str, Any]], int]:
        summary: dict[str, dict[str, Any]] = {}
        seen_clients: set[int] = set()
        total_skips = 0
        for source_id, source in self.sources.items():
            getter = getattr(source, "get_run_summary", None)
            if not callable(getter):
                continue
            run_key = None
            client = getattr(source, "search_client", None)
            if client is not None:
                run_key = id(client)
                if run_key in seen_clients:
                    continue
            try:
                payload = getter()
            except Exception:
                continue
            if isinstance(payload, dict) and payload:
                summary[source_id] = payload
                total_skips += int(payload.get("skip_total", 0))
                if run_key is not None:
                    seen_clients.add(run_key)
        return summary, total_skips

    async def _emit_progress(
        self,
        callback: Callable[[dict[str, Any]], Any] | None,
        payload: dict[str, Any],
    ) -> None:
        if callback is None:
            return
        try:
            maybe = callback(payload)
            if asyncio.iscoroutine(maybe):
                await maybe
        except Exception:
            return
