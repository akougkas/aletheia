"""Data Provenance Agent (The Archivist) - queries methodology knowledge base."""

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


class ArchivistAgent(Agent):
    """Queries the knowledge graph for methodology breaks affecting a claim."""

    name = "Archivist"
    role = "Data Provenance"
    system_prompt = "You identify methodology changes that could affect data interpretation."

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
        return MethodologyChange(
            id=row["id"],
            benchmark_case_id=row.get("benchmark_case_id"),
            dataset_id=row["dataset_id"],
            change_type=ChangeType(row["change_type"]),
            effective_date=row.get("effective_date"),
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

        async with get_connection() as conn:
            if dataset_code:
                row = await (
                    await conn.execute(
                        "SELECT id, code, name FROM datasets WHERE UPPER(code) = UPPER(%s)",
                        (dataset_code,),
                    )
                ).fetchone()
                if row:
                    return dict(row)

            # Strategy 2: infer via indicator text.
            row = await (
                await conn.execute(
                    """
                    SELECT d.id, d.code, d.name
                    FROM datasets d
                    JOIN indicators i ON i.dataset_id = d.id
                    WHERE i.name ILIKE %s OR i.code ILIKE %s
                    ORDER BY d.code
                    LIMIT 1
                    """,
                    (f"%{claim.indicator}%", f"%{claim.indicator}%"),
                )
            ).fetchone()
            if row:
                return dict(row)

            # Strategy 3: infer via dataset description.
            row = await (
                await conn.execute(
                    """
                    SELECT id, code, name
                    FROM datasets
                    WHERE description ILIKE %s
                    ORDER BY code
                    LIMIT 1
                    """,
                    (f"%{claim.indicator}%",),
                )
            ).fetchone()
            return dict(row) if row else None

    def _dedupe_breaks(self, breaks: list[MethodologyChange]) -> list[MethodologyChange]:
        by_key: dict[tuple[int | None, str | None], MethodologyChange] = {}
        for change in breaks:
            key = (change.id, change.benchmark_case_id)
            by_key[key] = change

        # Sort newest first; undated items last.
        return sorted(
            by_key.values(),
            key=lambda b: b.effective_date or date.min,
            reverse=True,
        )

    async def _hydrate_breaks_by_ids(self, ids: list[int]) -> list[MethodologyChange]:
        if not ids:
            return []

        async with get_connection() as conn:
            rows = await (
                await conn.execute(
                    """
                    SELECT id, benchmark_case_id, dataset_id, change_type, effective_date,
                           description, impact_estimate, severity, comparability,
                           is_documented, source_url
                    FROM methodology_changes
                    WHERE id = ANY(%s)
                    """,
                    (ids,),
                )
            ).fetchall()

        return [self._row_to_change(dict(row)) for row in rows]

    async def find_breaks(self, claim: PolicyClaim) -> list[MethodologyChange]:
        """Find methodology changes relevant to a policy claim."""
        breaks: list[MethodologyChange] = []
        dataset_row = await self._find_dataset_row(claim)
        period_end_year = extract_year(claim.period_end) or extract_year(claim.period_start)

        if dataset_row:
            dataset_id = dataset_row["id"]
            self.log(f"Found dataset: {dataset_row['code']} ({dataset_row['name']})")
            query = """
                SELECT id, benchmark_case_id, dataset_id, change_type, effective_date,
                       description, impact_estimate, severity, comparability,
                       is_documented, source_url
                FROM methodology_changes
                WHERE dataset_id = %s
            """
            params: list[Any] = [dataset_id]
            if period_end_year:
                # Keep nearby future breaks for early warning use-cases.
                query += " AND (effective_date IS NULL OR EXTRACT(YEAR FROM effective_date) <= %s)"
                params.append(period_end_year + 1)
            query += " ORDER BY effective_date DESC NULLS LAST, id DESC"

            async with get_connection() as conn:
                rows = await (await conn.execute(query, params)).fetchall()
            breaks.extend(self._row_to_change(dict(row)) for row in rows)
        else:
            self.log(f"No exact dataset match for {claim.dataset or claim.indicator}")

        # Semantic fallback catches claims with vague dataset names.
        semantic_rows = await self.semantic_search_breaks(claim.original_text, limit=5)
        semantic_ids = [int(row["id"]) for row in semantic_rows if row.get("id") is not None]
        if semantic_ids:
            breaks.extend(await self._hydrate_breaks_by_ids(semantic_ids))

        deduped = self._dedupe_breaks(breaks)
        self.log(f"Found {len(deduped)} methodology breaks")
        return deduped

    def _query_tokens(self, text: str, max_tokens: int = 6) -> list[str]:
        tokens = re.findall(r"[A-Za-z0-9-]+", text.lower())
        return [token for token in tokens if len(token) >= 4][:max_tokens]

    async def _lexical_document_search(self, query: str, limit: int) -> list[dict]:
        tokens = self._query_tokens(query)
        if not tokens:
            return []

        where_clause = " OR ".join(["d.title ILIKE %s OR dc.content ILIKE %s"] * len(tokens))
        params: list[Any] = []
        for token in tokens:
            pattern = f"%{token}%"
            params.extend([pattern, pattern])
        params.append(limit)

        async with get_connection() as conn:
            rows = await (
                await conn.execute(
                    f"""
                    SELECT dc.content, dc.metadata, d.title, d.url, NULL::float AS distance
                    FROM document_chunks dc
                    JOIN documents d ON d.id = dc.document_id
                    WHERE {where_clause}
                    ORDER BY d.publication_date DESC NULLS LAST, d.id DESC
                    LIMIT %s
                    """,
                    params,
                )
            ).fetchall()
        return [dict(row) for row in rows]

    async def _lexical_break_search(self, query: str, limit: int) -> list[dict]:
        tokens = self._query_tokens(query)
        if not tokens:
            return []

        where_clause = " OR ".join(["description ILIKE %s"] * len(tokens))
        params: list[Any] = [f"%{token}%" for token in tokens]
        params.append(limit)

        async with get_connection() as conn:
            rows = await (
                await conn.execute(
                    f"""
                    SELECT id, change_type, effective_date, description, impact_estimate, NULL::float AS distance
                    FROM methodology_changes
                    WHERE {where_clause}
                    ORDER BY effective_date DESC NULLS LAST, id DESC
                    LIMIT %s
                    """,
                    params,
                )
            ).fetchall()
        return [dict(row) for row in rows]

    async def semantic_search(self, query: str, limit: int = 5) -> list[dict]:
        """Search document chunks by semantic similarity via pgai embeddings."""
        try:
            query_embedding = await self.llm.embed(query)
            async with get_connection() as conn:
                rows = await (
                    await conn.execute(
                        """
                        SELECT dce.content, dce.metadata, d.title, d.url,
                               dce.embedding <=> %s::vector AS distance
                        FROM document_chunks_embedding dce
                        JOIN document_chunks dc ON dc.id = dce.id
                        JOIN documents d ON d.id = dc.document_id
                        ORDER BY distance
                        LIMIT %s
                        """,
                        (str(query_embedding), limit),
                    )
                ).fetchall()
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
            async with get_connection() as conn:
                rows = await (
                    await conn.execute(
                        """
                        SELECT mce.id, mce.change_type, mce.effective_date,
                               mce.description, mce.impact_estimate,
                               mce.embedding <=> %s::vector AS distance
                        FROM methodology_changes_embedding mce
                        ORDER BY distance
                        LIMIT %s
                        """,
                        (str(query_embedding), limit),
                    )
                ).fetchall()
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
