#!/usr/bin/env python
"""ALETHEIA CLI - Methodology-aware policy intelligence."""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
import os
import sys
from typing import Any

import httpx

from aletheia.agents.orchestrator import OrchestratorAgent
from aletheia.db import get_db_url, test_connection, close_db
from aletheia.retrieval_store import RetrievalStore
from aletheia.runtime_profiles import (
    PROFILE_CHOICES,
    ResolvedRuntimeProfile,
    apply_runtime_profile,
)
from aletheia.tui import TerminalUI


def _capability_rows() -> list[tuple[str, bool, str]]:
    crawl4ai_installed = importlib.util.find_spec("crawl4ai") is not None
    local_llm_endpoint = os.environ.get("ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234")
    embed_endpoint = os.environ.get(
        "ALETHEIA_EMBED_BASE_URL",
        os.environ.get("ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234"),
    )
    llm_model = os.environ.get("ALETHEIA_LLM_MODEL")
    embed_model = os.environ.get("ALETHEIA_EMBED_MODEL")
    runtime_profile = os.environ.get("ALETHEIA_RUNTIME_PROFILE", "zbook-single")

    google_ready = bool(
        os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX")
    )
    brave_ready = bool(os.environ.get("BRAVE_SEARCH_API_KEY"))
    serp_ready = bool(os.environ.get("SERPAPI_API_KEY"))
    openai_ready = bool(
        os.environ.get("OPENAI_API_KEY") or os.environ.get("ALETHEIA_OPENAI_API_KEY")
    )
    semantic_ready = bool(embed_endpoint)
    semantic_note = "run onboarding/db-doctor to verify embedding views + counts"

    return [
        ("runtime_profile", True, runtime_profile),
        (
            "local_llm",
            True,
            f"endpoint={local_llm_endpoint} model={llm_model or 'server-default'}",
        ),
        (
            "embedding_endpoint",
            bool(embed_endpoint),
            f"endpoint={embed_endpoint} model={embed_model or 'server-default'}",
        ),
        ("cloud_llm_openai", openai_ready, "optional API key"),
        ("web_search_duckduckgo", True, "no key required"),
        ("web_search_google_cse", google_ready, "optional API key pair"),
        ("web_search_brave", brave_ready, "optional API key"),
        ("scholar_serpapi", serp_ready, "optional API key"),
        ("semantic_vector_search", semantic_ready, semantic_note),
        (
            "crawl4ai_fallback",
            crawl4ai_installed,
            "installed (core dependency)" if crawl4ai_installed else "missing — reinstall with uv sync",
        ),
        ("fred_api_enhanced", bool(os.environ.get("FRED_API_KEY")), "optional API key"),
        ("census_api_enhanced", bool(os.environ.get("CENSUS_API_KEY")), "optional API key"),
    ]


def _runtime_override_args(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "ALETHEIA_LLM_BASE_URL": getattr(args, "llm_base_url", None),
        "ALETHEIA_LLM_MODEL": getattr(args, "llm_model", None),
        "ALETHEIA_EMBED_BASE_URL": getattr(args, "embed_base_url", None),
        "ALETHEIA_EMBED_MODEL": getattr(args, "embed_model", None),
        "ALETHEIA_DB_URL": getattr(args, "db_url", None),
    }


_CAPABILITY_FRIENDLY = {
    "runtime_profile": "Runtime Profile",
    "local_llm": "Local AI Model",
    "embedding_endpoint": "Embedding Model",
    "cloud_llm_openai": "Cloud AI (OpenAI)",
    "web_search_duckduckgo": "Web Search (DuckDuckGo)",
    "web_search_google_cse": "Web Search (Google)",
    "web_search_brave": "Web Search (Brave)",
    "scholar_serpapi": "Scholar Search",
    "semantic_vector_search": "Knowledge Search",
    "crawl4ai_fallback": "Web Page Reader",
    "fred_api_enhanced": "FRED Economic Data",
    "census_api_enhanced": "US Census Data",
}


def _render_capabilities(ui: TerminalUI) -> None:
    rows = [
        [_CAPABILITY_FRIENDLY.get(name, name),
         "Active" if enabled else "Inactive",
         note]
        for name, enabled, note in _capability_rows()
    ]
    ui.table("Available Capabilities", ["Feature", "Status", "Details"], rows)


def format_capability_matrix() -> str:
    """Render capability matrix in plain-text form (stable test/helper API)."""
    lines = ["Capability Matrix"]
    for name, enabled, note in _capability_rows():
        state = "enabled" if enabled else "optional/off"
        lines.append(f"- {name}: {state} ({note})")
    return "\n".join(lines)


def _render_help(ui: TerminalUI) -> None:
    """Render interactive help with grouped commands."""
    if ui._enabled and ui.console:
        from rich.panel import Panel as RichPanel

        body = (
            "[bold cyan]After a verdict:[/bold cyan]\n"
            "  [bold]details[/bold]    Full breakdown — caveats, data sources, routing, AI reasoning\n"
            "  [bold]trail[/bold]      List all documents and data used as evidence\n"
            "  [bold]trail 3[/bold]    Inspect a specific evidence document by number\n"
            "  [bold]trace[/bold]      See how the AI agents communicated internally\n"
            "\n"
            "[bold cyan]Re-analyze:[/bold cyan]\n"
            "  [bold]!rerun[/bold]     Re-analyze the last claim (useful after config changes)\n"
            "  [bold]!deep[/bold]      Re-analyze with deeper research (searches more sources)\n"
            "  [bold]!deep on[/bold]   Always use deep research for future claims\n"
            "  [bold]!deep off[/bold]  Return to normal research depth\n"
            "\n"
            "[bold cyan]Session:[/bold cyan]\n"
            "  [bold]!mode[/bold]      Show current settings (deep mode, last claim)\n"
            "  [bold]help[/bold]       Show this help\n"
            "  [bold]quit[/bold]       Exit Aletheia"
        )
        ui.console.print(RichPanel(body, title="[bold]Commands[/bold]",
                                   border_style="cyan", padding=(1, 2)))
    else:
        print("\n--- Commands ---")
        print("  After a verdict:")
        print("    details    Full breakdown — caveats, data sources, routing, AI reasoning")
        print("    trail      List all documents and data used as evidence")
        print("    trail 3    Inspect a specific evidence document by number")
        print("    trace      See how the AI agents communicated internally")
        print("  Re-analyze:")
        print("    !rerun     Re-analyze the last claim")
        print("    !deep      Re-analyze with deeper research")
        print("    !deep on   Always use deep research for future claims")
        print("    !deep off  Return to normal research depth")
        print("  Session:")
        print("    !mode      Show current settings")
        print("    help       Show this help")
        print("    quit       Exit Aletheia")
        print("---")


def _render_verdict(ui: TerminalUI, verdict, *, verbose: bool = False) -> None:
    """Render verdict — compact by default, full detail when verbose=True."""
    if ui._enabled and ui.console:
        _render_verdict_rich(ui, verdict, verbose=verbose)
    else:
        _render_verdict_plain(ui, verdict, verbose=verbose)


def _render_verdict_rich(ui: TerminalUI, verdict, *, verbose: bool = False) -> None:
    from rich.panel import Panel as RichPanel

    status_str = ui.style_status(verdict.status.value)
    conf_str = ui.style_confidence(verdict.confidence)
    sev_str = ui.style_severity(verdict.severity.value)
    comp_str = ui.style_comparability(verdict.comparability.value)
    conf_bar = ui.confidence_bar(verdict.confidence)

    # Status-aware border color
    border = {"SUPPORTED": "green", "PARTIALLY_SUPPORTED": "yellow",
              "MISLEADING": "red"}.get(verdict.status.value, "cyan")

    lines = [
        f"{status_str}  ({conf_str} confidence)    severity: {sev_str}",
        f"comparability: {comp_str}",
        f"confidence  {conf_bar}",
        "",
        f"{verdict.summary}",
    ]

    # Human-readable interpretation
    interpretation = _verdict_interpretation(verdict.status.value, verdict.confidence)
    if interpretation:
        lines.append("")
        lines.append(f"[dim italic]{interpretation}[/dim italic]")

    # Top breaks (max 3 in compact, 5 in verbose)
    if verdict.breaks_found:
        limit = 5 if verbose else 3
        lines.append("")
        n = len(verdict.breaks_found)
        lines.append(f"[bold]Detected {n} statistical methodology change(s):[/bold]")
        for change in verdict.breaks_found[:limit]:
            date_str = change.effective_date.isoformat() if change.effective_date else "unknown"
            ctype = change.change_type.value.replace("_", " ")
            impact = (change.impact_estimate or "")[:60]
            lines.append(f"  {date_str}  [dim]{ctype}[/dim] — {impact}")
        if n > limit:
            lines.append(f"  [dim]... and {n - limit} more[/dim]")

    # Decomposition bar (when available)
    if verdict.methodology_vs_real:
        mvr = verdict.methodology_vs_real
        share = mvr.get("methodology_share_estimate")
        if isinstance(share, (int, float)) and 0 < share < 1:
            m_line, r_line = ui.decomposition_bar(share)
            lines.append("")
            lines.append("[bold]Change decomposition:[/bold]")
            lines.append(f"  {m_line}")
            lines.append(f"  {r_line}")

    if not verbose:
        lines.append("")
        lines.append("[dim]Type 'details' for full analysis, 'trail' for evidence sources[/dim]")

    body = "\n".join(lines)
    assert ui.console is not None
    ui.console.print(
        RichPanel(
            body,
            title="[bold]Verdict[/bold]",
            border_style=border,
            expand=True,
            padding=(1, 2),
        )
    )

    if verbose:
        _render_verdict_detail_sections(ui, verdict)


