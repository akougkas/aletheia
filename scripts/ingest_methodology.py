#!/usr/bin/env python3
"""Ingest methodology documentation using crawl4ai (HTML) and httpx (PDF).

Scrapes target URLs from MARINA.md, chunks content, stores in document_chunks,
and optionally materializes pgai embeddings for semantic search.

Usage:
    uv run python scripts/ingest_methodology.py [--materialize] [--max-docs N]
    make ingest-methodology   # requires: make sync-crawler
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from pathlib import Path
from urllib.parse import urlparse

import psycopg

from aletheia.db import get_db_url
from aletheia.ingest import (
    _chunk_text,
    _ensure_agencies,
    _fetch_url_content,
    _normalize,
    _reference_docs,
    _upsert_chunks,
    _upsert_document,
    ingest_local_directory,
)
from aletheia.ingest import CorpusDocument


def _is_pdf_url(url: str) -> bool:
    return url.lower().endswith(".pdf") or ".pdf?" in url.lower()


def _extract_crawl4ai_markdown(result) -> str:
    """Extract best available markdown from crawl4ai result."""
    for field in ("markdown", "cleaned_markdown", "fit_markdown", "raw_markdown"):
        value = getattr(result, field, None)
        if isinstance(value, str) and value.strip():
            return _normalize(value.strip())
    return ""


async def _fetch_with_crawl4ai(url: str, timeout_seconds: float = 45.0) -> tuple[str, dict]:
    """Fetch HTML page via crawl4ai. Returns (text, metadata)."""
    meta: dict = {
        "url": url,
        "fetched": False,
        "fetched_by": "crawl4ai",
        "error": None,
    }
    try:
        from crawl4ai import AsyncWebCrawler, CacheMode, CrawlerRunConfig
    except ImportError:
        meta["error"] = "crawl4ai not installed (run: make sync-crawler)"
        return "", meta

    try:
        config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
        async with AsyncWebCrawler() as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url, config=config),
                timeout=timeout_seconds,
            )
    except asyncio.TimeoutError:
        meta["error"] = f"timeout after {timeout_seconds}s"
        return "", meta
    except Exception as exc:
        meta["error"] = str(exc)
        return "", meta

    if not getattr(result, "success", True):
        meta["error"] = getattr(result, "error_message", "crawl failed")
        return "", meta

    text = _extract_crawl4ai_markdown(result)
    meta["fetched"] = bool(text)
    meta["status_code"] = getattr(result, "status_code", None)
    return text, meta


def _fetch_pdf_content(url: str, timeout: float = 45.0) -> tuple[str, dict]:
    """Fetch PDF via httpx (crawl4ai does not handle PDFs)."""
    text, meta = _fetch_url_content(url, timeout=timeout)
    meta["fetched_by"] = "httpx"
    return text, meta


async def _fetch_document(doc: CorpusDocument, timeout: float = 45.0) -> tuple[str, dict]:
    """Fetch document content: crawl4ai for HTML, httpx for PDF."""
    if not doc.url:
        return "", {"url": None, "fetched": False, "error": "no url"}

    if _is_pdf_url(doc.url):
        # PDF: use httpx (run in executor to avoid blocking)
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: _fetch_pdf_content(doc.url, timeout),
        )

    # HTML: use crawl4ai
    return await _fetch_with_crawl4ai(doc.url, timeout_seconds=timeout)


def _clean_scraped_text(text: str) -> str:
    """Remove excessive whitespace and boilerplate."""
    if not text:
        return ""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return _normalize(text)


async def _run_ingest(
    marina_path: Path,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
    max_docs: int | None = None,
    timeout: float = 45.0,
    dry_run: bool = False,
) -> dict:
    """Scrape URLs, chunk, and store. Returns stats."""
    docs = _reference_docs(marina_path)
    if max_docs is not None:
        docs = [d for d in docs if d.url][:max_docs]
    else:
        docs = [d for d in docs if d.url]

    stats = {
        "documents_seen": len(docs),
        "documents_written": 0,
        "chunks_written": 0,
        "fetch_success": 0,
        "fetch_failed": 0,
        "fetch_timeout": 0,
    }

    if dry_run:
        return stats

    with psycopg.connect(get_db_url()) as conn:
        with conn.cursor() as cur:
            _ensure_agencies(cur)

            for doc in docs:
                text, fetch_meta = await _fetch_document(doc, timeout=timeout)

                if fetch_meta.get("error"):
                    if "timeout" in str(fetch_meta.get("error", "")).lower():
                        stats["fetch_timeout"] += 1
                    stats["fetch_failed"] += 1
                else:
                    stats["fetch_success"] += 1

                doc_id = _upsert_document(cur, doc)
                content = (
                    f"{doc.title}\n\n{doc.summary}\n\nSource URL: {doc.url}\n\n"
                    f"{_clean_scraped_text(text) if text else 'No content extracted; see metadata for fetch error.'}"
                )
                chunks = _chunk_text(content, chunk_size, overlap)
                if not chunks:
                    continue

                _upsert_chunks(
                    cur,
                    doc_id,
                    chunks,
                    metadata={
                        "source": "ingest_methodology",
                        "doc_type": doc.doc_type,
                        "fetch": fetch_meta,
                        "domain": (urlparse(doc.url).netloc or "").lower(),
                    },
                )
                stats["documents_written"] += 1
                stats["chunks_written"] += len(chunks)

        conn.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest methodology docs via crawl4ai (HTML) + httpx (PDF)."
    )
    parser.add_argument(
        "--marina-path",
        default="MARINA.md",
        help="Path to MARINA.md",
    )
    parser.add_argument(
        "--input-dir",
        default="inputs",
        help="Path to a directory containing general knowledge files (PDFs, MDs, TXT)",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1200,
        help="Character chunk size",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=150,
        help="Overlap between chunks",
    )
    parser.add_argument(
        "--max-docs",
        type=int,
        default=None,
        help="Cap number of URLs to fetch (for testing)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=45.0,
        help="Fetch timeout per URL (seconds)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report counts without writing to DB",
    )
    parser.add_argument(
        "--materialize",
        action="store_true",
        help="Run pgai vectorizer worker after ingest",
    )
    parser.add_argument(
        "--db-url",
        default=None,
        help="Override ALETHEIA_DB_URL",
    )
    args = parser.parse_args()

    if args.db_url:
        os.environ["ALETHEIA_DB_URL"] = args.db_url

    marina_path = Path(args.marina_path)
    if not marina_path.exists():
        print(json.dumps({"error": f"MARINA.md not found: {marina_path}"}, indent=2))
        raise SystemExit(1)

    stats = asyncio.run(
        _run_ingest(
            marina_path,
            chunk_size=args.chunk_size,
            overlap=args.chunk_overlap,
            max_docs=args.max_docs,
            timeout=args.timeout,
            dry_run=args.dry_run,
        )
    )

    output: dict = {"ingest": stats}

    if args.materialize and not args.dry_run:
        from aletheia.vectorizer import (
            create_vectorizers,
            materialize_embeddings_once,
            vectorizer_status,
        )

        create_vectorizers()
        output["materialize"] = materialize_embeddings_once()
        output["vectorizer"] = vectorizer_status()

    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
