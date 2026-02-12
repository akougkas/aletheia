# ALETHEIA Roadmap

> Last updated: 2025-02-12

## Demo Day Target (1 week: Feb 19, 2025)

**Goal**: Demonstrate end-to-end autonomous claim validation

**Success criteria**:
- [ ] User submits a claim → system autonomously validates → returns verdict with sources
- [ ] Works across multiple domains (official statistics, economics, health)
- [ ] Shows architecture can scale (aspirational: 10,000+ documents)
- [ ] Clear narrative connecting methodology awareness to broader claim validation

---

## Phase 1: Foundation ✅ (Current)

**Status**: Complete

| Component | Status | Notes |
|-----------|--------|-------|
| PostgreSQL + pgvector | ✅ Done | Running in Docker |
| Database schema | ✅ Done | Agencies, datasets, indicators, methodology_changes, documents |
| LLM client (llama.cpp) | ✅ Done | Connects to mini:8080 |
| Claim Parser agent | ✅ Done | Extracts structured claims from natural language |
| Archivist agent | ✅ Done | Queries knowledge graph for methodology breaks |
| Analyst agent | ⚠️ Stub | Data retrieval not yet implemented |
| Editor agent | ✅ Done | Synthesizes verdicts |
| Orchestrator | ✅ Done | Coordinates agent pipeline |
| CLI + Demo | ✅ Done | Interactive and presentation modes |
| 10 test cases seeded | ✅ Done | Marina's methodology break cases |

---

## Phase 2: Flexibility & Scale (This Week)

**Goal**: Make the system work for "any claim, any domain"

### Architecture Changes Needed

- [ ] **Pluggable evidence sources**: Abstract the knowledge base to support:
  - Methodology documents (current)
  - Academic papers (new)
  - Data APIs (BLS, FRED, ECB, etc.)
  - Web search fallback

- [ ] **Pluggable validators**: The Editor should be able to use different validation strategies:
  - Methodology break detection (current)
  - Statistical fact-checking
  - Source credibility assessment
  - Consensus across multiple papers

- [ ] **Generic claim-evidence schema**: Current schema is methodology-specific. Need:
  - Generic "evidence" table that can hold any type
  - Claim-evidence linking with relevance scores
  - Multi-source aggregation

### Content Ingestion

- [ ] **Paper-to-markdown pipeline**: Convert academic PDFs to searchable text
- [ ] **Embedding pipeline**: Generate vectors for semantic search
- [ ] **Source registry**: Track which sources are trusted for which domains

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
- [ ] Implement real API integrations
- [ ] Adversarial testing with rephrased claims
- [ ] Cross-domain generalization tests

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

---

## Open Questions

1. **Scope boundaries**: How do we decide what claims are "in scope" vs out of scope?
2. **Confidence calibration**: How do we calibrate verdict confidence levels?
3. **Source weighting**: How do we weight different types of evidence?
4. **Evaluation metrics**: What's our gold standard for "correct" validation?

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Unclear narrative | High | High | Weekly alignment meetings, clear docs |
| Scope creep | Medium | High | Demo day as forcing function |
| Not enough evidence in KB | Medium | Medium | Pre-seed with curated sources |
| LLM hallucination | Low | High | Only summarize found evidence, cite sources |
