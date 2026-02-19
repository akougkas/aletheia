# ALETHEIA

> *Aletheia (ἀλήθεια): Greek for "truth" or "unconcealment" — the act of revealing what is hidden.*

**ALETHEIA** is an autonomous AI platform that validates claims against evidence. Give it any claim — about economics, health, policy, or science — and it will search for supporting or contradicting evidence, flag methodology concerns, and explain its reasoning with full source citations.

## The Vision

Today, misinformation spreads faster than verification. Policy analysts, researchers, and journalists face an impossible task: manually checking every claim against primary sources, methodology notes, and academic literature.

ALETHEIA automates this process with a team of AI agents that:
1. **Parse** any claim into structured components
2. **Search** a knowledge base of trusted sources and academic papers
3. **Retrieve** relevant data from official APIs
4. **Validate** the claim against evidence
5. **Explain** the verdict with full provenance

```
┌─────────────────────────────────────────────────────────────────┐
│                         YOUR CLAIM                               │
│        "EU unemployment fell sharply in 2021, showing           │
│              strong labor market recovery"                       │
└───────────────────────────────┬─────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│                     ALETHEIA AGENT TEAM                           │
│                                                                   │
│   ┌────────┐   ┌──────────┐   ┌─────────┐   ┌─────────┐         │
│   │ PARSER │──▶│ ARCHIVIST│──▶│ ANALYST │──▶│ EDITOR  │         │
│   │        │   │          │   │         │   │         │         │
│   │ What's │   │ What     │   │ What do │   │ What's  │         │
│   │ being  │   │ evidence │   │ the     │   │ the     │         │
│   │ claimed│   │ exists?  │   │ numbers │   │ verdict?│         │
│   │   ?    │   │          │   │ show?   │   │         │         │
│   └────────┘   └────┬─────┘   └─────────┘   └─────────┘         │
│                     │                                            │
│              ┌──────▼──────┐                                     │
│              │  KNOWLEDGE  │                                     │
│              │    BASE     │                                     │
│              │             │                                     │
│              │ • Papers    │                                     │
│              │ • Data APIs │                                     │
│              │ • Method    │                                     │
│              │   notes     │                                     │
│              └─────────────┘                                     │
└───────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌───────────────────────────────────────────────────────────────────┐
│  VERDICT: PARTIALLY_SUPPORTED                                     │
│                                                                   │
│  The decline is real but overstated. Eurostat's 2021 definition  │
│  change reduced the measured rate by ~0.3-0.4 percentage points. │
│                                                                   │
│  Sources: Eurostat LFS Methodology (2021), ECB Working Paper     │
└───────────────────────────────────────────────────────────────────┘
```

## Why Methodology Awareness Matters

ALETHEIA starts with a unique capability: **methodology awareness**. Official statistics frequently change how they measure things — questionnaire redesigns, definitional shifts, classification updates — while the output still looks like a continuous time series.

Example: "E-cigarette use surged from 3.2% to 4.4% in 2019" sounds alarming. But ~half of that increase came from the CDC changing *how they asked the question*, not from more people vaping.

ALETHEIA catches these breaks because it reads methodology documentation AND connects it to specific time periods and data points.

## Current Status

We're in early development. The current version demonstrates:
- Claim parsing (natural language → structured query)
- Knowledge graph search with pgai-managed vector embeddings (10 seeded methodology break cases)
- Verdict synthesis (supported / partially supported / misleading)
- Pluggable evidence routing (methodology KB + data APIs + web fallback + scholar deep-research)
- Retrieval observability (run history, cache metrics, diagnostics)

See [ROADMAP.md](ROADMAP.md) for the development plan.

## MVP Operating Modes

ALETHEIA is designed as a research tool that works in multiple environments (macOS, Linux, Windows/WSL):

- **Baseline mode (no API keys):** local-first, team-ready default
  - Uses local LLM endpoint + seeded DB + public/default sources.
  - Works out-of-the-box for team demos and paper development.
- **Enhanced mode (optional keys):**
  - Adds higher-coverage search and data retrieval (Google CSE, Brave, SERP Scholar, FRED/Census keys).
  - Same workflow, richer evidence surface.

## Quickstart (New Computer)

### 1) Baseline setup (recommended first)

```bash
# Prerequisites: Docker, Python 3.11+, uv, local LLM endpoint (default: mini:8080)

# Optional if 5432 is busy on your machine:
export ALETHEIA_DB_PORT=5433

docker compose up -d                        # Start PostgreSQL + pgai vectorizer worker
uv sync                                     # Install dependencies
uv run python -m aletheia.bootstrap         # Install pgai + seed + validate (no psql required)
uv run python -m aletheia.ingest            # Ingest MARINA docs/papers into documents/chunks
uv run python -m aletheia.vectorizer        # Create embedding vectorizers
uv run python demo.py --quick               # Run the demo
```

### 2) Health checks

```bash
uv run python cli.py db-doctor
uv run python cli.py retrieval-stats --hours 24 --limit 10
```

### 3) Optional enhanced mode

Set only the keys you have; baseline works without them.

