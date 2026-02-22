# SurrealDB Migration Plan

> Decision made: 2026-02-22. Execute in next session(s).
> This replaces the pgai/vectorizer sections of NEXT_ENGINEERING.md.

---

## Research Summary (completed)

Evaluated 6 options: PostgreSQL+AGE, SurrealDB, ArangoDB, Neo4j, Gel/EdgeDB, FalkorDB.
Decision: **SurrealDB 3.0** (released Feb 17, 2026).

### Why SurrealDB wins for Aletheia

| Factor | PostgreSQL stack | SurrealDB |
|--------|-----------------|-----------|
| Containers | 3 (postgres, pgai-worker, ollama) | 1 (+ ollama) |
| Graph queries | CTE workarounds with AGE | Native `->edge->node` syntax |
| Vector search | pgvector (extension) | Built-in HNSW |
| Document storage | JSONB columns | Native document model |
| Schema | Rigid SQL DDL | Schemaful or schemaless per table |
| Embedding | pgai async worker (separate container) | `http::post()` to Ollama or batch |
| Session/audit | SQL tables | Same, but with graph edges for provenance |
| Python driver | psycopg3 (mature) | surrealdb SDK (async, adequate) |

### Scale Requirements

Aletheia is NOT a toy demo. The storage model must handle real-world research workloads:

| Scale tier | Papers | Chunks (est) | Vector RAM (F32, 4096d) | HNSW RAM (~2x) |
|------------|--------|--------------|------------------------|-----------------|
| Dev/test (current) | ~50 | ~500 | 8 MB | ~16 MB |
| Single study | 500 | 5K | 80 MB | ~160 MB |
| Multi-domain corpus | 5,000 | 50K | 800 MB | ~1.6 GB |
| Full deployment | 10,000+ | 100K+ | 1.6 GB+ | ~3.2 GB+ |
| Research lab scale | 50,000+ | 500K+ | 8 GB+ | ~16 GB+ |

**Memory budget on zbook (32GB):** Ollama ~8GB + OS ~4GB = 20GB available for SurrealDB.
At 4096-dim F32, comfortable up to ~100K chunks. Beyond that, options:
- Reduce to F16 type (halves RAM, negligible quality loss for cosine similarity)
- Reduce embedding dimensions (1536 or 2048 — most models support truncation)
- Deploy on a beefier machine

**Design implications:**
- All indexes must be designed for 100K+ records, not 500
- Batch embedding must support progress tracking and resumability
- Session/audit tables accumulate over time — need cleanup/archival strategy
- Graph traversal at scale needs explicit indexes on edge properties
- Ingestion pipeline must handle thousands of PDFs efficiently (parallelism, error recovery)

### Constraints to design around

1. **HNSW is in-memory** — vector index cached in RAM. Configurable via `SURREAL_HNSW_CACHE_SIZE`.
   Use F32 at 4096-dim for up to ~100K chunks. Consider F16 or lower dims for larger corpora.
2. **Synchronous embedding on insert** — Don't use `DEFAULT fn::embed()` for bulk ingestion.
   Instead: insert text first, then batch-embed via Python (call Ollama, update records).
   Must support: progress tracking, resumability, parallelism for large corpora.
3. **No JOINs** — use record links and arrow traversal instead.
4. **Transactions require WebSocket** — use `ws://` connection URI.
5. **Python SDK** — `surrealdb` PyPI package, v1.0.8. Has `AsyncSurreal` class.
6. **RocksDB on disk** — data persistence is disk-based (LSM-tree). Handles large datasets well.
   Only the HNSW vector index is in-memory; all other data is on disk.

### Embedding Dimension Strategy

Current: `qwen3-embedding:8b` at 4096 dimensions. This is configurable:
- `ALETHEIA_EMBED_DIM` env var controls dimension
- Most embedding models support Matryoshka truncation (truncate to 1536 or 2048 with
  minimal quality loss for similarity search)
- The HNSW DIMENSION in schema must match the configured embedding dimension
- Schema init script should read dimension from config, not hardcode 4096

---

## Data Model (SurrealQL Schema)

