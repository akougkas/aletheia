"""Ingest methodology and validation documents into the knowledge base."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path

import psycopg

from aletheia.db import DB_URL


KNOWN_METHOD_DOC_URLS = {
    "NHIS 2019 Questionnaire Redesign": "https://www.cdc.gov/nchs/nhis/2019_quest_redesign.htm",
    "BLS COVID 19 Misclassification FAQ": "https://www.bls.gov/cps/employment-situation-covid19-faq-april-2020.pdf",
    "ACS 2020 Experimental Estimates": "https://www.census.gov/programs-surveys/acs/technical-documentation/user-notes/2020.html",
    "CPI Collection Suspension Documentation": "https://www.bls.gov/cpi/covid-19-impact.htm",
    "Eurostat EU LFS 2021 Methodology Change": "https://ec.europa.eu/eurostat/web/lfs/methodology",
    "HICP Imputation Methodology": "https://ec.europa.eu/eurostat/documents/10186/10693286/Guidance-on-the-compilation-of-HICP.pdf",
    "Eurostat Mortality Revision Policy": "https://ec.europa.eu/eurostat/statistics-explained/index.php?title=Excess_mortality_-_statistics",
    "ESA 2010 Implementation Guide": "https://ec.europa.eu/eurostat/web/esa-2010",
    "EU SILC Quality Reports": "https://www.cso.ie/en/releasesandpublications/er/silc/surveyonincomeandlivingconditionssilc2016/",
}


DOMAIN_TO_AGENCY_CODE = {
    "cdc.gov": "CDC",
    "bls.gov": "BLS",
    "census.gov": "CENSUS",
    "ec.europa.eu": "EUROSTAT",
    "ecb.europa.eu": "ECB",
    "cso.ie": "CSO",
}


@dataclass
class CorpusDocument:
    title: str
    doc_type: str
    summary: str
    url: str | None = None
    publication_date: str | None = None
    agency_code: str | None = None


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
        for known_domain, code in DOMAIN_TO_AGENCY_CODE.items():
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
        url = KNOWN_METHOD_DOC_URLS.get(title)
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

    # De-duplicate by URL first, then title/type pair.
    deduped: dict[str, CorpusDocument] = {}
    for doc in docs:
        key = doc.url or f"{doc.doc_type}:{doc.title.lower()}"
        deduped[key] = doc
    return list(deduped.values())


def _upsert_document(cur: psycopg.Cursor, doc: CorpusDocument) -> int:
    if doc.url:
        cur.execute("SELECT id FROM documents WHERE url = %s", (doc.url,))
        row = cur.fetchone()
        if row:
            doc_id = row[0]
            cur.execute(
                """
                UPDATE documents
                SET title = %s,
                    doc_type = %s,
                    agency_id = (SELECT id FROM agencies WHERE code = %s),
                    publication_date = %s
                WHERE id = %s
                """,
                (
                    doc.title,
                    doc.doc_type,
                    doc.agency_code,
                    doc.publication_date,
                    doc_id,
                ),
            )
            return int(doc_id)

    cur.execute(
        """
        SELECT id
        FROM documents
        WHERE title = %s AND doc_type = %s
        ORDER BY id
        LIMIT 1
        """,
        (doc.title, doc.doc_type),
    )
    row = cur.fetchone()
    if row:
        return int(row[0])

    cur.execute(
        """
        INSERT INTO documents (title, doc_type, agency_id, url, publication_date)
        VALUES (%s, %s, (SELECT id FROM agencies WHERE code = %s), %s, %s)
        RETURNING id
        """,
        (doc.title, doc.doc_type, doc.agency_code, doc.url, doc.publication_date),
    )
    return int(cur.fetchone()[0])


def _upsert_chunks(
    cur: psycopg.Cursor,
    doc_id: int,
    chunks: list[str],
    metadata: dict[str, str],
) -> None:
    metadata_json = json.dumps(metadata)
    for idx, chunk in enumerate(chunks):
        cur.execute(
            """
            INSERT INTO document_chunks (document_id, chunk_index, content, metadata)
            VALUES (%s, %s, %s, %s::jsonb)
            ON CONFLICT (document_id, chunk_index) DO UPDATE
            SET content = EXCLUDED.content,
                metadata = EXCLUDED.metadata
            """,
            (doc_id, idx, chunk, metadata_json),
        )

    # Remove stale chunks when source text gets shorter.
    cur.execute(
        """
        DELETE FROM document_chunks
        WHERE document_id = %s AND chunk_index >= %s
        """,
        (doc_id, len(chunks)),
    )


def ingest_marina_corpus(
    marina_path: Path,
    *,
    chunk_size: int = 1000,
    overlap: int = 150,
    dry_run: bool = False,
) -> dict[str, int]:
    docs = parse_marina_file(marina_path)
    stats = {"documents_seen": len(docs), "documents_written": 0, "chunks_written": 0}

    if dry_run:
        return stats

    with psycopg.connect(DB_URL) as conn:
        with conn.cursor() as cur:
            for doc in docs:
                doc_id = _upsert_document(cur, doc)
                chunk_text = (
                    f"{doc.title}\n\n{doc.summary}\n\nSource URL: {doc.url or 'n/a'}"
                )
                chunks = _chunk_text(chunk_text, chunk_size, overlap)
                if not chunks:
                    continue
                _upsert_chunks(
                    cur,
                    doc_id,
                    chunks,
                    metadata={"source": "MARINA.md", "doc_type": doc.doc_type},
                )
                stats["documents_written"] += 1
                stats["chunks_written"] += len(chunks)
        conn.commit()

    return stats


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Ingest Marina methodology notes and papers into the KB."
    )
    parser.add_argument(
        "--marina-path",
        default="MARINA.md",
        help="Path to MARINA.md",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=1000,
        help="Character chunk size.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=150,
        help="Character overlap between chunks.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Parse and report counts without writing to DB.",
    )
    args = parser.parse_args()

    stats = ingest_marina_corpus(
        Path(args.marina_path),
        chunk_size=args.chunk_size,
        overlap=args.chunk_overlap,
        dry_run=args.dry_run,
    )
    print(json.dumps(stats, indent=2))


if __name__ == "__main__":
    main()
