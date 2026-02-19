# ALETHEIA Roadmap

> Last updated: 2026-02-19

## Demo Day Target (1 week: Feb 19, 2025)

**Goal**: Demonstrate end-to-end autonomous claim validation

**Success criteria**:
- [ ] User submits a claim → system autonomously validates → returns verdict with sources
- [ ] Works across multiple domains (official statistics, economics, health)
- [ ] Shows architecture can scale (aspirational: 10,000+ documents)
- [ ] Clear narrative connecting methodology awareness to broader claim validation

---

## Phase 1: Foundation ✅

**Status**: Complete

| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL + pgvector | ✅ Done | Running in Docker |
| Database schema | ✅ Done | Agencies, datasets, indicators, methodology_changes, documents |
| LLM client (llama.cpp) | ✅ Done | Connects to mini:8080 |
| Claim Parser agent | ✅ Done | Extracts structured claims from natural language |
| Archivist agent | ✅ Done | Queries knowledge graph for methodology breaks |
| Analyst agent | ✅ Done | Live connectors for BLS/FRED/Census/Eurostat/ECB |
| Editor agent | ✅ Done | Synthesizes verdicts |
| Orchestrator | ✅ Done | Coordinates agent pipeline |
| CLI + Demo | ✅ Done | Interactive and presentation modes |
| 10 test cases seeded | ✅ Done | Marina's methodology break cases |

---

## Phase 2: Flexibility & Scale ✅

**Goal**: Make the system work for "any claim, any domain" with local-first baseline and optional enhanced providers.

### Architecture Changes Needed

- [x] **Pluggable evidence sources**:
  - Methodology documents (current)
  - Academic papers (Google Scholar via SERP API, optional)
  - Data APIs (BLS, FRED, ECB, Census, Eurostat)
  - Web search fallback (Google/Brave/DDG chain)

- [x] **Deterministic routing + aggregation**:
  - Claim router selects source strategy by claim type
  - Evidence aggregator scores relevance/confidence
  - Fallback and deep-research paths are explicit and auditable

- [x] **Retrieval memory + observability**:
  - Retrieval run history and linked evidence docs
  - Cache hit tracking
  - Provider/source budget skip metrics
  - CLI diagnostics (`db-doctor`, `retrieval-stats`)

### Content Ingestion (Phase 2 outcome)

- [x] **Paper/web ingestion pipeline**:
  - Search -> fetch -> clean -> chunk -> index
  - Optional Crawl4AI fallback for weak/blocked pages
- [x] **Embedding pipeline**:
  - pgai vectorizer-backed semantic retrieval
- [x] **Source registry**:
  - Trusted source metadata and confidence priors

### MVP Deployment & Onboarding (cross-platform)

- [x] Local-first default mode (no API keys required)
- [x] Optional enhanced mode (keys add coverage, not required)
- [x] DB auth diagnostics + reset-friendly workflow for research environments
- [ ] Add a single onboarding command wrapper (future polish)

### Team Action Items

| Owner | Task | Deadline |
|-------|------|----------|
| Harry | Identify high-value data APIs (FRED, ECB, BLS, etc.) | Feb 14 |
| Harry | Create HARRY.md with econometrics domain knowledge | Feb 14 |
| Marina | Identify high-value document sources (methodology notes, papers) | Feb 14 |
| Marina | Create MARINA.md with policy domain knowledge | Feb 14 |
| Marina | Curate 100+ validation evidence papers | Feb 17 |
| Anthony | Implement pluggable evidence source architecture | Feb 16 |
| Anthony | Add live web search capability | Feb 17 |
| Anthony | Polish demo for presentation | Feb 18 |

---

## Phase 3: Intelligence Layer (Post-Demo)

- [ ] Fine-tune embedding model on methodology corpus
- [ ] Add statistical break detection (Chow test, CUSUM)
- [x] Implement real API integrations
- [ ] Adversarial testing with rephrased claims
- [ ] Cross-domain generalization tests
- [ ] CLI UX polish and demo narrative flow for presentation

---

## Phase 4: Publication (Q2 2025)

**Target**: JEBO (Journal of Economic Behavior and Organization)

### Paper Contributions

1. **Methodology**: Multi-agent architecture for claim validation with methodology awareness
2. **Scale**: Demonstration of agentic AI at scale (10K+ documents)
3. **Findings**: Empirical results on claim validation accuracy
4. **Open Source**: Platform release + MethodBench benchmark

### Deliverables

- [ ] Paper draft
- [ ] MethodBench benchmark dataset
- [ ] Open source code release
- [ ] Documentation for community contributions

---

## Architecture Evolution

### Current (Phase 1)
```
Claim → Parser → Archivist → Editor → Verdict
                    ↓
            PostgreSQL (methodology breaks only)
```

### Target (Phase 2+)
```
Claim → Parser → Router → [Multiple Evidence Sources] → Aggregator → Editor → Verdict
                              ↓
                    ┌─────────┼─────────┐
                    ↓         ↓         ↓
              Methodology   Papers    Data APIs
                 KG         Index     (FRED, etc.)
```

### Current Implementation Snapshot

```
Claim -> Parser -> Router -> Sources (KB + APIs + Web + Scholar*) -> Aggregator -> Editor
                                  |                   |
                                  +-> Retrieval memory/index + diagnostics
                                  +-> Deep research only on ambiguous evidence

* Scholar uses SERP API key when available; baseline runs without it.
```

---

## Open Questions

1. **Scope boundaries**: How do we decide what claims are "in scope" vs out of scope?
2. **Confidence calibration**: How should we calibrate score thresholds for publication-quality evaluation?
3. **Source weighting**: How do we weight different types of evidence?
4. **Evaluation metrics**: What's our gold standard for "correct" validation?
5. **Demo UX**: What CLI/UI flow best communicates methodology-aware reasoning to non-technical audiences?

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Unclear narrative | High | High | Weekly alignment meetings, clear docs |
| Scope creep | Medium | High | Demo day as forcing function |
| Not enough evidence in KB | Medium | Medium | Pre-seed with curated sources |
| LLM hallucination | Low | High | Only summarize found evidence, cite sources |