```surql
-- =============================================
-- NAMESPACE & DATABASE
-- =============================================
DEFINE NAMESPACE aletheia;
USE NS aletheia;
DEFINE DATABASE main;
USE DB main;

-- =============================================
-- TABLES (Structured Data)
-- =============================================

-- Statistical agencies (BLS, Census, Eurostat, etc.)
DEFINE TABLE agency SCHEMAFULL;
DEFINE FIELD code ON agency TYPE string ASSERT $value != NONE;
DEFINE FIELD name ON agency TYPE string ASSERT $value != NONE;
DEFINE FIELD country ON agency TYPE option<string>;
DEFINE FIELD url ON agency TYPE option<string>;
DEFINE INDEX idx_agency_code ON agency FIELDS code UNIQUE;

-- Datasets (CPS, NHIS, EU-LFS, etc.)
DEFINE TABLE dataset SCHEMAFULL;
DEFINE FIELD code ON dataset TYPE string ASSERT $value != NONE;
DEFINE FIELD name ON dataset TYPE string ASSERT $value != NONE;
DEFINE FIELD description ON dataset TYPE option<string>;
DEFINE FIELD frequency ON dataset TYPE option<string>;
DEFINE INDEX idx_dataset_code ON dataset FIELDS code UNIQUE;

-- Dataset versions (time-bounded releases)
DEFINE TABLE dataset_version SCHEMAFULL;
DEFINE FIELD version_code ON dataset_version TYPE string;
DEFINE FIELD effective_start ON dataset_version TYPE option<datetime>;
DEFINE FIELD effective_end ON dataset_version TYPE option<datetime>;
DEFINE FIELD notes ON dataset_version TYPE option<string>;

-- Indicators within datasets
DEFINE TABLE indicator SCHEMAFULL;
DEFINE FIELD code ON indicator TYPE string ASSERT $value != NONE;
DEFINE FIELD name ON indicator TYPE string ASSERT $value != NONE;
DEFINE FIELD unit ON indicator TYPE option<string>;
DEFINE FIELD description ON indicator TYPE option<string>;

-- Methodology changes (the core knowledge entity)
DEFINE TABLE methodology_change SCHEMAFULL;
DEFINE FIELD benchmark_case_id ON methodology_change TYPE option<string>;
DEFINE FIELD change_type ON methodology_change TYPE string ASSERT $value != NONE;
DEFINE FIELD effective_date ON methodology_change TYPE option<datetime>;
DEFINE FIELD description ON methodology_change TYPE string ASSERT $value != NONE;
DEFINE FIELD impact_estimate ON methodology_change TYPE option<string>;
DEFINE FIELD severity ON methodology_change TYPE option<string>;
DEFINE FIELD comparability ON methodology_change TYPE option<string>;
DEFINE FIELD is_documented ON methodology_change TYPE bool DEFAULT true;
DEFINE FIELD source_url ON methodology_change TYPE option<string>;
DEFINE FIELD created_at ON methodology_change TYPE datetime DEFAULT time::now();
DEFINE FIELD embedding ON methodology_change TYPE option<array<float>>;
DEFINE INDEX idx_change_case ON methodology_change FIELDS benchmark_case_id UNIQUE;
DEFINE INDEX idx_change_date ON methodology_change FIELDS effective_date;
DEFINE INDEX idx_change_type ON methodology_change FIELDS change_type;
-- NOTE: HNSW DIMENSION must match ALETHEIA_EMBED_DIM (default 4096).
-- Schema init script should parameterize this value.
DEFINE INDEX idx_change_embedding ON methodology_change
  FIELDS embedding HNSW DIMENSION 4096 DIST COSINE TYPE F32;

-- Source documents (methodology PDFs, release notes, papers)
DEFINE TABLE document SCHEMAFULL;
DEFINE FIELD title ON document TYPE string ASSERT $value != NONE;
DEFINE FIELD doc_type ON document TYPE option<string>;
DEFINE FIELD url ON document TYPE option<string>;
DEFINE FIELD publication_date ON document TYPE option<datetime>;
DEFINE FIELD content_hash ON document TYPE option<string>;
DEFINE FIELD summary ON document TYPE option<string>;
DEFINE FIELD agency_code ON document TYPE option<string>;
DEFINE FIELD created_at ON document TYPE datetime DEFAULT time::now();
DEFINE INDEX idx_doc_hash ON document FIELDS content_hash UNIQUE;

-- Document chunks for semantic search
DEFINE TABLE chunk SCHEMAFULL;
DEFINE FIELD chunk_index ON chunk TYPE int;
DEFINE FIELD content ON chunk TYPE string ASSERT $value != NONE;
DEFINE FIELD metadata ON chunk TYPE option<object>;
DEFINE FIELD embedding ON chunk TYPE option<array<float>>;
-- NOTE: DIMENSION must match ALETHEIA_EMBED_DIM. Parameterize in init script.
DEFINE INDEX idx_chunk_embedding ON chunk
  FIELDS embedding HNSW DIMENSION 4096 DIST COSINE TYPE F32;
-- Full-text search index for lexical fallback
DEFINE ANALYZER chunk_analyzer TOKENIZERS blank, class FILTERS lowercase, snowball(english);
DEFINE INDEX idx_chunk_fulltext ON chunk FIELDS content
  SEARCH ANALYZER chunk_analyzer BM25;

-- Analysis sessions (replaces retrieval_runs)
DEFINE TABLE session SCHEMAFULL;
DEFINE FIELD query_hash ON session TYPE string;
DEFINE FIELD claim_text ON session TYPE string;
DEFINE FIELD claim_dataset ON session TYPE option<string>;
DEFINE FIELD claim_indicator ON session TYPE option<string>;
DEFINE FIELD claim_type ON session TYPE option<string>;
DEFINE FIELD status ON session TYPE string DEFAULT 'running';
DEFINE FIELD verdict ON session TYPE option<object>;
DEFINE FIELD metadata ON session TYPE option<object>;
DEFINE FIELD started_at ON session TYPE datetime DEFAULT time::now();
DEFINE FIELD completed_at ON session TYPE option<datetime>;
DEFINE FIELD error_text ON session TYPE option<string>;
DEFINE INDEX idx_session_hash ON session FIELDS query_hash;
DEFINE INDEX idx_session_time ON session FIELDS started_at;

-- Batch runs (for MethodBench evaluation)
DEFINE TABLE batch SCHEMAFULL;
DEFINE FIELD name ON batch TYPE string;
DEFINE FIELD status ON batch TYPE string DEFAULT 'pending';
DEFINE FIELD total_claims ON batch TYPE int DEFAULT 0;
DEFINE FIELD completed_claims ON batch TYPE int DEFAULT 0;
DEFINE FIELD started_at ON batch TYPE datetime DEFAULT time::now();
DEFINE FIELD completed_at ON batch TYPE option<datetime>;
DEFINE FIELD results ON batch TYPE option<object>;

-- =============================================
-- GRAPH EDGES (Relationships)
-- =============================================

-- agency --publishes--> dataset
DEFINE TABLE publishes SCHEMAFULL TYPE RELATION IN agency OUT dataset;

-- dataset --has_version--> dataset_version
DEFINE TABLE has_version SCHEMAFULL TYPE RELATION IN dataset OUT dataset_version;

-- dataset --has_indicator--> indicator
DEFINE TABLE has_indicator SCHEMAFULL TYPE RELATION IN dataset OUT indicator;

-- methodology_change --affects--> indicator
DEFINE TABLE affects SCHEMAFULL TYPE RELATION
  IN methodology_change OUT indicator;
DEFINE FIELD impact_direction ON affects TYPE option<string>;
DEFINE FIELD impact_magnitude ON affects TYPE option<string>;

-- methodology_change --belongs_to--> dataset
DEFINE TABLE belongs_to SCHEMAFULL TYPE RELATION
  IN methodology_change OUT dataset;

-- document --describes--> methodology_change
DEFINE TABLE describes SCHEMAFULL TYPE RELATION
  IN document OUT methodology_change;
DEFINE FIELD relevance_score ON describes TYPE option<float>;

-- chunk --part_of--> document
DEFINE TABLE part_of SCHEMAFULL TYPE RELATION IN chunk OUT document;

-- session --found--> document (evidence discovered during analysis)
DEFINE TABLE found SCHEMAFULL TYPE RELATION IN session OUT document;
DEFINE FIELD source_id ON found TYPE option<string>;
DEFINE FIELD relevance_score ON found TYPE option<float>;
DEFINE FIELD confidence_score ON found TYPE option<float>;
DEFINE FIELD is_cached ON found TYPE bool DEFAULT false;
DEFINE FIELD rank ON found TYPE option<int>;

-- session --part_of_batch--> batch
DEFINE TABLE part_of_batch SCHEMAFULL TYPE RELATION IN session OUT batch;
```

