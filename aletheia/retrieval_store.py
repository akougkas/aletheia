"""Persistence for retrieval runs, cached evidence, and discovered documents."""

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


class RetrievalStore:
    """Stores retrieval history and indexed evidence in PostgreSQL."""

    def query_hash(self, claim: PolicyClaim, plan: RoutingPlan) -> str:
        payload = (
            f"{claim.original_text}|{claim.dataset or ''}|{claim.indicator}|"
            f"{plan.claim_type.value}|{','.join(plan.source_ids)}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    async def begin_run(self, claim: PolicyClaim, plan: RoutingPlan) -> int | None:
        query_hash = self.query_hash(claim, plan)
        try:
            async with get_connection() as conn:
                row = await (
                    await conn.execute(
                        """
                        INSERT INTO retrieval_runs (
                            query_hash,
                            claim_text,
                            claim_dataset,
                            claim_indicator,
                            claim_type,
                            status,
                            metadata
                        )
                        VALUES (%s, %s, %s, %s, %s, 'running', %s::jsonb)
                        RETURNING id
                        """,
                        (
                            query_hash,
                            claim.original_text,
                            claim.dataset,
                            claim.indicator,
                            plan.claim_type.value,
                            json.dumps({"source_ids": plan.source_ids}),
                        ),
                    )
                ).fetchone()
                await conn.commit()
                return int(row["id"]) if row else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("begin_run failed: %s", exc)
            return None

    async def complete_run(
        self,
        run_id: int | None,
        *,
        status: str = "completed",
        metadata: dict[str, Any] | None = None,
        error_text: str | None = None,
    ) -> None:
        if run_id is None:
            return
        try:
            async with get_connection() as conn:
                await conn.execute(
                    """
                    UPDATE retrieval_runs
                    SET status = %s,
                        metadata = COALESCE(metadata, '{}'::jsonb) || %s::jsonb,
                        error_text = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (status, json.dumps(metadata or {}), error_text, run_id),
                )
                await conn.commit()
        except Exception as exc:  # noqa: BLE001
            logger.warning("complete_run failed: %s", exc)

    async def cached_documents(
        self,
        claim: PolicyClaim,
        plan: RoutingPlan,
        *,
        source_id: str,
        max_age_hours: int = 24,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        query_hash = self.query_hash(claim, plan)
        try:
            async with get_connection() as conn:
                rows = await (
                    await conn.execute(
                        """
                        SELECT d.id AS document_id,
                               d.title,
                               d.url,
                               dc.content
                        FROM retrieval_runs rr
                        JOIN retrieval_run_documents rrd ON rrd.retrieval_run_id = rr.id
                        JOIN documents d ON d.id = rrd.document_id
                        LEFT JOIN LATERAL (
                            SELECT content
                            FROM document_chunks
                            WHERE document_id = d.id
                            ORDER BY chunk_index ASC
                            LIMIT 1
                        ) dc ON TRUE
                        WHERE rr.query_hash = %s
                          AND rr.status = 'completed'
                          AND rrd.source_id = %s
                          AND rr.started_at >= NOW() - (%s || ' hours')::interval
                        ORDER BY rr.started_at DESC, COALESCE(rrd.rank, 999999), d.id DESC
                        LIMIT %s
                        """,
                        (query_hash, source_id, max_age_hours, limit),
                    )
                ).fetchall()
            docs: list[dict[str, Any]] = []
            for row in rows:
                docs.append(
                    {
                        "title": row.get("title") or "Cached evidence",
                        "url": row.get("url"),
                        "content": row.get("content") or "",
                        "metadata": {"cached": True, "source_id": source_id},
                    }
                )
            return docs
        except Exception as exc:  # noqa: BLE001
            logger.warning("cached_documents failed: %s", exc)
            return []

    async def persist_aggregated(
        self,
        run_id: int | None,
        aggregated: "AggregatedEvidence",
    ) -> None:
        if run_id is None:
            return
        try:
            async with get_connection() as conn:
                for rank, doc in enumerate(aggregated.evidence_docs, start=1):
                    document_id = await self._upsert_document_with_chunks(conn, doc)
                    await conn.execute(
                        """
                        INSERT INTO retrieval_run_documents (
                            retrieval_run_id,
                            document_id,
                            source_id,
                            relevance_score,
                            confidence_score,
                            is_cached,
                            rank
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (retrieval_run_id, document_id) DO UPDATE SET
                            source_id = EXCLUDED.source_id,
                            relevance_score = EXCLUDED.relevance_score,
                            confidence_score = EXCLUDED.confidence_score,
                            is_cached = EXCLUDED.is_cached,
                            rank = EXCLUDED.rank,
                            retrieved_at = NOW()
                        """,
                        (
                            run_id,
                            document_id,
                            str(doc.get("source_id") or "unknown"),
                            self._safe_float(doc.get("relevance_score")),
                            self._safe_float(doc.get("confidence_score")),
                            self._is_cached_doc(doc),
                            rank,
                        ),
                    )
                await conn.commit()
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
            async with get_connection() as conn:
                summary_row = await (
                    await conn.execute(
                        """
                        SELECT COUNT(*) AS total_runs,
                               COUNT(*) FILTER (WHERE status = 'completed') AS completed_runs,
                               COUNT(*) FILTER (WHERE status <> 'completed') AS non_completed_runs,
                               COALESCE(
                                   SUM(
                                       CASE
                                           WHEN (metadata->>'provider_budget_skips') ~ '^[0-9]+$'
                                           THEN (metadata->>'provider_budget_skips')::int
                                           ELSE 0
                                       END
                                   ),
                                   0
                               ) AS provider_budget_skips,
                               COALESCE(
                                   AVG(
                                       CASE
                                           WHEN (metadata->>'aggregate_confidence') ~ '^[0-9.]+$'
                                           THEN (metadata->>'aggregate_confidence')::float
                                           ELSE NULL
                                       END
                                   ),
                                   0
                               ) AS avg_aggregate_confidence
                        FROM retrieval_runs
                        WHERE started_at >= NOW() - (%s || ' hours')::interval
                        """,
                        (window_hours,),
                    )
                ).fetchone()

                docs_row = await (
                    await conn.execute(
                        """
                        SELECT COUNT(*) AS linked_docs,
                               COUNT(*) FILTER (WHERE is_cached) AS cache_hits,
                               COUNT(DISTINCT source_id) AS distinct_sources
                        FROM retrieval_run_documents rrd
                        JOIN retrieval_runs rr ON rr.id = rrd.retrieval_run_id
                        WHERE rr.started_at >= NOW() - (%s || ' hours')::interval
                        """,
                        (window_hours,),
                    )
                ).fetchone()

                source_rows = await (
                    await conn.execute(
                        """
                        SELECT source_id,
                               COUNT(*) AS doc_count,
                               COUNT(*) FILTER (WHERE is_cached) AS cache_hits,
                               ROUND(AVG(COALESCE(confidence_score, 0))::numeric, 3) AS avg_confidence
                        FROM retrieval_run_documents rrd
                        JOIN retrieval_runs rr ON rr.id = rrd.retrieval_run_id
                        WHERE rr.started_at >= NOW() - (%s || ' hours')::interval
                        GROUP BY source_id
                        ORDER BY doc_count DESC, source_id
                        """,
                        (window_hours,),
                    )
                ).fetchall()

                recent_rows = await (
                    await conn.execute(
                        """
                        SELECT id,
                               claim_dataset,
                               claim_indicator,
                               claim_type,
                               status,
                               started_at,
                               completed_at,
                               COALESCE(
                                   CASE
                                       WHEN (metadata->>'fallback_used') IN ('true', 'false')
                                       THEN (metadata->>'fallback_used')::boolean
                                       ELSE false
                                   END,
                                   false
                               ) AS fallback_used,
                               COALESCE(
                                   CASE
                                       WHEN (metadata->>'deep_research_used') IN ('true', 'false')
                                       THEN (metadata->>'deep_research_used')::boolean
                                       ELSE false
                                   END,
                                   false
                               ) AS deep_research_used,
                               COALESCE(
                                   CASE
                                       WHEN (metadata->>'evidence_count') ~ '^[0-9]+$'
                                       THEN (metadata->>'evidence_count')::int
                                       ELSE 0
                                   END,
                                   0
                               ) AS evidence_count,
                               COALESCE(
                                   CASE
                                       WHEN (metadata->>'aggregate_confidence') ~ '^[0-9.]+$'
                                       THEN (metadata->>'aggregate_confidence')::float
                                       ELSE 0
                                   END,
                                   0
                               ) AS aggregate_confidence,
                               COALESCE(
                                   CASE
                                       WHEN (metadata->>'provider_budget_skips') ~ '^[0-9]+$'
                                       THEN (metadata->>'provider_budget_skips')::int
                                       ELSE 0
                                   END,
                                   0
                               ) AS provider_budget_skips
                        FROM retrieval_runs
                        WHERE started_at >= NOW() - (%s || ' hours')::interval
                        ORDER BY started_at DESC
                        LIMIT %s
                        """,
                        (window_hours, recent_limit),
                    )
                ).fetchall()

            total_runs = int(summary_row["total_runs"] or 0)
            completed_runs = int(summary_row["completed_runs"] or 0)
            linked_docs = int(docs_row["linked_docs"] or 0)
            cache_hits = int(docs_row["cache_hits"] or 0)
            cache_hit_rate = (cache_hits / linked_docs) if linked_docs else 0.0

            return {
                "window_hours": window_hours,
                "summary": {
                    "total_runs": total_runs,
                    "completed_runs": completed_runs,
                    "non_completed_runs": int(summary_row["non_completed_runs"] or 0),
                    "avg_aggregate_confidence": float(
                        summary_row["avg_aggregate_confidence"] or 0.0
                    ),
                    "provider_budget_skips": int(
                        summary_row["provider_budget_skips"] or 0
                    ),
                    "linked_docs": linked_docs,
                    "cache_hits": cache_hits,
                    "cache_hit_rate": round(cache_hit_rate, 4),
                    "distinct_sources": int(docs_row["distinct_sources"] or 0),
                },
                "sources": [dict(row) for row in source_rows],
                "recent_runs": [dict(row) for row in recent_rows],
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
        conn,
        doc: dict[str, Any],
    ) -> int:
        title = str(doc.get("title") or "Untitled evidence").strip()
        url = self._safe_url(doc.get("url"))
        source_id = str(doc.get("source_id") or "unknown")
        content = _normalize_space(str(doc.get("content") or doc.get("snippet") or ""))
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        content_hash = self._content_hash(title=title, url=url, content=content)

        existing = None
        if url:
            existing = await (
                await conn.execute(
                    "SELECT id FROM documents WHERE url = %s ORDER BY id DESC LIMIT 1",
                    (url,),
                )
            ).fetchone()
        if not existing:
            existing = await (
                await conn.execute(
                    "SELECT id FROM documents WHERE content_hash = %s ORDER BY id DESC LIMIT 1",
                    (content_hash,),
                )
            ).fetchone()

        if existing:
            document_id = int(existing["id"])
            await conn.execute(
                """
                UPDATE documents
                SET title = %s,
                    doc_type = %s,
                    url = COALESCE(%s, url),
                    content_hash = %s
                WHERE id = %s
                """,
                (title, f"retrieved_{source_id}", url, content_hash, document_id),
            )
        else:
            row = await (
                await conn.execute(
                    """
                    INSERT INTO documents (title, doc_type, url, publication_date, content_hash)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        title,
                        f"retrieved_{source_id}",
                        url,
                        datetime.now(timezone.utc).date(),
                        content_hash,
                    ),
                )
            ).fetchone()
            document_id = int(row["id"])

        chunk_source = f"{title}\n\n{content}\n\nURL: {url or 'n/a'}"
        chunks = _chunk_text(chunk_source)
        metadata_payload = json.dumps(
            {
                "source": "retrieval_store",
                "source_id": source_id,
                "url": url,
                **metadata,
            }
        )
        for idx, chunk in enumerate(chunks):
            await conn.execute(
                """
                INSERT INTO document_chunks (document_id, chunk_index, content, metadata)
                VALUES (%s, %s, %s, %s::jsonb)
                ON CONFLICT (document_id, chunk_index) DO UPDATE
                SET content = EXCLUDED.content,
                    metadata = EXCLUDED.metadata
                """,
                (document_id, idx, chunk, metadata_payload),
            )

        await conn.execute(
            """
            DELETE FROM document_chunks
            WHERE document_id = %s AND chunk_index >= %s
            """,
            (document_id, len(chunks)),
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
