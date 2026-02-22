"""pgai vectorizer setup + diagnostics for ALETHEIA embeddings."""

import argparse
import json
import os
import subprocess
import sys

import psycopg

from aletheia.db import get_db_url, install_pgai

DEFAULT_EMBED_MODEL = "text-embedding-ada-002"
DEFAULT_EMBED_DIM = 4096


def _resolve_embedding_base_url() -> str:
    """Resolve OpenAI-compatible embedding base URL for pgai."""
    raw = (
        os.environ.get("ALETHEIA_EMBED_BASE_URL")
        or os.environ.get("ALETHEIA_EMBED_URL")
        or os.environ.get("ALETHEIA_LLM_BASE_URL")
        or "http://127.0.0.1:11434"
    ).strip()
    base = raw.rstrip("/")
    if base.endswith("/v1"):
        return base
    return f"{base}/v1"


def _resolve_embedding_config() -> tuple[str, int, str]:
    model = os.environ.get("ALETHEIA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    try:
        dimensions = int(os.environ.get("ALETHEIA_EMBED_DIM", str(DEFAULT_EMBED_DIM)))
    except ValueError:
        dimensions = DEFAULT_EMBED_DIM
    base_url = _resolve_embedding_base_url()
    return model, dimensions, base_url


def create_vectorizers():
    """Create pgai vectorizers for all tables that need embeddings.

    Idempotent -- uses if_not_exists.
    """
    install_pgai()
    model, dimensions, base_url = _resolve_embedding_config()

    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            # Vectorizer for document_chunks: embeds the 'content' column.
            # pgai creates:
            #   - document_chunks_embedding_store (table with embeddings)
            #   - document_chunks_embedding (view joining chunks + embeddings)
            cur.execute(
                """
                SELECT ai.create_vectorizer(
                    'document_chunks'::regclass,
                    if_not_exists => true,
                    loading => ai.loading_column(column_name => 'content'),
                    embedding => ai.embedding_openai(
                        %s,
                        %s,
                        base_url => %s
                    ),
                    chunking => ai.chunking_none(),
                    formatting => ai.formatting_python_template(
                        '$chunk'
                    ),
                    destination => ai.destination_table(
                        target_table => 'document_chunks_embedding_store',
                        view_name => 'document_chunks_embedding'
                    )
                )
                """,
                (model, dimensions, base_url),
            )

            # Vectorizer for methodology_changes: embeds description + impact.
            # This enables semantic search over methodology break descriptions
            # without needing them in document_chunks.
            cur.execute(
                """
                SELECT ai.create_vectorizer(
                    'methodology_changes'::regclass,
                    if_not_exists => true,
                    loading => ai.loading_column(column_name => 'description'),
                    embedding => ai.embedding_openai(
                        %s,
                        %s,
                        base_url => %s
                    ),
                    chunking => ai.chunking_none(),
                    formatting => ai.formatting_python_template(
                        'methodology change: $chunk'
                    ),
                    destination => ai.destination_table(
                        target_table => 'methodology_changes_embedding_store',
                        view_name => 'methodology_changes_embedding'
                    )
                )
                """,
                (model, dimensions, base_url),
            )

        conn.commit()

    print(f"Vectorizers created (model={model}, dim={dimensions})")
    print(f"Embedding endpoint: {base_url}")
    print("Views available: document_chunks_embedding, methodology_changes_embedding")


def materialize_embeddings_once(timeout_seconds: int = 240) -> dict[str, object]:
    """Run one vectorizer-worker pass to materialize pending embeddings."""
    commands = [
        ["pgai", "vectorizer", "worker", "--once"],
        [sys.executable, "-m", "pgai.vectorizer_worker", "--once"],
    ]
    attempts: list[dict[str, object]] = []

    for cmd in commands:
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except FileNotFoundError as exc:
            attempts.append(
                {"command": " ".join(cmd), "ok": False, "error": str(exc)}
            )
            continue
        except subprocess.TimeoutExpired as exc:
            attempts.append(
                {
                    "command": " ".join(cmd),
                    "ok": False,
                    "error": f"timeout after {timeout_seconds}s",
                    "stdout_tail": (exc.stdout or "")[-400:],
                    "stderr_tail": (exc.stderr or "")[-400:],
                }
            )
            continue

        payload = {
            "command": " ".join(cmd),
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-600:],
            "stderr_tail": (proc.stderr or "")[-600:],
        }
        attempts.append(payload)
        if proc.returncode == 0:
            return {
                "ok": True,
                "command": payload["command"],
                "attempts": attempts,
            }

    return {
        "ok": False,
        "attempts": attempts,
        "error": (
            "Unable to run pgai vectorizer worker. "
            "Install pgai with vectorizer-worker extras."
        ),
    }


def vectorizer_status() -> dict[str, object]:
    """Report semantic index readiness and embedding coverage."""
    model, dimensions, base_url = _resolve_embedding_config()
    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
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
                ) AS break_view,
                EXISTS(
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'document_chunks_embedding_store'
                ) AS doc_store,
                EXISTS(
                    SELECT 1
                    FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = 'methodology_changes_embedding_store'
                ) AS break_store
                """
            )
            flags = cur.fetchone()

            doc_embeddings = 0
            break_embeddings = 0
            doc_chunks = 0
            method_changes = 0

            cur.execute("SELECT COUNT(*) FROM document_chunks")
            doc_chunks = int(cur.fetchone()[0])

            cur.execute("SELECT COUNT(*) FROM methodology_changes")
            method_changes = int(cur.fetchone()[0])

            if flags and bool(flags[0]):
                cur.execute("SELECT COUNT(*) FROM document_chunks_embedding")
                doc_embeddings = int(cur.fetchone()[0])
            if flags and bool(flags[1]):
                cur.execute("SELECT COUNT(*) FROM methodology_changes_embedding")
                break_embeddings = int(cur.fetchone()[0])

    doc_ready = doc_chunks == 0 or doc_embeddings > 0
    break_ready = method_changes == 0 or break_embeddings > 0
    semantic_ready = bool(flags and flags[0] and flags[1] and doc_ready and break_ready)

    return {
        "embedding_model": model,
        "embedding_dim": dimensions,
        "embedding_base_url": base_url,
        "document_chunks": doc_chunks,
        "methodology_changes": method_changes,
        "document_embeddings": doc_embeddings,
        "methodology_embeddings": break_embeddings,
        "document_embedding_view": bool(flags and flags[0]),
        "methodology_embedding_view": bool(flags and flags[1]),
        "document_embedding_store": bool(flags and flags[2]),
        "methodology_embedding_store": bool(flags and flags[3]),
        "semantic_search_ready": semantic_ready,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Create pgai vectorizers and inspect status.")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only print vectorizer status, do not create/update vectorizers.",
    )
    parser.add_argument(
        "--materialize-once",
        action="store_true",
        help="Run one vectorizer-worker pass after creating vectorizers.",
    )
    args = parser.parse_args()

    if not args.status_only:
        create_vectorizers()
    payload: dict[str, object] = {"status": vectorizer_status()}
    if args.materialize_once:
        payload["materialize"] = materialize_embeddings_once()
        payload["status"] = vectorizer_status()
    print(json.dumps(payload, indent=2))