def _verdict_interpretation(status: str, confidence: float) -> str | None:
    """Return a plain-English sentence explaining what the verdict means."""
    if status == "SUPPORTED" and confidence >= 0.8:
        return "The claim appears well-supported by the data, with no major methodology issues."
    if status == "SUPPORTED":
        return "The claim is supported, though confidence is moderate — some caveats may apply."
    if status == "PARTIALLY_SUPPORTED":
        return "Part of the claim checks out, but important nuances or methodology changes affect the full picture."
    if status == "MISLEADING" and confidence >= 0.8:
        return "The claim is likely misleading — methodology changes significantly distort the numbers being compared."
    if status == "MISLEADING":
        return "The claim appears misleading, though confidence is limited by available evidence."
    if status == "INSUFFICIENT_DATA":
        return "Not enough data was found to confidently verify or refute this claim."
    return None


def _render_verdict_plain(ui: TerminalUI, verdict, *, verbose: bool = False) -> None:
    status = verdict.status.value
    conf = f"{verdict.confidence:.0%}"
    sev = verdict.severity.value
    comp = verdict.comparability.value
    conf_bar = ui.confidence_bar_plain(verdict.confidence)

    print(f"\n--- Verdict ---")
    print(f"  {status}  ({conf} confidence)    severity: {sev}")
    print(f"  comparability: {comp}")
    print(f"  confidence  {conf_bar}")
    print(f"\n  {verdict.summary}")

    interpretation = _verdict_interpretation(status, verdict.confidence)
    if interpretation:
        print(f"\n  {interpretation}")

    if verdict.breaks_found:
        limit = 5 if verbose else 3
        n = len(verdict.breaks_found)
        print(f"\n  Detected {n} statistical methodology change(s):")
        for change in verdict.breaks_found[:limit]:
            date_str = change.effective_date.isoformat() if change.effective_date else "unknown"
            ctype = change.change_type.value.replace("_", " ")
            impact = (change.impact_estimate or "")[:60]
            print(f"    {date_str}  {ctype} — {impact}")
        if n > limit:
            print(f"    ... and {n - limit} more")

    if not verbose:
        print("\n  Type 'details' for full analysis, 'trail' for evidence sources")
    else:
        _render_verdict_detail_sections(ui, verdict)
    print("---")


def _render_verdict_detail_sections(ui: TerminalUI, verdict) -> None:
    """Render the verbose sections: decomposition, caveats, sources, snippets."""
    if verdict.methodology_vs_real:
        mvr = verdict.methodology_vs_real
        ui.kv_table(
            "Change Decomposition (estimate)",
            [
                ("Methodology share", mvr.get("methodology_share_estimate")),
                ("Methodology component", mvr.get("methodology_component_estimate")),
                ("Real change component", mvr.get("real_component_estimate")),
            ],
        )

    if verdict.breaks_found:
        rows: list[list[str]] = []
        for change in verdict.breaks_found:
            rows.append([
                change.effective_date.isoformat() if change.effective_date else "unknown",
                change.change_type.value.replace("_", " "),
                (change.impact_estimate or "")[:80],
            ])
        ui.table("All Methodology Changes", ["Date", "Type", "Impact"], rows)

    if verdict.caveats:
        ui.bullet_list("Caveats & Limitations", verdict.caveats)

    if verdict.sources:
        ui.bullet_list("Data Sources Used", [str(source) for source in verdict.sources[:5]])

    if verdict.evidence_snippets:
        ui.bullet_list("Key Evidence", [str(item) for item in verdict.evidence_snippets[:3]])


def _render_run_details(ui: TerminalUI, run: dict[str, Any]) -> None:
    routing = run.get("routing_plan")
    if isinstance(routing, dict):
        sources = routing.get("source_ids") or []
        fallback = routing.get("fallback_source_id") or "none"
        deep = routing.get("deep_research_source_ids") or []
        ui.kv_table(
            "How Aletheia Searched (Routing Plan)",
            [
                ("Claim type", routing.get("claim_type")),
                ("Sources queried", ", ".join(str(s) for s in sources) if sources else "none"),
                ("Backup source", fallback),
                ("Deep research sources", ", ".join(str(s) for s in deep) if deep else "none"),
            ],
        )

    source_outputs = run.get("source_outputs")
    if isinstance(source_outputs, list) and source_outputs:
        rows = []
        for output in source_outputs:
            if not isinstance(output, dict):
                continue
            analysis = output.get("analysis") if isinstance(output.get("analysis"), dict) else {}
            mode_bits = []
            if analysis.get("break_search_mode"):
                mode_bits.append(f"break={analysis.get('break_search_mode')}")
            if analysis.get("doc_search_mode"):
                mode_bits.append(f"docs={analysis.get('doc_search_mode')}")
            rows.append(
                [
                    output.get("source_id"),
                    output.get("doc_count", 0),
                    output.get("break_count", 0),
                    output.get("error_count", 0),
                    " | ".join(
                        bit
                        for bit in [
                            ", ".join(str(err) for err in (output.get("errors") or [])[:1]),
                            ", ".join(mode_bits),
                        ]
                        if bit
                    ),
                ]
            )
        if rows:
            ui.table(
                "Source Results",
                ["Source", "Documents", "Changes Found", "Errors", "Notes"],
                rows,
            )

    analysis = run.get("analysis") if isinstance(run.get("analysis"), dict) else {}
    claim_value_check = analysis.get("claim_value_check") if isinstance(
        analysis.get("claim_value_check"), dict
    ) else {}
    structural_break = analysis.get("structural_break_detected") if isinstance(
        analysis.get("structural_break_detected"), dict
    ) else {}

    fallback_used = analysis.get("fallback_used", run.get("fallback_used"))
    deep_used = analysis.get("deep_research_used", run.get("deep_research_used"))
    agg_conf = analysis.get("evidence_aggregate_confidence", run.get("aggregate_confidence", 0.0))
    within_tol = claim_value_check.get("within_tolerance")
    delta = claim_value_check.get("delta")
    struct_break = structural_break.get("detected")
    budget_skips = analysis.get("provider_budget_skips")

    signal_rows: list[tuple[str, Any]] = [
        ("Used backup sources", "Yes" if fallback_used else "No"),
        ("Used deep research", "Yes" if deep_used else "No"),
        ("Overall evidence confidence", f"{float(agg_conf):.1%}" if agg_conf else "n/a"),
    ]
    if within_tol is not None:
        signal_rows.append(("Claimed value matches data", "Yes" if within_tol else "No"))
    if delta is not None:
        signal_rows.append(("Difference from actual", str(delta)))
    if struct_break is not None:
        signal_rows.append(("Statistical break detected", "Yes" if struct_break else "No"))
    if budget_skips:
        signal_rows.append(("Sources skipped (budget limit)", str(budget_skips)))

    ui.kv_table("Analysis Signals", signal_rows)


def _render_evidence_trail(ui: TerminalUI, run: dict[str, Any]) -> None:
    docs = run.get("evidence_docs")
    if not isinstance(docs, list) or not docs:
        ui.warning("No evidence documents found yet. Run a claim first.")
        return
    rows = []
    for idx, row in enumerate(docs[:20], start=1):
        if not isinstance(row, dict):
            continue
        raw_conf = row.get("confidence_score", 0.0)
        try:
            conf_value = float(raw_conf)
        except (TypeError, ValueError):
            conf_value = 0.0
        rows.append(
            [
                idx,
                row.get("source_id", "unknown"),
                f"{conf_value:.0%}",
                row.get("title", "Untitled"),
                (row.get("url") or "")[:50],
            ]
        )
    ui.table("Evidence Documents", ["#", "Source", "Relevance", "Title", "URL"], rows)
    ui.hint("Type 'trail 3' to inspect document #3 in detail.")