### Example Graph Queries

```surql
-- "What methodology changes affect the unemployment rate?"
SELECT * FROM methodology_change
WHERE ->affects->indicator.code CONTAINS 'unemployment_rate';

-- "What other indicators are affected by the same change?"
SELECT ->affects->indicator.* FROM methodology_change:ph3_001;

-- "Full provenance: session → evidence → methodology change → dataset → agency"
SELECT
  ->found->document<-describes<-methodology_change
    ->belongs_to->dataset<-publishes<-agency.*
FROM session:abc123;

-- "Semantic search on document chunks"
LET $qvec = <embedding from Ollama>;
SELECT id, content, vector::distance::knn() AS dist
FROM chunk
WHERE embedding <|5|> $qvec
ORDER BY dist;

-- "Semantic search on methodology changes"
SELECT id, description, change_type, effective_date,
       vector::distance::knn() AS dist
FROM methodology_change
WHERE embedding <|5|> $qvec
ORDER BY dist;

-- "All claims in a batch with their verdicts"
SELECT <-part_of_batch<-session.{claim_text, verdict, status}
FROM batch:eval_run_1;
```

---

## Execution Plan

### Phase 1: Infrastructure (do first)

**Files to create/modify:**

1. **`docker-compose.yml`** — Replace postgres + vectorizer-worker services with surrealdb
   ```yaml
   services:
     surrealdb:
       image: surrealdb/surrealdb:latest
       command: start rocksdb:/data/aletheia.db --user root --pass root --bind 0.0.0.0:8000
       ports:
         - "8000:8000"
       volumes:
         - aletheia_surreal_data:/data
       restart: unless-stopped
     # ollama stays as-is (profiles: ollama, gpu)
   ```

