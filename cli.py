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
from aletheia.db import get_db_url, test_connection
from aletheia.retrieval_store import RetrievalStore
from aletheia.runtime_profiles import (
    PROFILE_CHOICES,
    ResolvedRuntimeProfile,
    apply_runtime_profile,
)
from aletheia.tui import TerminalUI


def _capability_rows() -> list[tuple[str, bool, str]]:
    crawl4ai_installed = importlib.util.find_spec("crawl4ai") is not None
    crawl4ai_enabled = os.environ.get("ALETHEIA_ENABLE_CRAWL4AI_FALLBACK", "0") == "1"
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


def _runtime_override_args(args: argparse.Namespace) -> dict[str, str | None]:
    return {
        "ALETHEIA_LLM_BASE_URL": getattr(args, "llm_base_url", None),
        "ALETHEIA_LLM_MODEL": getattr(args, "llm_model", None),
        "ALETHEIA_EMBED_BASE_URL": getattr(args, "embed_base_url", None),
        "ALETHEIA_EMBED_MODEL": getattr(args, "embed_model", None),
        "ALETHEIA_DB_URL": getattr(args, "db_url", None),
    }


def _render_capabilities(ui: TerminalUI) -> None:
    rows = [
        [name, "enabled" if enabled else "optional/off", note]
        for name, enabled, note in _capability_rows()
    ]
    ui.table("Capability Matrix", ["Capability", "State", "Notes"], rows)


def format_capability_matrix() -> str:
    """Render capability matrix in plain-text form (stable test/helper API)."""
    lines = ["Capability Matrix"]
    for name, enabled, note in _capability_rows():
        state = "enabled" if enabled else "optional/off"
        lines.append(f"- {name}: {state} ({note})")
    return "\n".join(lines)


def _render_verdict(ui: TerminalUI, verdict) -> None:
    ui.kv_table(
        "Verdict",
        [
            ("status", verdict.status.value),
            ("severity", verdict.severity.value),
            ("comparability", verdict.comparability.value),
            ("confidence", f"{verdict.confidence:.0%}"),
            ("claim", verdict.claim.original_text),
            ("summary", verdict.summary),
        ],
    )

    if verdict.methodology_vs_real:
        mvr = verdict.methodology_vs_real
        ui.kv_table(
            "Methodology vs Real (estimate)",
            [
                ("methodology_share", mvr.get("methodology_share_estimate")),
                ("methodology_component", mvr.get("methodology_component_estimate")),
                ("real_component", mvr.get("real_component_estimate")),
            ],
        )

    if verdict.breaks_found:
        rows: list[list[str]] = []
        for change in verdict.breaks_found[:5]:
            rows.append(
                [
                    change.effective_date.isoformat() if change.effective_date else "unknown",
                    change.change_type.value,
                    (change.impact_estimate or "")[:80],
                ]
            )
        ui.table("Methodology Breaks", ["Effective Date", "Type", "Impact"], rows)

    if verdict.caveats:
        ui.bullet_list("Caveats", verdict.caveats)

    if verdict.sources:
        ui.bullet_list("Top Sources", [str(source) for source in verdict.sources[:5]])

    if verdict.evidence_snippets:
        ui.bullet_list("Evidence Snippets", [str(item) for item in verdict.evidence_snippets[:3]])


