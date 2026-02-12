"""Data Provenance Agent (The Archivist) - queries methodology knowledge base."""

from typing import Optional
from datetime import date
import asyncpg

from aletheia.agents.base import Agent
from aletheia.schema import PolicyClaim, MethodologyChange, ChangeType
from aletheia.db import get_connection


class ArchivistAgent(Agent):
    """Queries the knowledge graph for methodology breaks affecting a claim."""

    name = "Archivist"
    role = "Data Provenance"
    system_prompt = "You identify methodology changes that could affect data interpretation."

    async def find_breaks(self, claim: PolicyClaim) -> list[MethodologyChange]:
        """Find methodology changes relevant to a policy claim."""
        breaks = []

        # Query DB for methodology changes matching the claim's dataset and time period
        async with get_connection() as conn:
            # First, find the dataset - try multiple strategies
            dataset_row = None

            # Strategy 1: Direct dataset code match
            if claim.dataset:
                dataset_row = await conn.fetchrow(
                    "SELECT id, code, name FROM datasets WHERE LOWER(code) = LOWER($1)",
                    claim.dataset,
                )

            # Strategy 2: Find dataset by indicator name/code
            if not dataset_row:
                dataset_row = await conn.fetchrow(
                    """
                    SELECT d.id, d.code, d.name
                    FROM datasets d
                    JOIN indicators i ON i.dataset_id = d.id
                    WHERE LOWER(i.name) ILIKE $1 OR LOWER(i.code) ILIKE $1
                    """,
                    f"%{claim.indicator}%",
                )

            # Strategy 3: Search by keyword in dataset description
            if not dataset_row and claim.indicator:
                dataset_row = await conn.fetchrow(
                    """
                    SELECT id, code, name FROM datasets
                    WHERE LOWER(description) ILIKE $1
                    """,
                    f"%{claim.indicator}%",
                )

            if not dataset_row:
                self.log(f"No dataset found for: {claim.dataset or claim.indicator}")
                return breaks

            dataset_id = dataset_row["id"]
            self.log(f"Found dataset: {dataset_row['code']} ({dataset_row['name']})")

            # Find methodology changes for this dataset
            # Filter by time period if claim has dates
            query = """
                SELECT mc.id, mc.change_type, mc.effective_date, mc.description,
                       mc.impact_estimate, mc.is_documented, mc.source_url
                FROM methodology_changes mc
                WHERE mc.dataset_id = $1
            """
            params = [dataset_id]

            # Add date filter if claim specifies a period
            if claim.period_start or claim.period_end:
                period_year = claim.period_end or claim.period_start
                if isinstance(period_year, int):
                    # Look for changes in or before the claim period
                    query += " AND EXTRACT(YEAR FROM mc.effective_date) <= $2"
                    params.append(period_year)

            query += " ORDER BY mc.effective_date DESC"

            rows = await conn.fetch(query, *params)

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

    async def semantic_search(
        self, query: str, limit: int = 5
    ) -> list[dict]:
        """Search document chunks by semantic similarity.

        Requires embeddings to be populated in the DB.
        Returns relevant document chunks with their metadata.
        """
        # TODO: Implement embedding-based search once we have embeddings populated
        # For now, fall back to keyword search
        async with get_connection() as conn:
            rows = await conn.fetch(
                """
                SELECT dc.content, dc.metadata, d.title, d.url
                FROM document_chunks dc
                JOIN documents d ON d.id = dc.document_id
                WHERE dc.content ILIKE $1
                LIMIT $2
                """,
                f"%{query}%",
                limit,
            )
            return [dict(row) for row in rows]
