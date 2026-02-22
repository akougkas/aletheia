# Engineering Next Steps

> Internal planning doc for Anthony + Claude. Not team-facing.
> Consolidates NEXT_ENGINEERING.md and SURREALDB_MIGRATION.md.
> Last updated: 2026-02-22

---

## What's Done

Everything below is complete and committed. Listed here for context only.

| Area | Status | Key commit |
|------|--------|------------|
| SurrealDB migration (phases 1-4) | Complete | All code ported from PostgreSQL |
| Data extraction to YAML | Complete | `data/*.yaml` + `aletheia/data_loader.py` |
| `aletheia ingest {url,dir,marina}` | Complete | CLI fully wired to ingest.py |
| `aletheia batch --benchmark` | Basic wiring | Reads data_loader, runs claims |
| `aletheia graph {provenance,impacts}` | Basic wiring | Raw SurrealQL output |
| 168 tests passing | Clean | 0 failures |

---

## Cleanup (5 min, do first)

Delete dead artifacts from the PostgreSQL era:

- `tests/integration/test_live_seed_db.py` — imports `psycopg`, will never pass
- `.planning/NEXT_ENGINEERING.md` — superseded by this file
- `.planning/SURREALDB_MIGRATION.md` — execution plan complete, reference below

Verify: `uv run python -m pytest tests/ -v` still 168 passed.

---

## Next: Batch Mode Hardening (case-centric update)

**What works now:** `aletheia batch --benchmark` and `aletheia batch claims.csv`
create `batch` records, update progress, and emit structured output.

**What it should do:**

1. Create a `batch` record in SurrealDB on start
2. Each claim creates a `session`; case-level linking remains:
   - `case ->has_session-> session`
   - `case ->has_batch-> batch`
3. TUI progress bar: `[12/40] PH3-012 NHIS e-cigarette...`
4. On completion: update `batch.completed_at`, `batch.results` with summary stats
5. `aletheia batch --benchmark --output eval.json` writes structured results
6. `aletheia batch claims.csv` reads user-provided claim file (one per line or CSV)

**Schema support:** Already in `surql/init.surql` (`batch`, `session`, `case`,
`has_session`, `has_batch`).

**Files:** `cli.py` (`_run_batch` function — extend existing).

---

## Next: Graph Query Enrichment

**What works now:** `graph provenance` and `graph impacts` render readable tables,
and `graph timeline <dataset-code>` provides chronology by dataset.

**What it should do:**

1. `graph provenance` — render as a readable chain:
   ```
   Session → Evidence docs → Methodology changes → Datasets → Agencies
   ```
   Use `ui.table()` or a tree view, not raw JSON.

2. `graph impacts` — render as a table:
   ```
   Change: PH3-016 EU-LFS definition change (2021-01-01)
   Affects: EU_UNEMPLOYMENT (decrease, ~0.3-0.4pp)
   Dataset: EU-LFS (EUROSTAT)
   ```

3. Expand the queries from "single hop report" to "oracle graph" views that expose:
   - prior verifications
   - ingestion provenance
   - relation confidence metadata
   - cross-case recall paths

**Files:** `cli.py` (graph rendering), possibly `aletheia/agents/archivist.py` (new query methods).

---

## Next: Session History & Export

Superseded by `case history` and `case export` for the case-centric workflow.

---

## Graph Oracle Phase (Incremental)

Build the knowledge graph as an operational "Aletheia brain" across three surfaces.

### 1) Backend Infrastructure

- Preserve strict write-time graph integrity (records + required RELATE edges).
- Add repair commands for legacy records, but keep read paths graph-first.
- Enrich edge metadata over time (confidence, source quality, ingest run IDs).

### 2) Human Infrastructure (UX/UI)

- Keep case-centric operator journey clear:
  - create case
  - run claim/batch with `--case`
  - review case history/export
  - inspect graph provenance/impacts/timeline
- Output should be concise for command-line use and readable in plain mode.

### 3) Agent Infrastructure

