"""Data Provenance Agent (The Archivist) - queries methodology knowledge base."""

import os
from typing import Optional

from aletheia.agents.base import Agent
from aletheia.schema import PolicyClaim, MethodologyChange, ChangeType
from aletheia.db import get_connection


# Embedding config for query-time embedding generation
EMBEDDING_MODEL = os.environ.get("ALETHEIA_EMBED_MODEL", "text-embedding-ada-002")
EMBEDDING_BASE_URL = os.environ.get("ALETHEIA_EMBED_URL", "http://mini:8080/v1")


class ArchivistAgent(Agent):
    """Queries the knowledge graph for methodology breaks affecting a claim."""

    name = "Archivist"
    role = "Data Provenance"
    system_prompt = (
        "You identify methodology changes that could affect data interpretation."
    )

    async def find_breaks(self, claim: PolicyClaim) -> list[MethodologyChange]:
        """Find methodology changes relevant to a policy claim."""
        breaks = []

        async with get_connection() as conn:
            # Strategy 1: Direct dataset code match
            dataset_row = None
            if claim.dataset:
                dataset_row = await (
                    await conn.execute(
                        "SELECT id, code, name FROM datasets WHERE LOWER(code) = LOWER(%s)",
                        (claim.dataset,),
                    )
                ).fetchone()

            # Strategy 2: Find dataset by indicator name/code
            if not dataset_row:
                dataset_row = await (
                    await conn.execute(
                        """
                        SELECT d.id, d.code, d.name
                        FROM datasets d
                        JOIN indicators i ON i.dataset_id = d.id
                        WHERE LOWER(i.name) ILIKE %s OR LOWER(i.code) ILIKE %s
                        """,
                        (f"%{claim.indicator}%", f"%{claim.indicator}%"),
                    )
                ).fetchone()

            # Strategy 3: Search by keyword in dataset description
            if not dataset_row and claim.indicator:
                dataset_row = await (
                    await conn.execute(
                        "SELECT id, code, name FROM datasets WHERE LOWER(description) ILIKE %s",
                        (f"%{claim.indicator}%",),
                    )
                ).fetchone()

            if not dataset_row:
                self.log(f"No dataset found for: {claim.dataset or claim.indicator}")
                return breaks

            dataset_id = dataset_row["id"]
            self.log(f"Found dataset: {dataset_row['code']} ({dataset_row['name']})")

            # Find methodology changes for this dataset
            query = """
                SELECT mc.id, mc.change_type, mc.effective_date, mc.description,
                       mc.impact_estimate, mc.is_documented, mc.source_url
                FROM methodology_changes mc
                WHERE mc.dataset_id = %s
            """
            params: list = [dataset_id]

            if claim.period_start or claim.period_end:
                period_year = claim.period_end or claim.period_start
                if isinstance(period_year, int):
                    query += " AND EXTRACT(YEAR FROM mc.effective_date) <= %s"
                    params.append(period_year)

            query += " ORDER BY mc.effective_date DESC"

            rows = await (await conn.execute(query, params)).fetchall()

            for row in rows:
                breaks.append(
                    MethodologyChange(
                        id=row["id"],
                        dataset_id=dataset_id,
                        change_type=ChangeType(row["change_type"]),
                        effective_date=row["effective_date"],
                        description=row["description"],
                        impact_estimate=row["impact_estimate"],
                        is_documented=row["is_documented"],
                        source_url=row["source_url"],
                    )
                )

        self.log(f"Found {len(breaks)} methodology breaks for {claim.dataset}")
        return breaks

    async def semantic_search(self, query: str, limit: int = 5) -> list[dict]:
        """Search document chunks by semantic similarity via pgai embeddings.

        Uses the pgai-managed document_chunks_embedding view which joins
        document_chunks with their auto-generated embeddings.
        Generates a query embedding at search time via the LLM endpoint.
        """
        # Generate query embedding via the same endpoint pgai uses
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
            return [dict(row) for row in rows]

    async def semantic_search_breaks(self, query: str, limit: int = 5) -> list[dict]:
        """Search methodology changes by semantic similarity.

        Uses the pgai-managed methodology_changes_embedding view.
        """
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
            return [dict(row) for row in rows]
