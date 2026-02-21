# ALETHEIA Architecture & Pipeline

ALETHEIA is a Python-based platform designed to intercept, analyze, and validate policy claims using a multi-agent system, a pluggable evidence pipeline, and a robust Postgres/pgai-backed knowledge base.

## 1. Core Data Structures (`aletheia.schema`)
The system is built on strong Pydantic typing:
- **`PolicyClaim`**: The core input. A structured representation of the user's natural language claim (indicator, dataset, timeframe, direction, magnitude).
- **`MethodologyChange`**: The critical business object. Represents a break in how a statistic was calculated (ChangeType, Severity, Comparability, Impact Estimate).
- **`Verdict`**: The final output. Contains the Status, Confidence, Severity, Caveats, and Provenance.

## 2. Evidence Pipeline (`aletheia.evidence`)
Evidence gathering is decoupled from agent logic via a pluggable, modular pipeline.
- **`ClaimRouter`**: Deterministically inspects the `PolicyClaim` and routes it to an execution strategy (`RoutingPlan`). Claims mentioning datasets known for high methodological churn (like "CPS" or "EU-LFS") trigger `METHODOLOGY_AWARE` routing.
- **Sources (`EvidenceSource`)**:
  - `MethodologyEvidenceSource`: Queries the Archivist for database records.
  - `DataApiEvidenceSource`: Queries the Analyst for live API data.
  - `DocumentIndexEvidenceSource`: Queries the ingested PDF/document knowledge base.
  - `WebSearchEvidenceSource`: Uses live Search APIs (Google, Brave) as a fallback.
  - `ScholarPaperEvidenceSource`: Specific deep-research retrieval via Google Scholar.
- **`EvidenceAggregator`**: Merges evidence, deduplicates methodology breaks, and ranks document snippets based on relevance/confidence scoring heuristics (e.g., token overlap, dataset matching).

## 3. Data Ingestion & Storage (`aletheia.db`, `aletheia.retrieval_store`)
- **Storage**: Uses PostgreSQL.
- **Vectorization**: Uses pgai (`pgvector`) for native embeddings. The `vectorizer.py` script automatically converts text chunks into embeddings directly inside Postgres.
- **Tables**: `datasets`, `indicators`, `methodology_changes`, `documents`, `document_chunks`.
- **Retrieval Observability**: `RetrievalStore` tracks cache hits, search latency, and budget execution across the multi-agent pipeline.

## 4. Execution Flow
1. **User Input** → CLI or Demo Harness (`demo.py`, `cli.py`).
2. **Orchestrator** (`ChiefAnalyst`) initializes the execution context.
3. **Auditor** parses the natural language text into a `PolicyClaim`.
4. **Router** creates a `RoutingPlan`.
5. **Pipeline** concurrently triggers all required `EvidenceSource` plugins.
6. Sources delegate specific tasks (DB queries to the **Archivist**, API queries to the **Analyst**).
7. Results are ranked by the **Aggregator**.
8. **Editor** receives the aggregated context and formulates a `Verdict`.
9. The verdict and trace logs are returned to the user interface.

## 5. Live Connector Infrastructure
The Analyst agent uses `httpx` to directly interface with major statistical bodies:
- **BLS (Bureau of Labor Statistics)**: Public Time Series API
- **Census ACS**: American Community Survey
- **FRED**: Federal Reserve Economic Data
- **Eurostat**: SDMX Dissemination API
- **ECB**: European Central Bank API

## 6. Mathematical Break Detection
ALETHEIA doesn't just read PDFs; it analyzes math. The Analyst applies:
- **Mean-shift testing** to find localized statistical gaps.
- **CUSUM (Cumulative Sum) style scoring** to confidently flag structural breaks inside real API data, serving as a secondary verification for the textual `MethodologyChange` records found by the Archivist.