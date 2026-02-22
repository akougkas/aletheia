"""Embedding materialization for ALETHEIA (SurrealDB backend).

No pgai vectorizer worker — embeddings are batch-computed via Ollama
and written directly to SurrealDB records.
"""

import argparse
import asyncio
import json
import os
from typing import Any

from aletheia.db import get_connection


DEFAULT_EMBED_MODEL = "text-embedding-ada-002"
DEFAULT_EMBED_DIM = 4096


def _resolve_embedding_config() -> tuple[str, int, str]:
    """Resolve embedding model, dimensions, and base URL."""
    try:
        from aletheia.providers import _active_embed_endpoint

        ep = _active_embed_endpoint()
        if ep is not None:
            model = ep.default_embed_model or os.environ.get("ALETHEIA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
            try:
                dimensions = int(os.environ.get("ALETHEIA_EMBED_DIM", str(DEFAULT_EMBED_DIM)))
            except ValueError:
                dimensions = DEFAULT_EMBED_DIM
            base_url = ep.url.rstrip("/")
            if not base_url.endswith("/v1"):
                base_url = f"{base_url}/v1"
            return model, dimensions, base_url
    except (ImportError, AttributeError):
        pass

    model = os.environ.get("ALETHEIA_EMBED_MODEL", DEFAULT_EMBED_MODEL)
    try:
        dimensions = int(os.environ.get("ALETHEIA_EMBED_DIM", str(DEFAULT_EMBED_DIM)))
    except ValueError:
        dimensions = DEFAULT_EMBED_DIM
    base_url = _resolve_embedding_base_url()
    return model, dimensions, base_url


def _resolve_embedding_base_url() -> str:
    """Resolve OpenAI-compatible embedding base URL."""
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


async def _embed_batch(texts: list[str], model: str, base_url: str) -> list[list[float]]:
    """Call the OpenAI-compatible /v1/embeddings endpoint for a batch of texts."""
    import httpx

    url = f"{base_url}/embeddings"
    payload = {"input": texts, "model": model}

    api_key = _resolve_embed_api_key() or "local"
    headers = {"Authorization": f"Bearer {api_key}"}

    async with httpx.AsyncClient(timeout=120.0, headers=headers) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        embeddings = [item["embedding"] for item in data["data"]]
        return embeddings


def _resolve_embed_api_key() -> str | None:
    """Get the embed endpoint's API key from provider config or env."""
    try:
        from aletheia.providers import _active_embed_endpoint

        ep = _active_embed_endpoint()
        if ep is not None and ep.api_key:
            return ep.api_key
    except (ImportError, AttributeError):
        pass
    return os.environ.get("ALETHEIA_EMBED_API_KEY") or os.environ.get("ALETHEIA_LLM_API_KEY")


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


async def materialize_embeddings(
    batch_size: int = 50,
    progress_callback: Any = None,
) -> dict[str, Any]:
    """Batch-embed all records with missing embeddings.

    Queries unembedded chunks and methodology changes, calls Ollama
    in batches, and updates the records. Resumable — always queries
    for records WHERE embedding IS NONE.
    """
    model, dimensions, base_url = _resolve_embedding_config()
    stats: dict[str, Any] = {
        "ok": False,
        "model": model,
        "dim": dimensions,
        "base_url": base_url,
        "chunks_embedded": 0,
        "changes_embedded": 0,
        "errors": [],
    }

    try:
        async with get_connection() as db:
            # Embed chunks
            while True:
                result = await db.query(
                    f"SELECT * FROM chunk WHERE embedding IS NONE LIMIT {batch_size}"
                )
                rows = _query_result_rows(result)
                if not rows:
                    break

                texts = [row.get("content", "") for row in rows]
                ids = [str(row.get("id", "")) for row in rows]

                try:
                    embeddings = await _embed_batch(texts, model, base_url)
                except Exception as exc:
                    stats["errors"].append(f"chunk_embed: {exc}")
                    break

                for rid, vec in zip(ids, embeddings):
                    await db.query(
                        "UPDATE $id SET embedding = $vec",
                        {"id": rid, "vec": vec},
                    )
                stats["chunks_embedded"] += len(rows)

                if progress_callback:
                    progress_callback(f"Embedded {stats['chunks_embedded']} chunks...")

            # Embed methodology changes
            while True:
                result = await db.query(
                    f"SELECT * FROM methodology_change WHERE embedding IS NONE LIMIT {batch_size}"
                )
                rows = _query_result_rows(result)
                if not rows:
                    break

                texts = [
                    f"methodology change: {row.get('description', '')}"
                    for row in rows
                ]
                ids = [str(row.get("id", "")) for row in rows]

                try:
                    embeddings = await _embed_batch(texts, model, base_url)
                except Exception as exc:
                    stats["errors"].append(f"change_embed: {exc}")
                    break

                for rid, vec in zip(ids, embeddings):
                    await db.query(
                        "UPDATE $id SET embedding = $vec",
                        {"id": rid, "vec": vec},
                    )
                stats["changes_embedded"] += len(rows)

                if progress_callback:
                    progress_callback(f"Embedded {stats['changes_embedded']} changes...")

        stats["ok"] = not stats["errors"]
    except Exception as exc:
        stats["errors"].append(str(exc))

    return stats


async def vectorizer_status() -> dict[str, Any]:
    """Report semantic index readiness and embedding coverage."""
    model, dimensions, base_url = _resolve_embedding_config()

    async with get_connection() as db:
        chunk_result = await db.query("SELECT count() AS total FROM chunk GROUP ALL")
        chunk_rows = _query_result_rows(chunk_result)
        doc_chunks = int(chunk_rows[0].get("total", 0)) if chunk_rows else 0

        mc_result = await db.query("SELECT count() AS total FROM methodology_change GROUP ALL")
        mc_rows = _query_result_rows(mc_result)
        method_changes = int(mc_rows[0].get("total", 0)) if mc_rows else 0

        chunk_embed_result = await db.query(
            "SELECT count() AS total FROM chunk WHERE embedding IS NOT NONE GROUP ALL"
        )
        ce_rows = _query_result_rows(chunk_embed_result)
        doc_embeddings = int(ce_rows[0].get("total", 0)) if ce_rows else 0

        mc_embed_result = await db.query(
            "SELECT count() AS total FROM methodology_change WHERE embedding IS NOT NONE GROUP ALL"
        )
        me_rows = _query_result_rows(mc_embed_result)
        method_embeddings = int(me_rows[0].get("total", 0)) if me_rows else 0

    doc_ready = doc_chunks == 0 or doc_embeddings > 0
    break_ready = method_changes == 0 or method_embeddings > 0
    semantic_ready = doc_ready and break_ready

    return {
        "embedding_model": model,
        "embedding_dim": dimensions,
        "embedding_base_url": base_url,
        "document_chunks": doc_chunks,
        "methodology_changes": method_changes,
        "document_embeddings": doc_embeddings,
        "methodology_embeddings": method_embeddings,
        "semantic_search_ready": semantic_ready,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Materialize embeddings and inspect status.")
    parser.add_argument(
        "--status-only",
        action="store_true",
        help="Only print vectorizer status.",
    )
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Run embedding materialization.",
    )
    args = parser.parse_args()

    async def _main():
        payload: dict[str, object] = {"status": await vectorizer_status()}
        if args.materialize and not args.status_only:
            payload["materialize"] = await materialize_embeddings()
            payload["status"] = await vectorizer_status()
        print(json.dumps(payload, indent=2))

    asyncio.run(_main())
