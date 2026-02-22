"""Data Provenance Agent (The Archivist) - queries methodology knowledge base (SurrealDB)."""

from __future__ import annotations

import logging
import re
from datetime import date
from typing import Any

from aletheia.agents.base import Agent
from aletheia.db import get_connection
from aletheia.schema import (
    ChangeType,
    ComparabilityLevel,
    MethodologyChange,
    PolicyClaim,
    SeverityLevel,
)
from aletheia.time_utils import extract_year


DATASET_ALIASES = {
    "EU LFS": "EU-LFS",
    "EULFS": "EU-LFS",
    "ESA 2010": "ESA2010",
    "EU SILC": "EU-SILC",
    "EU_MORTALITY": "EU-MORTALITY",
    "EU MORTALITY": "EU-MORTALITY",
}


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


class ArchivistAgent(Agent):
    """Queries the knowledge graph for methodology breaks affecting a claim."""

    name = "Archivist"
    role = "Data Provenance"
    system_prompt = (
        "You identify methodology changes that could affect data interpretation."
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.last_doc_search_mode = "uninitialized"
        self.last_break_search_mode = "uninitialized"

    def _normalize_dataset_code(self, value: str | None) -> str | None:
        if not value:
            return None
        normalized = value.strip().upper().replace("_", " ")
        normalized = re.sub(r"\s+", " ", normalized)
        return DATASET_ALIASES.get(normalized, normalized.replace(" ", "-"))

    def _enum_or_none(self, enum_type: Any, value: str | None):
        if not value:
            return None
        try:
            return enum_type(value)
        except ValueError:
            return None

    def _row_to_change(self, row: dict[str, Any]) -> MethodologyChange:
        rid = row.get("id", "")
        # Extract numeric-like id for MethodologyChange.id field
        # SurrealDB IDs look like "methodology_change:abc123"
        rid_str = str(rid)

        # Parse effective_date from SurrealDB datetime string
        effective_date_raw = row.get("effective_date")
        effective_date = None
        if effective_date_raw:
            if isinstance(effective_date_raw, date):
                effective_date = effective_date_raw
            elif isinstance(effective_date_raw, str):
                try:
                    effective_date = date.fromisoformat(effective_date_raw[:10])
                except (ValueError, TypeError):
                    effective_date = None

        # dataset_id: in SurrealDB, we link via belongs_to edge, not a column
        # Use the record ID string as dataset_id
        dataset_id_raw = row.get("dataset_id") or rid_str

        return MethodologyChange(
            id=hash(rid_str) % (2**31),  # Numeric hash for compatibility
            benchmark_case_id=row.get("benchmark_case_id"),
            dataset_id=hash(str(dataset_id_raw)) % (2**31),
            change_type=ChangeType(row["change_type"]),
            effective_date=effective_date,
            description=row["description"],
            impact_estimate=row.get("impact_estimate"),
            severity=self._enum_or_none(SeverityLevel, row.get("severity")),
            comparability=self._enum_or_none(
                ComparabilityLevel, row.get("comparability")
            ),
            is_documented=row.get("is_documented", True),
            source_url=row.get("source_url"),
        )

    async def _find_dataset_row(self, claim: PolicyClaim) -> dict[str, Any] | None:
        dataset_code = self._normalize_dataset_code(claim.dataset)

        async with get_connection() as db:
            if dataset_code:
                result = await db.query(
                    "SELECT * FROM dataset WHERE string::uppercase(code) = string::uppercase($code) LIMIT 1",
                    {"code": dataset_code},
                )
                rows = _query_result_rows(result)
                if rows:
                    return rows[0]

            # Strategy 2: infer via indicator text
            result = await db.query(
                """
                SELECT <-has_indicator<-dataset.* AS ds
                FROM indicator
                WHERE name CONTAINS $indicator OR code CONTAINS $indicator
                LIMIT 1
                """,
                {"indicator": claim.indicator},
            )
            rows = _query_result_rows(result)
            if rows:
                ds = rows[0].get("ds", [])
                if isinstance(ds, list) and ds:
                    return ds[0] if isinstance(ds[0], dict) else None

            # Strategy 3: infer via dataset description
            result = await db.query(
                """
                SELECT * FROM dataset
                WHERE description CONTAINS $indicator
                LIMIT 1
                """,
                {"indicator": claim.indicator},
            )
            rows = _query_result_rows(result)
            return rows[0] if rows else None

    def _dedupe_breaks(
        self, breaks: list[MethodologyChange]
    ) -> list[MethodologyChange]:
        by_key: dict[tuple[int | None, str | None], MethodologyChange] = {}
        for change in breaks:
            key = (change.id, change.benchmark_case_id)
            by_key[key] = change

        return sorted(
            by_key.values(),
            key=lambda b: b.effective_date or date.min,
            reverse=True,
        )

    async def _hydrate_breaks_by_ids(self, ids: list[str]) -> list[MethodologyChange]:
        """Hydrate full methodology change records from SurrealDB record IDs."""
        if not ids:
            return []

        async with get_connection() as db:
            results = []
            for rid in ids:
                result = await db.query(
                    "SELECT * FROM $id",
                    {"id": rid},
                )
                rows = _query_result_rows(result)
                results.extend(rows)

        return [self._row_to_change(row) for row in results]

    async def find_breaks(self, claim: PolicyClaim) -> list[MethodologyChange]:
        """Find methodology changes relevant to a policy claim."""
        breaks: list[MethodologyChange] = []
        dataset_row = await self._find_dataset_row(claim)
        period_end_year = extract_year(claim.period_end) or extract_year(
            claim.period_start
        )

        if dataset_row:
            ds_id = str(dataset_row.get("id", ""))
            ds_code = dataset_row.get("code", "")
            ds_name = dataset_row.get("name", "")
            self.log(f"Found dataset: {ds_code} ({ds_name})")

            # Find methodology changes linked to this dataset via belongs_to edge
            async with get_connection() as db:
                if period_end_year:
                    result = await db.query(
                        """
                        SELECT * FROM methodology_change
                        WHERE ->belongs_to->dataset CONTAINS $ds_id
                          AND (effective_date IS NONE OR time::year(effective_date) <= $year)
                        ORDER BY effective_date DESC
                        """,
                        {"ds_id": ds_id, "year": period_end_year + 1},
                    )
                else:
                    result = await db.query(
                        """
                        SELECT * FROM methodology_change
                        WHERE ->belongs_to->dataset CONTAINS $ds_id
                        ORDER BY effective_date DESC
                        """,
                        {"ds_id": ds_id},
                    )
                rows = _query_result_rows(result)
            breaks.extend(self._row_to_change(row) for row in rows)
        else:
            self.log(f"No exact dataset match for {claim.dataset or claim.indicator}")

        # Semantic fallback catches claims with vague dataset names
        semantic_rows = await self.semantic_search_breaks(claim.original_text, limit=5)
        semantic_ids = [
            str(row.get("id", "")) for row in semantic_rows if row.get("id") is not None
        ]
        if semantic_ids:
            breaks.extend(await self._hydrate_breaks_by_ids(semantic_ids))

        deduped = self._dedupe_breaks(breaks)
        self.log(f"Found {len(deduped)} methodology breaks")
        return deduped

    def _query_tokens(self, text: str, max_tokens: int = 6) -> list[str]:
        tokens = re.findall(r"[A-Za-z0-9-]+", text.lower())
        return [token for token in tokens if len(token) >= 4][:max_tokens]

    async def _lexical_document_search(self, query: str, limit: int) -> list[dict]:
        """Full-text search fallback using SurrealDB BM25 index."""
        async with get_connection() as db:
            result = await db.query(
                """
                SELECT content, metadata,
                       ->part_of->document.title[0] AS title,
                       ->part_of->document.url[0] AS url,
                       search::score(1) AS relevance
                FROM chunk
                WHERE content @1@ $query
                ORDER BY relevance DESC
                LIMIT $limit
                """,
                {"query": query, "limit": limit},
            )
            rows = _query_result_rows(result)

        if not rows:
            # Fallback to simple CONTAINS
            tokens = self._query_tokens(query)
            if not tokens:
                return []
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT content, metadata,
                           ->part_of->document.title[0] AS title,
                           ->part_of->document.url[0] AS url
                    FROM chunk
                    WHERE content CONTAINS $token
                    ORDER BY chunk_index ASC
                    LIMIT $limit
                    """,
                    {"token": tokens[0], "limit": limit},
                )
                rows = _query_result_rows(result)

        return [dict(row) for row in rows]

    async def _lexical_break_search(self, query: str, limit: int) -> list[dict]:
        tokens = self._query_tokens(query)
        if not tokens:
            return []

        async with get_connection() as db:
            result = await db.query(
                """
                SELECT * FROM methodology_change
                WHERE description CONTAINS $token
                ORDER BY effective_date DESC
                LIMIT $limit
                """,
                {"token": tokens[0], "limit": limit},
            )
            rows = _query_result_rows(result)
        return [dict(row) for row in rows]

    async def semantic_search(self, query: str, limit: int = 5) -> list[dict]:
        """Search document chunks by semantic similarity via SurrealDB vector KNN."""
        try:
            query_embedding = await self.llm.embed(query)
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT content, metadata,
                           ->part_of->document.title[0] AS title,
                           ->part_of->document.url[0] AS url,
                           vector::distance::knn() AS distance
                    FROM chunk
                    WHERE embedding <|$limit|> $qvec
                    ORDER BY distance
                    """,
                    {"qvec": query_embedding, "limit": limit},
                )
                rows = _query_result_rows(result)
            self.last_doc_search_mode = "semantic"
            self.log(f"Semantic document search returned {len(rows)} rows")
            return [dict(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            self.last_doc_search_mode = "lexical_fallback"
            self.log(
                f"Semantic doc search unavailable, using lexical fallback: {exc}",
                level=logging.WARNING,
            )
            return await self._lexical_document_search(query, limit)

    async def semantic_search_breaks(self, query: str, limit: int = 5) -> list[dict]:
        """Search methodology changes by semantic similarity."""
        try:
            query_embedding = await self.llm.embed(query)
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT id, change_type, effective_date,
                           description, impact_estimate,
                           vector::distance::knn() AS distance
                    FROM methodology_change
                    WHERE embedding <|$limit|> $qvec
                    ORDER BY distance
                    """,
                    {"qvec": query_embedding, "limit": limit},
                )
                rows = _query_result_rows(result)
            self.last_break_search_mode = "semantic"
            self.log(f"Semantic break search returned {len(rows)} rows")
            return [dict(row) for row in rows]
        except Exception as exc:  # noqa: BLE001
            self.last_break_search_mode = "lexical_fallback"
            self.log(
                f"Semantic break search unavailable, using lexical fallback: {exc}",
                level=logging.WARNING,
            )
            return await self._lexical_break_search(query, limit)

    async def find_evidence(self, claim: PolicyClaim, limit: int = 5) -> list[dict]:
        """Retrieve supporting snippets from ingested documents."""
        query = f"{claim.original_text}\nDataset: {claim.dataset or 'unknown'}\nIndicator: {claim.indicator}"
        return await self.semantic_search(query, limit=limit)

    # ------------------------------------------------------------------
    # New graph query methods
    # ------------------------------------------------------------------

    def _flatten_dict_records(self, value: Any) -> list[dict[str, Any]]:
        if isinstance(value, dict):
            return [value]
        if not isinstance(value, list):
            return []
        rows: list[dict[str, Any]] = []
        for item in value:
            rows.extend(self._flatten_dict_records(item))
        return rows

    def _dedupe_by_id(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}
        for row in records:
            row_id = str(row.get("id") or "")
            if not row_id:
                continue
            by_id[row_id] = row
        return list(by_id.values())

    async def provenance_chain(self, session_id: str) -> dict[str, Any] | None:
        """Full provenance: session -> evidence -> methodology change -> dataset -> agency."""
        async with get_connection() as db:
            result = await db.query(
                """
                SELECT
                    id,
                    case_id,
                    claim_text,
                    status,
                    started_at,
                    completed_at,
                    ->found->document.{id, title, url} AS documents,
                    ->found->document<-describes<-methodology_change.{id, change_type, effective_date, description, impact_estimate} AS methodology_changes,
                    ->found->document<-describes<-methodology_change->belongs_to->dataset.{id, code, name} AS datasets,
                    ->found->document<-describes<-methodology_change->belongs_to->dataset<-publishes<-agency.{id, code, name} AS agencies
                FROM $session_id
                LIMIT 1
                """,
                {"session_id": session_id},
            )
            rows = _query_result_rows(result)
            if not rows:
                return None
            row = rows[0]
            documents = self._dedupe_by_id(
                self._flatten_dict_records(row.get("documents", []))
            )
            changes = self._dedupe_by_id(
                self._flatten_dict_records(row.get("methodology_changes", []))
            )
            changes = sorted(
                changes, key=lambda item: str(item.get("effective_date") or "")
            )
            datasets = self._dedupe_by_id(
                self._flatten_dict_records(row.get("datasets", []))
            )
            agencies = self._dedupe_by_id(
                self._flatten_dict_records(row.get("agencies", []))
            )
            return {
                "session": {
                    "id": row.get("id"),
                    "case_id": row.get("case_id"),
                    "claim_text": row.get("claim_text"),
                    "status": row.get("status"),
                    "started_at": row.get("started_at"),
                    "completed_at": row.get("completed_at"),
                },
                "documents": documents,
                "methodology_changes": changes,
                "datasets": datasets,
                "agencies": agencies,
            }

    async def change_impacts(self, change_id: str) -> dict[str, Any] | None:
        """Get a methodology change with linked indicators/datasets/agencies."""
        async with get_connection() as db:
            change_result = await db.query(
                """
                SELECT id, benchmark_case_id, change_type, effective_date, description, impact_estimate, severity, comparability, source_url
                FROM $id
                LIMIT 1
                """,
                {"id": change_id},
            )
            change_rows = _query_result_rows(change_result)
            if not change_rows:
                return None

            indicators_result = await db.query(
                """
                SELECT id, code, name, unit
                FROM $id->affects->indicator
                """,
                {"id": change_id},
            )
            datasets_result = await db.query(
                """
                SELECT id, code, name
                FROM $id->belongs_to->dataset
                """,
                {"id": change_id},
            )
            agencies_result = await db.query(
                """
                SELECT id, code, name
                FROM $id->belongs_to->dataset<-publishes<-agency
                """,
                {"id": change_id},
            )

            return {
                "change": change_rows[0],
                "indicators": self._dedupe_by_id(_query_result_rows(indicators_result)),
                "datasets": self._dedupe_by_id(_query_result_rows(datasets_result)),
                "agencies": self._dedupe_by_id(_query_result_rows(agencies_result)),
            }

    async def dataset_timeline(self, dataset_code: str) -> dict[str, Any] | None:
        """Get chronological methodology change timeline for a dataset code."""
        normalized = self._normalize_dataset_code(dataset_code)
        if not normalized:
            return None

        async with get_connection() as db:
            dataset_result = await db.query(
                """
                SELECT id, code, name, description
                FROM dataset
                WHERE string::uppercase(code) = string::uppercase($code)
                LIMIT 1
                """,
                {"code": normalized},
            )
            dataset_rows = _query_result_rows(dataset_result)
            if not dataset_rows:
                return None

            dataset = dataset_rows[0]
            changes_result = await db.query(
                """
                SELECT id, benchmark_case_id, change_type, effective_date, description, impact_estimate, severity, comparability
                FROM methodology_change
                WHERE ->belongs_to->dataset CONTAINS $dataset_id
                ORDER BY effective_date ASC
                """,
                {"dataset_id": str(dataset.get("id"))},
            )
            changes = _query_result_rows(changes_result)
            return {"dataset": dataset, "changes": changes}

    async def prior_verification_recall(
        self,
        *,
        dataset: str | None = None,
        indicator: str | None = None,
        session_id: str | None = None,
        limit: int = 10,
    ) -> dict[str, Any]:
        """Find prior similar completed sessions and their linked methodology changes."""
        normalized_dataset = self._normalize_dataset_code(dataset)
        normalized_indicator = (indicator or "").strip() or None
        source_session_id = session_id

        async with get_connection() as db:
            if source_session_id:
                source_result = await db.query(
                    """
                    SELECT id, claim_dataset, claim_indicator
                    FROM $id
                    LIMIT 1
                    """,
                    {"id": source_session_id},
                )
                source_rows = _query_result_rows(source_result)
                if source_rows:
                    source_row = source_rows[0]
                    if normalized_dataset is None:
                        normalized_dataset = self._normalize_dataset_code(
                            source_row.get("claim_dataset")
                        )
                    if normalized_indicator is None:
                        source_indicator = source_row.get("claim_indicator")
                        normalized_indicator = (
                            str(source_indicator).strip() if source_indicator else None
                        )

            if normalized_dataset is None and normalized_indicator is None:
                return {
                    "query": {
                        "dataset": None,
                        "indicator": None,
                        "source_session_id": source_session_id,
                    },
                    "matches": [],
                }

            result = await db.query(
                """
                SELECT
                    id,
                    case_id,
                    claim_text,
                    claim_dataset,
                    claim_indicator,
                    status,
                    verdict,
                    metadata,
                    started_at,
                    completed_at,
                    ->found->document<-describes<-methodology_change.{id, change_type, effective_date, description, impact_estimate} AS methodology_changes
                FROM session
                WHERE status = 'completed'
                  AND (
                    ($has_dataset AND claim_dataset != NONE AND string::uppercase(claim_dataset) = string::uppercase($dataset))
                    OR ($has_indicator AND claim_indicator != NONE AND string::lowercase(claim_indicator) CONTAINS string::lowercase($indicator))
                  )
                ORDER BY started_at DESC
                LIMIT $limit
                """,
                {
                    "has_dataset": normalized_dataset is not None,
                    "dataset": normalized_dataset,
                    "has_indicator": normalized_indicator is not None,
                    "indicator": normalized_indicator,
                    "limit": max(1, int(limit)),
                },
            )
            rows = _query_result_rows(result)

        matches: list[dict[str, Any]] = []
        for row in rows:
            row_id = str(row.get("id") or "")
            if source_session_id and row_id == source_session_id:
                continue
            changes = self._dedupe_by_id(
                self._flatten_dict_records(row.get("methodology_changes", []))
            )
            changes = sorted(
                changes, key=lambda item: str(item.get("effective_date") or "")
            )
            verdict = row.get("verdict") if isinstance(row.get("verdict"), dict) else {}
            metadata = (
                row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
            )
            matches.append(
                {
                    "session": {
                        "id": row.get("id"),
                        "case_id": row.get("case_id"),
                        "claim_text": row.get("claim_text"),
                        "claim_dataset": row.get("claim_dataset"),
                        "claim_indicator": row.get("claim_indicator"),
                        "status": row.get("status"),
                        "started_at": row.get("started_at"),
                        "completed_at": row.get("completed_at"),
                    },
                    "verdict": {
                        "status": verdict.get("status"),
                        "confidence": verdict.get("confidence"),
                    },
                    "aggregate_confidence": metadata.get("aggregate_confidence"),
                    "methodology_changes": changes,
                }
            )

        return {
            "query": {
                "dataset": normalized_dataset,
                "indicator": normalized_indicator,
                "source_session_id": source_session_id,
            },
            "matches": matches,
        }

    async def affected_indicators(self, change_id: str) -> list[dict]:
        """Get all indicators affected by a methodology change."""
        async with get_connection() as db:
            result = await db.query(
                "SELECT ->affects->indicator.* FROM $id",
                {"id": change_id},
            )
            return _query_result_rows(result)
