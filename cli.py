#!/usr/bin/env python
"""ALETHEIA CLI - Methodology-Aware Policy Intelligence."""

import asyncio
import sys
import json
import argparse
import importlib.util
import os

from aletheia.agents.orchestrator import OrchestratorAgent
from aletheia.db import test_connection
from aletheia.retrieval_store import RetrievalStore


BLUE = "\033[94m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
GRAY = "\033[90m"
RESET = "\033[0m"
BOLD = "\033[1m"


def print_verdict(verdict):
    """Pretty-print a verdict."""
    status_colors = {
        "supported": GREEN,
        "partially_supported": YELLOW,
        "misleading": RED,
        "insufficient_data": GRAY,
    }
    color = status_colors.get(verdict.status.value, RESET)

    print(f"\n{BOLD}{'='*60}{RESET}")
    print(f"{BOLD}VERDICT: {color}{verdict.status.value.upper()}{RESET}")
    print(f"{'='*60}")
    print(f"{GRAY}Severity: {verdict.severity.value} | Comparability: {verdict.comparability.value}{RESET}")

    print(f"\n{BOLD}Claim:{RESET}")
    print(f"  {verdict.claim.original_text}")

    print(f"\n{BOLD}Summary:{RESET}")
    print(f"  {verdict.summary}")

    if verdict.breaks_found:
        print(f"\n{BOLD}Methodology Breaks Found ({len(verdict.breaks_found)}):{RESET}")
        for b in verdict.breaks_found[:5]:
            date_str = b.effective_date.isoformat() if b.effective_date else "unknown date"
            print(f"  {YELLOW}•{RESET} [{date_str}] {b.change_type.value}")
            print(f"    {b.description[:100]}...")
            if b.impact_estimate:
                print(f"    {GRAY}Impact: {b.impact_estimate}{RESET}")

    if verdict.caveats:
        print(f"\n{BOLD}Caveats:{RESET}")
        for c in verdict.caveats:
            print(f"  {GRAY}• {c}{RESET}")

    if verdict.methodology_vs_real:
        print(f"\n{BOLD}Methodology vs Reality (estimate):{RESET}")
        mvr = verdict.methodology_vs_real
        print(
            f"  methodology_share={mvr.get('methodology_share_estimate')} "
            f"real_component={mvr.get('real_component_estimate')}"
        )

    if verdict.sources:
        print(f"\n{BOLD}Sources:{RESET}")
        for s in verdict.sources[:3]:
            print(f"  {BLUE}{s}{RESET}")

    if verdict.evidence_snippets:
        print(f"\n{BOLD}Evidence snippets:{RESET}")
        for snippet in verdict.evidence_snippets[:2]:
            print(f"  {GRAY}• {snippet}{RESET}")

    print(f"\n{GRAY}Confidence: {verdict.confidence:.0%}{RESET}")
    print()


async def interactive_mode():
    """Run interactive CLI."""
    print(f"{BOLD}ALETHEIA{RESET} - Methodology-Aware Policy Intelligence")
    print(f"{GRAY}Type a policy claim to analyze, or 'quit' to exit.{RESET}\n")

    orchestrator = OrchestratorAgent()

    try:
        while True:
            try:
                claim = input(f"{BLUE}claim>{RESET} ").strip()
            except EOFError:
                break

            if not claim:
                continue
            if claim.lower() in ("quit", "exit", "q"):
                break

            if claim.lower() == "trace":
                # Show last trace
                print(json.dumps(orchestrator.get_trace(), indent=2, default=str))
                continue

            print(f"\n{GRAY}Analyzing...{RESET}")
            verdict = await orchestrator.process_claim(claim)
            print_verdict(verdict)

    finally:
        await orchestrator.close()
        print("Goodbye.")


async def single_claim(claim: str):
    """Process a single claim and exit."""
    orchestrator = OrchestratorAgent()
    try:
        verdict = await orchestrator.process_claim(claim)
        print_verdict(verdict)
        # Also output JSON for programmatic use
        print(f"\n{GRAY}JSON output:{RESET}")
        print(verdict.model_dump_json(indent=2))
    finally:
        await orchestrator.close()


def format_retrieval_stats(stats: dict) -> str:
    """Render retrieval observability stats for terminal output."""
    if stats.get("error"):
        lines = [f"{RED}retrieval stats unavailable:{RESET} {stats['error']}"]
        diagnosis = stats.get("diagnosis") or {}
        if diagnosis:
            lines.append(f"{GRAY}db_url: {diagnosis.get('db_url_redacted', 'n/a')}{RESET}")
            hints = diagnosis.get("hints") or []
            if hints:
                lines.append(f"{BOLD}Likely fixes:{RESET}")
                for hint in hints[:4]:
                    lines.append(f"- {hint}")
        return "\n".join(lines)

    summary = stats.get("summary") or {}
    window_hours = stats.get("window_hours")
    lines = [
        f"{BOLD}Retrieval Stats (last {window_hours}h){RESET}",
        (
            f"runs={summary.get('total_runs', 0)} "
            f"completed={summary.get('completed_runs', 0)} "
            f"non_completed={summary.get('non_completed_runs', 0)}"
        ),
        (
            f"linked_docs={summary.get('linked_docs', 0)} "
            f"cache_hits={summary.get('cache_hits', 0)} "
            f"cache_hit_rate={summary.get('cache_hit_rate', 0.0):.1%}"
        ),
        (
            f"distinct_sources={summary.get('distinct_sources', 0)} "
            f"avg_aggregate_confidence={summary.get('avg_aggregate_confidence', 0.0):.3f}"
        ),
        f"provider_budget_skips={summary.get('provider_budget_skips', 0)}",
    ]

    source_rows = stats.get("sources") or []
    if source_rows:
        lines.append(f"\n{BOLD}By Source:{RESET}")
        for row in source_rows[:10]:
            lines.append(
                (
                    f"- {row.get('source_id')}: docs={row.get('doc_count', 0)} "
                    f"cache_hits={row.get('cache_hits', 0)} "
                    f"avg_conf={row.get('avg_confidence', 0.0)}"
                )
            )

    recent_runs = stats.get("recent_runs") or []
    if recent_runs:
        lines.append(f"\n{BOLD}Recent Runs:{RESET}")
        for row in recent_runs:
            lines.append(
                (
                    f"- #{row.get('id')} {row.get('claim_dataset') or 'unknown'} / "
                    f"{row.get('claim_indicator') or 'unknown'} "
                    f"status={row.get('status')} "
                    f"evidence={row.get('evidence_count', 0)} "
                    f"fallback={row.get('fallback_used')} "
                    f"deep_research={row.get('deep_research_used')} "
                    f"budget_skips={row.get('provider_budget_skips', 0)} "
                    f"conf={float(row.get('aggregate_confidence', 0.0)):.3f}"
                )
            )

    return "\n".join(lines)


