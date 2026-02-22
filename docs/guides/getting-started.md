# Getting Started (AI Context)

**Target Audience**: AI coding assistants setting up the ALETHEIA environment or generating setup instructions.

## 1. Dependency Management (`uv`)
ALETHEIA relies on `uv` for deterministic environment management. The `pyproject.toml` defines optional dependency groups.

**Commands**:
- `uv sync`: Baseline runtime (default).
- `uv sync --extra dev`: Includes testing frameworks (`pytest`).
- `uv sync --extra crawler`: Includes `crawl4ai` dependencies.
- `uv sync --extra research`: Includes all data science/research add-ons.

**Lockfile Strategy**: Only use `uv lock` if `pyproject.toml` dependencies are explicitly modified.

## 2. Infrastructure (Docker & Postgres)
The platform requires a local PostgreSQL instance with `pgai` and `pgvector` extensions. The deployment topology is defined in stacked Compose files.

**Stack Topologies**:
1. **Core Database Only**: `docker-compose.yml` (Postgres on port `5432` by default).
2. **Web Crawler Addition**: `docker-compose.crawler.yml` (Adds Crawl4AI services).
3. **Local LLM Addition**: `docker-compose.local-ollama.yml` (Adds Ollama for fully local embedding/chat).

**Standard Invocation**:
```bash
# Copy .env.example to .env; set ALETHEIA_DB_PORT=5433 if 5432 is occupied
docker compose up -d
```

## 3. Database Bootstrap & Seeding
Once the Postgres container is running, the schema and initial knowledge base must be seeded.

**Execution Flow**:
1. **Bootstrap Schema & Seed Cases**: 
   ```bash
   uv run python -m aletheia.bootstrap
   ```
   - Executes `sql/init.sql` (creates `datasets`, `methodology_changes`, `documents` tables).
   - Executes `sql/seed_cases.sql` (inserts the 10 benchmark methodology break cases).
   - Executes `sql/validate_seed_cases.sql` (asserts structural integrity).

2. **Ingest Documents (PDFs/Markdown)**:
   ```bash
   uv run python -m aletheia.ingest
   ```
   - Reads methodology notes into the `documents` table and chunks them into `document_chunks`.

3. **Generate Embeddings**:
   ```bash
   uv run python -m aletheia.vectorizer
   ```
   - Triggers `pgai` to vectorize `document_chunks` into `document_chunks_embedding`.
   - Vectorizes `methodology_changes` into `methodology_changes_embedding`.
   - *Requirement*: `ALETHEIA_EMBED_BASE_URL` must point to an active LLM embedding endpoint.

## 4. Diagnostics (`cli.py`)
To verify the environment is correctly configured before running the orchestrator:

- **Database Connection Check**: 
  ```bash
  uv run python cli.py db-doctor
  ```
- **LLM/Embeddings Check**: 
  ```bash
  uv run python cli.py onboarding
  ```