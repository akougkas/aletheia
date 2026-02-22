# Engineering Backlog — Next Iterations

> Internal planning doc for Anthony + Claude. Not team-facing.
> These are implementation iterations within ROADMAP Phases 2 and 3.
> Last updated: 2026-02-22

---

## Iteration 2.x: Wire `aletheia ingest` CLI

**Phase**: 2 (Flexibility & Scale) — making existing capability accessible.
**Priority**: High — needed before demo day and open source release.
**Effort**: Small — the backend code exists, just needs CLI plumbing.

### What exists today

`aletheia/ingest.py` already has:
- `ingest_marina_corpus()` — parses MARINA.md knowledge lists, indexes summaries
- `ingest_reference_urls()` — fetches HTML/PDF from methodology URLs, chunks, stores
- `ingest_local_directory()` — scans a dir for PDF/MD/TXT/HTML files
- `seed_phase3_methodology_breaks()` — inserts 40 PH3-xxx break records
- `run_phase3_ingest()` — orchestrates all of the above with flags
- `_extract_pdf_text()`, `_extract_html_text()` — content extraction
- Full `main()` with argparse (invoked via `python -m aletheia.ingest`)

### What's missing

The `aletheia ingest` CLI subcommand is a stub ("not yet implemented").
Need to wire it to the existing `ingest.py` functions.

### Proposed subcommands

```
aletheia ingest url <url>              # Single URL (HTML or PDF)
aletheia ingest dir <path>             # Directory of local files
aletheia ingest marina                 # Parse MARINA.md knowledge lists
aletheia ingest --materialize          # Also run vectorizer after ingest
aletheia ingest --dry-run              # Preview without DB writes
```

### Files to change
- `cli.py` — replace ingest stub with real subcommand parser + handlers
- No changes to `aletheia/ingest.py` — it's already functional

---

## Iteration 3.x: pgai Vectorizer Upgrade

**Phase**: 3 (Intelligence Layer) — improving the knowledge engine.
**Priority**: Medium — optimization, not new capability.
**Effort**: Medium — requires understanding pgai's vectorizer stages.

### Current state

Custom embedding pipeline in `aletheia/ingest.py` + `aletheia/vectorizer.py`:
- Manual chunking (character-based splitter)
- Manual embedding materialization via pgai SQL functions
- Works, but doesn't leverage pgai's built-in document processing

### What pgai vectorizer offers

5-stage pipeline: Loading → Parsing → Chunking → Formatting → Embedding
- Built-in PDF/DOCX/HTML parsing (pymupdf, docling)
- Async queue-based embedding (never blocks writes)
- Exactly-once semantics, auto-retry
- Ollama embedding provider (first-party support)

### Trade-off

Replacing custom code with pgai's pipeline means:
- Less code to maintain
- Better PDF/DOCX parsing (docling > our pypdf fallback)
- But: pgai vectorizer doesn't do web crawling — crawl4ai stays external
- And: we lose fine-grained control over chunking strategy

### Decision needed

Is the chunking quality difference worth the migration effort?
Profile current embedding quality on eval harness before deciding.

---

## Future: Knowledge Graphs (Apache AGE)

**Phase**: Undecided — potentially Phase 3 or Phase 4 paper contribution.
**Priority**: Low — aspirational, not required for current capabilities.
**Effort**: Large — new extension, new query language (openCypher).

### What it would add

Graph-based relationships: claim → evidence → source → methodology_change
- Traversal queries ("what other claims are affected by this break?")
- Provenance chains (full audit trail as a graph)
- Cross-claim correlation detection

### Blockers

- Requires DB image change (Apache AGE extension not in pgvector:pg16)
- Options: custom Dockerfile, timescaledb-ha (1.5GB, too heavy), or postgres:17-slim + pgvector + AGE
- No urgent use case — current SQL schema handles eval harness fine

### Decision

Defer until paper writing reveals a need for graph queries.

---

## Future: Batch Mode & Session History

**Phase**: 2 (Flexibility & Scale) — if/when needed.
**Priority**: Low.

### Concepts

```
aletheia batch claims.csv --output results.json
aletheia history                    # Past verdicts
aletheia export <run-id>            # JSON/PDF report
```

### Decision

Not needed for demo day or paper. Revisit when evaluation workflow demands it.

---

## DB Image Decision

### Options

| Image | Size | Includes |
|---|---|---|
| pgvector/pgvector:pg16 | ~400MB | pgvector only (current) |
| ankane/pgvector:pg17 | ~450MB | pgvector, PG17 |
| timescale/timescaledb-ha:pg17 | ~1.5GB | Everything (too heavy) |
| Custom: postgres:17-slim + pgvector + AGE | ~500MB? | Only what we need |

### Decision

Stay on pgvector:pg16 until AGE is needed. Then build custom slim image.

---

## Research References

- pgai GitHub: https://github.com/timescale/pgai
- pgai Vectorizer docs: https://github.com/timescale/pgai/blob/main/docs/vectorizer/overview.md
- pgai Document embeddings: https://github.com/timescale/pgai/blob/main/docs/vectorizer/document-embeddings.md
- Apache AGE: https://age.apache.org/
- pgvectorscale: https://github.com/timescale/pgvectorscale
- crawl4ai docs: https://docs.crawl4ai.com/core/installation/
