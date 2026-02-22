# Configuration Reference (AI Context)

**Target Audience**: AI coding assistants modifying environment loading, adding new API providers, or adjusting system thresholds.

## Runtime Profiles
ALETHEIA uses a tiered configuration system where explicit CLI flags override Environment Variables, which override Profile defaults (`aletheia/runtime_profiles.py`).

## Core Environment Variables

### Database Connection
*Defined in `aletheia/db.py`*
- `ALETHEIA_DB_URL`: Fully qualified Postgres URI. If present, overrides component variables.
- `ALETHEIA_DB_HOST` (default: `localhost`)
- `ALETHEIA_DB_PORT` (default: `5432`)
- `ALETHEIA_DB_NAME` (default: `aletheia`)
- `ALETHEIA_DB_USER` (default: `aletheia`)
- `ALETHEIA_DB_PASSWORD` (default: `aletheia`)
- `ALETHEIA_DB_SSLMODE` (default: `disable`)

### LLM & Embeddings
*Defined in `aletheia/llm.py`*
- `ALETHEIA_LLM_BASE_URL` (default: `http://localhost:1234/v1`)
- `ALETHEIA_LLM_MODEL` (fallback: `llama3.2`)
- `ALETHEIA_LLM_API_KEY` (fallback: `local`)
- `ALETHEIA_EMBED_BASE_URL` (default: `http://localhost:1234/v1`)
- `ALETHEIA_EMBED_MODEL` (fallback: `nomic-embed-text`)
- `ALETHEIA_EMBED_API_KEY` (fallback: `local`)

### Pipeline & Routing Adjustments
*Defined in `aletheia/evidence.py` and `aletheia/agents/editor.py`*
- `ALETHEIA_LLM_SUMMARY`: Set to `"1"` to allow the LLM to refine the deterministically generated verdict summary.
- `ALETHEIA_CLAIM_VALUE_TOLERANCE`: Float (default: `0.5`). Acceptable absolute delta between claimed magnitude and retrieved API data.

### Web Search & Deep Research Options
*Defined in `aletheia/web_search.py` and `aletheia/evidence.py`*
- `ALETHEIA_WEB_SEARCH_PROVIDER`: `auto`, `google`, `brave`, `duckduckgo`.
- `ALETHEIA_WEB_SEARCH_CHAIN`: Comma-separated list of fallback providers (e.g., `google,brave,duckduckgo`).
- `ALETHEIA_ENABLE_DEEP_RESEARCH`: Set to `"1"` to enable `paper_scholar` retrieval.
- `ALETHEIA_DEEP_RESEARCH_CONF_THRESHOLD`: Float (default: `0.62`). Triggers deep research if aggregate confidence is below this score.
- `ALETHEIA_ENABLE_CRAWL4AI_FALLBACK`: Set to `"1"` to use headless browser scraping instead of raw HTTP GET.

### Evidence Limits & Budgeting
- `ALETHEIA_SOURCE_BUDGET_PER_RUN`: Comma-separated key:value limits (e.g., `methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1`).
- `ALETHEIA_WEB_CACHE_HOURS`: Integer (default: `24`).
- `ALETHEIA_PAPER_CACHE_HOURS`: Integer (default: `48`).

### External API Keys (Optional)
Required only if specific EvidenceSources are invoked:
- `GOOGLE_CSE_API_KEY` & `GOOGLE_CSE_CX`: Required for Google Web Search.
- `BRAVE_SEARCH_API_KEY`: Required for Brave Web Search.
- `SERPAPI_API_KEY`: Required for Google Scholar (Deep Research).
- `FRED_API_KEY`: Required for St. Louis Fed API connector.
- `CENSUS_API_KEY`: Required for Census ACS API connector.