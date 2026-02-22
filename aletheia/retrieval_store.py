"""Persistence for retrieval sessions, cached evidence, and discovered documents (SurrealDB)."""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any
from typing import TYPE_CHECKING

from aletheia.db import diagnose_connection_failure, get_connection
from aletheia.schema import PolicyClaim

if TYPE_CHECKING:
    from aletheia.evidence import AggregatedEvidence, RoutingPlan


logger = logging.getLogger("aletheia.retrieval_store")


def _normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _chunk_text(text: str, *, chunk_size: int = 1200, overlap: int = 150) -> list[str]:
    cleaned = _normalize_space(text)
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _query_result_rows(result: Any) -> list[dict]:
    """Extract rows from a SurrealDB query() result."""
    if not result:
        return []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                rows = item.get("result", [])
                if isinstance(rows, list):
                    return rows
            elif isinstance(item, list):
                return item
        return result if all(isinstance(r, dict) for r in result) else []
    return []


def _surreal_id(record: Any) -> str:
    if isinstance(record, dict):
        return str(record.get("id", ""))
    if isinstance(record, list) and record:
        return _surreal_id(record[0])
    return str(record)


class RetrievalStore:
    """Stores retrieval history and indexed evidence in SurrealDB."""

    def query_hash(self, claim: PolicyClaim, plan: "RoutingPlan") -> str:
        payload = (
            f"{claim.original_text}|{claim.dataset or ''}|{claim.indicator}|"
            f"{plan.claim_type.value}|{','.join(plan.source_ids)}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def begin_run(self, claim: PolicyClaim, plan: "RoutingPlan") -> str | None:
        query_hash = self.query_hash(claim, plan)
        try:
            async with get_connection() as db:
                result = await db.query(
                    """
                    CREATE session SET
                        query_hash = $hash,
                        claim_text = $claim_text,
                        claim_dataset = $dataset,
                        claim_indicator = $indicator,
                        claim_type = $claim_type,
                        status = 'running',
                        metadata = $metadata
                    """,
                    {
                        "hash": query_hash,
                        "claim_text": claim.original_text,
                        "dataset": claim.dataset,
                        "indicator": claim.indicator,
                        "claim_type": plan.claim_type.value,
                        "metadata": {"source_ids": plan.source_ids},
                    },
                )
                rows = _query_result_rows(result)
                return _surreal_id(rows[0]) if rows else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("begin_run failed: %s", exc)
            return None

    async def complete_run(
        self,
        run_id: str | None,
        *,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
        error_text: str | None = None,
    ) -> None:
        if run_id is None:
            return
        try:
            async with get_connection() as db:
                # Merge metadata
                if metadata:
                    await db.query(
                        """
                        UPDATE $id SET
                            status = $status,
                            metadata = object::extend(metadata OR {}, $meta),
                            error_text = $error_text,
                            completed_at = time::now()
                        """,
                        {
                            "id": run_id,
                            "status": status,
                            "meta": metadata,
                            "error_text": error_text,
                        },
                    )
                else:
                    await db.query(
                        """
                        UPDATE $id SET
                            status = $status,
                            error_text = $error_text,
                            completed_at = time::now()
                        """,
                        {"id": run_id, "status": status, "error_text": error_text},
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("complete_run failed: %s", exc)

    async def cached_documents(
        self,
        claim: PolicyClaim,
        plan: "RoutingPlan",
        *,
        source_id: str,
        max_age_hours: int = 24,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query_hash = self.query_hash(claim, plan)
        try:
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT
                        ->found->document.title AS title,
                        ->found->document.url AS url,
                        ->found->document<-part_of<-chunk.content[0] AS content
                    FROM session
                    WHERE query_hash = $hash
                      AND status = 'completed'
                      AND started_at >= time::now() - $age
                    ORDER BY started_at DESC
                    LIMIT $limit
                    """,
                    {
                        "hash": query_hash,
                        "age": f"{max_age_hours}h",
                        "limit": limit,
                    },
                )
                rows = _query_result_rows(result)
            docs: list[dict[str, Any]] = []
            for row in rows:
                # Flatten nested arrays from graph traversal
                titles = row.get("title", [])
                urls = row.get("url", [])
                contents = row.get("content", [])
                title = titles[0] if isinstance(titles, list) and titles else str(titles or "Cached evidence")
                url = urls[0] if isinstance(urls, list) and urls else None
                content = contents[0] if isinstance(contents, list) and contents else ""
                docs.append(
                    {
                        "title": title,
                        "url": url,
                        "content": content,
                        "metadata": {"cached": True, "source_id": source_id},
                    }
                )
            return docs
        except Exception as exc:  # noqa: BLE001
            logger.warning("cached_documents failed: %s", exc)
            return []

    async def persist_aggregated(
        self,
        run_id: str | None,
        aggregated: "AggregatedEvidence",
    ) -> None:
        if run_id is None:
            return
        try:
            async with get_connection() as db:
                for rank, doc in enumerate(aggregated.evidence_docs, start=1):
                    document_id = await self._upsert_document_with_chunks(db, doc)
                    await db.query(
                        """
                        RELATE $session->found->$document SET
                            source_id = $source_id,
                            relevance_score = $relevance,
                            confidence_score = $confidence,
                            is_cached = $cached,
                            rank = $rank
                        """,
                        {
                            "session": run_id,
                            "document": document_id,
                            "source_id": str(doc.get("source_id") or "unknown"),
                            "relevance": self._safe_float(doc.get("relevance_score")),
                            "confidence": self._safe_float(doc.get("confidence_score")),
                            "cached": self._is_cached_doc(doc),
                            "rank": rank,
                        },
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("persist_aggregated failed: %s", exc)

    async def get_stats(
        self,
        *,
        hours: int = 24,
        limit: int = 15,
    ) -> dict[str, Any]:
        """Summarize retrieval history and cache usage."""
        window_hours = max(1, int(hours))
        recent_limit = max(1, int(limit))
        try:
            async with get_connection() as db:
                cutoff = f"{window_hours}h"

                # Summary
                summary_result = await db.query(
                    """
                    SELECT
                        count() AS total_runs,
                        count(status = 'completed' OR NONE) AS completed_runs
                    FROM session
                    WHERE started_at >= time::now() - $cutoff
                    GROUP ALL
                    """,
                    {"cutoff": cutoff},
                )
                summary_rows = _query_result_rows(summary_result)
                total_runs = int(summary_rows[0].get("total_runs", 0)) if summary_rows else 0
                completed_runs = int(summary_rows[0].get("completed_runs", 0)) if summary_rows else 0

                # Recent runs
                recent_result = await db.query(
                    """
                    SELECT *
                    FROM session
                    WHERE started_at >= time::now() - $cutoff
                    ORDER BY started_at DESC
                    LIMIT $limit
                    """,
                    {"cutoff": cutoff, "limit": recent_limit},
                )
                recent_rows = _query_result_rows(recent_result)

            return {
                "window_hours": window_hours,
                "summary": {
                    "total_runs": total_runs,
                    "completed_runs": completed_runs,
                    "non_completed_runs": total_runs - completed_runs,
                    "avg_aggregate_confidence": 0.0,
                    "provider_budget_skips": 0,
                    "linked_docs": 0,
                    "cache_hits": 0,
                    "cache_hit_rate": 0.0,
                    "distinct_sources": 0,
                },
                "sources": [],
                "recent_runs": [
                    {
                        "id": _surreal_id(row),
                        "claim_dataset": row.get("claim_dataset"),
                        "claim_indicator": row.get("claim_indicator"),
                        "claim_type": row.get("claim_type"),
                        "status": row.get("status"),
                        "started_at": row.get("started_at"),
                        "completed_at": row.get("completed_at"),
                        "fallback_used": (row.get("metadata") or {}).get("fallback_used", False),
                        "deep_research_used": (row.get("metadata") or {}).get("deep_research_used", False),
                        "evidence_count": (row.get("metadata") or {}).get("evidence_count", 0),
                        "aggregate_confidence": (row.get("metadata") or {}).get("aggregate_confidence", 0.0),
                        "provider_budget_skips": (row.get("metadata") or {}).get("provider_budget_skips", 0),
                    }
                    for row in recent_rows
                ],
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("get_stats failed: %s", exc)
            diagnosis = diagnose_connection_failure(exc)
            return {
                "window_hours": window_hours,
                "error": str(exc),
                "diagnosis": diagnosis,
            }

    async def _upsert_document_with_chunks(
        self,
        db,
        doc: dict[str, Any],
    ) -> str:
        title = str(doc.get("title") or "Untitled evidence").strip()
        url = self._safe_url(doc.get("url"))
        source_id = str(doc.get("source_id") or "unknown")
        content = _normalize_space(str(doc.get("content") or doc.get("snippet") or ""))
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        content_hash = self._content_hash(title=title, url=url, content=content)

        # Find existing
        existing = None
        if url:
            result = await db.query(
                "SELECT * FROM document WHERE url = $url LIMIT 1",
                {"url": url},
            )
            rows = _query_result_rows(result)
            if rows:
                existing = rows[0]

        if not existing:
            result = await db.query(
                "SELECT * FROM document WHERE content_hash = $hash LIMIT 1",
                {"hash": content_hash},
            )
            rows = _query_result_rows(result)
            if rows:
                existing = rows[0]

        if existing:
            document_id = _surreal_id(existing)
            await db.query(
                """
                UPDATE $id SET
                    title = $title,
                    doc_type = $doc_type,
                    url = $url OR url,
                    content_hash = $hash
                """,
                {
                    "id": document_id,
                    "title": title,
                    "doc_type": f"retrieved_{source_id}",
                    "url": url,
                    "hash": content_hash,
                },
            )
        else:
            result = await db.query(
                """
                CREATE document SET
                    title = $title,
                    doc_type = $doc_type,
                    url = $url,
                    publication_date = $pub_date,
                    content_hash = $hash
                """,
                {
                    "title": title,
                    "doc_type": f"retrieved_{source_id}",
                    "url": url,
                    "pub_date": datetime.now(timezone.utc).isoformat(),
                    "hash": content_hash,
                },
            )
            rows = _query_result_rows(result)
            document_id = _surreal_id(rows[0]) if rows else ""

        # Upsert chunks
        chunk_source = f"{title}\n\n{content}\n\nURL: {url or 'n/a'}"
        chunks = _chunk_text(chunk_source)
        metadata_val = {
            "source": "retrieval_store",
            "source_id": source_id,
            "url": url,
            **metadata,
        }
        for idx, chunk in enumerate(chunks):
            result = await db.query(
                """
                CREATE chunk SET
                    chunk_index = $idx,
                    content = $content,
                    metadata = $metadata
                """,
                {"idx": idx, "content": chunk, "metadata": metadata_val},
            )
            chunk_rows = _query_result_rows(result)
            if chunk_rows:
                chunk_id = _surreal_id(chunk_rows[0])
                await db.query(
                    "RELATE $chunk->part_of->$doc",
                    {"chunk": chunk_id, "doc": document_id},
                )

        return document_id

    def _content_hash(self, *, title: str, url: str | None, content: str) -> str:
        payload = f"{title}|{url or ''}|{content}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _safe_float(self, value: Any) -> float | None:
        if isinstance(value, (float, int)):
            return float(value)
        try:
            return float(value)
        except Exception:  # noqa: BLE001
            return None

    def _safe_url(self, value: Any) -> str | None:
        if not value:
            return None
        text = str(value).strip()
        return text if text.startswith(("http://", "https://")) else None

    def _is_cached_doc(self, doc: dict[str, Any]) -> bool:
        metadata = doc.get("metadata")
        if not isinstance(metadata, dict):
            return False
        value = metadata.get("cached")
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.lower() == "true"
        return False