2. **`surql/init.surql`** — Full schema definition (the SurrealQL above)
   - Replaces `sql/init.sql`
   - Applied via: `surreal import --conn ws://localhost:8000 --ns aletheia --db main surql/init.surql`

3. **`aletheia/db.py`** — Rewrite for SurrealDB connection management
   - Replace `psycopg` imports with `surrealdb` SDK
   - Connection factory: `AsyncSurreal` with WebSocket URI
   - Connection pool/singleton pattern
   - Keep `get_connection()` as the public API (same interface, different backend)
   - Keep `get_db_url()` reading from env/config but returning WS URL
   - `diagnose_connection_failure()` updated for SurrealDB health check

4. **`.env`** — Update DB config
   ```
   ALETHEIA_DB_URL=ws://localhost:8000
   ALETHEIA_DB_NS=aletheia
   ALETHEIA_DB_NAME=main
   ALETHEIA_DB_USER=root
   ALETHEIA_DB_PASS=root
   ```

5. **`pyproject.toml`** — Replace `psycopg[binary]` with `surrealdb` in dependencies

**Verify:** `docker compose up -d surrealdb` → connect with SDK → run schema init → check tables exist.

### Phase 2: Core DB Layer

**Files to modify:**

6. **`aletheia/ingest.py`** — Rewrite DB operations
   - Replace all `psycopg.connect()` + SQL with SurrealDB SDK calls
   - Replace `INSERT INTO documents` → `CREATE document SET ...`
   - Replace `INSERT INTO document_chunks` → `CREATE chunk SET ...` + `RELATE chunk:X->part_of->document:Y`
   - `_upsert_document()` → `UPSERT document SET ... WHERE content_hash = $hash`
   - `_upsert_chunks()` → batch `CREATE chunk` + `RELATE`
   - `_ensure_agencies()` → `UPSERT agency SET ... WHERE code = $code`
   - `ingest_single_url()`, `ingest_local_directory()`, `ingest_marina_corpus()` — update DB calls
   - `seed_phase3_methodology_breaks()` → `CREATE methodology_change` + `RELATE`
   - Keep all non-DB logic (fetching, chunking, parsing) unchanged

7. **`aletheia/vectorizer.py`** — Simplify but design for scale
   - No more pgai vectorizer worker setup
   - `create_vectorizers()` → no-op or delete (HNSW indexes defined in schema)
   - `materialize_embeddings()` — redesign for large corpora:
     - Query unembedded records: `SELECT id, content FROM chunk WHERE embedding IS NONE LIMIT $batch_size`
     - Process in configurable batches (default 100, tunable)
     - Call Ollama embed API for each batch
     - `UPDATE chunk:X SET embedding = $vec` per record
     - Track progress: emit count/total to TUI
     - Resumable: if interrupted, next run picks up where it left off (queries NONE embeddings)
     - Concurrent: use asyncio.gather with configurable parallelism for Ollama calls
   - `vectorizer_status()` → `SELECT count() FROM chunk WHERE embedding IS NONE` vs total
   - Target: handle 100K+ chunks in a single run with progress reporting