def _render_evidence_doc(ui: TerminalUI, run: dict[str, Any], index: int) -> None:
    docs = run.get("evidence_docs")
    if not isinstance(docs, list) or not docs:
        ui.warning("No evidence documents available. Run a claim first.")
        return
    if index < 1 or index > len(docs):
        ui.warning(f"Document #{index} doesn't exist. Choose a number between 1 and {len(docs)}.")
        return
    doc = docs[index - 1]
    if not isinstance(doc, dict):
        ui.warning("Selected evidence entry is not structured.")
        return

    raw_rel = doc.get("relevance_score", 0.0)
    raw_conf = doc.get("confidence_score", 0.0)
    try:
        rel_str = f"{float(raw_rel):.0%}"
    except (TypeError, ValueError):
        rel_str = str(raw_rel)
    try:
        conf_str = f"{float(raw_conf):.0%}"
    except (TypeError, ValueError):
        conf_str = str(raw_conf)

    ui.kv_table(
        f"Evidence Document #{index}",
        [
            ("Source", doc.get("source_id")),
            ("Title", doc.get("title")),
            ("URL", doc.get("url") or "n/a"),
            ("Relevance", rel_str),
            ("Confidence", conf_str),
        ],
    )
    content = str(doc.get("content") or "").strip()
    if content:
        preview = content[:1200] + ("..." if len(content) > 1200 else "")
        ui.thinking_block(preview, collapsed_label="Document Content")


def _render_trace(ui: TerminalUI, trace: list[dict[str, Any]]) -> None:
    rows = []
    for message in trace[-25:]:
        rows.append(
            [
                message.get("timestamp"),
                message.get("sender"),
                message.get("receiver"),
                message.get("msg_type"),
                str(message.get("payload", ""))[:100],
            ]
        )
    if rows:
        ui.table("Agent Communication Log", ["Time", "From", "To", "Type", "Content"], rows)
        ui.hint("This shows how the AI agents coordinated to analyze your claim.")
    else:
        ui.warning("No trace captured yet. Run a claim first.")


def _render_retrieval_stats(ui: TerminalUI, stats: dict[str, Any]) -> None:
    if stats.get("error"):
        ui.error(f"Could not load retrieval stats: {stats['error']}")
        diagnosis = stats.get("diagnosis") or {}
        if diagnosis:
            ui.kv_table(
                "Connection Details",
                [("Database address", diagnosis.get("db_url_redacted", "n/a"))],
            )
            hints = diagnosis.get("hints") or []
            if hints:
                ui.bullet_list("How To Fix", [str(hint) for hint in hints[:6]])
        return

    summary = stats.get("summary") or {}
    hours = stats.get("window_hours", 24)
    ui.kv_table(
        f"Analysis History (last {hours} hours)",
        [
            ("Claims analyzed", summary.get("total_runs", 0)),
            ("Completed", summary.get("completed_runs", 0)),
            ("Incomplete", summary.get("non_completed_runs", 0)),
            ("Evidence documents found", summary.get("linked_docs", 0)),
            ("Cached results reused", summary.get("cache_hits", 0)),
            ("Cache hit rate", f"{summary.get('cache_hit_rate', 0.0):.1%}"),
            ("Distinct data sources", summary.get("distinct_sources", 0)),
            ("Average confidence", f"{summary.get('avg_aggregate_confidence', 0.0):.0%}"),
            ("Sources skipped (budget)", summary.get("provider_budget_skips", 0)),
        ],
    )

    source_rows = stats.get("sources") or []
    if source_rows:
        rows = [
            [
                row.get("source_id"),
                row.get("doc_count", 0),
                row.get("cache_hits", 0),
                f"{float(row.get('avg_confidence', 0.0)):.0%}",
            ]
            for row in source_rows[:12]
        ]
        ui.table("Results By Source", ["Source", "Documents", "Cached", "Avg Confidence"], rows)

    recent_runs = stats.get("recent_runs") or []
    if recent_runs:
        rows = [
            [
                row.get("id"),
                row.get("claim_dataset") or "unknown",
                row.get("claim_indicator") or "unknown",
                row.get("status"),
                row.get("evidence_count", 0),
                "Yes" if row.get("fallback_used") else "No",
                "Yes" if row.get("deep_research_used") else "No",
                f"{float(row.get('aggregate_confidence', 0.0)):.0%}",
            ]
            for row in recent_runs
        ]
        ui.table(
            "Recent Analyses",
            ["ID", "Dataset", "Indicator", "Status", "Evidence", "Backup Used", "Deep", "Confidence"],
            rows,
        )


