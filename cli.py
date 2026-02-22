#!/usr/bin/env python
"""ALETHEIA CLI - Methodology-aware policy intelligence."""

from __future__ import annotations

import argparse
import asyncio
import csv
import importlib.util
import json
import os
import sys
from pathlib import Path
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
    local_llm_endpoint = os.environ.get(
        "ALETHEIA_LLM_BASE_URL", "http://127.0.0.1:1234"
    )
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
            "installed (core dependency)"
            if crawl4ai_installed
            else "missing — reinstall with uv sync",
        ),
        ("fred_api_enhanced", bool(os.environ.get("FRED_API_KEY")), "optional API key"),
        (
            "census_api_enhanced",
            bool(os.environ.get("CENSUS_API_KEY")),
            "optional API key",
        ),
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
        [
            _CAPABILITY_FRIENDLY.get(name, name),
            "Active" if enabled else "Inactive",
            note,
        ]
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
        ui.console.print(
            RichPanel(
                body, title="[bold]Commands[/bold]", border_style="cyan", padding=(1, 2)
            )
        )
    else:
        print("\n--- Commands ---")
        print("  After a verdict:")
        print(
            "    details    Full breakdown — caveats, data sources, routing, AI reasoning"
        )
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
    border = {
        "SUPPORTED": "green",
        "PARTIALLY_SUPPORTED": "yellow",
        "MISLEADING": "red",
    }.get(verdict.status.value, "cyan")

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
            date_str = (
                change.effective_date.isoformat()
                if change.effective_date
                else "unknown"
            )
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
        lines.append(
            "[dim]Type 'details' for full analysis, 'trail' for evidence sources[/dim]"
        )

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
            date_str = (
                change.effective_date.isoformat()
                if change.effective_date
                else "unknown"
            )
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
            rows.append(
                [
                    change.effective_date.isoformat()
                    if change.effective_date
                    else "unknown",
                    change.change_type.value.replace("_", " "),
                    (change.impact_estimate or "")[:80],
                ]
            )
        ui.table("All Methodology Changes", ["Date", "Type", "Impact"], rows)

    if verdict.caveats:
        ui.bullet_list("Caveats & Limitations", verdict.caveats)

    if verdict.sources:
        ui.bullet_list(
            "Data Sources Used", [str(source) for source in verdict.sources[:5]]
        )

    if verdict.evidence_snippets:
        ui.bullet_list(
            "Key Evidence", [str(item) for item in verdict.evidence_snippets[:3]]
        )


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
                (
                    "Sources queried",
                    ", ".join(str(s) for s in sources) if sources else "none",
                ),
                ("Backup source", fallback),
                (
                    "Deep research sources",
                    ", ".join(str(s) for s in deep) if deep else "none",
                ),
            ],
        )

    source_outputs = run.get("source_outputs")
    if isinstance(source_outputs, list) and source_outputs:
        rows = []
        for output in source_outputs:
            if not isinstance(output, dict):
                continue
            analysis = (
                output.get("analysis")
                if isinstance(output.get("analysis"), dict)
                else {}
            )
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
                            ", ".join(
                                str(err) for err in (output.get("errors") or [])[:1]
                            ),
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
    claim_value_check = (
        analysis.get("claim_value_check")
        if isinstance(analysis.get("claim_value_check"), dict)
        else {}
    )
    structural_break = (
        analysis.get("structural_break_detected")
        if isinstance(analysis.get("structural_break_detected"), dict)
        else {}
    )

    fallback_used = analysis.get("fallback_used", run.get("fallback_used"))
    deep_used = analysis.get("deep_research_used", run.get("deep_research_used"))
    agg_conf = analysis.get(
        "evidence_aggregate_confidence", run.get("aggregate_confidence", 0.0)
    )
    within_tol = claim_value_check.get("within_tolerance")
    delta = claim_value_check.get("delta")
    struct_break = structural_break.get("detected")
    budget_skips = analysis.get("provider_budget_skips")

    signal_rows: list[tuple[str, Any]] = [
        ("Used backup sources", "Yes" if fallback_used else "No"),
        ("Used deep research", "Yes" if deep_used else "No"),
        (
            "Overall evidence confidence",
            f"{float(agg_conf):.1%}" if agg_conf else "n/a",
        ),
    ]
    if within_tol is not None:
        signal_rows.append(
            ("Claimed value matches data", "Yes" if within_tol else "No")
        )
    if delta is not None:
        signal_rows.append(("Difference from actual", str(delta)))
    if struct_break is not None:
        signal_rows.append(
            ("Statistical break detected", "Yes" if struct_break else "No")
        )
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
        ui.warning(
            f"Document #{index} doesn't exist. Choose a number between 1 and {len(docs)}."
        )
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
        ui.table(
            "Agent Communication Log", ["Time", "From", "To", "Type", "Content"], rows
        )
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
            (
                "Average confidence",
                f"{summary.get('avg_aggregate_confidence', 0.0):.0%}",
            ),
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
        ui.table(
            "Results By Source",
            ["Source", "Documents", "Cached", "Avg Confidence"],
            rows,
        )

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
            [
                "ID",
                "Dataset",
                "Indicator",
                "Status",
                "Evidence",
                "Backup Used",
                "Deep",
                "Confidence",
            ],
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


