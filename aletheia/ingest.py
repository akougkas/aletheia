"""Ingest methodology and validation documents into the knowledge base."""

from __future__ import annotations

import argparse
import html
import io
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from aletheia.data_loader import (
    domain_to_agency_code as _domain_to_agency_map,
    load_agencies,
    load_methodology_breaks,
    load_reference_docs,
)
from aletheia.db import get_connection


@dataclass
class CorpusDocument:
    title: str
    doc_type: str
    summary: str
    url: str | None = None
    publication_date: str | None = None
    agency_code: str | None = None


# ---------------------------------------------------------------------------
# SurrealDB helpers
# ---------------------------------------------------------------------------

def _surreal_id(record: Any) -> str:
    """Extract the string ID from a SurrealDB record result."""
    if isinstance(record, dict):
        rid = record.get("id", "")
        return str(rid)
    if isinstance(record, list) and record:
        return _surreal_id(record[0])
    return str(record)


def _query_result_rows(result: Any) -> list[dict]:
    """Extract rows from a SurrealDB query() result."""
    if not result:
        return []
    if isinstance(result, list):
        # query() returns list of statement results
        for item in result:
            if isinstance(item, dict):
                rows = item.get("result", [])
                if isinstance(rows, list):
                    return rows
            elif isinstance(item, list):
                return item
        return result if all(isinstance(r, dict) for r in result) else []
    return []


async def _ensure_agencies(db) -> None:
    """Upsert all known agencies."""
    for a in load_agencies():
        await db.query(
            """
            UPSERT agency SET
                code = $code,
                name = $name,
                country = $country,
                url = $url
            WHERE code = $code
            """,
            {"code": a["code"], "name": a["name"], "country": a["country"], "url": a["url"]},
        )


async def _upsert_document(db, doc: CorpusDocument) -> str:
    """Upsert a document and return its SurrealDB record ID."""
    # Try to find existing by URL
    if doc.url:
        result = await db.query(
            "SELECT * FROM document WHERE url = $url LIMIT 1",
            {"url": doc.url},
        )
        rows = _query_result_rows(result)
        if rows:
            doc_id = _surreal_id(rows[0])
            await db.query(
                """
                UPDATE $id SET
                    title = $title,
                    doc_type = $doc_type,
                    agency_code = $agency_code,
                    publication_date = $pub_date
                """,
                {
                    "id": doc_id,
                    "title": doc.title,
                    "doc_type": doc.doc_type,
                    "agency_code": doc.agency_code,
                    "pub_date": doc.publication_date,
                },
            )
            return doc_id

    # Try to find by title + doc_type
    result = await db.query(
        "SELECT * FROM document WHERE title = $title AND doc_type = $doc_type LIMIT 1",
        {"title": doc.title, "doc_type": doc.doc_type},
    )
    rows = _query_result_rows(result)
    if rows:
        return _surreal_id(rows[0])

    # Create new
    result = await db.query(
        """
        CREATE document SET
            title = $title,
            doc_type = $doc_type,
            agency_code = $agency_code,
            url = $url,
            publication_date = $pub_date
        """,
        {
            "title": doc.title,
            "doc_type": doc.doc_type,
            "agency_code": doc.agency_code,
            "url": doc.url,
            "pub_date": doc.publication_date,
        },
    )
    rows = _query_result_rows(result)
    return _surreal_id(rows[0]) if rows else ""


