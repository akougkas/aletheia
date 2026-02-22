import os
from pathlib import Path

import psycopg
import pytest

from aletheia.agents.archivist import ArchivistAgent
from aletheia.db import DB_URL
from aletheia.ingest import ingest_MARINA_corpus
from aletheia.schema import Direction, PolicyClaim


ROOT = Path(__file__).resolve().parents[2]
RUN_INTEGRATION = os.environ.get("ALETHEIA_RUN_INTEGRATION", "0") == "1"


def _db_available() -> bool:
    try:
        with psycopg.connect(DB_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def seeded_db():
    if not RUN_INTEGRATION:
        pytest.skip("Set ALETHEIA_RUN_INTEGRATION=1 to run integration tests.")
    if not _db_available():
        pytest.skip(f"Live Postgres not available at {DB_URL}.")

    seed_sql = (ROOT / "sql" / "seed_cases.sql").read_text(encoding="utf-8")
    validate_sql = (ROOT / "sql" / "validate_seed_cases.sql").read_text(encoding="utf-8")

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(seed_sql)
            cur.execute(validate_sql)
        conn.commit()

    ingest_MARINA_corpus(ROOT / "MARINA.md")
    return True


@pytest.mark.integration
def test_seeded_benchmark_count(seeded_db):
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM methodology_changes
                WHERE benchmark_case_id LIKE 'MB-%'
                """
            )
            count = cur.fetchone()[0]
    assert count == 10


@pytest.mark.integration
def test_seeded_cases_have_indicator_links(seeded_db):
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(DISTINCT mc.benchmark_case_id)
                FROM methodology_changes mc
                JOIN change_indicator_impacts cii ON cii.change_id = mc.id
                WHERE mc.benchmark_case_id LIKE 'MB-%'
                """
            )
            linked = cur.fetchone()[0]
    assert linked == 10


@pytest.mark.integration
def test_ingested_MARINA_chunks_exist(seeded_db):
    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*)
                FROM document_chunks
                WHERE metadata->>'source' = 'MARINA.md'
                """
            )
            count = cur.fetchone()[0]
    assert count > 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_archivist_finds_known_benchmark_break(seeded_db):
    claim = PolicyClaim(
        original_text="The unemployment rate peaked in April 2020.",
        indicator="unemployment rate",
        dataset="CPS",
        geography="USA",
        period_start=2020,
        period_end=2020,
        direction=Direction.UNKNOWN,
    )

    archivist = ArchivistAgent()

    async def _no_semantic(*args, **kwargs):
        return []

    archivist.semantic_search_breaks = _no_semantic  # type: ignore[assignment]
    breaks = await archivist.find_breaks(claim)
    assert any(change.benchmark_case_id == "MB-003" for change in breaks)
