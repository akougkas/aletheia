# ALETHEIA Roadmap

> Last updated: 2026-02-22

## Demo Day Target (Thursday Feb 26, 2026)

**Goal**: Demonstrate end-to-end autonomous claim validation for Macro-Economic & Public Health Official Statistics.

**Success criteria**:
- [x] User submits a claim → system autonomously validates → returns verdict with sources
- [x] System successfully fetches official time-series data and proves structural methodology breaks mathematically
- [ ] System retrieves and explicitly cites the corresponding methodology PDFs
- [ ] Clear narrative connecting rigorous econometric tests to LLM-driven claim validation

---

## Phase 1: Foundation ✅

**Status**: Complete

| Component | Status | Notes |
|-----------|--------|-------|
| SurrealDB (graph + vector + relational) | ✅ Done | Single container, HNSW vector indexes |
| Database schema | ✅ Done | Agencies, datasets, indicators, methodology_changes, document_chunks |
| LLM client | ✅ Done | OpenAI-compatible endpoints (LM Studio, Ollama) with provider abstraction |
| Claim Parser agent | ✅ Done | Extracts structured claims from natural language |
| Archivist agent | ✅ Done | Semantic vector search over methodology KB + document index |
| Analyst agent | ✅ Done | Live connectors for BLS, FRED, Census ACS, Eurostat, ECB |
| Editor agent | ✅ Done | Synthesizes verdicts with methodology-vs-real decomposition |
| Orchestrator | ✅ Done | Coordinates full agent pipeline |
| CLI | ✅ Done | `uv run aletheia` — interactive, single-claim, onboarding, diagnostics |
| 10 test cases seeded | ✅ Done | Marina's methodology break cases + 40 expanded adversarial cases |

---

## Phase 2: Flexibility & Scale ✅

**Status**: Complete

- [x] **Pluggable evidence sources**: Methodology KB, Data APIs (BLS, FRED, ECB, Census ACS, Eurostat), document index, web search fallback, scholar deep-research.
- [x] **Deterministic routing + aggregation**: Claim router selects source strategy by claim type. Evidence aggregator scores relevance/confidence.
- [x] **Retrieval memory + observability**: Run history, cache metrics, CLI diagnostics (`db-doctor`, `retrieval-stats`, `onboarding`).
- [x] **Local-first default mode**: No API keys required for baseline functionality.

---

## Phase 3: The Intelligence Layer ✅

**Status**: Complete

### 3.1: The Knowledge Engine
- [x] Ingestion pipeline to load methodology documentation into document_chunks table.
- [x] Materialized pgai embeddings (4096-dim, qwen3-embedding) enabling semantic vector search for the Archivist agent.
- [x] 408 document chunks + 50 methodology change embeddings indexed.

### 3.2: The Math Engine
- [x] Chow F-test structural break detection in the Analyst agent on live statistical data.
- [x] Math confidence scores wired into evidence aggregator — Editor cannot ignore structural breaks.
- [x] EU dataset routing (Eurostat LFS, HICP, ECB) alongside US sources.

### 3.3: End-to-End Validation
- [x] Eval harness: 39/40 (98%) on seed benchmark cases, avg 4.0s/claim, avg 81% confidence.
- [x] Color-coded TUI with live pipeline spinner, confidence bars, and plain-English explanations.
- [x] Portable packaging: single `uv run aletheia` entry point, all dependencies in core.

---

## Phase 4: Publication (Q2/Q3 2026)

**Target**: JEBO (Journal of Economic Behavior and Organization)

**Status**: Not started

### Paper Contributions

1. **Methodology**: Multi-agent architecture for claim validation combining LLM retrieval with programmatic econometric testing.
2. **Findings**: Empirical results on claim validation accuracy when data series contain undocumented methodology breaks.
3. **Open Source**: Platform release + MethodBench benchmark dataset of structural methodology breaks.

### Deliverables

- [ ] MethodBench benchmark dataset curation
- [ ] Paper draft
- [ ] Open source code release
