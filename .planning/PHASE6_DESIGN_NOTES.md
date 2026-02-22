# Phase 6: Backend Redesign & I/O Pipeline — Design Notes

Captured during Phase 5 planning session (Feb 22, 2026). These notes preserve
research and decisions for the next session.

---

## Core Vision

Aletheia is a retrieval/crawling/analysis powerhouse. Every capability —
searching, crawling, retrieving, semantically analyzing, caching, indexing,
knowledge graphs — is core, not optional. The backend must support:

- Text storage (raw documents, claims, verdicts)
- Vector embeddings (semantic search)
- Knowledge graphs (claim → evidence → source relationships)
- SQL queries (structured data, metrics, stats)
- Caching and persistence (intermediate results, embeddings)
- Batch processing (multiple claims, corpus ingestion)

---

## pgai Research Summary

### What pgai IS (three-layer stack)

| Layer | Extension | Role |
|---|---|---|
| Foundation | pgvector | Vector data type, cosine/L2/IP similarity, IVFFlat + HNSW indexes |
| Performance | pgvectorscale | StreamingDiskANN (disk-based, exceeds-RAM), Statistical Binary Quantization |
| Orchestration | pgai | Python lib + vectorizer-worker + SQL functions for LLM API calls |

### pgai Vectorizer Pipeline (5 stages)

1. **Loading** — S3 URIs, HTTPS endpoints, BYTEA columns, local file paths
2. **Parsing** — pymupdf, docling, auto-detect (PDF, Markdown, DOCX, XLSX, EPUB, HTML)
3. **Chunking** — Recursive character splitter with configurable size/overlap
4. **Formatting** — Template-based formatting before embedding
5. **Embedding** — Async, queue-based, exactly-once semantics, auto-retry

Key: Application writes are never blocked by embedding API calls. Worker runs
separately, polls internal queue, processes in batches.

### pgai Embedding Providers

- First-party: Ollama (local), OpenAI, Voyage AI
- Via LiteLLM: Cohere, Hugging Face, Mistral, Azure OpenAI, AWS Bedrock, Vertex AI

### pgai Semantic Catalog (text-to-SQL)

- Introspects schema, generates NL descriptions for tables/columns/functions
- Stores descriptions so LLMs can generate accurate SQL from natural language
- 27% improvement in SQL generation accuracy in early tests
- Install: `pip install pgai[semantic-catalog]`

### What pgai CANNOT Do

- No knowledge graphs (need Apache AGE)
- No web crawling (need crawl4ai externally, feed results into Postgres)
- No full-text search (native Postgres tsvector/tsquery)
- No graph traversal or relationship modeling
- No reranking (can call Cohere rerank via in-DB LLM functions)
- No agentic orchestration

### pgai Vectorizer Worker

- Docker image: `timescale/pgai-vectorizer-worker`
- Stateless Python process, polls internal queue
- Horizontally scalable (multiple workers coordinate through DB)
- Could replace custom `aletheia/ingest.py` embedding pipeline
- No crawl4ai integration — crawling must happen first, store content in PG,
  then vectorizer processes it

---

## Knowledge Graphs: Apache AGE

pgai has ZERO knowledge graph support. For graph capabilities:

**Apache AGE** — PostgreSQL extension for graph databases:
- openCypher query language alongside standard SQL
- Property graph model (nodes + edges)
- ACID transactions, MVCC
- PostgreSQL 11–18
- Apache Software Foundation, actively maintained
- GitHub: apache/age

**pgai + Apache AGE coexist** in the same Postgres instance. Complementary,
not overlapping. pgai handles vectors/embeddings, AGE handles graph traversal.

---

## Database Image Decision (deferred)

### Options Evaluated

| Image | Size | Includes | Notes |
|---|---|---|---|
| pgvector/pgvector:pg16 | ~400MB | pgvector only | Current. Minimal. |
| ankane/pgvector:pg17 | ~450MB | pgvector, PG17 | Newer PG, same footprint |
| timescale/timescaledb-ha:pg17 | ~1.5GB | pgvector + pgvectorscale + pgai ext + TimescaleDB + plpython3u | Everything pre-installed |

### User Preference

1.5GB feels too heavy. Explore alternatives:
- Custom Dockerfile from postgres:17-slim adding only pgvector + AGE?
- SurrealDB or other unified backends?
- Vanilla Postgres + pgvector (current) with AGE added?