async def show_retrieval_stats(hours: int, limit: int):
    """Print retrieval history and cache hit rates."""
    store = RetrievalStore()
    stats = await store.get_stats(hours=hours, limit=limit)
    print(format_retrieval_stats(stats))


async def show_db_doctor():
    """Run DB diagnostics and print actionable hints."""
    result = await test_connection()
    if result.get("ok"):
        print(f"{GREEN}DB connection OK{RESET}")
        print(f"{GRAY}db_url: {result.get('db_url_redacted')}{RESET}")
        print(
            (
                f"pgvector={result.get('pgvector_enabled')} "
                f"pgai={result.get('pgai_installed')} "
                f"tables={len(result.get('tables') or [])}"
            )
        )
        print()
        print(format_capability_matrix())
        return

    print(f"{RED}DB connection FAILED{RESET}")
    print(f"{GRAY}db_url: {result.get('db_url_redacted', 'n/a')}{RESET}")
    print(f"category={result.get('category', 'unknown')}")
    print(f"error={result.get('message', 'n/a')}")
    for hint in result.get("hints", [])[:6]:
        print(f"- {hint}")

    print()
    print(format_capability_matrix())


def _capability_rows() -> list[tuple[str, bool, str]]:
    crawl4ai_installed = importlib.util.find_spec("crawl4ai") is not None
    crawl4ai_enabled = os.environ.get("ALETHEIA_ENABLE_CRAWL4AI_FALLBACK", "0") == "1"
    local_llm_endpoint = os.environ.get("ALETHEIA_LLM_BASE_URL", "http://mini:8080")

    google_ready = bool(
        os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX")
    )
    brave_ready = bool(os.environ.get("BRAVE_SEARCH_API_KEY"))
    serp_ready = bool(os.environ.get("SERPAPI_API_KEY"))
    openai_ready = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("ALETHEIA_OPENAI_API_KEY")
    )

    return [
        ("local_llm", True, f"endpoint={local_llm_endpoint}"),
        ("cloud_llm_openai", openai_ready, "optional API key"),
        ("web_search_duckduckgo", True, "no key required"),
        ("web_search_google_cse", google_ready, "optional API key pair"),
        ("web_search_brave", brave_ready, "optional API key"),
        ("scholar_serpapi", serp_ready, "optional API key"),
        (
            "crawl4ai_fallback",
            crawl4ai_enabled and crawl4ai_installed,
            (
                "enabled+installed"
                if crawl4ai_enabled and crawl4ai_installed
                else "set ALETHEIA_ENABLE_CRAWL4AI_FALLBACK=1 and install crawl4ai"
            ),
        ),
        ("fred_api_enhanced", bool(os.environ.get("FRED_API_KEY")), "optional API key"),
        ("census_api_enhanced", bool(os.environ.get("CENSUS_API_KEY")), "optional API key"),
    ]


def format_capability_matrix() -> str:
    rows = _capability_rows()
    lines = [f"{BOLD}Capability Matrix{RESET}"]
    for name, enabled, note in rows:
        state = f"{GREEN}enabled{RESET}" if enabled else f"{YELLOW}optional/off{RESET}"
        lines.append(f"- {name}: {state} ({note})")
    return "\n".join(lines)


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "retrieval-stats":
        parser = argparse.ArgumentParser(
            prog="cli.py retrieval-stats",
            description="Show retrieval history and cache metrics.",
        )
        parser.add_argument("--hours", type=int, default=24, help="Rolling time window.")
        parser.add_argument("--limit", type=int, default=15, help="Recent runs to show.")
        args = parser.parse_args(sys.argv[2:])
        asyncio.run(show_retrieval_stats(args.hours, args.limit))
        return

    if len(sys.argv) > 1 and sys.argv[1] == "db-doctor":
        asyncio.run(show_db_doctor())
        return

    if len(sys.argv) > 1 and sys.argv[1] in {"--help", "-h"}:
        print("Usage:")
        print("  uv run python cli.py                    # interactive")
        print("  uv run python cli.py \"<claim text>\"       # single claim")
        print("  uv run python cli.py retrieval-stats [--hours 24 --limit 15]")
        print("  uv run python cli.py db-doctor")
        return

    if len(sys.argv) > 1:
        claim = " ".join(sys.argv[1:])
        asyncio.run(single_claim(claim))
        return

    asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
