# Agent State Machine & Workflow (AI Context)

**Target Audience**: AI coding assistants modifying the overarching control flow or adding new Agent roles, excluding LLM implementation details.

## Orchestrator (`aletheia.agents.orchestrator.OrchestratorAgent`)
The Chief Analyst is the entry point for claim processing. It does not perform domain logic; it manages state and sub-agent invocation.

**Execution Flow (`process_claim`)**:
1. Initializes an empty audit trace (`self.trace`).
2. Invokes **Parser** (`ClaimParserAgent`).
3. Invokes **EvidencePipeline** (which manages the Router and Aggregator).
4. Invokes **Analyst** (`quantify_methodology_vs_reality`) using the aggregated evidence to mathematically decompose real vs methodological change.
5. Invokes **Editor** (`EditorAgent`) to synthesize the final `Verdict`.
6. Populates `last_run_details` with structured output for the CLI/UI.

## Parser (`aletheia.agents.parser.ClaimParserAgent`)
Responsible for strict structural extraction.
- **Input**: Natural language string.
- **Output**: `PolicyClaim` (Pydantic).
- **Failure Mode**: If parsing fails, it yields a fallback `PolicyClaim` with `indicator="unknown"` and `confidence=0.0`.

## Archivist (`aletheia.agents.archivist.ArchivistAgent`)
Responsible for deterministic database resolution and record fetching.
- **Dataset Resolution**: Uses `_normalize_dataset_code` to map common aliases (e.g., "EU LFS" -> "EU-LFS") before querying the `datasets` table.
- **Break Fetching**: (`find_breaks`) 
  1. Tries exact `dataset_id` match in `methodology_changes`.
  2. Filters breaks based on `claim.period_start` and `claim.period_end` (keeping nearby future breaks).
  3. Uses semantic fallback (`semantic_search_breaks`) if the dataset name is ambiguous.
- **Deduplication**: `_dedupe_breaks` ensures that if a break is found via both exact-match and semantic search, it only appears once based on `(id, benchmark_case_id)`.

## Analyst (`aletheia.agents.analyst.AnalystAgent`)
Responsible for live data fetching and statistical math.
- **Live Connectors**: Dispatches to `_fetch_bls_series`, `_fetch_fred_series`, `_fetch_eurostat_series`, `_fetch_ecb_series`, or `_fetch_acs_median_income` based on `claim.dataset` and `claim.indicator`.
- **Break Detection (`detect_structural_break`)**:
  - Uses `_choose_break_index` to find the most likely split point in a time series using a rolling window variance.
  - Calculates `effect_size` (mean shift / pooled standard deviation).
  - Calculates `cusum_score` (cumulative sum of residuals over pooled std dev).
  - Yields a dictionary with `detected: bool` and confidence metrics.
- **Quantification (`quantify_methodology_vs_reality`)**: 
  - Estimates the scalar impact of documented methodology breaks.
  - Compares the estimated impact against the `observed_change` in the API data to yield a `methodology_share_estimate` (0.0 to 1.0).

## Editor (`aletheia.agents.editor.EditorAgent`)
Responsible for deterministic business rules regarding verdicts.
- **Relevance Filtering**: `_is_relevant_break` filters out methodology changes that occurred far outside the `claim.period_start` / `claim.period_end` window.
- **Verdict Logic Matrix**:
  - *No breaks + Data found* -> `SUPPORTED`
  - *No breaks + No data* -> `INSUFFICIENT_DATA`
  - *Irrelevant breaks only* -> `PARTIALLY_SUPPORTED`
  - *Relevant breaks (Not Comparable or Major Severity)* -> `MISLEADING`
  - *Relevant breaks (Normal Revisions with low impact)* -> `PARTIALLY_SUPPORTED`
- **Deviation Caveats**: If `claim_value_check` shows the user's claimed number is wildly inaccurate compared to API data, it forces `SUPPORTED` claims down to `PARTIALLY_SUPPORTED` and inserts a caveat at the top of the list.