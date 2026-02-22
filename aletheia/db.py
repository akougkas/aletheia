"""Database connection and diagnostics for ALETHEIA."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, AsyncGenerator
from urllib.parse import parse_qsl, quote, urlencode, urlparse, urlunparse

import pgai
import psycopg
from psycopg.rows import dict_row


def _as_int(value: str | None, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


@dataclass(frozen=True)
class DBSettings:
    """Portable DB settings resolved from env."""

    url_override: str | None
    host: str
    port: int
    name: str
    user: str
    password: str
    sslmode: str | None
    connect_timeout: int

    @classmethod
    def from_env(cls) -> "DBSettings":
        return cls(
            url_override=os.environ.get("ALETHEIA_DB_URL"),
            host=os.environ.get("ALETHEIA_DB_HOST", "localhost"),
            port=_as_int(os.environ.get("ALETHEIA_DB_PORT"), 5432),
            name=os.environ.get("ALETHEIA_DB_NAME", "aletheia"),
            user=os.environ.get("ALETHEIA_DB_USER", "aletheia"),
            password=os.environ.get("ALETHEIA_DB_PASSWORD", "aletheia"),
            sslmode=os.environ.get("ALETHEIA_DB_SSLMODE"),
            connect_timeout=_as_int(os.environ.get("ALETHEIA_DB_CONNECT_TIMEOUT"), 8),
        )

    def dsn(self, *, redacted: bool = False) -> str:
        if self.url_override:
            return self._normalize_override(self.url_override, redacted=redacted)

        user = quote(self.user, safe="")
        password = "***" if redacted else quote(self.password, safe="")
        host = self.host
        port = self.port
        name = self.name
        auth = f"{user}:{password}"
        base = f"postgres://{auth}@{host}:{port}/{name}"
        params: dict[str, str] = {}
        if self.sslmode:
            params["sslmode"] = self.sslmode
        if self.connect_timeout > 0:
            params["connect_timeout"] = str(self.connect_timeout)
        if not params:
            return base
        return f"{base}?{urlencode(params)}"

    def _normalize_override(self, url: str, *, redacted: bool) -> str:
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return url

        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        if self.connect_timeout > 0 and "connect_timeout" not in query:
            query["connect_timeout"] = str(self.connect_timeout)
        if self.sslmode and "sslmode" not in query:
            query["sslmode"] = self.sslmode

        username = parsed.username or ""
        password = parsed.password or ""
        safe_password = "***" if redacted and password else password
        userinfo = quote(username, safe="")
        if password:
            userinfo = f"{userinfo}:{quote(safe_password, safe='')}"
        host = parsed.hostname or ""
        netloc = host
        if userinfo:
            netloc = f"{userinfo}@{host}"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"

        return urlunparse(
            (
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                urlencode(query),
                parsed.fragment,
            )
        )


def get_db_settings() -> DBSettings:
    """Resolve DB settings from the current environment."""
    return DBSettings.from_env()


def get_db_url(*, redacted: bool = False) -> str:
    """Build DSN from environment with optional redaction."""
    return get_db_settings().dsn(redacted=redacted)


def diagnose_connection_failure(exc: BaseException) -> dict[str, Any]:
    """Return actionable diagnosis hints for DB connection failures."""
    msg = str(exc)
    lower = msg.lower()
    hints: list[str] = []
    category = "unknown"

    if "password authentication failed" in lower:
        category = "auth_failed"
        hints.extend(
            [
                "Credentials mismatch between app env and PostgreSQL role password.",
                "If using Docker with a persisted volume, POSTGRES_USER/POSTGRES_PASSWORD are only applied at first init.",
                "Check active settings with redacted DSN and env vars (ALETHEIA_DB_URL or ALETHEIA_DB_USER/ALETHEIA_DB_PASSWORD).",
                "For local draft mode where reset is acceptable: recreate DB volume and reseed.",
            ]
        )
    elif "connection refused" in lower:
        category = "connection_refused"
        hints.extend(
            [
                "Database service is not reachable on host/port.",
                "Ensure docker compose stack is running and ALETHEIA_DB_PORT matches exposed port.",
            ]
        )
    elif "connection is bad" in lower:
        category = "connection_unusable"
        hints.extend(
            [
                "Database socket accepted but connection is unusable.",
                "Verify ALETHEIA_DB_HOST/ALETHEIA_DB_PORT target the correct PostgreSQL instance.",
                "If Docker is running on a non-default host port, set ALETHEIA_DB_PORT accordingly (for example 5433).",
            ]
        )
    elif "could not translate host name" in lower:
        category = "dns_error"
        hints.extend(
            [
                "Hostname in ALETHEIA_DB_HOST/ALETHEIA_DB_URL is invalid or not resolvable.",
                "Use localhost for host machine access or postgres service name inside Docker network.",
            ]
        )
    elif "database" in lower and "does not exist" in lower:
        category = "missing_database"
        hints.extend(
            [
                "Target database does not exist.",
                "Create DB (aletheia) or update ALETHEIA_DB_NAME / ALETHEIA_DB_URL.",
            ]
        )
    elif "ssl" in lower and ("required" in lower or "handshake" in lower):
        category = "ssl_mismatch"
        hints.extend(
            [
                "SSL mode mismatch between client and server.",
                "Set ALETHEIA_DB_SSLMODE appropriately (for local Docker usually disable or prefer).",
            ]
        )
    else:
        hints.extend(
            [
                "Verify connection settings and DB server health.",
                "Run `uv run python cli.py db-doctor` for full diagnostics.",
            ]
        )

    return {
        "category": category,
        "message": msg,
        "db_url_redacted": get_db_url(redacted=True),
        "hints": hints,
    }


def install_pgai() -> None:
    """Install pgai objects."""
    pgai.install(get_db_url())


@asynccontextmanager
async def get_connection() -> AsyncGenerator[psycopg.AsyncConnection, None]:
    """Get an async connection with dict rows."""
    async with await psycopg.AsyncConnection.connect(
        get_db_url(),
        row_factory=dict_row,
    ) as conn:
        yield conn


async def test_connection() -> dict[str, Any]:
    """Test database connection and return status + diagnostics."""
    return _test_connection_sync()


def _test_connection_sync() -> dict[str, Any]:
    """Synchronous DB diagnostic probe used by CLI/onboarding health checks."""
    try:
        with psycopg.connect(get_db_url(), row_factory=dict_row) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version()")
                pg_version = cur.fetchone()

                cur.execute("SELECT EXISTS(SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                ext_check = cur.fetchone()

                cur.execute("SELECT EXISTS(SELECT 1 FROM pg_namespace WHERE nspname = 'ai')")
                pgai_check = cur.fetchone()

                cur.execute(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
                )
                tables = cur.fetchall()

                cur.execute(
                    """
                    SELECT EXISTS(
                        SELECT 1
                        FROM information_schema.views
                        WHERE table_schema = 'public' AND table_name = 'document_chunks_embedding'
                    ) AS doc_view,
                    EXISTS(
                        SELECT 1
                        FROM information_schema.views
                        WHERE table_schema = 'public' AND table_name = 'methodology_changes_embedding'
                    ) AS break_view
                    """
                )
                semantic_views = cur.fetchone() or {}

                cur.execute("SELECT COUNT(*) AS count FROM methodology_changes")
                method_change_count = int((cur.fetchone() or {}).get("count", 0))

                cur.execute("SELECT COUNT(*) AS count FROM document_chunks")
                doc_chunk_count = int((cur.fetchone() or {}).get("count", 0))

                method_embed_count = 0
                doc_embed_count = 0
                if semantic_views.get("doc_view"):
                    cur.execute("SELECT COUNT(*) AS count FROM document_chunks_embedding")
                    doc_embed_count = int((cur.fetchone() or {}).get("count", 0))
                if semantic_views.get("break_view"):
                    cur.execute("SELECT COUNT(*) AS count FROM methodology_changes_embedding")
                    method_embed_count = int((cur.fetchone() or {}).get("count", 0))

                semantic_ready = bool(
                    semantic_views.get("doc_view")
                    and semantic_views.get("break_view")
                    and (doc_chunk_count == 0 or doc_embed_count > 0)
                    and (method_change_count == 0 or method_embed_count > 0)
                )

        return {
            "ok": True,
            "db_url_redacted": get_db_url(redacted=True),
            "pg_version": pg_version["version"] if pg_version else None,
            "pgvector_enabled": ext_check["exists"] if ext_check else False,
            "pgai_installed": pgai_check["exists"] if pgai_check else False,
            "tables": [t["tablename"] for t in tables],
            "semantic_search_ready": semantic_ready,
            "semantic_views": {
                "document_chunks_embedding": bool(semantic_views.get("doc_view")),
                "methodology_changes_embedding": bool(semantic_views.get("break_view")),
            },
            "counts": {
                "methodology_changes": method_change_count,
                "document_chunks": doc_chunk_count,
                "methodology_embeddings": method_embed_count,
                "document_embeddings": doc_embed_count,
            },
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            **diagnose_connection_failure(exc),
        }


if __name__ == "__main__":
    import asyncio
    import json

    install_pgai()
    result = asyncio.run(test_connection())
    print(json.dumps(result, indent=2))
