"""Database connection and diagnostics for ALETHEIA (SurrealDB backend)."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator

from surrealdb import AsyncSurreal


@dataclass(frozen=True)
class DBSettings:
    """Portable DB settings resolved from env."""

    url: str
    ns: str
    db_name: str
    user: str
    password: str

    @classmethod
    def from_env(cls) -> "DBSettings":
        return cls(
            url=os.environ.get("ALETHEIA_DB_URL", "ws://localhost:8000/rpc"),
            ns=os.environ.get("ALETHEIA_DB_NS", "aletheia"),
            db_name=os.environ.get("ALETHEIA_DB_NAME", "main"),
            user=os.environ.get("ALETHEIA_DB_USER", "root"),
            password=os.environ.get("ALETHEIA_DB_PASS", "root"),
        )

    def display_url(self, *, redacted: bool = False) -> str:
        if redacted:
            return f"{self.url} (ns={self.ns}, db={self.db_name}, user={self.user})"
        return f"{self.url} (ns={self.ns}, db={self.db_name}, user={self.user}, pass={self.password})"


# ---------------------------------------------------------------------------
# Singleton connection
# ---------------------------------------------------------------------------

_db_instance: AsyncSurreal | None = None


async def _get_singleton() -> AsyncSurreal:
    """Return a connected AsyncSurreal singleton. Creates on first call."""
    global _db_instance
    if _db_instance is not None:
        return _db_instance

    settings = DBSettings.from_env()
    db = AsyncSurreal(settings.url)
    await db.connect(settings.url)
    await db.signin({"username": settings.user, "password": settings.password})
    await db.use(settings.ns, settings.db_name)
    _db_instance = db
    return db


async def close_db() -> None:
    """Close the singleton connection if open."""
    global _db_instance
    if _db_instance is not None:
        await _db_instance.close()
        _db_instance = None


@asynccontextmanager
async def get_connection() -> AsyncGenerator[AsyncSurreal, None]:
    """Get the shared async SurrealDB connection."""
    db = await _get_singleton()
    yield db


# ---------------------------------------------------------------------------
# Convenience helpers
# ---------------------------------------------------------------------------

def get_db_settings() -> DBSettings:
    """Resolve DB settings from the current environment."""
    return DBSettings.from_env()


def get_db_url(*, redacted: bool = False) -> str:
    """Return display-friendly connection string."""
    return get_db_settings().display_url(redacted=redacted)


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def diagnose_connection_failure(exc: BaseException) -> dict[str, Any]:
    """Return actionable diagnosis hints for DB connection failures."""
    msg = str(exc)
    lower = msg.lower()
    hints: list[str] = []
    category = "unknown"

    if "connection refused" in lower or "connect call failed" in lower:
        category = "connection_refused"
        hints.extend(
            [
                "SurrealDB is not reachable on the configured host/port.",
                "Ensure docker compose stack is running: docker compose up -d surrealdb",
                "Check ALETHEIA_DB_URL (default ws://localhost:8000/rpc).",
            ]
        )
    elif "authentication" in lower or "signin" in lower or "credentials" in lower:
        category = "auth_failed"
        hints.extend(
            [
                "SurrealDB authentication failed.",
                "Check ALETHEIA_DB_USER and ALETHEIA_DB_PASS (default root/root).",
            ]
        )
    elif "namespace" in lower or "database" in lower:
        category = "missing_namespace"
        hints.extend(
            [
                "SurrealDB namespace or database not found.",
                "Run schema init: surreal import --conn ws://localhost:8000 --user root --pass root --ns aletheia --db main surql/init.surql",
                "Or run: uv run aletheia seed",
            ]
        )
    else:
        hints.extend(
            [
                "Verify SurrealDB is running and connection settings are correct.",
                "Run `uv run aletheia db-doctor` for full diagnostics.",
            ]
        )

    return {
        "category": category,
        "message": msg,
        "db_url_redacted": get_db_url(redacted=True),
        "hints": hints,
    }


async def test_connection() -> dict[str, Any]:
    """Test SurrealDB connection and return status + diagnostics."""
    try:
        settings = DBSettings.from_env()
        db = AsyncSurreal(settings.url)
        await db.connect(settings.url)
        await db.signin({"username": settings.user, "password": settings.password})
        await db.use(settings.ns, settings.db_name)

        # Check tables exist
        info_result = await db.query("INFO FOR DB")
        tables: list[str] = []
        if info_result and isinstance(info_result, list) and info_result[0]:
            result = info_result[0].get("result", {})
            if isinstance(result, dict):
                tables = list(result.get("tables", {}).keys())

        # Count records
        mc_result = await db.query("SELECT count() AS total FROM methodology_change GROUP ALL")
        mc_count = 0
        if mc_result and isinstance(mc_result, list) and mc_result[0]:
            rows = mc_result[0].get("result", [])
            if rows and isinstance(rows, list) and rows[0]:
                mc_count = int(rows[0].get("total", 0))

        chunk_result = await db.query("SELECT count() AS total FROM chunk GROUP ALL")
        chunk_count = 0
        if chunk_result and isinstance(chunk_result, list) and chunk_result[0]:
            rows = chunk_result[0].get("result", [])
            if rows and isinstance(rows, list) and rows[0]:
                chunk_count = int(rows[0].get("total", 0))

        doc_result = await db.query("SELECT count() AS total FROM document GROUP ALL")
        doc_count = 0
        if doc_result and isinstance(doc_result, list) and doc_result[0]:
            rows = doc_result[0].get("result", [])
            if rows and isinstance(rows, list) and rows[0]:
                doc_count = int(rows[0].get("total", 0))

        # Count embedded records
        mc_embed_result = await db.query(
            "SELECT count() AS total FROM methodology_change WHERE embedding IS NOT NONE GROUP ALL"
        )
        mc_embed_count = 0
        if mc_embed_result and isinstance(mc_embed_result, list) and mc_embed_result[0]:
            rows = mc_embed_result[0].get("result", [])
            if rows and isinstance(rows, list) and rows[0]:
                mc_embed_count = int(rows[0].get("total", 0))

        chunk_embed_result = await db.query(
            "SELECT count() AS total FROM chunk WHERE embedding IS NOT NONE GROUP ALL"
        )
        chunk_embed_count = 0
        if chunk_embed_result and isinstance(chunk_embed_result, list) and chunk_embed_result[0]:
            rows = chunk_embed_result[0].get("result", [])
            if rows and isinstance(rows, list) and rows[0]:
                chunk_embed_count = int(rows[0].get("total", 0))

        semantic_ready = (
            (chunk_count == 0 or chunk_embed_count > 0)
            and (mc_count == 0 or mc_embed_count > 0)
        )

        await db.close()

        return {
            "ok": True,
            "db_url_redacted": get_db_url(redacted=True),
            "backend": "surrealdb",
            "tables": sorted(tables),
            "semantic_search_ready": semantic_ready,
            "counts": {
                "methodology_changes": mc_count,
                "document_chunks": chunk_count,
                "documents": doc_count,
                "methodology_embeddings": mc_embed_count,
                "document_embeddings": chunk_embed_count,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            **diagnose_connection_failure(exc),
        }


async def apply_schema() -> None:
    """Apply the SurrealQL schema from surql/init.surql."""
    from pathlib import Path

    schema_path = Path(__file__).resolve().parents[1] / "surql" / "init.surql"
    if not schema_path.exists():
        raise FileNotFoundError(f"Schema file not found: {schema_path}")

    schema = schema_path.read_text(encoding="utf-8")
    async with get_connection() as db:
        await db.query(schema)
