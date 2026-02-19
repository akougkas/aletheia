#!/usr/bin/env python
"""Probe local/homelab AI endpoints and generate ALETHEIA env profiles."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

import httpx

from aletheia.runtime_profiles import PROFILE_CHOICES


# LAN-IP-first for personal homelab reliability/performance.
ENDPOINTS = [
    {"name": "zbook_lmstudio_models", "url": "http://127.0.0.1:1234/v1/models", "kind": "openai_models"},
    {"name": "zbook_ollama_tags", "url": "http://127.0.0.1:11434/api/tags", "kind": "ollama_tags"},
    {"name": "zbook_ollama_models", "url": "http://127.0.0.1:11434/v1/models", "kind": "openai_models"},
    {"name": "mini_llama_models", "url": "http://192.168.86.141:8080/v1/models", "kind": "openai_models"},
    {"name": "mini_llama_embeddings", "url": "http://192.168.86.141:8080/v1/embeddings", "kind": "embed_probe"},
    {"name": "mini_ollama_tags", "url": "http://192.168.86.141:11434/api/tags", "kind": "ollama_tags"},
    {"name": "dynamo_lmstudio_models", "url": "http://192.168.86.143:1234/v1/models", "kind": "openai_models"},
    {"name": "dynamo_ollama_tags", "url": "http://192.168.86.143:11434/api/tags", "kind": "ollama_tags"},
]

def _probe(client: httpx.Client, endpoint: dict[str, str]) -> dict[str, Any]:
    name = endpoint["name"]
    url = endpoint["url"]
    kind = endpoint["kind"]
    payload: dict[str, Any] = {
        "name": name,
        "url": url,
        "ok": False,
        "status": None,
        "error": None,
        "models": [],
    }

    try:
        if kind == "embed_probe":
            response = client.post(url, json={"input": "healthcheck"})
        else:
            response = client.get(url)
    except Exception as exc:  # noqa: BLE001
        payload["error"] = str(exc)
        return payload

    payload["status"] = response.status_code
    payload["ok"] = 200 <= response.status_code < 300
    if response.status_code >= 400:
        payload["error"] = response.text[:300]
        return payload

    try:
        data = response.json()
    except Exception:  # noqa: BLE001
        payload["raw"] = response.text[:300]
        return payload

    if kind in {"openai_models", "embed_probe"} and isinstance(data, dict):
        items = data.get("data")
        if isinstance(items, list):
            payload["models"] = [row.get("id") for row in items if isinstance(row, dict) and row.get("id")]
    elif kind == "ollama_tags" and isinstance(data, dict):
        items = data.get("models")
        if isinstance(items, list):
            payload["models"] = [row.get("name") for row in items if isinstance(row, dict) and row.get("name")]
    else:
        payload["raw"] = data
    return payload


def _pick_model(models: list[str], preferred: list[str]) -> str | None:
    by_lower = {model.lower(): model for model in models}
    for candidate in preferred:
        if candidate.lower() in by_lower:
            return by_lower[candidate.lower()]
    return models[0] if models else None


def _choose_chat_target(profile: str, lookup: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    zbook_ollama = lookup.get("zbook_ollama_tags", {}).get("models", [])
    if isinstance(zbook_ollama, list) and zbook_ollama:
        model = _pick_model(
            [str(item) for item in zbook_ollama],
            ["granite4:small-h", "gpt-oss:20b", "gpt-oss:latest"],
        )
        if model:
            return "http://127.0.0.1:11434", model

    zbook_lmstudio = lookup.get("zbook_lmstudio_models", {}).get("models", [])
    zbook_chat = [str(item) for item in zbook_lmstudio if "embedding" not in str(item).lower()]
    if zbook_chat:
        model = _pick_model(zbook_chat, ["qwen/qwen3-4b-2507", "mistralai/ministral-3-3b"])
        if model:
            return "http://127.0.0.1:1234", model

    if profile == "homelab-dev":
        mini_llama = lookup.get("mini_llama_models", {}).get("models", [])
        if isinstance(mini_llama, list) and mini_llama:
            return "http://192.168.86.141:8080", str(mini_llama[0])

        dynamo_ollama = lookup.get("dynamo_ollama_tags", {}).get("models", [])
        if isinstance(dynamo_ollama, list) and dynamo_ollama:
            model = _pick_model([str(item) for item in dynamo_ollama], ["rnj-1:8b", "nemotron-3-nano:30b"])
            if model:
                return "http://192.168.86.143:11434", model

    return None, None


def _choose_embed_target(profile: str, lookup: dict[str, dict[str, Any]]) -> tuple[str | None, str | None]:
    zbook_ollama = lookup.get("zbook_ollama_tags", {}).get("models", [])
    zbook_embed = [str(item) for item in zbook_ollama if "embedding" in str(item).lower()]
    if zbook_embed:
        model = _pick_model(zbook_embed, ["qwen3-embedding:8b", "qwen3-embedding:0.6b", "embeddinggemma"])
        if model:
            return "http://127.0.0.1:11434", model

    zbook_lmstudio = lookup.get("zbook_lmstudio_models", {}).get("models", [])
    lms_embed = [str(item) for item in zbook_lmstudio if "embedding" in str(item).lower()]
    if lms_embed:
        model = _pick_model(lms_embed, ["text-embedding-qwen3-embedding-0.6b", "text-embedding-nomic-embed-text-v1.5"])
        if model:
            return "http://127.0.0.1:1234", model

    if profile == "homelab-dev":
        dynamo_lmstudio = lookup.get("dynamo_lmstudio_models", {}).get("models", [])
        dyn_embed = [str(item) for item in dynamo_lmstudio if "embedding" in str(item).lower()]
        if dyn_embed:
            return "http://192.168.86.143:1234", dyn_embed[0]

    return None, None


def _build_env_lines(
    *,
    profile: str,
    chat_base: str | None,
    chat_model: str | None,
    embed_base: str | None,
    embed_model: str | None,
) -> list[str]:
    lines: list[str] = [
        f"# Generated by scripts/probe_homelab_ai.py ({profile})",
        "# Chat + embeddings endpoints",
        f"ALETHEIA_RUNTIME_PROFILE={profile}",
        f"ALETHEIA_LLM_BASE_URL={chat_base or 'http://127.0.0.1:1234'}",
    ]
    if chat_model:
        lines.append(f"ALETHEIA_LLM_MODEL={chat_model}")
    else:
        lines.append("# ALETHEIA_LLM_MODEL=<load a chat model and set it here>")

    if embed_base:
        lines.append(f"ALETHEIA_EMBED_BASE_URL={embed_base}")
    else:
        lines.append("ALETHEIA_EMBED_BASE_URL=http://127.0.0.1:1234")
    if embed_model:
        lines.append(f"ALETHEIA_EMBED_MODEL={embed_model}")
    else:
        lines.append("# ALETHEIA_EMBED_MODEL=<load an embedding model and set it here>")

    lines.extend(
        [
            "",
            "# Retrieval/search defaults (Brave-first, no Google/SERP required)",
            "ALETHEIA_WEB_SEARCH_PROVIDER=auto",
            "ALETHEIA_WEB_SEARCH_CHAIN=brave,duckduckgo",
            "ALETHEIA_ENABLE_CRAWL4AI_FALLBACK=1",
            "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN=brave:3,duckduckgo:2,google:0,serpapi_google_scholar:0",
            "ALETHEIA_WEB_RATE_LIMIT_PER_MIN=brave:30,duckduckgo:40,google:0,serpapi_google_scholar:0",
            "ALETHEIA_ENABLE_DEEP_RESEARCH=0",
            "",
            "# Optional homelab references",
            "ALETHEIA_MINI_LLM_BASE_URL=http://192.168.86.141:8080",
            "ALETHEIA_DYNAMO_LMSTUDIO_BASE_URL=http://192.168.86.143:1234",
            "ALETHEIA_DYNAMO_OLLAMA_BASE_URL=http://192.168.86.143:11434",
            "",
            "# API keys (fill locally, never commit real values)",
            f"BRAVE_SEARCH_API_KEY={os.environ.get('BRAVE_SEARCH_API_KEY', '')}",
            f"FRED_API_KEY={os.environ.get('FRED_API_KEY', '')}",
            "GOOGLE_CSE_API_KEY=",
            "GOOGLE_CSE_CX=",
            "SERPAPI_API_KEY=",
            "CENSUS_API_KEY=",
        ]
    )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=PROFILE_CHOICES,
        default="zbook-single",
        help="Target profile: local single-laptop or personal homelab-dev.",
    )
    parser.add_argument("--timeout", type=float, default=10.0, help="Per-request timeout (seconds).")
    parser.add_argument("--write-env", type=Path, help="Write generated env profile to this file.")
    args = parser.parse_args()

    with httpx.Client(timeout=args.timeout) as client:
        results = [_probe(client, endpoint) for endpoint in ENDPOINTS]
    lookup = {row["name"]: row for row in results}

    chat_base, chat_model = _choose_chat_target(args.profile, lookup)
    embed_base, embed_model = _choose_embed_target(args.profile, lookup)
    env_lines = _build_env_lines(
        profile=args.profile,
        chat_base=chat_base,
        chat_model=chat_model,
        embed_base=embed_base,
        embed_model=embed_model,
    )

    report = {
        "profile": args.profile,
        "probe_results": results,
        "recommended": {
            "ALETHEIA_LLM_BASE_URL": chat_base,
            "ALETHEIA_LLM_MODEL": chat_model,
            "ALETHEIA_EMBED_BASE_URL": embed_base,
            "ALETHEIA_EMBED_MODEL": embed_model,
            "ALETHEIA_WEB_SEARCH_CHAIN": "brave,duckduckgo",
            "ALETHEIA_ENABLE_CRAWL4AI_FALLBACK": "1",
        },
        "env_lines": env_lines,
    }
    print(json.dumps(report, indent=2))

    if args.write_env:
        args.write_env.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
        print(f"\nWrote environment profile: {args.write_env}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