def _llm_guidance_from_error(
    status: int | None, detail: str, *, kind: str
) -> list[str]:
    lowered = detail.lower()
    hints: list[str] = []

    if "no models loaded" in lowered:
        hints.append(
            "Model server is reachable but no model is loaded. Load a chat/embedding model in LM Studio or Ollama first."
        )
    if "model" in lowered and "required" in lowered:
        if kind == "chat":
            hints.append(
                "Set ALETHEIA_LLM_MODEL or pass --llm-model for endpoints that require explicit model IDs."
            )
        else:
            hints.append(
                "Set ALETHEIA_EMBED_MODEL or pass --embed-model for endpoints that require explicit model IDs."
            )
    if "connection refused" in lowered or "name or service not known" in lowered:
        hints.append(
            "Verify endpoint host/port and that the model runtime is listening on that interface."
        )

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
                if isinstance(models_payload, dict) and isinstance(
                    models_payload.get("data"), list
                ):
                    payload["models"] = [
                        str(row.get("id"))
                        for row in models_payload["data"]
                        if isinstance(row, dict) and row.get("id")
                    ]
            else:
                detail = _error_detail(models_resp)
                payload["errors"].append(f"models:{models_resp.status_code} {detail}")
                payload["hints"].extend(
                    _llm_guidance_from_error(models_resp.status_code, detail, kind=mode)
                )

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
                payload["hints"].extend(
                    _llm_guidance_from_error(call_resp.status_code, detail, kind=mode)
                )
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
        "chat_ok": bool(
            chat_result.get("request_ok") and chat_result.get("model_ready")
        ),
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
            '  Example: "The US poverty rate increased by 3% in 2020"\n\n'
            "Type [bold]help[/bold] for commands, or just type a claim to get started."
            if ui._enabled
            else "Enter a policy claim and Aletheia will check it against official data,\n"
            "detect methodology changes, and tell you how trustworthy the numbers are.\n\n"
            '  Example: "The US poverty rate increased by 3% in 2020"\n\n'
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
                            ui.thinking_block(
                                content, collapsed_label=f"{agent} Reasoning"
                            )
                continue
            if claim.lower() == "!mode":
                ui.kv_table(
                    "Current Settings",
                    [
                        (
                            "Deep research",
                            "Always on" if persistent_deep else "Auto (normal)",
                        ),
                        (
                            "Last claim",
                            last_claim[:60] + "..."
                            if last_claim and len(last_claim) > 60
                            else (last_claim or "none"),
                        ),
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
    case_id: str | None = None,
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
                case_id=case_id,
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
                        ui.thinking_block(
                            text,
                            collapsed_label=f"{block.get('agent', 'LLM')} Reasoning",
                        )

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


def _render_profile_context(
    ui: TerminalUI, resolved_profile: ResolvedRuntimeProfile | None
) -> None:
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
        (
            "BRAVE_SEARCH_API_KEY",
            bool(os.environ.get("BRAVE_SEARCH_API_KEY")),
            "Improves web fallback coverage.",
        ),
        (
            "FRED_API_KEY",
            bool(os.environ.get("FRED_API_KEY")),
            "Enables macroeconomic data enrichment.",
        ),
        (
            "CENSUS_API_KEY",
            bool(os.environ.get("CENSUS_API_KEY")),
            "Enables Census API enrichment.",
        ),
        (
            "GOOGLE_CSE_API_KEY + GOOGLE_CSE_CX",
            bool(
                os.environ.get("GOOGLE_CSE_API_KEY") and os.environ.get("GOOGLE_CSE_CX")
            ),
            "Optional Google web retrieval provider.",
        ),
        (
            "SERPAPI_API_KEY",
            bool(os.environ.get("SERPAPI_API_KEY")),
            "Optional scholar deep-research provider.",
        ),
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
            ui.console.print(
                RichPanel(
                    body,
                    title="[bold]Database Health[/bold]",
                    border_style="green",
                    padding=(1, 2),
                )
            )
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
    counts = (
        db_result.get("counts") if isinstance(db_result.get("counts"), dict) else {}
    )
    semantic_ok = bool(db_result.get("semantic_search_ready")) if db_ok else False
    chat_diag = (
        llm_result.get("chat") if isinstance(llm_result.get("chat"), dict) else {}
    )
    embed_diag = (
        llm_result.get("embeddings")
        if isinstance(llm_result.get("embeddings"), dict)
        else {}
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
        ui.status_dot(
            semantic_ok,
            "Knowledge Search",
            "ready" if semantic_ok else "needs embedding setup",
        ),
    ]

    if ui._enabled and ui.console:
        from rich.panel import Panel as RichPanel

        overall = (
            "[bold green]All systems ready[/bold green]"
            if all_ok
            else "[bold yellow]Some components need attention[/bold yellow]"
        )
        body = "\n".join(status_lines) + f"\n\n{overall}"
        ui.console.print(
            RichPanel(
                body,
                title="[bold]System Status[/bold]",
                border_style="green" if all_ok else "yellow",
                padding=(1, 2),
            )
        )
    else:
        print("\n--- System Status ---")
        for line in status_lines:
            print(f"  {line}")
        print(
            f"\n  {'All systems ready' if all_ok else 'Some components need attention'}"
        )
        print("---")

    # -- Section 2: Knowledge Base (when DB is connected) ------------------
    counts = (
        db_result.get("counts") if isinstance(db_result.get("counts"), dict) else {}
    )
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
    _render_onboarding_diagnostics(
        ui,
        chat_ok=chat_ok,
        embed_ok=embed_ok,
        db_ok=db_ok,
        chat_diag=chat_diag,
        embed_diag=embed_diag,
        db_result=db_result,
    )

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
        [
            _FRIENDLY_KEY_NAMES.get(name, name),
            "Active" if ready else "Not configured",
            note,
        ]
        for name, ready, note in key_rows
    ]
    ui.table(
        "Optional Data Sources (not required)",
        ["Feature", "Status", "What It Adds"],
        opt_rows,
    )

    # -- Section 5: What To Do Next ----------------------------------------
    if all_ok:
        next_steps = [
            "You're all set! Try analyzing a claim:",
            '  uv run aletheia claim "The US poverty rate increased by 3% in 2020"',
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
            next_steps.append(
                "Load an embedding model (e.g., qwen3-embedding in Ollama)"
            )
        if db_ok and not semantic_ok:
            next_steps.append("Build the knowledge base:")
            next_steps.append("  uv run aletheia seed")

    ui.bullet_list("Next Steps", next_steps)

    return 0 if all_ok else 2


def _render_onboarding_diagnostics(
    ui: TerminalUI,
    *,
    chat_ok: bool,
    embed_ok: bool,
    db_ok: bool,
    chat_diag: dict,
    embed_diag: dict,
    db_result: dict,
) -> None:
    """Render diagnostic details only for components that need attention."""
    if chat_ok and embed_ok and db_ok:
        return

    issues: list[str] = []

    if not chat_ok:
        chat_errors = [
            str(e).strip()
            for e in (chat_diag.get("errors") or [])[:3]
            if str(e).strip()
        ]
        chat_hints = [
            str(h).strip() for h in (chat_diag.get("hints") or [])[:3] if str(h).strip()
        ]
        if chat_errors:
            issues.append(f"AI Chat Model: {chat_errors[0]}")
        for h in chat_hints:
            issues.append(f"  Fix: {h}")

    if not embed_ok:
        embed_errors = [
            str(e).strip()
            for e in (embed_diag.get("errors") or [])[:3]
            if str(e).strip()
        ]
        embed_hints = [
            str(h).strip()
            for h in (embed_diag.get("hints") or [])[:3]
            if str(h).strip()
        ]
        if chat_ok and bool(embed_diag.get("unsupported")):
            issues.append(
                "Embedding Model: Chat works but this server doesn't support embeddings"
            )
            issues.append(
                "  Fix: Point ALETHEIA_EMBED_BASE_URL to an embedding-capable server"
            )
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
        target.add_argument(
            "--llm-base-url", default=None, help="Override ALETHEIA_LLM_BASE_URL."
        )
        target.add_argument(
            "--llm-model", default=None, help="Override ALETHEIA_LLM_MODEL."
        )
        target.add_argument(
            "--embed-base-url",
            default=None,
            help="Override ALETHEIA_EMBED_BASE_URL.",
        )
        target.add_argument(
            "--embed-model", default=None, help="Override ALETHEIA_EMBED_MODEL."
        )
        target.add_argument("--db-url", default=None, help="Override ALETHEIA_DB_URL.")

    parser = argparse.ArgumentParser(
        prog="aletheia",
        description="ALETHEIA case-centric investigation CLI.",
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

    sub.add_parser(
        "interactive",
        help="Start interactive claim analysis.",
        parents=[runtime_parent],
    )

    claim = sub.add_parser(
        "claim",
        help="Analyze one claim (optionally under a case).",
        parents=[runtime_parent],
    )
    claim.add_argument("text", nargs="+", help="Claim text.")
    claim.add_argument("--json", action="store_true", help="Print verdict JSON.")
    claim.add_argument("--trace", action="store_true", help="Print agent trace.")
    claim.add_argument(
        "--case",
        dest="case_id",
        default=None,
        help="Case ID to attach this session to (case:<id> or <id>).",
    )

    case_parser = sub.add_parser(
        "case",
        help="Create, inspect, and export investigation cases.",
        description=(
            "Case-centric workflow: create a case, run claim/batch with --case, "
            "then review history/export."
        ),
        parents=[runtime_parent],
    )
    case_sub = case_parser.add_subparsers(dest="case_action")
    case_create = case_sub.add_parser("create", help="Create a new investigation case.")
    case_create.add_argument("name", help="Case name.")
    case_create.add_argument(
        "--description", default=None, help="Optional case description."
    )
    case_list = case_sub.add_parser("list", help="List recent cases.")
    case_list.add_argument(
        "--limit", type=int, default=20, help="Maximum cases to show."
    )
    case_show = case_sub.add_parser("show", help="Show case details.")
    case_show.add_argument("case_id", help="Case ID (case:<id> or <id>).")
    case_history = case_sub.add_parser("history", help="Show case activity timeline.")
    case_history.add_argument("case_id", help="Case ID (case:<id> or <id>).")
    case_history.add_argument(
        "--limit", type=int, default=20, help="Max activity rows to show."
    )
    case_history.add_argument(
        "--json", action="store_true", help="Print structured JSON output."
    )
    case_export = case_sub.add_parser("export", help="Export case data.")
    case_export.add_argument("case_id", help="Case ID (case:<id> or <id>).")
    case_export.add_argument(
        "--format",
        choices=["json", "jsonl", "md"],
        default="json",
        help="Export format (default: json).",
    )
    case_export.add_argument(
        "--output", default=None, help="Write export to file path."
    )
    case_reconcile = case_sub.add_parser(
        "reconcile",
        help="Repair missing case graph links from case_id fields.",
    )
    case_reconcile.add_argument("case_id", help="Case ID (case:<id> or <id>).")

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
    sub.add_parser(
        "capabilities", help="Show capability matrix.", parents=[runtime_parent]
    )
    sub.add_parser(
        "onboarding", help="Run local-first setup checks.", parents=[runtime_parent]
    )

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
    ingest_dir = ingest_sub.add_parser(
        "dir", help="Ingest all files from a local directory."
    )
    ingest_dir.add_argument("path", help="Directory path to scan.")
    ingest_sub.add_parser(
        "marina", help="Parse MARINA.md knowledge lists and index summaries."
    )

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
        help="Run case-linked batch analysis on multiple claims.",
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
    batch_parser.add_argument(
        "--case",
        dest="case_id",
        default=None,
        help="Case ID to attach this batch to (case:<id> or <id>).",
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
    graph_prov.add_argument(
        "session_id", help="Session record ID (e.g. session:abc123)."
    )
    graph_impacts = graph_sub.add_parser(
        "impacts",
        help="Show indicators affected by a methodology change.",
    )
    graph_impacts.add_argument(
        "change_id", help="Change record ID (e.g. methodology_change:ph3_001)."
    )
    graph_timeline = graph_sub.add_parser(
        "timeline",
        help="Show methodology timeline for a dataset.",
    )
    graph_timeline.add_argument(
        "dataset_code", help="Dataset code (e.g. CPS, EU-LFS, ACS)."
    )
    graph_recall = graph_sub.add_parser(
        "recall",
        help="Recall prior similar verification sessions.",
    )
    graph_recall.add_argument(
        "--session",
        dest="session_id",
        default=None,
        help="Source session ID to derive dataset/indicator context.",
    )
    graph_recall.add_argument(
        "--dataset",
        dest="dataset_code",
        default=None,
        help="Dataset code to match prior sessions.",
    )
    graph_recall.add_argument(
        "--indicator",
        dest="indicator",
        default=None,
        help="Indicator text to match prior sessions.",
    )
    graph_recall.add_argument(
        "--limit",
        type=int,
        default=10,
        help="Maximum similar sessions to return.",
    )

    # Endpoint management
    endpoints_parser = sub.add_parser(
        "endpoints",
        help="List endpoints and health status.",
        parents=[runtime_parent],
    )
    endpoints_sub = endpoints_parser.add_subparsers(dest="endpoints_action")
    endpoints_sub.add_parser("list", help="List configured endpoints (default).")
    endpoints_probe = endpoints_sub.add_parser(
        "probe", help="Probe a URL to detect provider type."
    )
    endpoints_probe.add_argument("url", help="Endpoint URL to probe.")

    return parser


def _normalize_argv(argv: list[str]) -> list[str]:
    if not argv:
        return ["interactive"]

    known = {
        "interactive",
        "claim",
        "case",
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


def _normalize_case_id(case_id: str | None) -> str | None:
    if not case_id:
        return None
    value = case_id.strip()
    if not value:
        return None
    if value.startswith("case:"):
        return value
    return f"case:{value}"


def _query_result_rows(result: Any) -> list[dict[str, Any]]:
    if not result:
        return []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                rows = item.get("result", [])
                if isinstance(rows, list):
                    return rows
            elif isinstance(item, list):
                return item
        if all(isinstance(r, dict) for r in result):
            return result
    return []


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _claim_snippet(value: Any, *, width: int = 80) -> str:
    text = str(value or "").strip().replace("\n", " ")
    if len(text) <= width:
        return text
    return text[: width - 3] + "..."


def _batch_summary_text(batch_row: dict[str, Any]) -> str:
    results = batch_row.get("results")
    if not isinstance(results, dict):
        return ""
    succeeded = results.get("succeeded")
    failed = results.get("failed")
    avg_conf = _safe_float(results.get("avg_confidence"))
    parts: list[str] = []
    if isinstance(succeeded, int):
        parts.append(f"ok={succeeded}")
    if isinstance(failed, int):
        parts.append(f"fail={failed}")
    if avg_conf is not None:
        parts.append(f"avg={avg_conf:.2f}")
    return " ".join(parts)


async def _load_case_bundle(
    case_id: str,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]]]:
    from aletheia.db import get_connection

    async with get_connection() as db:
        case_result = await db.query("SELECT * FROM $case LIMIT 1", {"case": case_id})
        case_rows = _query_result_rows(case_result)
        if not case_rows:
            return None, [], []

        sessions_result = await db.query(
            """
            SELECT id, case_id, claim_text, status, started_at, completed_at, verdict, metadata, error_text
            FROM $case->has_session->session
            ORDER BY started_at ASC
            """,
            {"case": case_id},
        )
        batches_result = await db.query(
            """
            SELECT id, case_id, name, status, total_claims, completed_claims, started_at, completed_at, results
            FROM $case->has_batch->batch
            ORDER BY started_at ASC
            """,
            {"case": case_id},
        )
        return (
            case_rows[0],
            _query_result_rows(sessions_result),
            _query_result_rows(batches_result),
        )


async def _case_exists(case_id: str) -> bool:
    from aletheia.db import get_connection

    async with get_connection() as db:
        case_result = await db.query("SELECT id FROM $case LIMIT 1", {"case": case_id})
        return bool(_query_result_rows(case_result))


async def _reconcile_case_links(case_id: str) -> dict[str, int]:
    from aletheia.db import get_connection

    async with get_connection() as db:
        sessions_by_case = await db.query(
            """
            SELECT id
            FROM session
            WHERE case_id = $case
            """,
            {"case": case_id},
        )
        linked_sessions = await db.query(
            """
            SELECT id
            FROM $case->has_session->session
            """,
            {"case": case_id},
        )
        session_ids = {
            str(row.get("id")) for row in _query_result_rows(sessions_by_case)
        }
        linked_session_ids = {
            str(row.get("id")) for row in _query_result_rows(linked_sessions)
        }
        linked_session_count = 0
        for session_id in sorted(session_ids - linked_session_ids):
            await db.query(
                "RELATE $case->has_session->$session",
                {"case": case_id, "session": session_id},
            )
            linked_session_count += 1

        batches_by_case = await db.query(
            """
            SELECT id
            FROM batch
            WHERE case_id = $case
            """,
            {"case": case_id},
        )
        linked_batches = await db.query(
            """
            SELECT id
            FROM $case->has_batch->batch
            """,
            {"case": case_id},
        )
        batch_ids = {str(row.get("id")) for row in _query_result_rows(batches_by_case)}
        linked_batch_ids = {
            str(row.get("id")) for row in _query_result_rows(linked_batches)
        }
        linked_batch_count = 0
        for batch_id in sorted(batch_ids - linked_batch_ids):
            await db.query(
                "RELATE $case->has_batch->$batch",
                {"case": case_id, "batch": batch_id},
            )
            linked_batch_count += 1

        return {
            "linked_sessions": linked_session_count,
            "linked_batches": linked_batch_count,
        }


def _build_case_rollup(
    sessions: list[dict[str, Any]], batches: list[dict[str, Any]]
) -> dict[str, int]:
    return {
        "total_sessions": len(sessions),
        "completed_sessions": sum(
            1 for row in sessions if row.get("status") == "completed"
        ),
        "failed_sessions": sum(
            1 for row in sessions if row.get("status") in {"failed", "error"}
        ),
        "total_batches": len(batches),
        "completed_batches": sum(
            1 for row in batches if row.get("status") == "completed"
        ),
        "failed_batches": sum(
            1 for row in batches if row.get("status") in {"failed", "error"}
        ),
    }


def _build_case_history_payload(
    case_row: dict[str, Any],
    sessions: list[dict[str, Any]],
    batches: list[dict[str, Any]],
    *,
    limit: int,
) -> dict[str, Any]:
    rollup = _build_case_rollup(sessions, batches)
    activity: list[dict[str, Any]] = []
    for row in sessions:
        confidence = None
        metadata = row.get("metadata")
        if isinstance(metadata, dict):
            confidence = _safe_float(metadata.get("aggregate_confidence"))
        if confidence is None and isinstance(row.get("verdict"), dict):
            confidence = _safe_float(row["verdict"].get("confidence"))
        activity.append(
            {
                "type": "session",
                "id": row.get("id"),
                "status": row.get("status"),
                "claim": row.get("claim_text"),
                "claim_snippet": _claim_snippet(row.get("claim_text")),
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
                "confidence": confidence,
            }
        )
    for row in batches:
        activity.append(
            {
                "type": "batch",
                "id": row.get("id"),
                "status": row.get("status"),
                "name": row.get("name"),
                "total_claims": row.get("total_claims"),
                "completed_claims": row.get("completed_claims"),
                "started_at": row.get("started_at"),
                "completed_at": row.get("completed_at"),
                "summary": _batch_summary_text(row),
            }
        )

    activity.sort(key=lambda row: str(row.get("started_at") or ""))
    if limit > 0:
        activity = activity[-limit:]

    return {
        "case": {
            "id": case_row.get("id"),
            "name": case_row.get("name"),
            "status": case_row.get("status"),
            "description": case_row.get("description"),
            "created_at": case_row.get("created_at"),
            "updated_at": case_row.get("updated_at"),
        },
        "rollup": rollup,
        "activity": activity,
    }


def _render_case_export_markdown(payload: dict[str, Any]) -> str:
    case_row = payload["case"]
    sessions = payload["sessions"]
    batches = payload["batches"]
    rollup = payload["rollup"]
    lines = [
        f"# Case Report: {case_row.get('name') or case_row.get('id')}",
        "",
        "## Case Metadata",
        f"- ID: {case_row.get('id')}",
        f"- Status: {case_row.get('status')}",
        f"- Created: {case_row.get('created_at')}",
        f"- Updated: {case_row.get('updated_at')}",
        f"- Description: {case_row.get('description') or ''}",
        "",
        "## Rollup",
        f"- Sessions: {rollup['total_sessions']} (completed={rollup['completed_sessions']}, failed={rollup['failed_sessions']})",
        f"- Batches: {rollup['total_batches']} (completed={rollup['completed_batches']}, failed={rollup['failed_batches']})",
        "",
        "## Sessions",
    ]
    if sessions:
        for row in sessions:
            claim = _claim_snippet(row.get("claim_text"), width=120)
            lines.append(
                f"- {row.get('id')} | {row.get('status')} | started={row.get('started_at')} | completed={row.get('completed_at')} | claim={claim}"
            )
    else:
        lines.append("- No sessions linked to this case.")

    lines.extend(["", "## Batches"])
    if batches:
        for row in batches:
            lines.append(
                f"- {row.get('id')} | {row.get('status')} | {row.get('completed_claims')}/{row.get('total_claims')} completed | started={row.get('started_at')} | completed={row.get('completed_at')}"
            )
            summary_text = _batch_summary_text(row)
            if summary_text:
                lines.append(f"  - summary: {summary_text}")
    else:
        lines.append("- No batches linked to this case.")

    return "\n".join(lines) + "\n"


async def show_models(
    ui: TerminalUI, action: str | None, args: argparse.Namespace
) -> int:
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
                    rows.append(
                        [
                            m.name,
                            _humanize_size(m.size_bytes),
                            m.quantization or "—",
                            m.parameter_count or "—",
                            "yes" if m.loaded else "—",
                            ", ".join(m.capabilities),
                            m.provider,
                            ep_name,
                        ]
                    )
            except Exception as exc:
                rows.append(
                    [
                        f"(error: {exc})",
                        "—",
                        "—",
                        "—",
                        "—",
                        "—",
                        ep.provider_type,
                        ep_name,
                    ]
                )
            finally:
                await provider.close()
        if rows:
            ui.table(
                "Models",
                [
                    "Name",
                    "Size",
                    "Quant",
                    "Params",
                    "Loaded",
                    "Caps",
                    "Provider",
                    "Endpoint",
                ],
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


async def show_endpoints(
    ui: TerminalUI, action: str | None, args: argparse.Namespace
) -> int:
    """Endpoint management commands."""
    from aletheia.providers import (
        get_configured_endpoints,
        get_provider,
        probe_endpoint,
    )

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
                [
                    m["name"],
                    m.get("family") or "—",
                    m.get("parameter_count") or "—",
                    ", ".join(m.get("capabilities", [])),
                ]
                for m in models
            ]
            ui.table(
                "Available Models", ["Name", "Family", "Params", "Capabilities"], rows
            )
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
            rows.append(
                [
                    ep_name,
                    ep.url,
                    ep.provider_type,
                    ", ".join(ep.roles),
                    "healthy" if health.get("ok") else "unreachable",
                    health.get("model_count", "—"),
                ]
            )
        except Exception as exc:
            rows.append(
                [
                    ep_name,
                    ep.url,
                    ep.provider_type,
                    ", ".join(ep.roles),
                    f"error: {exc}",
                    "—",
                ]
            )
        finally:
            await provider.close()

    if rows:
        ui.table(
            "Endpoints", ["Name", "URL", "Provider", "Roles", "Status", "Models"], rows
        )
    else:
        ui.warning(
            "No endpoints configured. Create aletheia.yaml or set ALETHEIA_LLM_BASE_URL."
        )
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
            ui.success(
                f"Dry run: {stats['documents_seen']} documents would be ingested"
            )
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


def _run_case(ui: TerminalUI, args: argparse.Namespace) -> int:
    """Dispatch case management subcommand."""
    from aletheia.db import get_connection

    action = getattr(args, "case_action", None)
    if not action:
        ui.error(
            "Missing case action. Use: aletheia case {create,list,show,history,export,reconcile}"
        )
        return 2

    if action == "create":
        name = str(getattr(args, "name", "")).strip()
        if not name:
            ui.error("Case name cannot be empty.")
            return 2
        description = getattr(args, "description", None)

        async def _create() -> dict[str, Any] | None:
            async with get_connection() as db:
                result = await db.query(
                    """
                    CREATE case SET
                        name = $name,
                        description = $description,
                        status = 'active'
                    """,
                    {"name": name, "description": description},
                )
                rows = _query_result_rows(result)
                return rows[0] if rows else None

        created = asyncio.run(_create())
        if not created:
            ui.error("Failed to create case.")
            return 2
        case_id = str(created.get("id", ""))
        ui.success(f"Case created: {case_id}")
        ui.info(f"Use with claim/batch: --case {case_id}")
        ui.info(f"Next: aletheia case history {case_id}")
        return 0

    if action == "list":
        limit = max(1, int(getattr(args, "limit", 20)))

        async def _list() -> list[dict[str, Any]]:
            async with get_connection() as db:
                result = await db.query(
                    """
                    SELECT id, name, status, created_at
                    FROM case
                    ORDER BY created_at DESC
                    LIMIT $limit
                    """,
                    {"limit": limit},
                )
                return _query_result_rows(result)

        rows = asyncio.run(_list())
        if not rows:
            ui.warning("No cases found.")
            return 0
        ui.table(
            "Cases",
            ["ID", "Name", "Status", "Created"],
            [
                [
                    row.get("id"),
                    row.get("name"),
                    row.get("status"),
                    row.get("created_at"),
                ]
                for row in rows
            ],
        )
        return 0

    if action == "show":
        case_id = _normalize_case_id(getattr(args, "case_id", None))
        if case_id is None:
            ui.error("Case ID is required.")
            return 2

        async def _show() -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
            async with get_connection() as db:
                case_result = await db.query(
                    "SELECT * FROM $case LIMIT 1", {"case": case_id}
                )
                case_rows = _query_result_rows(case_result)
                if not case_rows:
                    return None, None
                stats_result = await db.query(
                    """
                    SELECT
                        count(->has_session) AS sessions,
                        count(->has_batch) AS batches
                    FROM $case
                    GROUP ALL
                    """,
                    {"case": case_id},
                )
                stats_rows = _query_result_rows(stats_result)
                return case_rows[0], (stats_rows[0] if stats_rows else None)

        case_row, stats = asyncio.run(_show())
        if case_row is None:
            ui.error(f"Case not found: {case_id}")
            return 2
        ui.kv_table(
            "Case",
            [
                ("id", case_row.get("id")),
                ("name", case_row.get("name")),
                ("status", case_row.get("status")),
                ("description", case_row.get("description") or ""),
                ("created_at", case_row.get("created_at")),
                ("sessions", (stats or {}).get("sessions", 0)),
                ("batches", (stats or {}).get("batches", 0)),
            ],
        )
        return 0

    if action == "reconcile":
        case_id = _normalize_case_id(getattr(args, "case_id", None))
        if case_id is None:
            ui.error("Case ID is required.")
            return 2
        if not asyncio.run(_case_exists(case_id)):
            ui.error(f"Case not found: {case_id}")
            return 2
        counts = asyncio.run(_reconcile_case_links(case_id))
        ui.success(
            "Case links reconciled: "
            f"sessions={counts['linked_sessions']} batches={counts['linked_batches']}"
        )
        return 0

    if action == "history":
        case_id = _normalize_case_id(getattr(args, "case_id", None))
        if case_id is None:
            ui.error("Case ID is required.")
            return 2
        limit = max(1, int(getattr(args, "limit", 20)))

        if not asyncio.run(_case_exists(case_id)):
            ui.error(f"Case not found: {case_id}")
            return 2

        case_row, sessions, batches = asyncio.run(_load_case_bundle(case_id))
        if case_row is None:
            ui.error(f"Case loading failed: {case_id}")
            return 2

        payload = _build_case_history_payload(case_row, sessions, batches, limit=limit)
        if bool(getattr(args, "json", False)):
            print(json.dumps(payload, indent=2, default=str))
            return 0

        ui.kv_table(
            "Case Rollup",
            [
                ("id", payload["case"]["id"]),
                ("name", payload["case"]["name"]),
                ("sessions", payload["rollup"]["total_sessions"]),
                ("batches", payload["rollup"]["total_batches"]),
                ("completed_sessions", payload["rollup"]["completed_sessions"]),
                ("failed_sessions", payload["rollup"]["failed_sessions"]),
                ("completed_batches", payload["rollup"]["completed_batches"]),
                ("failed_batches", payload["rollup"]["failed_batches"]),
            ],
        )
        if not payload["activity"]:
            ui.warning("No case activity found.")
            return 0

        rows: list[list[Any]] = []
        for row in payload["activity"]:
            if row["type"] == "session":
                confidence = row.get("confidence")
                confidence_text = ""
                if isinstance(confidence, float):
                    confidence_text = f"{confidence:.2f}"
                rows.append(
                    [
                        "session",
                        row.get("id"),
                        row.get("status"),
                        row.get("claim_snippet"),
                        row.get("started_at"),
                        row.get("completed_at"),
                        confidence_text,
                    ]
                )
            else:
                rows.append(
                    [
                        "batch",
                        row.get("id"),
                        row.get("status"),
                        f"{row.get('completed_claims')}/{row.get('total_claims')} {_claim_snippet(row.get('summary'), width=32)}",
                        row.get("started_at"),
                        row.get("completed_at"),
                        "",
                    ]
                )
        ui.table(
            "Activity",
            ["Type", "ID", "Status", "Detail", "Started", "Completed", "Confidence"],
            rows,
        )
        return 0

    if action == "export":
        case_id = _normalize_case_id(getattr(args, "case_id", None))
        if case_id is None:
            ui.error("Case ID is required.")
            return 2

        export_format = str(getattr(args, "format", "json"))
        output_path = getattr(args, "output", None)

        if not asyncio.run(_case_exists(case_id)):
            ui.error(f"Case not found: {case_id}")
            return 2

        case_row, sessions, batches = asyncio.run(_load_case_bundle(case_id))
        if case_row is None:
            ui.error(f"Case loading failed: {case_id}")
            return 2

        payload = {
            "case": case_row,
            "rollup": _build_case_rollup(sessions, batches),
            "sessions": sessions,
            "batches": batches,
        }

        rendered = ""
        if export_format == "json":
            rendered = json.dumps(payload, indent=2, default=str)
        elif export_format == "jsonl":
            lines = [json.dumps({"type": "case", "record": case_row}, default=str)]
            lines.extend(
                json.dumps({"type": "session", "record": row}, default=str)
                for row in sessions
            )
            lines.extend(
                json.dumps({"type": "batch", "record": row}, default=str)
                for row in batches
            )
            rendered = "\n".join(lines) + "\n"
        else:
            rendered = _render_case_export_markdown(payload)

        if output_path:
            Path(output_path).write_text(rendered, encoding="utf-8")
            ui.success(f"Case export written: {output_path}")
            return 0

        print(rendered)
        return 0

    ui.error(f"Unknown case action: {action}")
    return 2


def _run_batch(ui: TerminalUI, args: argparse.Namespace) -> int:
    """Dispatch batch evaluation subcommand."""
    from aletheia.data_loader import load_methodology_breaks
    from aletheia.db import get_connection

    benchmark = getattr(args, "benchmark", False)
    claims_file = getattr(args, "claims_file", None)
    output_path = getattr(args, "output", None)
    case_id = _normalize_case_id(getattr(args, "case_id", None))

    def _read_claims(path: str) -> list[str]:
        file_path = Path(path)
        if file_path.suffix.lower() != ".csv":
            return [
                line.strip()
                for line in file_path.read_text().splitlines()
                if line.strip()
            ]

        claims: list[str] = []
        with file_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames:
                claim_key = None
                for name in reader.fieldnames:
                    if name is None:
                        continue
                    if name.strip().lower() in {"claim", "text", "description"}:
                        claim_key = name
                        break
                if claim_key is not None:
                    for row in reader:
                        value = (row.get(claim_key) or "").strip()
                        if value:
                            claims.append(value)
                    return claims

        with file_path.open(newline="", encoding="utf-8") as fh:
            for row in csv.reader(fh):
                if not row:
                    continue
                value = row[0].strip()
                if value:
                    claims.append(value)
        return claims

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
        claims = _read_claims(claims_file)
        ui.info(f"Running batch: {len(claims)} claims from {claims_file}")

    if not claims:
        ui.error("No claims found in input.")
        return 2

    if case_id is not None and not asyncio.run(_case_exists(case_id)):
        ui.error(f"Case not found: {case_id}")
        return 2

    orchestrator = OrchestratorAgent()
    results: list[dict[str, Any]] = []
    mode = "benchmark" if benchmark else "file"
    batch_name = f"{mode}-{len(claims)}"

    async def _run() -> tuple[str | None, dict[str, Any]]:
        batch_id: str | None = None
        status_counts: dict[str, int] = {}

        async def _create_batch() -> str | None:
            try:
                async with get_connection() as db:
                    created = await db.query(
                        """
                        CREATE batch SET
                            name = $name,
                            case_id = $case_id,
                            status = 'running',
                            total_claims = $total_claims,
                            completed_claims = 0
                        """,
                        {
                            "name": batch_name,
                            "case_id": case_id,
                            "total_claims": len(claims),
                        },
                    )
                    rows = _query_result_rows(created)
                    return str(rows[0].get("id")) if rows else None
            except Exception as exc:  # noqa: BLE001
                ui.warning(f"Batch tracking unavailable: {exc}")
                return None

        async def _link_case(batch_record: str) -> None:
            if case_id is None:
                return
            try:
                async with get_connection() as db:
                    await db.query(
                        "RELATE $case->has_batch->$batch",
                        {"case": case_id, "batch": batch_record},
                    )
            except Exception:
                return

        async def _update_progress(completed: int) -> None:
            if batch_id is None:
                return
            try:
                async with get_connection() as db:
                    await db.query(
                        "UPDATE $batch SET completed_claims = $completed",
                        {"batch": batch_id, "completed": completed},
                    )
            except Exception:
                return

        async def _complete_batch(summary: dict[str, Any]) -> None:
            if batch_id is None:
                return
            try:
                async with get_connection() as db:
                    await db.query(
                        """
                        UPDATE $batch SET
                            status = 'completed',
                            completed_claims = $completed,
                            completed_at = time::now(),
                            results = $results
                        """,
                        {
                            "batch": batch_id,
                            "completed": len(results),
                            "results": summary,
                        },
                    )
            except Exception:
                return

        try:
            batch_id = await _create_batch()
            if batch_id:
                ui.info(f"Batch record: {batch_id}")
                await _link_case(batch_id)

            for i, claim in enumerate(claims, 1):
                suffix = "" if len(claim) <= 80 else "..."
                ui.info(f"[{i}/{len(claims)}] {claim[:80]}{suffix}")
                try:
                    verdict = await orchestrator.process_claim(claim, case_id=case_id)
                    status_key = verdict.status.value
                    status_counts[status_key] = status_counts.get(status_key, 0) + 1
                    results.append(
                        {
                            "claim": claim,
                            "status": status_key,
                            "confidence": verdict.confidence,
                            "severity": verdict.severity.value,
                            "comparability": verdict.comparability.value,
                            "summary": verdict.summary,
                            "breaks_found": len(verdict.breaks_found),
                        }
                    )
                except Exception as exc:
                    results.append({"claim": claim, "error": str(exc)})
                await _update_progress(i)

            successful = [
                row
                for row in results
                if "error" not in row
                and isinstance(row.get("confidence"), (int, float))
            ]
            avg_confidence = (
                sum(float(row["confidence"]) for row in successful) / len(successful)
                if successful
                else 0.0
            )
            summary = {
                "total_claims": len(results),
                "succeeded": len(successful),
                "failed": len(results) - len(successful),
                "avg_confidence": avg_confidence,
                "status_counts": status_counts,
            }
            await _complete_batch(summary)
            return batch_id, summary
        finally:
            await orchestrator.close()

    batch_id, summary = asyncio.run(_run())

    output_payload = {
        "batch_id": batch_id,
        "case_id": case_id,
        "name": batch_name,
        "mode": mode,
        "source": "PHASE3_BREAKS" if benchmark else claims_file,
        "summary": summary,
        "results": results,
    }

    output_json = json.dumps(output_payload, indent=2)
    if output_path:
        from pathlib import Path as P

        P(output_path).write_text(output_json)
        ui.success(f"Results written to {output_path}")
    else:
        print(output_json)

    ui.success(
        f"Batch complete: {summary['succeeded']}/{summary['total_claims']} succeeded"
    )
    return 0


def _run_graph(ui: TerminalUI, args: argparse.Namespace) -> int:
    """Dispatch graph query subcommand."""
    action = getattr(args, "graph_action", None)
    if not action:
        ui.error(
            "Missing graph action. Use: aletheia graph {provenance,impacts,timeline,recall}"
        )
        return 2

    from aletheia.agents.archivist import ArchivistAgent

    archivist = ArchivistAgent()

    if action == "provenance":
        session_id = args.session_id

        payload = asyncio.run(archivist.provenance_chain(session_id))
        if payload is None:
            ui.error(f"Session not found: {session_id}")
            return 2

        session = (
            payload.get("session") if isinstance(payload.get("session"), dict) else {}
        )
        ui.kv_table(
            "Session",
            [
                ("id", session.get("id")),
                ("case_id", session.get("case_id") or ""),
                ("status", session.get("status")),
                ("started_at", session.get("started_at")),
                ("completed_at", session.get("completed_at")),
            ],
        )

        documents = (
            payload.get("documents")
            if isinstance(payload.get("documents"), list)
            else []
        )
        if documents:
            ui.table(
                "Evidence Documents",
                ["ID", "Title", "URL"],
                [
                    [
                        row.get("id"),
                        row.get("title") or "",
                        row.get("url") or "",
                    ]
                    for row in documents
                    if isinstance(row, dict)
                ],
            )
        else:
            ui.warning("No evidence documents linked to this session.")

        changes = (
            payload.get("methodology_changes")
            if isinstance(payload.get("methodology_changes"), list)
            else []
        )
        if changes:
            ui.table(
                "Methodology Changes",
                ["ID", "Type", "Effective", "Description", "Impact"],
                [
                    [
                        row.get("id"),
                        row.get("change_type") or "",
                        row.get("effective_date") or "",
                        _claim_snippet(row.get("description"), width=72),
                        row.get("impact_estimate") or "",
                    ]
                    for row in changes
                    if isinstance(row, dict)
                ],
            )

        datasets = (
            payload.get("datasets") if isinstance(payload.get("datasets"), list) else []
        )
        if datasets:
            ui.table(
                "Datasets",
                ["ID", "Code", "Name"],
                [
                    [row.get("id"), row.get("code") or "", row.get("name") or ""]
                    for row in datasets
                    if isinstance(row, dict)
                ],
            )

        agencies = (
            payload.get("agencies") if isinstance(payload.get("agencies"), list) else []
        )
        if agencies:
            ui.table(
                "Agencies",
                ["ID", "Code", "Name"],
                [
                    [row.get("id"), row.get("code") or "", row.get("name") or ""]
                    for row in agencies
                    if isinstance(row, dict)
                ],
            )
        return 0

    if action == "impacts":
        change_id = args.change_id

        payload = asyncio.run(archivist.change_impacts(change_id))
        if payload is None:
            ui.error(f"Methodology change not found: {change_id}")
            return 2

        change = (
            payload.get("change") if isinstance(payload.get("change"), dict) else {}
        )
        ui.kv_table(
            "Methodology Change",
            [
                ("id", change.get("id")),
                ("type", change.get("change_type")),
                ("effective_date", change.get("effective_date") or ""),
                ("severity", change.get("severity") or ""),
                ("comparability", change.get("comparability") or ""),
                ("impact_estimate", change.get("impact_estimate") or ""),
                ("description", change.get("description") or ""),
            ],
        )

        indicators = (
            payload.get("indicators")
            if isinstance(payload.get("indicators"), list)
            else []
        )
        if indicators:
            ui.table(
                "Affected Indicators",
                ["ID", "Code", "Name", "Unit"],
                [
                    [
                        row.get("id"),
                        row.get("code") or "",
                        row.get("name") or "",
                        row.get("unit") or "",
                    ]
                    for row in indicators
                    if isinstance(row, dict)
                ],
            )
        else:
            ui.warning("No affected indicators linked to this methodology change.")

        datasets = (
            payload.get("datasets") if isinstance(payload.get("datasets"), list) else []
        )
        if datasets:
            ui.table(
                "Linked Datasets",
                ["ID", "Code", "Name"],
                [
                    [row.get("id"), row.get("code") or "", row.get("name") or ""]
                    for row in datasets
                    if isinstance(row, dict)
                ],
            )

        agencies = (
            payload.get("agencies") if isinstance(payload.get("agencies"), list) else []
        )
        if agencies:
            ui.table(
                "Publishing Agencies",
                ["ID", "Code", "Name"],
                [
                    [row.get("id"), row.get("code") or "", row.get("name") or ""]
                    for row in agencies
                    if isinstance(row, dict)
                ],
            )
        return 0

    if action == "timeline":
        dataset_code = str(getattr(args, "dataset_code", "")).strip()
        if not dataset_code:
            ui.error("Dataset code is required.")
            return 2

        payload = asyncio.run(archivist.dataset_timeline(dataset_code))
        if payload is None:
            ui.error(f"Dataset not found: {dataset_code}")
            return 2

        dataset = (
            payload.get("dataset") if isinstance(payload.get("dataset"), dict) else {}
        )
        ui.kv_table(
            "Dataset",
            [
                ("id", dataset.get("id")),
                ("code", dataset.get("code") or ""),
                ("name", dataset.get("name") or ""),
                ("description", dataset.get("description") or ""),
            ],
        )

        changes = (
            payload.get("changes") if isinstance(payload.get("changes"), list) else []
        )
        if not changes:
            ui.warning("No methodology changes found for this dataset.")
            return 0

        ui.table(
            "Methodology Timeline",
            ["Effective", "ID", "Type", "Severity", "Comparability", "Description"],
            [
                [
                    row.get("effective_date") or "",
                    row.get("id"),
                    row.get("change_type") or "",
                    row.get("severity") or "",
                    row.get("comparability") or "",
                    _claim_snippet(row.get("description"), width=72),
                ]
                for row in changes
                if isinstance(row, dict)
            ],
        )
        return 0

    if action == "recall":
        source_session_id = str(getattr(args, "session_id", "") or "").strip() or None
        dataset_code = str(getattr(args, "dataset_code", "") or "").strip() or None
        indicator = str(getattr(args, "indicator", "") or "").strip() or None
        limit = max(1, int(getattr(args, "limit", 10)))

        if source_session_id is None and dataset_code is None and indicator is None:
            ui.error("Provide --session or --dataset or --indicator.")
            return 2

        payload = asyncio.run(
            archivist.prior_verification_recall(
                dataset=dataset_code,
                indicator=indicator,
                session_id=source_session_id,
                limit=limit,
            )
        )
        query = payload.get("query") if isinstance(payload.get("query"), dict) else {}
        matches = (
            payload.get("matches") if isinstance(payload.get("matches"), list) else []
        )

        ui.kv_table(
            "Recall Query",
            [
                ("source_session_id", query.get("source_session_id") or ""),
                ("dataset", query.get("dataset") or ""),
                ("indicator", query.get("indicator") or ""),
                ("matches", len(matches)),
            ],
        )
        if not matches:
            ui.warning("No prior similar sessions found.")
            return 0

        rows: list[list[Any]] = []
        for item in matches:
            if not isinstance(item, dict):
                continue
            session = (
                item.get("session") if isinstance(item.get("session"), dict) else {}
            )
            verdict = (
                item.get("verdict") if isinstance(item.get("verdict"), dict) else {}
            )
            changes = (
                item.get("methodology_changes")
                if isinstance(item.get("methodology_changes"), list)
                else []
            )
            rows.append(
                [
                    session.get("id"),
                    session.get("case_id") or "",
                    session.get("claim_dataset") or "",
                    session.get("claim_indicator") or "",
                    verdict.get("status") or "",
                    verdict.get("confidence") or "",
                    len(changes),
                    session.get("started_at") or "",
                ]
            )

        ui.table(
            "Prior Verification Recall",
            [
                "Session",
                "Case",
                "Dataset",
                "Indicator",
                "Verdict",
                "Confidence",
                "Changes",
                "Started",
            ],
            rows,
        )
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
        case_id = _normalize_case_id(getattr(args, "case_id", None))
        if case_id is not None and not asyncio.run(_case_exists(case_id)):
            ui.error(f"Case not found: {case_id}")
            return 2
        asyncio.run(
            single_claim(
                ui,
                claim,
                show_json=bool(args.json),
                show_trace=bool(args.trace),
                case_id=case_id,
            )
        )
        return 0
    if command == "case":
        return _run_case(ui, args)
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
            ui.success(
                f"Seed complete: {result['actions']} (db: {result['db_url_redacted']})"
            )
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
        return asyncio.run(
            show_endpoints(ui, getattr(args, "endpoints_action", None), args)
        )

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
