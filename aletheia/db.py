"""Database connection and operations for the methodology knowledge base."""

import os
import pgai
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import psycopg
from psycopg.rows import dict_row

# Connection URL (override via ALETHEIA_DB_URL environment variable)
DB_URL = os.environ.get(
    "ALETHEIA_DB_URL",
    "postgres://aletheia:aletheia@localhost:5432/aletheia",
)


def install_pgai():
    """Install pgai database objects (ai schema, vectorizer functions).

    Safe to call repeatedly -- pgai.install is idempotent.
    """
    pgai.install(DB_URL)


@asynccontextmanager
async def get_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """Get an async connection with dict rows."""
    async with await psycopg.AsyncConnection.connect(
        DB_URL, row_factory=dict_row
    ) as conn:
        yield conn


async def test_connection() -> dict:
    """Test database connection, pgvector extension, and pgai installation."""
    async with get_connection() as conn:
        pg_version = await (await conn.execute("SELECT version()")).fetchone()

        ext_check = await (
            await conn.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')"
            )
        ).fetchone()

        pgai_check = await (
            await conn.execute(
                "SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'ai')"
            )
        ).fetchone()

        tables = await (
            await conn.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
        ).fetchall()

        return {
            "pg_version": pg_version["version"] if pg_version else None,
            "pgvector_enabled": ext_check["exists"] if ext_check else False,
            "pgai_installed": pgai_check["exists"] if pgai_check else False,
            "tables": [t["tablename"] for t in tables],
        }


if __name__ == "__main__":
    import asyncio
    import json

    # Ensure pgai is installed before testing
    install_pgai()
    result = asyncio.run(test_connection())
    print(json.dumps(result, indent=2))
