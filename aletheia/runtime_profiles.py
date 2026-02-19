"""Runtime profile resolution for ALETHEIA."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping

DEFAULT_PROFILE = "zbook-single"
PROFILE_CHOICES = ("zbook-single", "homelab-dev")

_BASE_SOURCE_BUDGET = "methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1"

PROFILE_DEFAULTS: dict[str, dict[str, str]] = {
    "zbook-single": {
        "ALETHEIA_LLM_BASE_URL": "http://127.0.0.1:1234",
        "ALETHEIA_EMBED_BASE_URL": "http://127.0.0.1:1234",
        "ALETHEIA_WEB_SEARCH_PROVIDER": "auto",
        "ALETHEIA_WEB_SEARCH_CHAIN": "brave,duckduckgo",
        "ALETHEIA_ENABLE_CRAWL4AI_FALLBACK": "1",
        "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN": "brave:3,duckduckgo:2,google:0,serpapi_google_scholar:0",
        "ALETHEIA_WEB_RATE_LIMIT_PER_MIN": "brave:30,duckduckgo:40,google:0,serpapi_google_scholar:0",
        "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
        "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
        "ALETHEIA_DB_HOST": "localhost",
        "ALETHEIA_DB_PORT": "5432",
        "ALETHEIA_DB_NAME": "aletheia",
        "ALETHEIA_DB_USER": "aletheia",
        "ALETHEIA_DB_PASSWORD": "aletheia",
    },
    "homelab-dev": {
        "ALETHEIA_LLM_BASE_URL": "http://127.0.0.1:11434",
        "ALETHEIA_LLM_MODEL": "granite4:small-h",
        "ALETHEIA_EMBED_BASE_URL": "http://127.0.0.1:11434",
        "ALETHEIA_EMBED_MODEL": "qwen3-embedding:8b",
        "ALETHEIA_MINI_LLM_BASE_URL": "http://192.168.86.141:8080",
        "ALETHEIA_DYNAMO_LMSTUDIO_BASE_URL": "http://192.168.86.143:1234",
        "ALETHEIA_DYNAMO_OLLAMA_BASE_URL": "http://192.168.86.143:11434",
        "ALETHEIA_WEB_SEARCH_PROVIDER": "auto",
        "ALETHEIA_WEB_SEARCH_CHAIN": "brave,duckduckgo",
        "ALETHEIA_ENABLE_CRAWL4AI_FALLBACK": "1",
        "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN": "brave:3,duckduckgo:2,google:0,serpapi_google_scholar:0",
        "ALETHEIA_WEB_RATE_LIMIT_PER_MIN": "brave:30,duckduckgo:40,google:0,serpapi_google_scholar:0",
        "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
        # Keep blade AI services out of homelab routing defaults.
        "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
        "ALETHEIA_DB_HOST": "localhost",
        "ALETHEIA_DB_PORT": "5432",
        "ALETHEIA_DB_NAME": "aletheia",
        "ALETHEIA_DB_USER": "aletheia",
        "ALETHEIA_DB_PASSWORD": "aletheia",
    },
}


@dataclass(frozen=True)
class ResolvedRuntimeProfile:
    """Resolved runtime profile values and source provenance."""

    name: str
    values: dict[str, str]
    source_by_key: dict[str, str]
    profile_file: str | None

    def source_for(self, key: str) -> str:
        return self.source_by_key.get(key, "unset")


def _normalize_profile_name(profile: str | None, env: Mapping[str, str]) -> str:
    selected = (profile or env.get("ALETHEIA_RUNTIME_PROFILE") or DEFAULT_PROFILE).strip()
    if selected not in PROFILE_CHOICES:
        known = ", ".join(PROFILE_CHOICES)
        raise ValueError(f"Unknown profile '{selected}'. Choose one of: {known}.")
    return selected


def _parse_env_file(path: Path) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        parsed[key] = value
    return parsed


def resolve_runtime_profile(
    *,
    profile: str | None = None,
    profile_file: str | Path | None = None,
    cli_overrides: Mapping[str, str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedRuntimeProfile:
    """Resolve profile configuration with precedence: CLI > env > profile file > defaults."""
    runtime_env = env if env is not None else os.environ
    profile_name = _normalize_profile_name(profile, runtime_env)
    defaults = dict(PROFILE_DEFAULTS[profile_name])

    resolved_values: dict[str, str] = {}
    source_by_key: dict[str, str] = {}
    for key, value in defaults.items():
        resolved_values[key] = value
        source_by_key[key] = "profile-default"

    selected_profile_file = profile_file or runtime_env.get("ALETHEIA_PROFILE_FILE")
    file_values: dict[str, str] = {}
    if selected_profile_file:
        path = Path(selected_profile_file).expanduser()
        if not path.exists():
            raise ValueError(f"Profile file not found: {path}")
        file_values = _parse_env_file(path)
        for key, value in file_values.items():
            resolved_values[key] = value
            source_by_key[key] = "profile-file"
        selected_profile_file = str(path)
    else:
        selected_profile_file = None

    override_map = dict(cli_overrides or {})
    managed_keys = set(resolved_values) | set(file_values) | set(override_map)

    for key in managed_keys:
        if key in runtime_env:
            resolved_values[key] = runtime_env[key]
            source_by_key[key] = "env"

    for key, value in override_map.items():
        if value is None:
            continue
        resolved_values[key] = value
        source_by_key[key] = "cli"

    resolved_values["ALETHEIA_RUNTIME_PROFILE"] = profile_name
    source_by_key["ALETHEIA_RUNTIME_PROFILE"] = "cli" if profile else "env/default"
    if selected_profile_file:
        resolved_values["ALETHEIA_PROFILE_FILE"] = selected_profile_file
        source_by_key["ALETHEIA_PROFILE_FILE"] = "cli/env"

    return ResolvedRuntimeProfile(
        name=profile_name,
        values=resolved_values,
        source_by_key=source_by_key,
        profile_file=selected_profile_file,
    )


def apply_runtime_profile(
    *,
    profile: str | None = None,
    profile_file: str | Path | None = None,
    cli_overrides: Mapping[str, str | None] | None = None,
) -> ResolvedRuntimeProfile:
    """Resolve and apply profile settings to process environment."""
    resolved = resolve_runtime_profile(
        profile=profile,
        profile_file=profile_file,
        cli_overrides=cli_overrides,
        env=os.environ,
    )
    for key, value in resolved.values.items():
        os.environ[key] = value
    return resolved