8. **`aletheia/retrieval_store.py`** — Rewrite for SurrealDB
   - `RetrievalStore.begin_run()` → `CREATE session SET ...`
   - `RetrievalStore.complete_run()` → `UPDATE session:X SET status='completed'`
   - `RetrievalStore.record_document()` → `RELATE session:X->found->document:Y SET ...`
   - `RetrievalStore.find_cached()` → `SELECT ... FROM session WHERE query_hash = $hash`
   - Cache hit metrics → same queries, SurrealQL syntax
   - Discovery indexing → `CREATE document` + `CREATE chunk` + `RELATE`

### Phase 3: Agent Layer

**Files to modify:**

9. **`aletheia/agents/archivist.py`** — Rewrite search queries
   - `semantic_search()` → SurrealDB vector KNN query on chunks
     ```python
     result = await db.query("""
       SELECT id, content, metadata, vector::distance::knn() AS distance
       FROM chunk WHERE embedding <|$limit|> $query_vec
       ORDER BY distance
     """, {"query_vec": embedding, "limit": limit})
     ```
   - `semantic_search_breaks()` → Same pattern on methodology_change table
   - `_search_breaks_by_dataset()` → `SELECT * FROM methodology_change WHERE ->belongs_to->dataset.code = $code`
   - `_hydrate_breaks_by_ids()` → `SELECT * FROM methodology_change WHERE id IN $ids`
   - `_lexical_search()` → SurrealDB full-text search or string matching
   - Add new graph query methods:
     - `provenance_chain(session_id)` → graph traversal query
     - `affected_indicators(change_id)` → `SELECT ->affects->indicator.* FROM methodology_change:$id`

10. **`aletheia/agents/orchestrator.py`** — Update retrieval store calls
    - `get_last_run_details()` → query session table
    - Trace log → update session metadata

### Phase 4: CLI & Tests

**Files to modify:**

11. **`cli.py`** — Update DB-dependent commands
    - `db-doctor` → SurrealDB health check (HTTP `/health` endpoint)
    - `seed` → call updated `seed_phase3_methodology_breaks()` and `ingest_marina_corpus()`
    - `onboarding` → check SurrealDB connectivity instead of PostgreSQL
    - `retrieval-stats` → query session table
    - `ingest` subcommands → already dispatch to ingest.py (auto-updated)
    - Add `batch` subcommand (new):
      ```
      aletheia batch <claims.csv> --output results.json
      ```

12. **`tests/`** — Update all DB-touching tests
    - `test_cli_doctor.py` — mock SurrealDB health check
    - `test_ingest_phase3_unit.py` — update mocks
    - `test_vectorizer_phase3.py` — update for simplified vectorizer
    - `test_cli_ux.py` — ingest tests should still pass (parser-level)
    - Consider: SurrealDB embedded mode (`memory://`) for test isolation

13. **Delete/archive:**
    - `sql/init.sql` → replaced by `surql/init.surql`
    - `sql/seed_cases.sql` → seed logic moves to Python (ingest.py)
    - `sql/validate_seed_cases.sql` → replaced by SurrealQL validation queries

### Phase 5: Batch Mode & Knowledge Graph Queries

14. **Add `aletheia batch` CLI command**
    ```
    aletheia batch claims.csv --output results.json
    aletheia batch --benchmark  # Run all 40 seed cases
    ```
    - Creates a `batch` record
    - Iterates claims, creates `session` per claim, links via `RELATE session:X->part_of_batch->batch:Y`
    - Collects verdicts into structured JSON output

15. **Add graph query CLI command**
    ```
    aletheia graph provenance <session-id>  # Show evidence chain
    aletheia graph impacts <change-id>      # Show affected indicators
    ```

---

## Dependency Changes

### Remove
- `psycopg[binary]`
- `psycopg-pool` (if present)

### Add
- `surrealdb` (PyPI, v1.0.8+)

### Keep
- All other deps unchanged (crawl4ai, httpx, scipy, etc.)

---

## Docker Compose Changes

```yaml
# REMOVE these services:
#   postgres (pgvector/pgvector:pg16)
#   vectorizer-worker (timescale/pgai-vectorizer-worker)

# ADD:
services:
  surrealdb:
    image: surrealdb/surrealdb:latest
    command: start rocksdb:/data/aletheia.db --user root --pass root --bind 0.0.0.0:8000
    ports:
      - "${ALETHEIA_SURREAL_PORT:-8000}:8000"
    volumes:
      - aletheia_surreal_data:/data
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "surreal", "isready", "--conn", "http://localhost:8000"]
      interval: 5s
      timeout: 3s
      retries: 5

  # ollama and ollama-gpu services stay unchanged

volumes:
  aletheia_surreal_data:
  # remove aletheia_pgdata
```

