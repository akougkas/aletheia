# ALETHEIA Developer Documentation (AI Context)

**Purpose**: This documentation is optimized for AI coding assistants and LLMs operating within the ALETHEIA repository. It provides deterministic mappings between domain concepts, execution flows, and file locations to minimize hallucination and search overhead.

## Architecture Context
ALETHEIA is an autonomous multi-agent platform for validating statistical policy claims against known methodology breaks. 
- **Language**: Python 3.11+
- **Environment Management**: `uv` (strict locking)
- **Database**: PostgreSQL with `pgai` (pgvector for embeddings)
- **Core Abstractions**: Pydantic schemas, `asyncio`, pluggable Evidence Sources.

## Documentation Index

### 1. Execution Guides (`docs/guides/`)
Target these files to understand how to spin up, configure, and invoke the system:
- [getting-started.md](guides/getting-started.md): Environment dependencies, DB seeding, and baseline initialization.
- [configuration.md](guides/configuration.md): Complete index of all `ALETHEIA_*` environment variables, API key requirements, and runtime profiles.
- [usage.md](guides/usage.md): CLI entrypoints, demo harness flags, and integration test execution.

### 2. Core Components (`docs/components/`)
Target these files to understand the business logic of the multi-agent pipeline:
- [agents.md](components/agents.md): Flow control from Orchestrator -> Parser -> Archivist/Analyst -> Editor.
- [evidence-pipeline.md](components/evidence-pipeline.md): Routing strategies, aggregation logic, and plugin execution (`aletheia/evidence.py`).
- [knowledge-graph.md](components/knowledge-graph.md): Database schema mappings, semantic search, and document ingestion pipelines.
- [web-search.md](components/web-search.md): Fallback search providers, scholar allowlists, and the deep research workflow.

### 3. Class & Interface Definitions (`docs/classes/`)
Target these files when modifying data structures or implementing new plugins:
- [schema.md](classes/schema.md): Exact Pydantic model definitions (`PolicyClaim`, `Verdict`, `MethodologyChange`).
- [base-agent.md](classes/base-agent.md): Inherited `Agent` class behaviors, LLM invocation methods, and logging standards.
- [evidence.md](classes/evidence.md): Protocols and base classes for `RoutingPlan`, `SourceOutput`, and `EvidenceSource`.
- [retrieval-store.md](classes/retrieval-store.md): Telemetry, caching logic, and state management within `RetrievalStore`.

**Critical Note for AI Contributors**: Always refer to `aletheia/schema.py` as the ultimate source of truth for data shapes. Do not assume fields exist without verifying against the Pydantic models.