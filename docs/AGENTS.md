# ALETHEIA Agent Team

The ALETHEIA system operates using a multi-agent architecture where specialized AI models communicate to parse, research, retrieve data, and synthesize policy verdicts. All agents inherit from a common `Agent` base class (`aletheia.agents.base`) which provides standardized LLM invocation (including reasoning modes) and structured inter-agent logging.

## Chief Analyst (OrchestratorAgent)
**Role:** Coordinator and Pipeline Manager
**Implementation:** `aletheia/agents/orchestrator.py`

The Chief Analyst orchestrates the entire lifecycle of a policy claim:
1. Receives the natural language claim from the user.
2. Invokes the **Auditor** (ClaimParserAgent) to structure the claim.
3. Consults the **EvidencePipeline** and **ClaimRouter** to formulate a strategy.
4. Orchestrates parallel execution of the **Archivist**, **Analyst**, and Web Search Fallbacks.
5. Feeds aggregated evidence (via `EvidenceAggregator`) to the **Editor** for final synthesis.
6. Maintains a full audit trail (`self.trace`) logging all inter-agent messages.

## Auditor (ClaimParserAgent)
**Role:** Natural Language Extraction
**Implementation:** `aletheia/agents/parser.py`

Responsible for parsing unstructured claims into strict `PolicyClaim` Pydantic models. It forces the LLM to output a precise JSON schema with reasoning blocks:
- **indicator**: The statistical measure (e.g., "unemployment rate").
- **dataset**: The source dataset if mentioned (e.g., "CPS", "FRED").
- **geography**: Scope (defaults to "USA").
- **direction** & **magnitude**: The mathematical claim being made.
- **period_start** / **period_end**: The timeline of the claim.

## Archivist (ArchivistAgent)
**Role:** Data Provenance and Knowledge Graph Queries
**Implementation:** `aletheia/agents/archivist.py`

The Archivist is responsible for identifying *methodology changes* that could affect data interpretation. It operates as the "memory" of the statistical ecosystem:
- Resolves dataset acronyms (e.g., "EU-LFS", "ESA2010").
- Queries the PostgreSQL knowledge base for known `MethodologyChange` records via dataset codes.
- Performs **Semantic Search** using `pgai` embeddings to find methodology breaks (`methodology_changes_embedding`) and broader document evidence (`document_chunks_embedding`).
- Gracefully falls back to lexical/keyword searching if semantic embeddings fail.

## Analyst (AnalystAgent)
**Role:** Data Retrieval & Structural Break Analysis
**Implementation:** `aletheia/agents/analyst.py`

The Analyst pulls live, raw numerical data from statistical APIs (BLS, Census ACS, FRED, Eurostat, ECB) to verify the numbers underlying a claim.
- **Live Connectors**: Normalizes calls to various APIs to fetch time-series data matching the claim's timeline.
- **Structural Break Detection**: Runs mathematical diagnostics (mean-shift analysis and CUSUM-style scoring) to statistically detect hidden methodology breaks in the time series, assigning an `effect_size` and `cusum_score`.
- **Reality vs Methodology Quantification**: Estimates how much of an observed change is "real" versus an artifact of methodology (e.g., "50% of the unemployment drop is purely definitional").

## Editor (EditorAgent)
**Role:** Verdict Synthesis
**Implementation:** `aletheia/agents/editor.py`

The Editor provides the final synthesized output. It takes the parsed claim, methodology breaks, API analysis, and aggregated document evidence to determine a strict `VerdictStatus`:
- **SUPPORTED**: Data matches claim; no major methodology breaks.
- **PARTIALLY_SUPPORTED**: Claim is directionally true, but methodology changes require significant caveats.
- **MISLEADING**: Claim completely ignores overlapping/major methodology breaks (e.g., non-comparable time series).
- **INSUFFICIENT_DATA**: No data or methodology could be retrieved.

The Editor carefully ranks `SeverityLevel` and `ComparabilityLevel`, producing a detailed summary, caveats, and deduplicated provenance citations.

---

### Agent Communication Protocol
Agents communicate via `AgentMessage` records (defined in `aletheia/schema.py`). Every request and response is appended to the Chief Analyst's trace, providing full explainability and observability into *how* the AI team reached its conclusion.