---

## Environment Variables

| Old | New | Notes |
|-----|-----|-------|
| `ALETHEIA_DB_URL=postgresql://...` | `ALETHEIA_DB_URL=ws://localhost:8000` | WebSocket for transactions |
| (none) | `ALETHEIA_DB_NS=aletheia` | SurrealDB namespace |
| (none) | `ALETHEIA_DB_NAME=main` | SurrealDB database |
| (none) | `ALETHEIA_DB_USER=root` | SurrealDB auth |
| (none) | `ALETHEIA_DB_PASS=root` | SurrealDB auth |
| `POSTGRES_*` vars | Remove | No longer needed |

---

## Verification Plan

### After Phase 1 (Infrastructure)
```bash
docker compose up -d surrealdb
surreal import --conn ws://localhost:8000 --user root --pass root \
  --ns aletheia --db main surql/init.surql
# Verify: connect with Python SDK, list tables
```

### After Phase 2 (Core DB)
```bash
uv run aletheia seed              # Seeds methodology breaks + agencies
uv run aletheia db-doctor         # Checks SurrealDB health
uv run aletheia ingest marina     # Ingests MARINA.md corpus
uv run aletheia onboarding        # Full system check
```

### After Phase 3 (Agents)
```bash
uv run aletheia claim "US unemployment dropped sharply in 2020"
# Should: parse → search KB (vector) → fetch data → verdict
```

### After Phase 4 (Tests)
```bash
uv run python -m pytest -v
# Target: all existing test count passing (currently 153)
```

### After Phase 5 (Batch + Graph)
```bash
uv run aletheia batch --benchmark --output eval_results.json
# Should: run all 40 seed cases, output structured results
uv run aletheia graph provenance <session-id>
# Should: show claim → evidence → source → change → dataset → agency
```

---

## Execution Order & Estimates

| Phase | What | Files | Effort |
|-------|------|-------|--------|
| 1 | Infrastructure | docker-compose.yml, surql/init.surql, aletheia/db.py, .env, pyproject.toml | 1 session |
| 2 | Core DB Layer | ingest.py, vectorizer.py, retrieval_store.py | 1-2 sessions |
| 3 | Agent Layer | archivist.py, orchestrator.py | 1 session |
| 4 | CLI & Tests | cli.py, tests/* | 1 session |
| 5 | Batch + Graph | cli.py (batch cmd), new graph queries | 1 session |

---

## Key Design Decisions

1. **Scale-first design**: Schema, indexes, and batch operations designed for 10K+ papers
   (100K+ chunks). Current dev data (~500 chunks) is irrelevant to architecture decisions.

2. **Embedding strategy**: Batch post-insert with progress tracking and resumability.
   Insert text first, then run `materialize_embeddings()` which queries unembedded records
   in batches, calls Ollama with configurable concurrency, and updates. Resumable — queries
   `WHERE embedding IS NONE` each run.

3. **Embedding dimensions**: Configurable via `ALETHEIA_EMBED_DIM` (default 4096).
   Schema init script parameterizes HNSW DIMENSION. Models support Matryoshka truncation
   to 1536/2048 for memory efficiency at scale.

4. **Connection pattern**: WebSocket (`ws://`) for all connections (required for transactions).
   Singleton `AsyncSurreal` instance, similar to current `get_connection()` pattern.

5. **Record IDs**: Use SurrealDB's typed IDs (`agency:bls`, `dataset:cps`, `methodology_change:ph3_001`).
   Human-readable, no auto-increment integers. Simplifies debugging and graph queries.

6. **Graph edges**: All relationships are explicit `RELATE` edges (first-class records with metadata).
   No foreign key columns. The graph IS the schema. This is the paper's contribution —
   provenance chains as first-class graph structures.

7. **Backward compatibility**: CLI interface stays identical. `uv run aletheia` commands unchanged.
   Only the backend changes. Users see no difference.

8. **HNSW memory management**: At scale (100K+ chunks), monitor RAM via `vectorizer_status()`.
   If HNSW exceeds available RAM, either:
   - Reduce `ALETHEIA_EMBED_DIM` to 1536 (4x less RAM)
   - Switch HNSW TYPE from F32 to F16 (2x less RAM)
   - Deploy on a larger machine
   - RocksDB handles all non-vector data on disk — only HNSW is in-memory.
