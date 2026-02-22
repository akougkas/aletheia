# Retrieval Store & Telemetry (AI Context)

**Target Audience**: AI coding assistants modifying caching logic, tracking API budgets, or adding UI observability.

## File Location
`aletheia/retrieval_store.py`

## Class: `RetrievalStore`
A lightweight SQLite-backed (or Postgres-backed depending on environment) storage mechanism distinct from the Knowledge Graph. It tracks the *operational* execution of the pipeline rather than the *domain* data.

### Purpose
1. **Caching**: Prevents redundant, expensive web searches or deep-research API calls for identical claims within a time window (`max_age_hours`).
2. **Observability**: Tracks budget exhaustion (`provider_budget_skips`), execution time, and confidence metrics per run.
3. **Telemetry**: Powers the `cli.py retrieval-stats` command.

### Key Methods
- `async begin_run(self, claim: PolicyClaim, plan: RoutingPlan) -> int`: Initializes a run record and returns a `run_id`.
- `async persist_aggregated(self, run_id: int, aggregated: AggregatedEvidence)`: Saves the `AggregatedEvidence` output (JSON serialized) to the run record.
- `async complete_run(self, run_id: int, status: str, metadata: dict[str, Any])`: Closes the run, updating elapsed time and final telemetry metadata.
- `async cached_documents(self, claim: PolicyClaim, plan: RoutingPlan, source_id: str, max_age_hours: int, limit: int)`: Attempts to fetch previously retrieved unstructured snippets for a specific source, bypassing network execution if successful.