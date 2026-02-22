# ALETHEIA Roadmap

> Last updated: 2026-02-21

## Demo Day Target (Upcoming Thursday: Feb 26, 2026)

**Goal**: Demonstrate end-to-end autonomous claim validation for Macro-Economic & Public Health Official Statistics.

**Success criteria**:
- [ ] User submits a claim → system autonomously validates → returns verdict with sources
- [ ] System successfully fetches official time-series data and proves structural methodology breaks mathematically
- [ ] System retrieves and explicitly cites the corresponding methodology PDFs
- [ ] Clear narrative connecting rigorous econometric tests to LLM-driven claim validation

---

## Phase 1: Foundation ✅

**Status**: Complete

| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL + pgvector | ✅ Done | Running in Docker |
| Database schema | ✅ Done | Agencies, datasets, indicators, methodology_changes, documents |
| LLM client (llama.cpp) | ✅ Done | Connects to mini:8080 |
| Claim Parser agent | ✅ Done | Extracts structured claims from natural language |
| Archivist agent | ✅ Done | Queries MARINA graph for methodology breaks |
| Analyst agent | ✅ Done | Live connectors for BLS/FRED/Census/Eurostat/ECB |
| Editor agent | ✅ Done | Synthesizes verdicts |
| Orchestrator | ✅ Done | Coordinates agent pipeline |
| CLI + Demo | ✅ Done | Interactive and presentation modes |
| 10 test cases seeded | ✅ Done | Marina's methodology break cases |

---

## Phase 2: Flexibility & Scale ✅

**Status**: Complete

- [x] **Pluggable evidence sources**: Methodology documents, Data APIs (BLS, FRED, ECB, Census, Eurostat), Web search fallback.
- [x] **Deterministic routing + aggregation**: Claim router selects source strategy by claim type. Evidence aggregator scores relevance/confidence.
- [x] **Retrieval memory + observability**: Retrieval run history, CLI diagnostics (`db-doctor`, `retrieval-stats`).
- [x] **Local-first default mode**: No API keys required for baseline functionality.

---

## Phase 3: The Intelligence Layer (Current)

**Goal**: Move from a generic RAG pipeline to a mathematically rigorous specialized tool. 

### Phase 3.1: The Knowledge Engine (Data Ingestion)
- [ ] Build `crawl4ai` pipeline to autonomously ingest official methodology documentation from URLs in `MARINA.md`.
- [ ] Materialize `pgai` embeddings to enable true semantic vector search for the `Archivist` agent.

### Phase 3.2: The Math Engine (Econometric Rigor)
- [ ] Upgrade the `Analyst` agent to perform rigorous statistical break detection (e.g., Chow Test) on live statistical data.
- [ ] Wire the `Analyst`'s mathematical confidence scores into the evidence aggregator so the `Editor` cannot ignore structural breaks.

---

## Phase 4: Publication (Q2/Q3 2026)

**Target**: JEBO (Journal of Economic Behavior and Organization)

### Paper Contributions

1. **Methodology**: Multi-agent architecture for claim validation combining LLM retrieval with programmatic econometric testing.
2. **Findings**: Empirical results on claim validation accuracy when data series contain undocumented methodology breaks.
3. **Open Source**: Platform release + MethodBench benchmark dataset of structural methodology breaks.

### Deliverables

- [ ] MethodBench benchmark dataset curation
- [ ] Paper draft
- [ ] Open source code release