async def _upsert_chunks(
    db,
    doc_id: str,
    chunks: list[str],
    metadata: dict[str, Any],
) -> None:
    """Create or update chunks for a document, linked via part_of edges."""
    metadata_val = metadata

    for idx, chunk in enumerate(chunks):
        # Check if chunk exists for this doc at this index
        result = await db.query(
            """
            SELECT * FROM chunk
            WHERE ->part_of->document CONTAINS $doc_id
              AND chunk_index = $idx
            LIMIT 1
            """,
            {"doc_id": doc_id, "idx": idx},
        )
        rows = _query_result_rows(result)

        if rows:
            chunk_id = _surreal_id(rows[0])
            await db.query(
                "UPDATE $id SET content = $content, metadata = $metadata",
                {"id": chunk_id, "content": chunk, "metadata": metadata_val},
            )
        else:
            result = await db.query(
                "CREATE chunk SET chunk_index = $idx, content = $content, metadata = $metadata",
                {"idx": idx, "content": chunk, "metadata": metadata_val},
            )
            chunk_rows = _query_result_rows(result)
            if chunk_rows:
                chunk_id = _surreal_id(chunk_rows[0])
                await db.query(
                    "RELATE $chunk->part_of->$doc",
                    {"chunk": chunk_id, "doc": doc_id},
                )

    # Remove stale chunks beyond the current count
    result = await db.query(
        """
        SELECT * FROM chunk
        WHERE ->part_of->document CONTAINS $doc_id
          AND chunk_index >= $max_idx
        """,
        {"doc_id": doc_id, "max_idx": len(chunks)},
    )
    for row in _query_result_rows(result):
        stale_id = _surreal_id(row)
        await db.query("DELETE $id", {"id": stale_id})


# ---------------------------------------------------------------------------
# Text parsing (unchanged from PostgreSQL version)
# ---------------------------------------------------------------------------

def _section(text: str, start: str, end: str) -> list[str]:
    start_idx = text.find(start)
    if start_idx == -1:
        return []
    end_idx = text.find(end, start_idx)
    if end_idx == -1:
        end_idx = len(text)
    return text[start_idx:end_idx].splitlines()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _domain(url: str) -> str:
    value = re.sub(r"^https?://", "", url)
    return value.split("/", 1)[0].lower()


def _guess_agency_code(url: str | None, title: str) -> str | None:
    if url:
        domain = _domain(url)
        for known_domain, code in _domain_to_agency_map().items():
            if domain.endswith(known_domain):
                return code
    title_lower = title.lower()
    if "eurostat" in title_lower:
        return "EUROSTAT"
    if "census" in title_lower:
        return "CENSUS"
    if "bls" in title_lower:
        return "BLS"
    if "nhis" in title_lower or "cdc" in title_lower:
        return "CDC"
    return None


def _chunk_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    cleaned = _normalize(text)
    if not cleaned:
        return []

    chunks: list[str] = []
    start = 0
    while start < len(cleaned):
        end = min(start + chunk_size, len(cleaned))
        chunks.append(cleaned[start:end])
        if end >= len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def parse_marina_file(path: Path) -> list[CorpusDocument]:
    text = path.read_text(encoding="utf-8")
    docs: list[CorpusDocument] = []
    known_urls = load_reference_docs()["known_method_doc_urls"]

    key_docs_lines = _section(
        text,
        "### Key Methodology Documentation",
        "### Papers for Validation Evidence",
    )
    for line in key_docs_lines:
        line = line.strip()
        if not line:
            continue
        match = re.match(r"^\d+\.\s*(.+)$", line)
        if not match:
            continue
        content = match.group(1)
        parts = [part.strip() for part in content.split(" - ") if part.strip()]
        title = parts[0]
        summary = " - ".join(parts[1:]) if len(parts) > 1 else title
        url = known_urls.get(title)
        docs.append(
            CorpusDocument(
                title=title,
                doc_type="methodology_note",
                summary=summary,
                url=url,
                agency_code=_guess_agency_code(url, title),
            )
        )

    paper_lines = _section(text, "### Papers for Validation Evidence", "## Test Cases")
    for line in paper_lines:
        line = line.strip()
        if not line or line.startswith("|"):
            continue
        match = re.match(r"^(.*?)\s*-\s*(https?://\S+)\s*$", line)
        if not match:
            continue
        title = _normalize(match.group(1))
        url = match.group(2).strip()
        docs.append(
            CorpusDocument(
                title=title,
                doc_type="validation_paper",
                summary=title,
                url=url,
                agency_code=_guess_agency_code(url, title),
            )
        )

    deduped: dict[str, CorpusDocument] = {}
    for doc in docs:
        key = doc.url or f"{doc.doc_type}:{doc.title.lower()}"
        deduped[key] = doc
    return list(deduped.values())