### pgvectorscale Benefits

- StreamingDiskANN index: 28x lower p95 latency at 99% recall vs Pinecone
- Statistical Binary Quantization: vector compression
- Only available in timescaledb-ha image or built from source

---

## I/O Pipeline Redesign

### Questions to Answer in Phase 6

1. **Inputs**: How does a user pass a corpus of claims for batch checking?
   - File-based (CSV, JSON, text file with one claim per line)?
   - CLI argument list?
   - Interactive session with history?

2. **Document Ingestion**: How does a user feed their knowledge corpus?
   - `aletheia ingest <url-or-file>` — single doc
   - `aletheia ingest --dir ./papers/` — directory scan
   - Watch folder / auto-ingest?
   - What formats: PDF, HTML, Markdown, DOCX?

3. **Intermediate Storage**: Where do embeddings, vectors, graphs live?
   - All in Postgres (pgai vectorizer handles embedding materialization)
   - Knowledge graph in AGE extension
   - Retrieval cache in Postgres tables

4. **Output**: What does Aletheia produce and where?
   - Verdicts: displayed in TUI, cached in DB?
   - Evidence trail: stored per-claim for later retrieval?
   - Export: JSON, PDF report, CSV summary?

5. **Session Persistence**:
   - Can a user close and reopen Aletheia and see past results?
   - Is there a "workspace" concept?
   - How does `aletheia history` or `aletheia results` work?

6. **Batch Mode**:
   - `aletheia batch claims.csv --output results.json`?
   - Progress tracking for long-running batches?
   - Parallel claim processing?

### Current Ingest Pipeline (scripts/ingest_methodology.py)

What it does today (partially implemented):
- Reads URLs from MARINA.md (stale reference)
- Fetches HTML via crawl4ai, PDFs via httpx
- Chunks content (configurable size/overlap)
- Stores chunks in `document_chunks` table
- Optionally materializes pgai embeddings
- Has --dry-run, --max-docs, --timeout, --materialize flags

What needs to change:
- Remove MARINA.md dependency
- Become a proper CLI subcommand (`aletheia ingest`)
- Support local files (PDF, MD, DOCX) not just URLs
- Leverage pgai's built-in URI loading + parsing instead of custom code
- Integrate with knowledge graph (AGE) for relationship modeling
- Support incremental ingestion (don't re-process known docs)

### Current Data Flow

```
User claim → Parser → Router → Evidence Sources → Aggregator → Editor → Verdict
                                      ↓
                            methodology_kb (pgai semantic search)
                            data_api (BLS, Census, Eurostat connectors)
                            document_index (document_chunks table)
                            web_fallback (crawl4ai + web search)
                            paper_scholar (academic search)
```

### Proposed Phase 6 Data Flow (aspirational)

```
User → aletheia ingest <docs>  → pgai vectorizer → embeddings materialized
     → aletheia claim "..."    → pipeline → verdict → stored in DB
     → aletheia batch <file>   → parallel claims → results exported
     → aletheia history        → past verdicts + evidence trails
     → aletheia export <id>    → JSON/PDF report
```

---

## Docker Architecture (decided, implement in Phase 5)

Single `docker-compose.yml` with profiles:
- **Always on**: postgres (pgvector:pg16) + vectorizer-worker
- **Profile "ollama"**: Ollama CPU
- **Profile "gpu"**: Ollama + NVIDIA GPU passthrough
- App runs on host via `uv run aletheia`
- LM Studio discovered via host.docker.internal
- GPU is a HARD REQUIREMENT — no GPU = warn and exit

---

## References

- pgai GitHub: https://github.com/timescale/pgai
- pgai Vectorizer docs: https://github.com/timescale/pgai/blob/main/docs/vectorizer/overview.md
- pgai Document embeddings: https://github.com/timescale/pgai/blob/main/docs/vectorizer/document-embeddings.md
- pgai Releases: https://github.com/timescale/pgai/releases
- Apache AGE: https://age.apache.org/
- Apache AGE GitHub: https://github.com/apache/age
- pgvectorscale: https://github.com/timescale/pgvectorscale
- timescaledb-ha Docker: https://github.com/timescale/timescaledb-docker-ha
- Open WebUI compose patterns: https://github.com/open-webui/open-webui
- Docker Compose profiles: https://docs.docker.com/compose/how-tos/profiles/
- crawl4ai docs: https://docs.crawl4ai.com/core/installation/
