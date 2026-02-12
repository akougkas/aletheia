"""Database connection and operations for the methodology knowledge base."""

import asyncpg
from contextlib import asynccontextmanager
from typing import AsyncGenerator

# Default connection settings (override via environment or config)
DB_CONFIG = {
    "host": "localhost",
    "port": 5432,
    "user": "aletheia",
    "password": "aletheia",
    "database": "aletheia",
}


async def get_pool() -> asyncpg.Pool:
    """Create a connection pool."""
    return await asyncpg.create_pool(**DB_CONFIG, min_size=2, max_size=10)


@asynccontextmanager
async def get_connection() -> AsyncGenerator[asyncpg.Connection, None]:
    """Get a single connection (for simple scripts/tests)."""
    conn = await asyncpg.connect(**DB_CONFIG)
    try:
        yield conn
    finally:
        await conn.close()


async def test_connection() -> dict:
    """Test database connection and pgvector extension."""
    async with get_connection() as conn:
        # Check PostgreSQL version
        pg_version = await conn.fetchval("SELECT version()")

        # Check pgvector extension
        ext_check = await conn.fetchval(
            "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
        )

        # Check our tables exist
        tables = await conn.fetch("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)

        return {
            "pg_version": pg_version,
            "pgvector_enabled": ext_check,
            "tables": [t["tablename"] for t in tables],
        }


if __name__ == "__main__":
    import asyncio
    import json

    result = asyncio.run(test_connection())
    print(json.dumps(result, indent=2))
