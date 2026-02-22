# Evidence Pipeline & Routing (AI Context)

**Target Audience**: AI coding assistants modifying how ALETHEIA decides which data sources to query and how it ranks the resulting evidence.

## File Location
Core logic resides entirely in `aletheia/evidence.py`.

## 1. ClaimRouter
The router uses deterministic heuristics to categorize claims into three `ClaimType` buckets, which dictate the `RoutingPlan`.

**Routing Rules**:
- `METHODOLOGY_AWARE`: Triggered if `claim.dataset` matches high-churn datasets (e.g., `CPS`, `EU-LFS`, `ACS`) OR if the claim text contains keywords (`methodology`, `redesign`, `series break`).
  - **Strategy**: Queries `methodology_kb`, `data_api`, and `document_index`.
- `STATISTICAL_FACT`: Triggered if `claim.dataset` matches standard data APIs (`BLS`, `FRED`, `ECB`) OR text contains standard indicators (`rate`, `gdp`, `inflation`).
  - **Strategy**: Queries `data_api`, `methodology_kb`, and `document_index`.
- `GENERAL`: Fallback.
  - **Strategy**: Queries `document_index` and `methodology_kb`.

All plans include `web_fallback` as the `fallback_source_id` and `paper_scholar` as the `deep_research_source_ids`.

## 2. Evidence Pipeline Execution
The `EvidencePipeline.collect()` method orchestrates the parallel execution of `EvidenceSource` plugins.

**Execution Flow**:
1. Obtain `RoutingPlan` from `ClaimRouter`.
2. Check `ALETHEIA_SOURCE_BUDGET_PER_RUN`. If a source (e.g., `web_fallback`) has exhausted its budget limit (tracked in `_run_source_calls`), it is skipped.
3. Concurrently execute `source.collect(claim, plan)` for all primary `source_ids`.
4. If results lack substantive evidence (no breaks, no docs, no API data), trigger the `fallback_source_id` (`web_fallback`).
5. Pass all collected `SourceOutput` objects to `EvidenceAggregator`.
6. If `ALETHEIA_ENABLE_DEEP_RESEARCH=1` AND aggregate confidence < `ALETHEIA_DEEP_RESEARCH_CONF_THRESHOLD` OR evidence is sparse/weak, trigger the `deep_research_source_ids` (`paper_scholar`).
7. Re-aggregate and persist telemetry to `RetrievalStore`.

## 3. Evidence Aggregator (`EvidenceAggregator`)
Responsible for deduplicating breaks, merging analysis dicts, and ranking unstructured document snippets.

**Scoring Algorithm (`_score_confidence`)**:
- Starts with a base confidence defined by `SourceRegistry.base_confidence` (e.g., `methodology_kb` has a higher base than `web_fallback`).
- Adds `_score_relevance` (TF-IDF style token overlap between the claim and the document text).
- Adds `trust_bonus` (0.1) if the URL matches an official statistical domain (e.g., `.gov`, `europa.eu`).
- Subtracts `fallback_penalty` (0.1) if the source was `web_fallback`.
- Adds `data_consistency_adjust` if the Analyst's API data matches the user's claimed number (`claim_value_check`).
- Adds `break_signal_adjust` if the Analyst's mathematical break detection flagged a structural break.
- Outputs a normalized `confidence_score` (0.0 to 1.0) and sorts the `evidence_docs` array descending.