- Archivist remains the graph query layer for CLI + orchestrator use.
- Orchestrator/editor should progressively consume richer graph context:
  - prior methodology findings
  - source lineage
  - similar-case retrieval hooks
- Keep all query methods deterministic and testable for reproducibility.

```
aletheia history                    # Recent verdicts from session table
aletheia export <session-id>       # JSON/PDF report for a single analysis
```

**Schema support:** Already in `surql/init.surql` (session table with verdict field).

---

## Optimization: Scale & Embedding Strategy

These aren't blocking but matter as corpus grows past dev/test size (~500 chunks).

### Embedding Dimension Tuning

Current: `qwen3-embedding:8b` at 4096 dimensions, F32.

| Chunks | F32/4096d RAM | F32/1536d RAM | F16/4096d RAM |
|--------|--------------|--------------|--------------|
| 500 | 16 MB | 6 MB | 8 MB |
| 50K | 1.6 GB | 600 MB | 800 MB |
| 100K | 3.2 GB | 1.2 GB | 1.6 GB |

**Action when needed:** Set `ALETHEIA_EMBED_DIM=1536` for 4x RAM reduction.
Most models support Matryoshka truncation with negligible quality loss for cosine similarity.
Requires re-running `materialize_embeddings` and schema HNSW DIMENSION update.

### Chunking Strategy

Current: character-based splitter (fixed window + overlap). Works fine for eval harness
(98% accuracy). Not worth changing unless quality drops on larger, more diverse corpora.

Potential improvement: sentence-aware splitting or semantic chunking. Profile against
eval harness before investing effort.

### Batch Embedding Performance

Current: sequential calls to Ollama. For 100K+ chunks, add:
- Configurable batch size (`ALETHEIA_EMBED_BATCH_SIZE`, default 100)
- `asyncio.gather` with concurrency limit for parallel Ollama calls
- Progress callback to TUI spinner

Already partially designed in `vectorizer.py` — just needs the concurrency layer.

---

## SurrealDB Architecture Reference

Kept here as a condensed reference. Full original in git history.

### Why SurrealDB

Single container replaces PostgreSQL + pgai-worker + pgvector. Native graph edges
(`RELATE`), built-in HNSW vector search, document model. Python SDK: `AsyncSurreal`
over WebSocket.

### Connection

```
ALETHEIA_DB_URL=ws://localhost:8000
ALETHEIA_DB_NS=aletheia
ALETHEIA_DB_NAME=main
ALETHEIA_DB_USER=root
ALETHEIA_DB_PASS=root
```

### Key Design Decisions

1. **Graph edges as first-class records.** All relationships are `RELATE` edges with
   metadata (impact_direction, relevance_score, etc.). The graph IS the schema.

2. **Batch post-insert embedding.** Insert text first, then `materialize_embeddings()`
   queries `WHERE embedding IS NONE` in batches. Resumable by design.

3. **HNSW in-memory, data on disk.** RocksDB handles persistence. Only vector indexes
   consume RAM. Monitor via `vectorizer_status()`.

4. **Configurable embedding dimensions.** `ALETHEIA_EMBED_DIM` (default 4096). Schema
   HNSW DIMENSION must match. Matryoshka truncation supported for memory efficiency.

### Schema

Lives in `surql/init.surql`. Applied via `bootstrap.py:apply_schema()`.

Tables: agency, dataset, dataset_version, indicator, methodology_change, document,
chunk, session, batch.

Edges: publishes, has_version, has_indicator, affects, belongs_to, describes,
part_of, found, part_of_batch.

### Example Queries

```surql
-- Methodology changes affecting an indicator
SELECT * FROM methodology_change
WHERE ->affects->indicator.code CONTAINS 'UNEMPLOYMENT_RATE';

-- Full provenance chain
SELECT ->found->document<-describes<-methodology_change
  ->belongs_to->dataset<-publishes<-agency.*
FROM session:abc123;

-- Semantic search
SELECT id, content, vector::distance::knn() AS dist
FROM chunk WHERE embedding <|5|> $qvec ORDER BY dist;
```