def _render_run_details(ui: TerminalUI, run: dict[str, Any]) -> None:
    routing = run.get("routing_plan")
    if isinstance(routing, dict):
        ui.kv_table(
            "Routing Plan",
            [
                ("claim_type", routing.get("claim_type")),
                ("source_ids", routing.get("source_ids")),
                ("fallback_source_id", routing.get("fallback_source_id")),
                ("deep_research_source_ids", routing.get("deep_research_source_ids")),
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
                "Source Execution",
                ["Source", "Docs", "Breaks", "Errors", "Top Error"],
                rows,
            )

    analysis = run.get("analysis") if isinstance(run.get("analysis"), dict) else {}
    claim_value_check = analysis.get("claim_value_check") if isinstance(
        analysis.get("claim_value_check"), dict
    ) else {}
    structural_break = analysis.get("structural_break_detected") if isinstance(
        analysis.get("structural_break_detected"), dict
    ) else {}
    ui.kv_table(
        "Runtime Signals",
        [
            ("fallback_used", analysis.get("fallback_used", run.get("fallback_used"))),
            (
                "deep_research_used",
                analysis.get("deep_research_used", run.get("deep_research_used")),
            ),
            (
                "aggregate_confidence",
                analysis.get(
                    "evidence_aggregate_confidence",
                    run.get("aggregate_confidence", 0.0),
                ),
            ),
            ("claim_value_within_tolerance", claim_value_check.get("within_tolerance")),
            ("claim_value_delta", claim_value_check.get("delta")),
            ("structural_break_detected", structural_break.get("detected")),
            ("provider_budget_skips", analysis.get("provider_budget_skips")),
        ],
    )


def _render_evidence_trail(ui: TerminalUI, run: dict[str, Any]) -> None:
    docs = run.get("evidence_docs")
    if not isinstance(docs, list) or not docs:
        ui.warning("No evidence trail captured yet.")
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
                f"{conf_value:.3f}",
                row.get("title", "Untitled"),
                row.get("url", ""),
            ]
        )
    ui.table("Evidence Trail", ["#", "Source", "Confidence", "Title", "URL"], rows)


def _render_evidence_doc(ui: TerminalUI, run: dict[str, Any], index: int) -> None:
    docs = run.get("evidence_docs")
    if not isinstance(docs, list) or not docs:
        ui.warning("No evidence docs available.")
        return
    if index < 1 or index > len(docs):
        ui.warning(f"Evidence index out of range. Choose 1..{len(docs)}.")
        return
    doc = docs[index - 1]
    if not isinstance(doc, dict):
        ui.warning("Selected evidence entry is not structured.")
        return
    ui.kv_table(
        f"Evidence #{index}",
        [
            ("source_id", doc.get("source_id")),
            ("title", doc.get("title")),
            ("url", doc.get("url")),
            ("relevance_score", doc.get("relevance_score")),
            ("confidence_score", doc.get("confidence_score")),
        ],
    )
    content = str(doc.get("content") or "").strip()
    if content:
        preview = content[:1200] + ("..." if len(content) > 1200 else "")
        ui.thinking_block(preview, collapsed_label="Evidence Content")


def _render_trace(ui: TerminalUI, trace: list[dict[str, Any]]) -> None:
    rows = []
    for message in trace[-25:]:
        rows.append(
            [
                message.get("timestamp"),
                message.get("sender"),
                message.get("receiver"),
                message.get("msg_type"),
                str(message.get("payload", ""))[:120],
            ]
        )
    if rows:
        ui.table("Recent Agent Trace", ["Time", "From", "To", "Type", "Payload"], rows)
    else:
        ui.warning("No trace captured yet. Run a claim first.")