```bash
export GOOGLE_CSE_API_KEY=...
export GOOGLE_CSE_CX=...
export BRAVE_SEARCH_API_KEY=...
export SERPAPI_API_KEY=...
export FRED_API_KEY=...
export CENSUS_API_KEY=...
```

The quick demo walks through validated methodology-break cases and now exercises routed multi-source retrieval.

### Integration Tests (Live DB)

```bash
# Requires docker compose stack running and seeded DB
ALETHEIA_RUN_INTEGRATION=1 uv run --extra dev pytest -m integration -q
```

### Optional: Live Web Search Engines

For Phase 2 web fallback, ALETHEIA can query live providers directly:

```bash
# Provider selection:
# - auto (default): tries chain from ALETHEIA_WEB_SEARCH_CHAIN
# - google | brave | duckduckgo
export ALETHEIA_WEB_SEARCH_PROVIDER=auto
export ALETHEIA_WEB_SEARCH_CHAIN=google,brave,duckduckgo

# Google Programmable Search (optional)
export GOOGLE_CSE_API_KEY=...
export GOOGLE_CSE_CX=...

# Brave Search API (optional)
export BRAVE_SEARCH_API_KEY=...

# SERP API (Google Scholar only, for deep research papers)
export SERPAPI_API_KEY=...

# Deep-research mode (runs paper_scholar only when evidence is ambiguous)
export ALETHEIA_ENABLE_DEEP_RESEARCH=1
export ALETHEIA_DEEP_RESEARCH_CONF_THRESHOLD=0.62

# Optional Crawl4AI markdown fallback for weak/blocked HTML fetches
# pip install crawl4ai
export ALETHEIA_ENABLE_CRAWL4AI_FALLBACK=1

# Provider guardrails (rate limit + circuit breaker)
export ALETHEIA_WEB_RATE_LIMIT_PER_MIN="google:20,brave:30,duckduckgo:40,serpapi_google_scholar:15"
export ALETHEIA_WEB_CIRCUIT_FAILURE_THRESHOLD=3
export ALETHEIA_WEB_CIRCUIT_COOLDOWN_SECONDS=120
export ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN="google:2,brave:2,duckduckgo:2,serpapi_google_scholar:1"
export ALETHEIA_SOURCE_BUDGET_PER_RUN="methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1"

# Scholar ingestion allowlist policy
# modes: strict | balanced | open
export ALETHEIA_SCHOLAR_ALLOWLIST_MODE=balanced
export ALETHEIA_SCHOLAR_ALLOW_DOMAINS="doi.org,nber.org,arxiv.org,ssrn.com,oecd.org,imf.org,worldbank.org"
```

Design intent:
- `strict`: high precision, low noise (hard filter)
- `balanced` (default): keeps untrusted domains but down-ranks confidence
- `open`: max recall for exploratory research

### Retrieval Observability

Inspect retrieval history, source usage, and cache hit rates:

```bash
uv run python cli.py retrieval-stats --hours 48 --limit 20
```

### DB Doctor & Auth Troubleshooting

Run diagnostics:

```bash
uv run python cli.py db-doctor
```

`db-doctor` includes a capability matrix showing what is enabled by default (no-key baseline) versus optional API-key enhancements.

Common local auth failure cause:
- `password authentication failed` often means your Docker Postgres volume was initialized with older credentials.
- `POSTGRES_USER` / `POSTGRES_PASSWORD` in `docker-compose.yml` only apply when the volume is first created.

Portable/safe configuration pattern:
- Prefer a single `ALETHEIA_DB_URL` in your shell/CI secrets for production or remote DBs.
- For local dev, use component env vars (`ALETHEIA_DB_HOST`, `ALETHEIA_DB_PORT`, `ALETHEIA_DB_NAME`, `ALETHEIA_DB_USER`, `ALETHEIA_DB_PASSWORD`) and keep them in a local `.env` (not committed).
- Keep `ALETHEIA_DB_SSLMODE` explicit when using managed databases.
- Keep local baseline defaults simple (`aletheia:aletheia`), then layer optional config only when needed.

If reset is acceptable in this draft stage:

```bash
docker compose down -v
docker compose up -d
uv run python -m aletheia.bootstrap
```

### Dependency/Lock Strategy

- Runtime dependencies stay minimal in `pyproject.toml` to keep installs fast and deterministic.
- Use `uv lock` only when dependency declarations change.
- Use `uv sync --extra dev` for local testing tooling.

## Team

| Member | Role | Focus |
|--------|------|-------|
| **Marina** | Public Policy | Domain expertise, test cases, validation |
| **Harry** | Econometrics | Statistical methods, evaluation design |
| **Anthony** | AI/Infrastructure | Architecture, implementation |

See individual contribution docs: [MARINA.md](MARINA.md) | [HARRY.md](HARRY.md)

## Contributing

This is an open research project targeting publication in JEBO (Journal of Economic Behavior and Organization). We welcome:
- High-value data source suggestions
- Domain-specific test cases
- Methodology documentation contributions

See [ROADMAP.md](ROADMAP.md) for current priorities.

## Links

- [ROADMAP.md](ROADMAP.md) — Development phases and milestones
- [MEETINGS.md](MEETINGS.md) — Team decisions and notes
- [INITIAL-PLAN.md](INITIAL-PLAN.md) — Original project conception
