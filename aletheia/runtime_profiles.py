"""Runtime profile resolution for ALETHEIA."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any, Mapping

DEFAULT_PROFILE = "zbook-single"

_BASE_SOURCE_BUDGET = "methodology_kb:1,data_api:1,document_index:1,web_fallback:1,paper_scholar:1"

PROFILE_DEFAULTS: dict[str, dict[str, str]] = {
    "zbook-single": {
        "ALETHEIA_LLM_BASE_URL": "http://127.0.0.1:1234",
        "ALETHEIA_EMBED_BASE_URL": "http://127.0.0.1:11434",
        "ALETHEIA_EMBED_MODEL": "qwen3-embedding:8b",
        "ALETHEIA_WEB_SEARCH_PROVIDER": "auto",
        "ALETHEIA_WEB_SEARCH_CHAIN": "brave,duckduckgo",
        "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN": "brave:3,duckduckgo:2,google:0,serpapi_google_scholar:0",
        "ALETHEIA_WEB_RATE_LIMIT_PER_MIN": "brave:30,duckduckgo:40,google:0,serpapi_google_scholar:0",
        "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
        "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
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
        "ALETHEIA_WEB_PROVIDER_BUDGET_PER_RUN": "brave:3,duckduckgo:2,google:0,serpapi_google_scholar:0",
        "ALETHEIA_WEB_RATE_LIMIT_PER_MIN": "brave:30,duckduckgo:40,google:0,serpapi_google_scholar:0",
        "ALETHEIA_ENABLE_DEEP_RESEARCH": "0",
        # Keep blade AI services out of homelab routing defaults.
        "ALETHEIA_SOURCE_BUDGET_PER_RUN": _BASE_SOURCE_BUDGET,
    },
}
PROFILE_CHOICES = tuple(PROFILE_DEFAULTS.keys())

# Default YAML config search paths (checked in order)
_CONFIG_SEARCH_PATHS = [
    "aletheia.yaml",
    "aletheia.yml",
]


@dataclass(frozen=True)
class ResolvedRuntimeProfile:
    """Resolved runtime profile values and source provenance."""

    name: str
    values: dict[str, str]
    source_by_key: dict[str, str]
    profile_file: str | None
    config_file: str | None = None

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


# ---------------------------------------------------------------------------
# YAML config file support
# ---------------------------------------------------------------------------

def load_config_file(path: str | Path | None = None) -> dict[str, Any] | None:
    """Load aletheia.yaml config file.

    If *path* is None, searches CWD for aletheia.yaml / aletheia.yml.
    Returns parsed dict or None if no config file found.
    """
    import yaml  # lazy import — only needed when YAML config exists

    if path is not None:
        p = Path(path).expanduser()
        if not p.exists():
            raise ValueError(f"Config file not found: {p}")
        return yaml.safe_load(p.read_text(encoding="utf-8"))

    for name in _CONFIG_SEARCH_PATHS:
        p = Path(name)
        if p.exists():
            return yaml.safe_load(p.read_text(encoding="utf-8"))

    return None


def _endpoints_from_config(config: dict[str, Any]) -> dict[str, Any]:
    """Parse endpoints section from YAML config into Endpoint objects.

    Returns dict with keys: endpoints, chat_endpoint, embed_endpoint,
    and env_overrides (env vars derived from the YAML config).
    """
    from aletheia.providers.base import Endpoint

    endpoints: dict[str, Endpoint] = {}
    env_overrides: dict[str, str] = {}

    # Parse endpoints section
    raw_endpoints = config.get("endpoints", {})
    for ep_name, ep_cfg in raw_endpoints.items():
        if not isinstance(ep_cfg, dict):
            continue
        endpoints[ep_name] = Endpoint(
            name=ep_name,
            url=str(ep_cfg.get("url", "")),
            provider_type=str(ep_cfg.get("provider", "openai_compat")),
            roles=ep_cfg.get("roles", ["chat"]),
            api_key=ep_cfg.get("api_key"),
            default_chat_model=ep_cfg.get("default_chat_model"),
            default_embed_model=ep_cfg.get("default_embed_model"),
        )

    # Chat routing
    chat_section = config.get("chat", {}) or {}
    chat_ep_name = chat_section.get("endpoint")
    chat_model = chat_section.get("model")
    if chat_ep_name and chat_ep_name in endpoints:
        ep = endpoints[chat_ep_name]
        env_overrides["ALETHEIA_LLM_BASE_URL"] = ep.url
        if ep.api_key:
            env_overrides["ALETHEIA_LLM_API_KEY"] = ep.api_key
        if chat_model:
            env_overrides["ALETHEIA_LLM_MODEL"] = chat_model
            ep.default_chat_model = chat_model

    # Embed routing
    embed_section = config.get("embed", {}) or {}
    embed_ep_name = embed_section.get("endpoint")
    embed_model = embed_section.get("model")
    if embed_ep_name and embed_ep_name in endpoints:
        ep = endpoints[embed_ep_name]
        env_overrides["ALETHEIA_EMBED_BASE_URL"] = ep.url
        if ep.api_key:
            env_overrides["ALETHEIA_EMBED_API_KEY"] = ep.api_key
        if embed_model:
            env_overrides["ALETHEIA_EMBED_MODEL"] = embed_model
            ep.default_embed_model = embed_model

    # DB section
    db_section = config.get("db", {}) or {}
    if db_section.get("host"):
        env_overrides["ALETHEIA_DB_HOST"] = str(db_section["host"])
    if db_section.get("port"):
        env_overrides["ALETHEIA_DB_PORT"] = str(db_section["port"])
    if db_section.get("name"):
        env_overrides["ALETHEIA_DB_NAME"] = str(db_section["name"])
    if db_section.get("user"):
        env_overrides["ALETHEIA_DB_USER"] = str(db_section["user"])
    if db_section.get("password"):
        env_overrides["ALETHEIA_DB_PASSWORD"] = str(db_section["password"])

    return {
        "endpoints": endpoints,
        "chat_endpoint": chat_ep_name,
        "embed_endpoint": embed_ep_name,
        "env_overrides": env_overrides,
    }


def resolve_runtime_profile(
    *,
    profile: str | None = None,
    profile_file: str | Path | None = None,
    config_file: str | Path | None = None,
    cli_overrides: Mapping[str, str | None] | None = None,
    env: Mapping[str, str] | None = None,
) -> ResolvedRuntimeProfile:
    """Resolve profile configuration.

    Precedence: CLI > env > YAML config > profile file > profile defaults.
    """
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
        # Auto-load .env from CWD when no explicit profile file is given
        # and we're using real os.environ (not a synthetic test env).
        if env is None:
            dotenv_path = Path(".env")
            if dotenv_path.exists():
                dotenv_values = _parse_env_file(dotenv_path)
                for key, value in dotenv_values.items():
                    resolved_values[key] = value
                    source_by_key[key] = "dotenv"

    # YAML config file (layered over profile file + defaults)
    resolved_config_file: str | None = None
    yaml_config = None
    yaml_env: dict[str, str] = {}
    try:
        explicit_config = config_file or runtime_env.get("ALETHEIA_CONFIG_FILE")
        yaml_config = load_config_file(explicit_config)
        if yaml_config is not None:
            parsed = _endpoints_from_config(yaml_config)
            yaml_env = parsed.get("env_overrides", {})
            for key, value in yaml_env.items():
                resolved_values[key] = value
                source_by_key[key] = "yaml-config"

            # Resolve actual config file path for reporting
            if explicit_config:
                resolved_config_file = str(Path(explicit_config).expanduser())
            else:
                for name in _CONFIG_SEARCH_PATHS:
                    p = Path(name)
                    if p.exists():
                        resolved_config_file = str(p)
                        break

            # Use profile name from YAML if specified
            yaml_profile = yaml_config.get("profile")
            if yaml_profile and yaml_profile in PROFILE_CHOICES and not profile:
                profile_name = yaml_profile
    except (ImportError, ValueError):
        # No pyyaml or config file not found — skip silently
        pass

    override_map = dict(cli_overrides or {})
    managed_keys = set(resolved_values) | set(file_values) | set(yaml_env) | set(override_map)

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
        config_file=resolved_config_file,
    )


def apply_runtime_profile(
    *,
    profile: str | None = None,
    profile_file: str | Path | None = None,
    config_file: str | Path | None = None,
    cli_overrides: Mapping[str, str | None] | None = None,
) -> ResolvedRuntimeProfile:
    """Resolve and apply profile settings to process environment."""
    resolved = resolve_runtime_profile(
        profile=profile,
        profile_file=profile_file,
        config_file=config_file,
        cli_overrides=cli_overrides,
    )
    for key, value in resolved.values.items():
        os.environ[key] = value

    # Register endpoints from YAML config if available
    _register_yaml_endpoints(resolved.config_file)

    return resolved


def _register_yaml_endpoints(config_file: str | None) -> None:
    """Load YAML config and register endpoints in the provider registry."""
    try:
        yaml_config = load_config_file(config_file)
        if yaml_config is None:
            return
        parsed = _endpoints_from_config(yaml_config)
        from aletheia.providers import register_endpoints

        register_endpoints(
            parsed["endpoints"],
            chat_endpoint=parsed.get("chat_endpoint"),
            embed_endpoint=parsed.get("embed_endpoint"),
        )
    except (ImportError, ValueError):
        pass