def _render_retrieval_stats(ui: TerminalUI, stats: dict[str, Any]) -> None:
    if stats.get("error"):
        ui.error(f"retrieval stats unavailable: {stats['error']}")
        diagnosis = stats.get("diagnosis") or {}
        if diagnosis:
            ui.kv_table(
                "DB Diagnostics",
                [("db_url", diagnosis.get("db_url_redacted", "n/a"))],
            )
            hints = diagnosis.get("hints") or []
            if hints:
                ui.bullet_list("Likely fixes", [str(hint) for hint in hints[:6]])
        return

    summary = stats.get("summary") or {}
    ui.kv_table(
        f"Retrieval Summary (last {stats.get('window_hours')}h)",
        [
            ("runs", summary.get("total_runs", 0)),
            ("completed_runs", summary.get("completed_runs", 0)),
            ("non_completed_runs", summary.get("non_completed_runs", 0)),
            ("linked_docs", summary.get("linked_docs", 0)),
            ("cache_hits", summary.get("cache_hits", 0)),
            ("cache_hit_rate", f"{summary.get('cache_hit_rate', 0.0):.1%}"),
            ("distinct_sources", summary.get("distinct_sources", 0)),
            ("avg_aggregate_confidence", f"{summary.get('avg_aggregate_confidence', 0.0):.3f}"),
            ("provider_budget_skips", summary.get("provider_budget_skips", 0)),
        ],
    )

    source_rows = stats.get("sources") or []
    if source_rows:
        rows = [
            [
                row.get("source_id"),
                row.get("doc_count", 0),
                row.get("cache_hits", 0),
                row.get("avg_confidence", 0.0),
            ]
            for row in source_rows[:12]
        ]
        ui.table("By Source", ["Source", "Docs", "Cache Hits", "Avg Confidence"], rows)

    recent_runs = stats.get("recent_runs") or []
    if recent_runs:
        rows = [
            [
                row.get("id"),
                row.get("claim_dataset") or "unknown",
                row.get("claim_indicator") or "unknown",
                row.get("status"),
                row.get("evidence_count", 0),
                row.get("fallback_used"),
                row.get("deep_research_used"),
                row.get("provider_budget_skips", 0),
                f"{float(row.get('aggregate_confidence', 0.0)):.3f}",
            ]
            for row in recent_runs
        ]
        ui.table(
            "Recent Runs",
            [
                "ID",
                "Dataset",
                "Indicator",
                "Status",
                "Evidence",
                "Fallback",
                "Deep",
                "Budget Skips",
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
        "ALETHEIA CLI",
        (
            "Type a policy claim to analyze.\n"
            "Built-in commands: help, trace, details, trail, !deep, !rerun, quit"
        ),
    )
    orchestrator = OrchestratorAgent()
    last_claim: str | None = None
    persistent_deep = False

    def _runtime_overrides(*, force_deep: bool) -> dict[str, str] | None:
        if not force_deep:
            return None
        return {"ALETHEIA_ENABLE_DEEP_RESEARCH": "1"}

    def _progress(event: dict[str, Any]) -> None:
        kind = event.get("event")
        if kind == "parser_started":
            ui.info("Pipeline: parsing claim...")
            return
        if kind == "routing_selected":
            sources = event.get("source_ids") or []
            ui.info(f"Pipeline: routed to sources {sources}")
            return
        if kind == "source_started":
            ui.info(f"Pipeline: running source `{event.get('source_id')}`...")
            return
        if kind == "source_completed":
            ui.info(
                (
                    f"Pipeline: `{event.get('source_id')}` done "
                    f"(docs={event.get('doc_count', 0)}, breaks={event.get('break_count', 0)}, "
                    f"errors={event.get('error_count', 0)})"
                )
            )
            return
        if kind == "editor_started":
            ui.info("Pipeline: synthesizing verdict...")
            return
        if kind == "collection_completed":
            ui.info(
                (
                    "Pipeline: evidence collection complete "
                    f"(docs={event.get('evidence_count', 0)}, breaks={event.get('break_count', 0)}, "
                    f"confidence={event.get('aggregate_confidence', 0.0)})"
                )
            )

    async def _run_claim_text(text: str, *, force_deep: bool) -> None:
        nonlocal last_claim
        mode_note = "deep-on" if force_deep else "deep-auto"
        ui.info(f"Analyzing claim ({mode_note})...")
        verdict = await orchestrator.process_claim(
            text,
            runtime_overrides=_runtime_overrides(force_deep=force_deep),
            progress_callback=_progress,
        )
        run = orchestrator.get_last_run_details()
        _render_verdict(ui, verdict)
        _render_run_details(ui, run)
        thinking_blocks = run.get("thinking_blocks")
        if isinstance(thinking_blocks, list):
            for block in thinking_blocks:
                if not isinstance(block, dict):
                    continue
                content = str(block.get("text") or "").strip()
                if not content:
                    continue
                agent = str(block.get("agent") or "LLM")
                ui.thinking_block(content, collapsed_label=f"{agent} Reasoning")
        last_claim = text

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
                ui.bullet_list(
                    "Interactive Commands",
                    [
                        "help: show commands",
                        "trace: show latest inter-agent trace",
                        "details: show latest routing/source runtime details",
                        "trail: list current evidence trail",
                        "trail <n>: inspect one evidence item",
                        "!deep: rerun last claim with deep research forced once",
                        "!deep on|off: toggle persistent deep mode for future claims",
                        "!rerun: rerun last claim with current mode",
                        "!mode: show current interactive mode",
                        "quit: exit session",
                    ],
                )
                continue
            if claim.lower() == "trace":
                _render_trace(ui, orchestrator.get_trace())
                continue
            if claim.lower() == "details":
                _render_run_details(ui, orchestrator.get_last_run_details())
                continue
            if claim.lower() == "!mode":
                ui.kv_table(
                    "Interactive Mode",
                    [
                        ("persistent_deep", persistent_deep),
                        ("last_claim_available", bool(last_claim)),
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
        verdict = await orchestrator.process_claim(claim)
        _render_verdict(ui, verdict)
        run = orchestrator.get_last_run_details()
        _render_run_details(ui, run)
        thinking_blocks = run.get("thinking_blocks")
        if isinstance(thinking_blocks, list):
            for block in thinking_blocks:
                if not isinstance(block, dict):
                    continue
                text = str(block.get("text") or "").strip()
                if text:
                    ui.thinking_block(text, collapsed_label=f"{block.get('agent', 'LLM')} Reasoning")
        if show_trace:
            _render_trace(ui, orchestrator.get_trace())
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
        "Runtime Profile",
        [
            ("name", resolved_profile.name),
            ("profile_file", resolved_profile.profile_file or "(built-in defaults)"),
            (
                "chat_endpoint",
                f"{os.environ.get('ALETHEIA_LLM_BASE_URL')} ({resolved_profile.source_for('ALETHEIA_LLM_BASE_URL')})",
            ),
            (
                "embedding_endpoint",
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
        ui.success("DB connection OK")
        ui.kv_table(
            "Database Health",
            [
                ("db_url", result.get("db_url_redacted")),
                ("pgvector", result.get("pgvector_enabled")),
                ("pgai", result.get("pgai_installed")),
                ("semantic_search_ready", result.get("semantic_search_ready")),
                ("methodology_changes", (result.get("counts") or {}).get("methodology_changes", 0)),
                ("document_chunks", (result.get("counts") or {}).get("document_chunks", 0)),
                ("methodology_embeddings", (result.get("counts") or {}).get("methodology_embeddings", 0)),
                ("document_embeddings", (result.get("counts") or {}).get("document_embeddings", 0)),
                ("tables", len(result.get("tables") or [])),
            ],
        )
        _render_capabilities(ui)
        return 0

    ui.error("DB connection FAILED")
    ui.kv_table(
        "Failure Details",
        [
            ("db_url", result.get("db_url_redacted", "n/a")),
            ("category", result.get("category", "unknown")),
            ("error", result.get("message", "n/a")),
        ],
    )
    hints = [str(hint) for hint in (result.get("hints") or [])[:8]]
    if hints:
        ui.bullet_list("Likely fixes", hints)
    _render_capabilities(ui)
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
    semantic_ok = bool(db_result.get("semantic_search_ready")) if db_ok else False
    chat_diag = llm_result.get("chat") if isinstance(llm_result.get("chat"), dict) else {}
    embed_diag = (
        llm_result.get("embeddings") if isinstance(llm_result.get("embeddings"), dict) else {}
    )

    ui.banner(
        "ALETHEIA Onboarding",
        (
            "Local-first system check for stable Phase 3 foundations.\n"
            f"TUI mode: {ui.state.reason}"
        ),
    )
    _render_profile_context(ui, resolved_profile)

    ui.table(
        "Critical Subsystems",
        ["Component", "State", "Details"],
        [
            [
                "database",
                "ready" if db_ok else "not ready",
                db_result.get("db_url_redacted", "n/a"),
            ],
            [
                "llm_chat",
                "ready" if chat_ok else "not ready",
                chat_diag.get("endpoint", "n/a"),
            ],
            [
                "embeddings",
                "ready" if embed_ok else "not ready",
                embed_diag.get("endpoint", "n/a"),
            ],
            [
                "semantic_search",
                "ready" if semantic_ok else "not ready",
                (
                    "document_chunks_embedding + methodology_changes_embedding available"
                    if semantic_ok
                    else "run vectorizer/materialization"
                ),
            ],
        ],
    )

    counts = db_result.get("counts") if isinstance(db_result.get("counts"), dict) else {}
    if db_ok and counts:
        ui.kv_table(
            "Knowledge Base Coverage",
            [
                ("methodology_changes", counts.get("methodology_changes", 0)),
                ("document_chunks", counts.get("document_chunks", 0)),
                ("methodology_embeddings", counts.get("methodology_embeddings", 0)),
                ("document_embeddings", counts.get("document_embeddings", 0)),
            ],
        )

    chat_errors = [
        str(err).strip()
        for err in (chat_diag.get("errors") or [])[:6]
        if str(err).strip()
    ]
    chat_hints = [
        str(hint).strip()
        for hint in (chat_diag.get("hints") or [])[:6]
        if str(hint).strip()
    ]
    if chat_errors or chat_hints:
        ui.bullet_list(
            "LLM Chat Diagnostics",
            [*chat_errors, *chat_hints],
        )

    embed_errors = [
        str(err).strip()
        for err in (embed_diag.get("errors") or [])[:6]
        if str(err).strip()
    ]
    embed_hints = [
        str(hint).strip()
        for hint in (embed_diag.get("hints") or [])[:6]
        if str(hint).strip()
    ]
    if chat_ok and not embed_ok and bool(embed_diag.get("unsupported")):
        embed_hints.insert(
            0,
            "Chat is reachable but embeddings are unsupported on this endpoint; configure a different embedding endpoint/model.",
        )
    if not embed_ok and not embed_errors and not embed_hints:
        embed_hints.append(
            "Embedding probe failed without detailed server message; verify embedding model is loaded and /v1/embeddings is enabled."
        )
    if embed_errors or embed_hints:
        ui.bullet_list(
            "Embedding Diagnostics",
            [*embed_errors, *embed_hints],
        )

    if not db_ok:
        db_hints = [str(hint) for hint in (db_result.get("hints") or [])[:6]]
        if db_hints:
            ui.bullet_list("DB fixes", db_hints)

    key_rows = _optional_key_status()
    ui.table(
        "Optional Keys (Non-blocking)",
        ["Key", "State", "Impact"],
        [
            [name, "present" if ready else "missing", note]
            for name, ready, note in key_rows
        ],
    )

    _render_capabilities(ui)

    next_steps = [
        "Run `uv run python cli.py db-doctor` after DB credential/volume fixes.",
        "Run `uv run python cli.py onboarding` after starting your local model runtime and loading models.",
        "Run `uv run python -m aletheia.ingest --seed-phase3 --fetch-urls --materialize-embeddings` to build the expanded Phase 3 KB.",
        "Run `uv run python -m aletheia.vectorizer` to create/refresh semantic embedding views.",
        "Use `uv run python demo.py --quick --assert-phase2` for strict demo contract checks.",
    ]
    ui.bullet_list("Next steps", next_steps)

    return 0 if (db_ok and chat_ok and embed_ok and semantic_ok) else 2


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
        prog="cli.py",
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
        "-h",
        "--help",
    }
    if argv[0] in known:
        return argv
    if argv[0].startswith("-"):
        return argv
    # Backward compatibility: `cli.py "<claim text>"`
    return ["claim", *argv]


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

    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
