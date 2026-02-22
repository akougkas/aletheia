# Web Search & Fallback Strategies (AI Context)

**Target Audience**: AI coding assistants extending the web crawler, adding search providers, or modifying allowlists.

## Provider Topology (`aletheia/web_search.py`)
Web search is used strictly when the local Postgres `knowledge_graph` and live `data_api` connectors yield sparse results.

### 1. Standard Search Providers
Defined via `ALETHEIA_WEB_SEARCH_PROVIDER`.
- **Google CSE**: High quality, strict rate limits.
- **Brave Search**: Excellent fallback, good general index.
- **DuckDuckGo**: Free, HTML scraping-based fallback.

### 2. Deep Research (`paper_scholar`)
The `ScholarPaperEvidenceSource` executes a specialized Google Scholar query via the SERP API.
- **Trigger**: Only invoked if `ALETHEIA_ENABLE_DEEP_RESEARCH=1` and `aggregate_confidence` is below the configured threshold.
- **Allowlist Filtering**: Managed by `ALETHEIA_SCHOLAR_ALLOWLIST_MODE` (`strict`, `balanced`, `open`) and `ALETHEIA_SCHOLAR_ALLOW_DOMAINS` (default: `.edu`, `.org`, `nber.org`, etc.).
  - `strict`: Excludes results not matching the domain list.
  - `balanced`: Keeps results, but marks them as `untrusted` in metadata, causing the `EvidenceAggregator` to heavily penalize their confidence score.

### 3. Page Fetching & Crawl4AI
After search results are returned, ALETHEIA attempts to fetch the raw HTML/Markdown of the target URLs.
- **Standard Fetch**: Uses `httpx` to grab raw HTML, passing it through `BeautifulSoup` to strip boilerplate tags and extract `<p>` tags.
- **Crawl4AI Fallback**: If `ALETHEIA_ENABLE_CRAWL4AI_FALLBACK=1`, the system uses `crawl4ai` (headless Playwright) to render JS-heavy pages and extract clean Markdown. This is slower but essential for modern official statistic portals (e.g., BLS or Eurostat dynamic dashboards).

## Circuit Breakers
To prevent rate-limit bans or infinite hangs:
- Search providers maintain internal failure counters.
- If consecutive failures exceed `ALETHEIA_WEB_CIRCUIT_FAILURE_THRESHOLD` (default: 3), the provider enters a cooldown state (`ALETHEIA_WEB_CIRCUIT_COOLDOWN_SECONDS`, default: 120) and immediately returns empty results.