def format_retrieval_stats(stats: dict[str, Any]) -> str:
    """Render retrieval observability stats in plain-text form."""
    if stats.get("error"):
        lines = [f"retrieval stats unavailable: {stats['error']}"]
        diagnosis = stats.get("diagnosis") or {}
        if diagnosis:
            lines.append(f"db_url: {diagnosis.get('db_url_redacted', 'n/a')}")
            hints = diagnosis.get("hints") or []
            if hints:
                lines.append("Likely fixes:")
                for hint in hints[:6]:
                    lines.append(f"- {hint}")
        return "\n".join(lines)

    summary = stats.get("summary") or {}
    lines = [
        f"Retrieval Stats (last {stats.get('window_hours')}h)",
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

    sources = stats.get("sources") or []
    if sources:
        lines.append("")
        lines.append("By Source:")
        for row in sources[:12]:
            lines.append(
                (
                    f"- {row.get('source_id')}: docs={row.get('doc_count', 0)} "
                    f"cache_hits={row.get('cache_hits', 0)} "
                    f"avg_conf={row.get('avg_confidence', 0.0)}"
                )
            )

    recent_runs = stats.get("recent_runs") or []
    if recent_runs:
        lines.append("")
        lines.append("Recent Runs:")
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


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return (response.text or "").strip()[:220]
    if isinstance(payload, dict):
        err = payload.get("error")
        if isinstance(err, dict):
            message = err.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
        message = payload.get("message")
        if isinstance(message, str) and message.strip():
            return message.strip()
    return (response.text or "").strip()[:220]


def _llm_guidance_from_error(status: int | None, detail: str, *, kind: str) -> list[str]:
    lowered = detail.lower()
    hints: list[str] = []

    if "no models loaded" in lowered:
        hints.append(
            "Model server is reachable but no model is loaded. Load a chat/embedding model in LM Studio or Ollama first."
        )
    if "model" in lowered and "required" in lowered:
        if kind == "chat":
            hints.append("Set ALETHEIA_LLM_MODEL or pass --llm-model for endpoints that require explicit model IDs.")
        else:
            hints.append("Set ALETHEIA_EMBED_MODEL or pass --embed-model for endpoints that require explicit model IDs.")
    if "connection refused" in lowered or "name or service not known" in lowered:
        hints.append("Verify endpoint host/port and that the model runtime is listening on that interface.")

    if kind == "embeddings" and status == 501:
        hints.append(
            "Embedding endpoint is unsupported on this server. Point ALETHEIA_EMBED_BASE_URL to an embedding-capable LM Studio/Ollama endpoint."
        )

    return hints


async def _probe_openai_health(
    *,
    base_url: str,
    mode: str,
    model: str | None,
    api_key: str | None = None,
) -> dict[str, Any]:
    endpoint = base_url.rstrip("/")
    payload: dict[str, Any] = {
        "endpoint": endpoint,
        "model": model,
        "models_ok": False,
        "models": [],
        "model_ready": False,
        "request_ok": False,
        "status": None,
        "errors": [],
        "hints": [],
        "unsupported": False,
    }

    headers = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            models_resp = await client.get(f"{endpoint}/v1/models")
            payload["models_ok"] = 200 <= models_resp.status_code < 300
            if payload["models_ok"]:
                models_payload = models_resp.json()
                if isinstance(models_payload, dict) and isinstance(models_payload.get("data"), list):
                    payload["models"] = [
                        str(row.get("id"))
                        for row in models_payload["data"]
                        if isinstance(row, dict) and row.get("id")
                    ]
            else:
                detail = _error_detail(models_resp)
                payload["errors"].append(f"models:{models_resp.status_code} {detail}")
                payload["hints"].extend(_llm_guidance_from_error(models_resp.status_code, detail, kind=mode))

            known_models = payload["models"]
            if known_models:
                if model:
                    payload["model_ready"] = model in known_models
                    if not payload["model_ready"]:
                        payload["errors"].append(
                            f"model_not_found:{model} (available: {', '.join(known_models[:8])})"
                        )
                else:
                    payload["model_ready"] = True
            elif payload["models_ok"]:
                payload["errors"].append("no_models_loaded")
                payload["hints"].append(
                    "Endpoint responded to /v1/models but returned zero models; load at least one model."
                )

            if mode == "chat":
                request_payload: dict[str, Any] = {
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                    "temperature": 0,
                }
                if model:
                    request_payload["model"] = model
                call_resp = await client.post(
                    f"{endpoint}/v1/chat/completions",
                    json=request_payload,
                )
            else:
                request_payload = {"input": "healthcheck"}
                if model:
                    request_payload["model"] = model
                call_resp = await client.post(
                    f"{endpoint}/v1/embeddings",
                    json=request_payload,
                )

            payload["status"] = call_resp.status_code
            payload["request_ok"] = 200 <= call_resp.status_code < 300
            if not payload["request_ok"]:
                detail = _error_detail(call_resp)
                payload["errors"].append(f"{mode}:{call_resp.status_code} {detail}")
                payload["hints"].extend(_llm_guidance_from_error(call_resp.status_code, detail, kind=mode))
                if mode == "embeddings" and call_resp.status_code == 501:
                    payload["unsupported"] = True
    except Exception as exc:  # noqa: BLE001
        detail = str(exc)
        payload["errors"].append(detail)
        payload["hints"].extend(_llm_guidance_from_error(None, detail, kind=mode))

    # Preserve insertion order while removing duplicates.
    payload["hints"] = list(dict.fromkeys(payload["hints"]))
    return payload


async def _check_llm_health() -> dict[str, Any]:
    chat_url = os.environ.get("ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234")
    embed_url = os.environ.get(
        "ALETHEIA_EMBED_BASE_URL",
        chat_url,
    )
    chat_model = os.environ.get("ALETHEIA_LLM_MODEL")
    embed_model = os.environ.get("ALETHEIA_EMBED_MODEL") or chat_model
    chat_key = os.environ.get("ALETHEIA_LLM_API_KEY")
    embed_key = os.environ.get("ALETHEIA_EMBED_API_KEY")

    chat_result, embed_result = await asyncio.gather(
        _probe_openai_health(
            base_url=chat_url,
            mode="chat",
            model=chat_model,
            api_key=chat_key,
        ),
        _probe_openai_health(
            base_url=embed_url,
            mode="embeddings",
            model=embed_model,
            api_key=embed_key,
        ),
    )

    return {
        "chat": chat_result,
        "embeddings": embed_result,
        "chat_ok": bool(chat_result.get("request_ok") and chat_result.get("model_ready")),
        "embeddings_ok": bool(
            embed_result.get("request_ok") and embed_result.get("model_ready")
        ),
    }


async def _safe_llm_check(timeout_seconds: float = 15.0) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(_check_llm_health(), timeout=timeout_seconds)
    except TimeoutError:
        timeout_msg = f"LLM diagnostic timed out after {timeout_seconds:.0f}s."
        return {
            "chat_ok": False,
            "embeddings_ok": False,
            "chat": {
                "endpoint": os.environ.get("ALETHEIA_LLM_BASE_URL", "n/a"),
                "errors": [timeout_msg],
                "hints": [
                    "Check that chat endpoint is reachable and responsive.",
                ],
            },
            "embeddings": {
                "endpoint": os.environ.get(
                    "ALETHEIA_EMBED_BASE_URL",
                    os.environ.get("ALETHEIA_LLM_BASE_URL", "n/a"),
                ),
                "errors": [timeout_msg],
                "hints": [
                    "Check that embeddings endpoint is reachable and supports /v1/embeddings.",
                ],
                "unsupported": False,
            },
        }


async def interactive_mode(ui: TerminalUI):
    """Run interactive CLI session."""
    ui.banner(
        "ALETHEIA — Policy Claim Analyzer",
        (
            "Enter a policy claim and Aletheia will check it against official data,\n"
            "detect methodology changes, and tell you how trustworthy the numbers are.\n\n"
            "  Example: \"The US poverty rate increased by 3% in 2020\"\n\n"
            "Type [bold]help[/bold] for commands, or just type a claim to get started."
            if ui._enabled else
            "Enter a policy claim and Aletheia will check it against official data,\n"
            "detect methodology changes, and tell you how trustworthy the numbers are.\n\n"
            "  Example: \"The US poverty rate increased by 3% in 2020\"\n\n"
            "Type 'help' for commands, or just type a claim to get started."
        ),
    )
    orchestrator = OrchestratorAgent()
    last_claim: str | None = None
    last_verdict = None
    persistent_deep = False

    def _runtime_overrides(*, force_deep: bool) -> dict[str, str] | None:
        if not force_deep:
            return None
        return {"ALETHEIA_ENABLE_DEEP_RESEARCH": "1"}

    async def _run_claim_text(text: str, *, force_deep: bool) -> None:
        nonlocal last_claim, last_verdict
        mode_note = "deep-on" if force_deep else "deep-auto"
        ui.info(f"Analyzing claim ({mode_note})...")

        spinner = ui.create_spinner()
        spinner.start()
        try:
            verdict = await orchestrator.process_claim(
                text,
                runtime_overrides=_runtime_overrides(force_deep=force_deep),
                progress_callback=spinner.update,
            )
        finally:
            spinner.stop()

        _render_verdict(ui, verdict)
        last_claim = text
        last_verdict = verdict

    try:
        while True:
            try:
                claim = input("claim> ").strip()
            except EOFError:
                break

            if not claim:
                continue
            if claim.lower() in {"quit", "exit", "q"}:
                break
            if claim.lower() == "help":
                _render_help(ui)
                continue
            if claim.lower() == "trace":
                _render_trace(ui, orchestrator.get_trace())
                continue
            if claim.lower() == "details":
                run = orchestrator.get_last_run_details()
                if last_verdict is not None:
                    _render_verdict_detail_sections(ui, last_verdict)
                _render_run_details(ui, run)
                thinking_blocks = run.get("thinking_blocks")
                if isinstance(thinking_blocks, list):
                    for block in thinking_blocks:
                        if not isinstance(block, dict):
                            continue
                        content = str(block.get("text") or "").strip()
                        if content:
                            agent = str(block.get("agent") or "LLM")
                            ui.thinking_block(content, collapsed_label=f"{agent} Reasoning")
                continue
            if claim.lower() == "!mode":
                ui.kv_table(
                    "Current Settings",
                    [
                        ("Deep research", "Always on" if persistent_deep else "Auto (normal)"),
                        ("Last claim", last_claim[:60] + "..." if last_claim and len(last_claim) > 60 else (last_claim or "none")),
                    ],
                )
                continue
            if claim.lower().startswith("trail"):
                parts = claim.split()
                if len(parts) == 1:
                    _render_evidence_trail(ui, orchestrator.get_last_run_details())
                else:
                    try:
                        idx = int(parts[1])
                    except ValueError:
                        ui.warning("Usage: trail <number>")
                        continue
                    _render_evidence_doc(ui, orchestrator.get_last_run_details(), idx)
                continue
            if claim.lower() == "!rerun":
                if not last_claim:
                    ui.warning("No previous claim to rerun.")
                    continue
                await _run_claim_text(last_claim, force_deep=persistent_deep)
                continue
            if claim.lower().startswith("!deep"):
                parts = claim.split()
                if len(parts) == 1:
                    if not last_claim:
                        ui.warning("No previous claim to rerun with deep mode.")
                        continue
                    await _run_claim_text(last_claim, force_deep=True)
                    continue
                mode = parts[1].lower()
                if mode in {"on", "true", "1"}:
                    persistent_deep = True
                    ui.info("Persistent deep mode enabled.")
                elif mode in {"off", "false", "0"}:
                    persistent_deep = False
                    ui.info("Persistent deep mode disabled.")
                else:
                    ui.warning("Usage: !deep [on|off]")
                continue

            await _run_claim_text(claim, force_deep=persistent_deep)
    finally:
        await orchestrator.close()
        ui.info("Goodbye.")


async def single_claim(
    ui: TerminalUI,
    claim: str,
    *,
    show_json: bool = False,
    show_trace: bool = False,
) -> None:
    """Process a single claim and exit."""
    orchestrator = OrchestratorAgent()
    try:
        spinner = ui.create_spinner()
        spinner.start()
        try:
            verdict = await orchestrator.process_claim(
                claim,
                progress_callback=spinner.update,
            )
        finally:
            spinner.stop()

        _render_verdict(ui, verdict)
        run = orchestrator.get_last_run_details()

        if show_trace:
            _render_run_details(ui, run)
            _render_trace(ui, orchestrator.get_trace())
            thinking_blocks = run.get("thinking_blocks")
            if isinstance(thinking_blocks, list):
                for block in thinking_blocks:
                    if not isinstance(block, dict):
                        continue
                    text = str(block.get("text") or "").strip()
                    if text:
                        ui.thinking_block(text, collapsed_label=f"{block.get('agent', 'LLM')} Reasoning")

        if show_json:
            print(verdict.model_dump_json(indent=2))
    finally:
        await orchestrator.close()


async def show_retrieval_stats(ui: TerminalUI, hours: int, limit: int) -> None:
    """Print retrieval history and cache hit rates."""
    store = RetrievalStore()
    stats = await store.get_stats(hours=hours, limit=limit)
    _render_retrieval_stats(ui, stats)


async def _safe_db_check(timeout_seconds: float = 12.0) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(test_connection(), timeout=timeout_seconds)
    except TimeoutError:
        return {
            "ok": False,
            "category": "timeout",
            "message": f"DB diagnostic timed out after {timeout_seconds:.0f}s.",
            "db_url_redacted": get_db_url(redacted=True),
            "hints": [
                "Database handshake exceeded timeout; verify ALETHEIA_DB_HOST/ALETHEIA_DB_PORT reachability.",
                "If DB is remote, ensure firewall/LAN routing allows TCP traffic.",
                "Use ALETHEIA_DB_CONNECT_TIMEOUT to tune connect behavior if needed.",
            ],
        }


def _render_profile_context(ui: TerminalUI, resolved_profile: ResolvedRuntimeProfile | None) -> None:
    if resolved_profile is None:
        return
    ui.kv_table(
        "Configuration",
        [
            ("Profile", resolved_profile.name),
            ("Config file", resolved_profile.profile_file or "(built-in defaults)"),
            (
                "AI model server",
                f"{os.environ.get('ALETHEIA_LLM_BASE_URL')} ({resolved_profile.source_for('ALETHEIA_LLM_BASE_URL')})",
            ),
            (
                "Embedding server",
                f"{os.environ.get('ALETHEIA_EMBED_BASE_URL', os.environ.get('ALETHEIA_LLM_BASE_URL', 'n/a'))} "
                f"({resolved_profile.source_for('ALETHEIA_EMBED_BASE_URL')})",
            ),
        ],
    )


def _optional_key_status() -> list[tuple[str, bool, str]]:
    return [
        ("BRAVE_SEARCH_API_KEY", bool(os.environ.get("BRAVE_SEARCH_API_KEY")), "Improves web fallback coverage."),
        ("FRED_API_KEY", bool(os.environ.get("FRED_API_KEY")), "Enables macroeconomic data enrichment."),
        ("CENSUS_API_KEY", bool(os.environ.get("CENSUS_API_KEY")), "Enables Census API enrichment."),
        (
            "GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX",
            bool(os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX")),
            "Optional Google web retrieval provider.",
        ),
        ("SERPAPI_API_KEY", bool(os.environ.get("SERPAPI_API_KEY")), "Optional scholar deep-research provider."),
    ]


async def show_db_doctor(
    ui: TerminalUI,
    *,
    resolved_profile: ResolvedRuntimeProfile | None = None,
) -> int:
    """Run DB diagnostics and print actionable hints."""
    _render_profile_context(ui, resolved_profile)
    result = await _safe_db_check()
    if result.get("ok"):
        counts = result.get("counts") or {}
        semantic = result.get("semantic_search_ready")

        status_lines = [
            ui.status_dot(True, "Connection", result.get("db_url_redacted", "")),
            ui.status_dot(True, "Backend", result.get("backend", "surrealdb")),
            ui.status_dot(bool(semantic), "Knowledge search ready"),
        ]

        if ui._enabled and ui.console:
            from rich.panel import Panel as RichPanel
            body = "\n".join(status_lines)
            ui.console.print(RichPanel(body, title="[bold]Database Health[/bold]",
                                       border_style="green", padding=(1, 2)))
        else:
            print("\n--- Database Health ---")
            for line in status_lines:
                print(f"  {line}")
            print("---")

        ui.kv_table(
            "Knowledge Base Contents",
            [
                ("Known statistical changes", counts.get("methodology_changes", 0)),
                ("Research documents", counts.get("document_chunks", 0)),
                ("Searchable change records", counts.get("methodology_embeddings", 0)),
                ("Searchable document records", counts.get("document_embeddings", 0)),
                ("Total tables", len(result.get("tables") or [])),
            ],
        )
        return 0

    ui.error("Database connection failed")
    ui.kv_table(
        "Connection Details",
        [
            ("Address", result.get("db_url_redacted", "n/a")),
            ("Problem type", result.get("category", "unknown")),
            ("Error message", result.get("message", "n/a")),
        ],
    )
    hints = [str(hint) for hint in (result.get("hints") or [])[:8]]
    if hints:
        ui.bullet_list("How To Fix", hints)
    return 2


async def show_onboarding(
    ui: TerminalUI,
    *,
    resolved_profile: ResolvedRuntimeProfile | None = None,
) -> int:
    """Run local-first onboarding checks for stable foundations."""
    db_result, llm_result = await asyncio.gather(
        _safe_db_check(),
        _safe_llm_check(),
    )
    db_ok = bool(db_result.get("ok"))
    chat_ok = bool(llm_result.get("chat_ok"))
    embed_ok = bool(llm_result.get("embeddings_ok"))
    counts = db_result.get("counts") if isinstance(db_result.get("counts"), dict) else {}
    semantic_ok = bool(db_result.get("semantic_search_ready")) if db_ok else False
    chat_diag = llm_result.get("chat") if isinstance(llm_result.get("chat"), dict) else {}
    embed_diag = (
        llm_result.get("embeddings") if isinstance(llm_result.get("embeddings"), dict) else {}
    )
    all_ok = db_ok and chat_ok and embed_ok and semantic_ok

    ui.banner(
        "ALETHEIA — System Check",
        (
            "Checking that all components are running and properly configured.\n"
            "Aletheia needs a database, an AI model, and an embedding model to work."
        ),
    )

    # -- Section 1: System Status Overview ---------------------------------
    status_lines = [
        ui.status_dot(db_ok, "Database", db_result.get("db_url_redacted", "")),
        ui.status_dot(chat_ok, "AI Chat Model", chat_diag.get("endpoint", "")),
        ui.status_dot(embed_ok, "Embedding Model", embed_diag.get("endpoint", "")),
        ui.status_dot(semantic_ok, "Knowledge Search",
                      "ready" if semantic_ok else "needs embedding setup"),
    ]

    if ui._enabled and ui.console:
        from rich.panel import Panel as RichPanel
        overall = "[bold green]All systems ready[/bold green]" if all_ok else "[bold yellow]Some components need attention[/bold yellow]"
        body = "\n".join(status_lines) + f"\n\n{overall}"
        ui.console.print(RichPanel(body, title="[bold]System Status[/bold]",
                                   border_style="green" if all_ok else "yellow",
                                   padding=(1, 2)))
    else:
        print("\n--- System Status ---")
        for line in status_lines:
            print(f"  {line}")
        print(f"\n  {'All systems ready' if all_ok else 'Some components need attention'}")
        print("---")

    # -- Section 2: Knowledge Base (when DB is connected) ------------------
    counts = db_result.get("counts") if isinstance(db_result.get("counts"), dict) else {}
    if db_ok and counts:
        ui.kv_table(
            "Knowledge Base",
            [
                ("Known statistical changes", counts.get("methodology_changes", 0)),
                ("Research documents", counts.get("document_chunks", 0)),
                ("Searchable change records", counts.get("methodology_embeddings", 0)),
                ("Searchable document records", counts.get("document_embeddings", 0)),
            ],
        )

    # -- Section 3: Diagnostics (only when something is wrong) -------------
    _render_onboarding_diagnostics(ui, chat_ok=chat_ok, embed_ok=embed_ok, db_ok=db_ok,
                                   chat_diag=chat_diag, embed_diag=embed_diag,
                                   db_result=db_result)

    # -- Section 4: Optional Enhancements ----------------------------------
    key_rows = _optional_key_status()
    has_optional = any(ready for _, ready, _ in key_rows)

    _FRIENDLY_KEY_NAMES = {
        "BRAVE_SEARCH_API_KEY": "Brave Web Search",
        "FRED_API_KEY": "FRED Economic Data",
        "CENSUS_API_KEY": "US Census Bureau",
        "GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX": "Google Custom Search",
        "SERPAPI_API_KEY": "Scholar Deep Research",
    }
    opt_rows = [
        [_FRIENDLY_KEY_NAMES.get(name, name),
         "Active" if ready else "Not configured",
         note]
        for name, ready, note in key_rows
    ]
    ui.table("Optional Data Sources (not required)", ["Feature", "Status", "What It Adds"], opt_rows)

    # -- Section 5: What To Do Next ----------------------------------------
    if all_ok:
        next_steps = [
            "You're all set! Try analyzing a claim:",
            "  uv run aletheia claim \"The US poverty rate increased by 3% in 2020\"",
            "Or start an interactive session:",
            "  uv run aletheia interactive",
        ]
    else:
        next_steps = []
        if not db_ok:
            next_steps.append("Start the database: docker compose up -d surrealdb")
            next_steps.append("Then re-run: uv run aletheia onboarding")
        if not chat_ok:
            next_steps.append("Start your AI model server (LM Studio or Ollama)")
            next_steps.append("Load a chat model, then re-run this check")
        if not embed_ok:
            next_steps.append("Load an embedding model (e.g., qwen3-embedding in Ollama)")
        if db_ok and not semantic_ok:
            next_steps.append("Build the knowledge base:")
            next_steps.append("  uv run aletheia seed")

    ui.bullet_list("Next Steps", next_steps)

    return 0 if all_ok else 2


def _render_onboarding_diagnostics(
    ui: TerminalUI, *, chat_ok: bool, embed_ok: bool, db_ok: bool,
    chat_diag: dict, embed_diag: dict, db_result: dict,
) -> None:
    """Render diagnostic details only for components that need attention."""
    if chat_ok and embed_ok and db_ok:
        return

    issues: list[str] = []

    if not chat_ok:
        chat_errors = [str(e).strip() for e in (chat_diag.get("errors") or [])[:3] if str(e).strip()]
        chat_hints = [str(h).strip() for h in (chat_diag.get("hints") or [])[:3] if str(h).strip()]
        if chat_errors:
            issues.append(f"AI Chat Model: {chat_errors[0]}")
        for h in chat_hints:
            issues.append(f"  Fix: {h}")

    if not embed_ok:
        embed_errors = [str(e).strip() for e in (embed_diag.get("errors") or [])[:3] if str(e).strip()]
        embed_hints = [str(h).strip() for h in (embed_diag.get("hints") or [])[:3] if str(h).strip()]
        if chat_ok and bool(embed_diag.get("unsupported")):
            issues.append("Embedding Model: Chat works but this server doesn't support embeddings")
            issues.append("  Fix: Point ALETHEIA_EMBED_BASE_URL to an embedding-capable server")
        elif embed_errors:
            issues.append(f"Embedding Model: {embed_errors[0]}")
        for h in embed_hints:
            issues.append(f"  Fix: {h}")

    if not db_ok:
        db_hints = [str(h) for h in (db_result.get("hints") or [])[:3]]
        issues.append(f"Database: {db_result.get('message', 'connection failed')}")
        for h in db_hints:
            issues.append(f"  Fix: {h}")

    if issues:
        ui.bullet_list("Issues Found", issues)


def _build_parser() -> argparse.ArgumentParser:
    def _add_runtime_args(target: argparse.ArgumentParser) -> None:
        target.add_argument(
            "--profile",
            choices=PROFILE_CHOICES,
            default=None,
            help="Runtime profile to apply before command execution.",
        )
        target.add_argument(
            "--profile-file",
            default=None,
            help="Optional .env-style profile file layered over built-in profile defaults.",
        )
        target.add_argument("--llm-base-url", default=None, help="Override ALETHEIA_LLM_BASE_URL.")
        target.add_argument("--llm-model", default=None, help="Override ALETHEIA_LLM_MODEL.")
        target.add_argument(
            "--embed-base-url",
            default=None,
            help="Override ALETHEIA_EMBED_BASE_URL.",
        )
        target.add_argument("--embed-model", default=None, help="Override ALETHEIA_EMBED_MODEL.")
        target.add_argument("--db-url", default=None, help="Override ALETHEIA_DB_URL.")

    parser = argparse.ArgumentParser(
        prog="aletheia",
        description="ALETHEIA terminal interface.",
    )
    _add_runtime_args(parser)
    parser.add_argument(
        "--plain",
        action="store_true",
        help="Disable rich formatting and use plain text output.",
    )

    sub = parser.add_subparsers(dest="command")

    runtime_parent = argparse.ArgumentParser(add_help=False)
    _add_runtime_args(runtime_parent)
    runtime_parent.add_argument(
        "--plain",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    sub.add_parser("interactive", help="Start interactive claim analysis.", parents=[runtime_parent])

    claim = sub.add_parser("claim", help="Analyze one claim.", parents=[runtime_parent])
    claim.add_argument("text", nargs="+", help="Claim text.")
    claim.add_argument("--json", action="store_true", help="Print verdict JSON.")
    claim.add_argument("--trace", action="store_true", help="Print agent trace.")

    stats = sub.add_parser(
        "retrieval-stats",
        help="Show retrieval history and cache metrics.",
        parents=[runtime_parent],
    )
    stats.add_argument("--hours", type=int, default=24, help="Rolling time window.")
    stats.add_argument("--limit", type=int, default=15, help="Recent runs to show.")

    sub.add_parser(
        "db-doctor",
        help="Diagnose DB connectivity and extension readiness.",
        parents=[runtime_parent],
    )
    sub.add_parser("capabilities", help="Show capability matrix.", parents=[runtime_parent])
    sub.add_parser("onboarding", help="Run local-first setup checks.", parents=[runtime_parent])

    seed_parser = sub.add_parser(
        "seed",
        help="Load benchmark seed data and Phase 3 methodology breaks into DB.",
        parents=[runtime_parent],
    )
    seed_parser.add_argument(
        "--no-validate", action="store_true", help="Skip seed validation queries."
    )
    seed_parser.add_argument(
        "--no-phase3-breaks",
        action="store_true",
        help="Skip expanded Phase 3 methodology-break seed rows.",
    )

    ingest_parser = sub.add_parser(
        "ingest",
        help="Ingest external documents into the knowledge base.",
        parents=[runtime_parent],
    )
    ingest_parser.add_argument(
        "--materialize",
        action="store_true",
        help="Run vectorizer materialization after ingest writes.",
    )
    ingest_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview without DB writes.",
    )
    ingest_sub = ingest_parser.add_subparsers(dest="ingest_action")
    ingest_url = ingest_sub.add_parser("url", help="Ingest a single URL (HTML or PDF).")
    ingest_url.add_argument("target", help="URL to fetch and ingest.")
    ingest_dir = ingest_sub.add_parser("dir", help="Ingest all files from a local directory.")
    ingest_dir.add_argument("path", help="Directory path to scan.")
    ingest_sub.add_parser("marina", help="Parse MARINA.md knowledge lists and index summaries.")

    # Model management
    models_parser = sub.add_parser(
        "models",
        help="List and manage models across endpoints.",
        parents=[runtime_parent],
    )
    models_sub = models_parser.add_subparsers(dest="models_action")
    models_sub.add_parser("list", help="List all models (default).")
    models_pull = models_sub.add_parser("pull", help="Pull a model (Ollama only).")
    models_pull.add_argument("model_name", help="Model name to pull.")
    models_delete = models_sub.add_parser("delete", help="Delete a model.")
    models_delete.add_argument("model_name", help="Model name to delete.")
    models_info = models_sub.add_parser("info", help="Show model details.")
    models_info.add_argument("model_name", help="Model name to inspect.")
    models_load = models_sub.add_parser("load", help="Load a model into memory.")
    models_load.add_argument("model_name", help="Model name to load.")
    models_unload = models_sub.add_parser("unload", help="Unload a model from memory.")
    models_unload.add_argument("model_name", help="Model name to unload.")

    # Batch evaluation
    batch_parser = sub.add_parser(
        "batch",
        help="Run batch evaluation on multiple claims.",
        parents=[runtime_parent],
    )
    batch_parser.add_argument(
        "claims_file",
        nargs="?",
        help="CSV or text file with one claim per line.",
    )
    batch_parser.add_argument(
        "--benchmark",
        action="store_true",
        help="Run all 40 PHASE3_BREAKS seed cases.",
    )
    batch_parser.add_argument(
        "--output",
        default=None,
        help="Path to write JSON results (default: stdout).",
    )

    # Graph queries
    graph_parser = sub.add_parser(
        "graph",
        help="Query the knowledge graph.",
        parents=[runtime_parent],
    )
    graph_sub = graph_parser.add_subparsers(dest="graph_action")
    graph_prov = graph_sub.add_parser(
        "provenance",
        help="Show full evidence chain for a session.",
    )
    graph_prov.add_argument("session_id", help="Session record ID (e.g. session:abc123).")
    graph_impacts = graph_sub.add_parser(
        "impacts",
        help="Show indicators affected by a methodology change.",
    )
    graph_impacts.add_argument("change_id", help="Change record ID (e.g. methodology_change:ph3_001).")

    # Endpoint management
    endpoints_parser = sub.add_parser(
        "endpoints",
        help="List endpoints and health status.",
        parents=[runtime_parent],
    )
    endpoints_sub = endpoints_parser.add_subparsers(dest="endpoints_action")
    endpoints_sub.add_parser("list", help="List configured endpoints (default).")
    endpoints_probe = endpoints_sub.add_parser("probe", help="Probe a URL to detect provider type.")
    endpoints_probe.add_argument("url", help="Endpoint URL to probe.")

    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["interactive"]

    known = {
        "interactive",
        "claim",
        "retrieval-stats",
        "db-doctor",
        "capabilities",
        "onboarding",
        "seed",
        "ingest",
        "batch",
        "graph",
        "models",
        "endpoints",
        "-h",
        "--help",
    }
    if argv[0] in known:
        return argv
    if argv[0].startswith("-"):
        return argv
    # Backward compatibility: `cli.py "<claim text>"`
    return ["claim", *argv]


def _humanize_size(size_bytes: int | None) -> str:
    if size_bytes is None:
        return "—"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024  # type: ignore[assignment]
    return f"{size_bytes:.1f} PB"


async def show_models(ui: TerminalUI, action: str | None, args: argparse.Namespace) -> int:
    """Model management commands."""
    from aletheia.providers import get_configured_endpoints, get_provider

    endpoints = get_configured_endpoints()
    if not endpoints:
        # No YAML config — build endpoints from env vars
        endpoints = _endpoints_from_env()

    if action is None or action == "list":
        rows: list[list[Any]] = []
        for ep_name, ep in endpoints.items():
            provider = get_provider(ep)
            try:
                models = await provider.list_models()
                for m in models:
                    rows.append([
                        m.name,
                        _humanize_size(m.size_bytes),
                        m.quantization or "—",
                        m.parameter_count or "—",
                        "yes" if m.loaded else "—",
                        ", ".join(m.capabilities),
                        m.provider,
                        ep_name,
                    ])
            except Exception as exc:
                rows.append([f"(error: {exc})", "—", "—", "—", "—", "—", ep.provider_type, ep_name])
            finally:
                await provider.close()
        if rows:
            ui.table(
                "Models",
                ["Name", "Size", "Quant", "Params", "Loaded", "Caps", "Provider", "Endpoint"],
                rows,
            )
        else:
            ui.warning("No models found across configured endpoints.")
        return 0

    # Action-specific: find the right provider
    model_name = getattr(args, "model_name", None)
    if not model_name:
        ui.error("Model name required.")
        return 2

    if action == "pull":
        provider = _find_provider_for_action(endpoints, "model_pull")
        if provider is None:
            ui.error("No endpoint supports model pulling (Ollama required).")
            return 2
        try:
            ui.info(f"Pulling {model_name}...")

            def _progress(chunk: dict) -> None:
                status = chunk.get("status", "")
                total = chunk.get("total", 0)
                completed = chunk.get("completed", 0)
                if total:
                    pct = completed / total * 100
                    ui.info(f"  {status}: {pct:.0f}%")
                elif status:
                    ui.info(f"  {status}")

            result = await provider.pull_model(model_name, progress_callback=_progress)
            ui.success(f"Pull complete: {result.get('status', 'ok')}")
            return 0
        finally:
            await provider.close()

    if action == "delete":
        provider = _find_provider_for_action(endpoints, "model_delete")
        if provider is None:
            ui.error("No endpoint supports model deletion.")
            return 2
        try:
            result = await provider.delete_model(model_name)
            ui.success(f"Deleted {model_name}")
            return 0
        finally:
            await provider.close()

    if action == "info":
        provider = _find_provider_for_action(endpoints, "model_info")
        if provider is None:
            ui.error("No endpoint supports model info.")
            return 2
        try:
            info = await provider.model_info(model_name)
            ui.kv_table(
                f"Model: {info.name}",
                [
                    ("size", _humanize_size(info.size_bytes)),
                    ("quantization", info.quantization or "—"),
                    ("family", info.family or "—"),
                    ("parameter_count", info.parameter_count or "—"),
                    ("capabilities", ", ".join(info.capabilities)),
                    ("provider", info.provider),
                    ("endpoint", info.endpoint_name),
                ],
            )
            return 0
        finally:
            await provider.close()

    if action == "load":
        provider = _find_provider_for_action(endpoints, "model_load")
        if provider is None:
            ui.error("No endpoint supports model loading.")
            return 2
        try:
            result = await provider.load_model(model_name)
            if result.get("ok"):
                ui.success(f"Loaded {model_name}")
            else:
                ui.error(f"Load failed: {result.get('error', 'unknown')}")
            return 0
        finally:
            await provider.close()

    if action == "unload":
        provider = _find_provider_for_action(endpoints, "model_unload")
        if provider is None:
            ui.error("No endpoint supports model unloading.")
            return 2
        try:
            result = await provider.unload_model(model_name)
            if result.get("ok"):
                ui.success(f"Unloaded {model_name}")
            else:
                ui.error(f"Unload failed: {result.get('error', 'unknown')}")
            return 0
        finally:
            await provider.close()

    ui.error(f"Unknown models action: {action}")
    return 2


async def show_endpoints(ui: TerminalUI, action: str | None, args: argparse.Namespace) -> int:
    """Endpoint management commands."""
    from aletheia.providers import get_configured_endpoints, get_provider, probe_endpoint

    if action == "probe":
        url = getattr(args, "url", None)
        if not url:
            ui.error("URL required.")
            return 2
        ui.info(f"Probing {url}...")
        result = await probe_endpoint(url)
        ui.kv_table(
            "Probe Result",
            [
                ("url", result["url"]),
                ("provider_type", result["provider_type"]),
                ("healthy", result["health"].get("ok", False)),
            ],
        )
        models = result.get("models", [])
        if models:
            rows = [
                [m["name"], m.get("family") or "—", m.get("parameter_count") or "—", ", ".join(m.get("capabilities", []))]
                for m in models
            ]
            ui.table("Available Models", ["Name", "Family", "Params", "Capabilities"], rows)
        return 0

    # Default: list endpoints with health
    endpoints = get_configured_endpoints()
    if not endpoints:
        endpoints = _endpoints_from_env()

    rows: list[list[Any]] = []
    for ep_name, ep in endpoints.items():
        provider = get_provider(ep)
        try:
            health = await provider.health_check()
            rows.append([
                ep_name,
                ep.url,
                ep.provider_type,
                ", ".join(ep.roles),
                "healthy" if health.get("ok") else "unreachable",
                health.get("model_count", "—"),
            ])
        except Exception as exc:
            rows.append([ep_name, ep.url, ep.provider_type, ", ".join(ep.roles), f"error: {exc}", "—"])
        finally:
            await provider.close()

    if rows:
        ui.table("Endpoints", ["Name", "URL", "Provider", "Roles", "Status", "Models"], rows)
    else:
        ui.warning("No endpoints configured. Create aletheia.yaml or set ALETHEIA_LLM_BASE_URL.")
    return 0


def _endpoints_from_env() -> dict:
    """Build endpoint configs from env vars when no YAML config exists."""
    from aletheia.providers.base import Endpoint

    endpoints: dict[str, Endpoint] = {}
    chat_url = os.environ.get("ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234")
    embed_url = os.environ.get("ALETHEIA_EMBED_BASE_URL", chat_url)

    endpoints["chat"] = Endpoint(
        name="chat",
        url=chat_url,
        provider_type="openai_compat",
        roles=["chat"],
        api_key=os.environ.get("ALETHEIA_LLM_API_KEY"),
        default_chat_model=os.environ.get("ALETHEIA_LLM_MODEL"),
    )
    if embed_url != chat_url:
        endpoints["embed"] = Endpoint(
            name="embed",
            url=embed_url,
            provider_type="openai_compat",
            roles=["embed"],
            api_key=os.environ.get("ALETHEIA_EMBED_API_KEY"),
            default_embed_model=os.environ.get("ALETHEIA_EMBED_MODEL"),
        )
    else:
        endpoints["chat"].roles = ["chat", "embed"]
        endpoints["chat"].default_embed_model = os.environ.get("ALETHEIA_EMBED_MODEL")

    return endpoints


def _find_provider_for_action(endpoints: dict, action: str):
    """Find the first endpoint that supports the given capability."""
    from aletheia.providers import Capability, get_provider

    cap_map = {
        "model_pull": Capability.MODEL_PULL,
        "model_delete": Capability.MODEL_DELETE,
        "model_info": Capability.MODEL_INFO,
        "model_load": Capability.MODEL_LOAD,
        "model_unload": Capability.MODEL_UNLOAD,
    }
    target_cap = cap_map.get(action)
    if target_cap is None:
        return None
    for ep in endpoints.values():
        provider = get_provider(ep)
        if target_cap in provider.capabilities():
            return provider
    return None


def _run_ingest(ui: TerminalUI, args: argparse.Namespace) -> int:
    """Dispatch ingest subcommands to aletheia.ingest functions."""
    from pathlib import Path

    from aletheia.ingest import (
        ingest_local_directory,
        ingest_marina_corpus,
        ingest_single_url,
    )

    action = getattr(args, "ingest_action", None)
    dry_run = getattr(args, "dry_run", False)
    materialize = getattr(args, "materialize", False)

    if action is None:
        ui.error("Missing ingest action. Use: aletheia ingest {url,dir,marina}")
        return 2

    if action == "url":
        target = args.target
        label = f"URL: {target}"
        if dry_run:
            label += " (dry run)"
        ui.info(f"Ingesting {label}...")
        stats = asyncio.run(ingest_single_url(target, dry_run=dry_run))
        if stats.get("error"):
            ui.error(f"Fetch failed: {stats['error']}")
            return 2
        if dry_run:
            ui.success(
                f"Dry run: {stats['text_length']} chars, "
                f"would produce {stats['chunks_expected']} chunks"
            )
        else:
            ui.success(
                f"Done: {stats['chunks_written']} chunks from "
                f"{stats['documents_written']} document"
            )

    elif action == "dir":
        dir_path = Path(args.path)
        if not dir_path.is_dir():
            ui.error(f"Not a directory: {dir_path}")
            return 2
        label = f"directory: {dir_path}"
        if dry_run:
            label += " (dry run)"
        ui.info(f"Ingesting {label}...")
        stats = asyncio.run(ingest_local_directory(dir_path, dry_run=dry_run))
        if dry_run:
            ui.success(f"Dry run: found {stats['files_seen']} supported files")
        else:
            if stats.get("errors"):
                ui.warning(f"{stats['errors']} file(s) had extraction errors.")
            ui.success(
                f"Done: {stats['files_ingested']}/{stats['files_seen']} files, "
                f"{stats['chunks_written']} chunks"
            )

    elif action == "marina":
        marina_path = Path(".humans-collaborate/MARINA.md")
        if not marina_path.exists():
            marina_path = Path("MARINA.md")
        if not marina_path.exists():
            ui.error("MARINA.md not found in project root or .humans-collaborate/.")
            return 2
        label = f"MARINA corpus: {marina_path}"
        if dry_run:
            label += " (dry run)"
        ui.info(f"Ingesting {label}...")
        stats = asyncio.run(ingest_marina_corpus(marina_path, dry_run=dry_run))
        if dry_run:
            ui.success(f"Dry run: {stats['documents_seen']} documents would be ingested")
        else:
            ui.success(
                f"Done: {stats['documents_written']}/{stats['documents_seen']} documents, "
                f"{stats['chunks_written']} chunks"
            )

    else:
        ui.error(f"Unknown ingest action: {action}")
        return 2

    if materialize and not dry_run:
        ui.info("Running embedding materialization...")
        from aletheia.vectorizer import materialize_embeddings

        mat_stats = asyncio.run(materialize_embeddings())
        ui.success(f"Materialization complete: {mat_stats}")

    return 0


def _run_batch(ui: TerminalUI, args: argparse.Namespace) -> int:
    """Dispatch batch evaluation subcommand."""
    from aletheia.data_loader import load_methodology_breaks

    benchmark = getattr(args, "benchmark", False)
    claims_file = getattr(args, "claims_file", None)
    output_path = getattr(args, "output", None)

    if not benchmark and not claims_file:
        ui.error("Provide a claims file or use --benchmark.")
        return 2

    claims: list[str] = []
    if benchmark:
        breaks = load_methodology_breaks()
        claims = [b["description"] for b in breaks]
        ui.info(f"Running benchmark: {len(claims)} methodology-break claims")
    else:
        from pathlib import Path

        path = Path(claims_file)
        if not path.exists():
            ui.error(f"File not found: {claims_file}")
            return 2
        claims = [line.strip() for line in path.read_text().splitlines() if line.strip()]
        ui.info(f"Running batch: {len(claims)} claims from {claims_file}")

    orchestrator = OrchestratorAgent()
    results: list[dict[str, Any]] = []

    async def _run():
        try:
            for i, claim in enumerate(claims, 1):
                ui.info(f"[{i}/{len(claims)}] {claim[:80]}...")
                try:
                    verdict = await orchestrator.process_claim(claim)
                    results.append({
                        "claim": claim,
                        "status": verdict.status.value,
                        "confidence": verdict.confidence,
                        "severity": verdict.severity.value,
                        "comparability": verdict.comparability.value,
                        "summary": verdict.summary,
                        "breaks_found": len(verdict.breaks_found),
                    })
                except Exception as exc:
                    results.append({"claim": claim, "error": str(exc)})
        finally:
            await orchestrator.close()

    asyncio.run(_run())

    output_json = json.dumps(results, indent=2)
    if output_path:
        from pathlib import Path as P

        P(output_path).write_text(output_json)
        ui.success(f"Results written to {output_path}")
    else:
        print(output_json)

    passed = sum(1 for r in results if "error" not in r)
    ui.success(f"Batch complete: {passed}/{len(results)} succeeded")
    return 0


def _run_graph(ui: TerminalUI, args: argparse.Namespace) -> int:
    """Dispatch graph query subcommand."""
    action = getattr(args, "graph_action", None)
    if not action:
        ui.error("Missing graph action. Use: aletheia graph {provenance,impacts}")
        return 2

    from aletheia.db import get_connection

    if action == "provenance":
        session_id = args.session_id

        async def _prov():
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT *,
                        ->uses_evidence->evidence_doc.* AS evidence,
                        ->produces->verdict.* AS verdicts
                    FROM $session
                    """,
                    {"session": session_id},
                )
                return result

        result = asyncio.run(_prov())
        print(json.dumps(result, indent=2, default=str))
        return 0

    if action == "impacts":
        change_id = args.change_id

        async def _impacts():
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT *,
                        ->affects->indicator.* AS affected_indicators,
                        ->belongs_to->dataset.* AS datasets
                    FROM $change
                    """,
                    {"change": change_id},
                )
                return result

        result = asyncio.run(_impacts())
        print(json.dumps(result, indent=2, default=str))
        return 0

    ui.error(f"Unknown graph action: {action}")
    return 2


def main() -> int:
    parser = _build_parser()
    argv = _normalize_argv(sys.argv[1:])
    args = parser.parse_args(argv)

    try:
        resolved_profile = apply_runtime_profile(
            profile=getattr(args, "profile", None),
            profile_file=getattr(args, "profile_file", None),
            cli_overrides=_runtime_override_args(args),
        )
    except ValueError as exc:
        print(f"profile error: {exc}")
        return 2

    ui = TerminalUI(plain=getattr(args, "plain", False))

    command = args.command or "interactive"
    if command == "interactive":
        asyncio.run(interactive_mode(ui))
        return 0
    if command == "claim":
        claim = " ".join(args.text)
        asyncio.run(
            single_claim(
                ui,
                claim,
                show_json=bool(args.json),
                show_trace=bool(args.trace),
            )
        )
        return 0
    if command == "retrieval-stats":
        asyncio.run(show_retrieval_stats(ui, args.hours, args.limit))
        return 0
    if command == "db-doctor":
        return asyncio.run(show_db_doctor(ui, resolved_profile=resolved_profile))
    if command == "capabilities":
        _render_capabilities(ui)
        return 0
    if command == "onboarding":
        return asyncio.run(show_onboarding(ui, resolved_profile=resolved_profile))
    if command == "seed":
        from aletheia.bootstrap import bootstrap_db

        ui.info("Seeding database with benchmark cases and methodology breaks...")
        try:
            result = asyncio.run(
                bootstrap_db(
                    include_seed=True,
                    include_validate=not getattr(args, "no_validate", False),
                    include_phase3_breaks=not getattr(args, "no_phase3_breaks", False),
                )
            )
            ui.success(f"Seed complete: {result['actions']} (db: {result['db_url_redacted']})")
            return 0
        except Exception as exc:
            ui.error(f"Seed failed: {exc}")
            return 2
    if command == "ingest":
        return _run_ingest(ui, args)
    if command == "batch":
        return _run_batch(ui, args)
    if command == "graph":
        return _run_graph(ui, args)
    if command == "models":
        return asyncio.run(show_models(ui, getattr(args, "models_action", None), args))
    if command == "endpoints":
        return asyncio.run(show_endpoints(ui, getattr(args, "endpoints_action", None), args))

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