def _reference_docs(marina_path: Path) -> list[CorpusDocument]:
    docs = parse_marina_file(marina_path)
    for row in load_reference_docs()["extra_reference_docs"]:
        docs.append(
            CorpusDocument(
                title=row["title"],
                doc_type=row["doc_type"],
                summary=row["summary"],
                url=row["url"],
                agency_code=_guess_agency_code(row["url"], row["title"]),
            )
        )

    deduped: dict[str, CorpusDocument] = {}
    for doc in docs:
        key = doc.url or f"{doc.doc_type}:{doc.title.lower()}"
        deduped[key] = doc
    return list(deduped.values())


def _extract_html_text(content: str) -> str:
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", content)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?is)<noscript[^>]*>.*?</noscript>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    return _normalize(text)


def _extract_pdf_text(payload: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(io.BytesIO(payload))
        pages = []
        for page in reader.pages:
            text = page.extract_text() or ""
            if text.strip():
                pages.append(text)
        extracted = "\n".join(pages)
        if extracted.strip():
            return _normalize(extracted)
    except Exception:
        pass

    decoded = payload.decode("latin-1", errors="ignore")
    decoded = re.sub(r"[^\x20-\x7E\n]", " ", decoded)
    decoded = re.sub(r"\s+", " ", decoded)
    return decoded.strip()


def _fetch_url_content(url: str, timeout: float = 30.0) -> tuple[str, dict[str, Any]]:
    meta: dict[str, Any] = {
        "url": url,
        "status_code": None,
        "content_type": None,
        "fetched": False,
        "error": None,
    }
    headers = {
        "User-Agent": "ALETHEIA/0.1 (+https://github.com/aletheia-research)",
        "Accept": "text/html,application/xhtml+xml,application/pdf,text/plain,*/*;q=0.8",
    }
    try:
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            meta["status_code"] = response.status_code
            response.raise_for_status()
            content_type = (response.headers.get("content-type") or "").lower()
            meta["content_type"] = content_type
            meta["final_url"] = str(response.url)

            if "pdf" in content_type or str(response.url).lower().endswith(".pdf"):
                text = _extract_pdf_text(response.content)
            elif "html" in content_type or "xml" in content_type:
                text = _extract_html_text(response.text)
            else:
                text = _normalize(response.text)

            meta["fetched"] = True
            return text, meta
    except Exception as exc:  # noqa: BLE001
        meta["error"] = str(exc)
        return "", meta


# ---------------------------------------------------------------------------
# Async ingest functions (SurrealDB)
# ---------------------------------------------------------------------------

async def ingest_marina_corpus(
    marina_path: Path,
    *,
    chunk_size: int = 1000,
    overlap: int = 150,
    dry_run: bool = False,
) -> dict[str, int]:
    """Compatibility ingest: parse knowledge lists and index short summaries."""
    docs = parse_marina_file(marina_path)
    stats = {"documents_seen": len(docs), "documents_written": 0, "chunks_written": 0}

    if dry_run:
        return stats

    async with get_connection() as db:
        await _ensure_agencies(db)
        for doc in docs:
            doc_id = await _upsert_document(db, doc)
            chunk_text = (
                f"{doc.title}\n\n{doc.summary}\n\nSource URL: {doc.url or 'n/a'}"
            )
            chunks = _chunk_text(chunk_text, chunk_size, overlap)
            if not chunks:
                continue
            await _upsert_chunks(
                db,
                doc_id,
                chunks,
                metadata={"source": "MARINA.md", "doc_type": doc.doc_type},
            )
            stats["documents_written"] += 1
            stats["chunks_written"] += len(chunks)

    return stats


async def ingest_reference_urls(
    marina_path: Path,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
    max_docs: int | None = None,
    dry_run: bool = False,
) -> dict[str, int]:
    """Fetch and ingest methodology references (HTML/PDF) from knowledge + extras."""
    docs = _reference_docs(marina_path)
    if max_docs is not None:
        docs = docs[: max(0, max_docs)]

    stats = {
        "documents_seen": len(docs),
        "documents_written": 0,
        "chunks_written": 0,
        "fetch_success": 0,
        "fetch_failed": 0,
    }

    if dry_run:
        return stats

    async with get_connection() as db:
        await _ensure_agencies(db)
        for doc in docs:
            if not doc.url:
                continue
            fetched_text, fetch_meta = _fetch_url_content(doc.url)
            if fetched_text:
                stats["fetch_success"] += 1
            else:
                stats["fetch_failed"] += 1

            doc_id = await _upsert_document(db, doc)
            content = (
                f"{doc.title}\n\n{doc.summary}\n\nSource URL: {doc.url}\n\n"
                f"{fetched_text if fetched_text else 'No content extracted; see metadata for fetch error.'}"
            )
            chunks = _chunk_text(content, chunk_size, overlap)
            if not chunks:
                continue
            await _upsert_chunks(
                db,
                doc_id,
                chunks,
                metadata={
                    "source": "phase3_url_ingest",
                    "doc_type": doc.doc_type,
                    "fetch": fetch_meta,
                    "domain": (urlparse(doc.url).netloc or "").lower(),
                },
            )
            stats["documents_written"] += 1
            stats["chunks_written"] += len(chunks)

    return stats


async def seed_phase3_methodology_breaks(
    *,
    dry_run: bool = False,
) -> dict[str, int]:
    """Insert expanded methodology-break corpus for Phase 3 coverage."""
    breaks = load_methodology_breaks()
    stats = {
        "break_rows_target": len(breaks),
        "break_rows_written": 0,
        "impact_links_written": 0,
        "impact_links_skipped_missing_indicator": 0,
    }
    if dry_run:
        return stats

    async with get_connection() as db:
        await _ensure_agencies(db)

        for row in breaks:
            # Upsert methodology change by benchmark_case_id
            result = await db.query(
                """
                UPSERT methodology_change SET
                    benchmark_case_id = $case_id,
                    change_type = $change_type,
                    effective_date = $effective_date,
                    description = $description,
                    impact_estimate = $impact_estimate,
                    severity = $severity,
                    comparability = $comparability,
                    is_documented = true,
                    source_url = $source_url
                WHERE benchmark_case_id = $case_id
                """,
                {
                    "case_id": row["benchmark_case_id"],
                    "change_type": row["change_type"],
                    "effective_date": row["effective_date"],
                    "description": row["description"],
                    "impact_estimate": row["impact_estimate"],
                    "severity": row["severity"],
                    "comparability": row["comparability"],
                    "source_url": row["source_url"],
                },
            )
            change_rows = _query_result_rows(result)
            if not change_rows:
                continue
            change_id = _surreal_id(change_rows[0])
            stats["break_rows_written"] += 1

            # Link change -> belongs_to -> dataset
            ds_result = await db.query(
                "SELECT * FROM dataset WHERE code = $code LIMIT 1",
                {"code": row["dataset_code"]},
            )
            ds_rows = _query_result_rows(ds_result)
            if ds_rows:
                ds_id = _surreal_id(ds_rows[0])
                await db.query(
                    "RELATE $change->belongs_to->$dataset",
                    {"change": change_id, "dataset": ds_id},
                )

            # Link change -> affects -> indicator
            ind_result = await db.query(
                """
                SELECT * FROM indicator
                WHERE code = $ind_code
                  AND ->has_indicator<-dataset.code CONTAINS $ds_code
                LIMIT 1
                """,
                {"ind_code": row["indicator_code"], "ds_code": row["dataset_code"]},
            )
            ind_rows = _query_result_rows(ind_result)

            if not ind_rows:
                # Simpler fallback: just find by indicator code
                ind_result = await db.query(
                    "SELECT * FROM indicator WHERE code = $code LIMIT 1",
                    {"code": row["indicator_code"]},
                )
                ind_rows = _query_result_rows(ind_result)

            if not ind_rows:
                stats["impact_links_skipped_missing_indicator"] += 1
                continue

            ind_id = _surreal_id(ind_rows[0])
            await db.query(
                """
                RELATE $change->affects->$indicator SET
                    impact_direction = $direction,
                    impact_magnitude = $magnitude
                """,
                {
                    "change": change_id,
                    "indicator": ind_id,
                    "direction": row.get("impact_direction", "unknown"),
                    "magnitude": row.get("impact_magnitude"),
                },
            )
            stats["impact_links_written"] += 1

    return stats


async def ingest_single_url(
    url: str,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Fetch and ingest a single URL (HTML or PDF) into the knowledge base."""
    text, fetch_meta = _fetch_url_content(url)

    stats: dict[str, Any] = {
        "url": url,
        "fetched": fetch_meta.get("fetched", False),
        "content_type": fetch_meta.get("content_type"),
        "text_length": len(text) if text else 0,
        "chunks_expected": 0,
        "documents_written": 0,
        "chunks_written": 0,
        "error": fetch_meta.get("error"),
    }

    if not text:
        return stats

    parsed = urlparse(url)
    title = parsed.path.rsplit("/", 1)[-1] or parsed.netloc
    content = f"{title}\n\n{text}"
    chunks = _chunk_text(content, chunk_size, overlap)
    stats["chunks_expected"] = len(chunks)

    if dry_run:
        return stats

    doc = CorpusDocument(
        title=title,
        doc_type="external_url",
        summary=f"Ingested from {url}",
        url=url,
        agency_code=_guess_agency_code(url, title),
    )

    async with get_connection() as db:
        await _ensure_agencies(db)
        doc_id = await _upsert_document(db, doc)
        if chunks:
            await _upsert_chunks(
                db,
                doc_id,
                chunks,
                metadata={
                    "source": "cli_url_ingest",
                    "doc_type": doc.doc_type,
                    "fetch": fetch_meta,
                    "domain": (parsed.netloc or "").lower(),
                },
            )
            stats["documents_written"] = 1
            stats["chunks_written"] = len(chunks)

    return stats


async def ingest_local_directory(
    dir_path: Path,
    *,
    chunk_size: int = 1200,
    overlap: int = 150,
    dry_run: bool = False,
) -> dict[str, int]:
    """Ingest all generic documents (PDF, MD, TXT, HTML) from a directory."""
    stats = {
        "files_seen": 0,
        "files_ingested": 0,
        "chunks_written": 0,
        "errors": 0,
    }

    if not dir_path.exists() or not dir_path.is_dir():
        return stats

    _SUPPORTED = {".pdf", ".html", ".htm", ".md", ".txt"}
    supported_files = [
        f for f in dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in _SUPPORTED
    ]
    stats["files_seen"] = len(supported_files)

    if dry_run:
        return stats

    async with get_connection() as db:
        await _ensure_agencies(db)
        for filepath in supported_files:
            ext = filepath.suffix.lower()
            text = ""

            try:
                if ext == ".pdf":
                    text = _extract_pdf_text(filepath.read_bytes())
                elif ext in (".html", ".htm"):
                    text = _extract_html_text(filepath.read_text(encoding="utf-8", errors="ignore"))
                elif ext in (".md", ".txt"):
                    text = _normalize(filepath.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                stats["errors"] += 1
                continue

            if not text:
                continue

            doc = CorpusDocument(
                title=filepath.name,
                doc_type="local_knowledge",
                summary=f"Local knowledge file: {filepath.name}",
                url=f"file://{filepath.absolute()}",
            )

            doc_id = await _upsert_document(db, doc)
            content = f"{doc.title}\n\n{text}"
            chunks = _chunk_text(content, chunk_size, overlap)

            if not chunks:
                continue

            await _upsert_chunks(
                db,
                doc_id,
                chunks,
                metadata={
                    "source": "local_directory",
                    "doc_type": doc.doc_type,
                    "filename": filepath.name,
                    "filepath": str(filepath),
                },
            )
            stats["files_ingested"] += 1
            stats["chunks_written"] += len(chunks)

    return stats


async def kb_counts() -> dict[str, int]:
    """Return current knowledge base record counts."""
    async with get_connection() as db:
        counts: dict[str, int] = {}
        for table, key in [
            ("methodology_change", "methodology_changes"),
            ("chunk", "document_chunks"),
            ("document", "documents"),
        ]:
            result = await db.query(f"SELECT count() AS total FROM {table} GROUP ALL")
            rows = _query_result_rows(result)
            counts[key] = int(rows[0].get("total", 0)) if rows else 0
        return counts


async def run_phase3_ingest(
    marina_path: Path,
    *,
    chunk_size: int,
    overlap: int,
    dry_run: bool,
    seed_phase3: bool,
    fetch_urls: bool,
    max_docs: int | None,
    materialize_embeddings: bool,
) -> dict[str, Any]:
    output: dict[str, Any] = {
        "marina": await ingest_marina_corpus(
            marina_path,
            chunk_size=chunk_size,
            overlap=overlap,
            dry_run=dry_run,
        )
    }

    if seed_phase3:
        output["phase3_breaks"] = await seed_phase3_methodology_breaks(dry_run=dry_run)

    if fetch_urls:
        output["url_ingest"] = await ingest_reference_urls(
            marina_path,
            chunk_size=chunk_size,
            overlap=overlap,
            max_docs=max_docs,
            dry_run=dry_run,
        )

    if not dry_run:
        output["counts"] = await kb_counts()

    if materialize_embeddings and not dry_run:
        from aletheia.vectorizer import materialize_embeddings as mat_embed, vectorizer_status

        output["materialize"] = await mat_embed()
        output["vectorizer"] = await vectorizer_status()

    return output


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(
        description="Ingest methodology notes and papers into the ALETHEIA knowledge base."
    )
    parser.add_argument("--marina-path", default="MARINA.md", help="Path to MARINA.md")
    parser.add_argument("--chunk-size", type=int, default=1200, help="Character chunk size.")
    parser.add_argument("--chunk-overlap", type=int, default=150, help="Character overlap between chunks.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report counts without writing to DB.")
    parser.add_argument("--seed-phase3", action="store_true", help="Insert expanded methodology-break corpus.")
    parser.add_argument("--fetch-urls", action="store_true", help="Fetch and ingest full text from reference URLs.")
    parser.add_argument("--max-docs", type=int, default=None, help="Optional cap on number of URLs to fetch.")
    parser.add_argument("--materialize-embeddings", action="store_true", help="Run embedding materialization after ingest.")
    parser.add_argument("--db-url", default=None, help="Override ALETHEIA_DB_URL for this ingest run.")
    args = parser.parse_args()

    if args.db_url:
        os.environ["ALETHEIA_DB_URL"] = args.db_url

    stats = asyncio.run(
        run_phase3_ingest(
            Path(args.marina_path),
            chunk_size=args.chunk_size,
            overlap=args.chunk_overlap,
            dry_run=args.dry_run,
            seed_phase3=bool(args.seed_phase3),
            fetch_urls=bool(args.fetch_urls),
            max_docs=args.max_docs,
            materialize_embeddings=bool(args.materialize_embeddings),
        )
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
