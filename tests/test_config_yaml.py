"""Tests for YAML config file loading and endpoint registration."""

from __future__ import annotations

import os
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from aletheia.runtime_profiles import (
    load_config_file,
    resolve_runtime_profile,
    _endpoints_from_config,
)


@pytest.fixture
def yaml_config_file(tmp_path: Path) -> Path:
    """Create a temporary aletheia.yaml config file."""
    content = textwrap.dedent("""\
        profile: zbook-single

        endpoints:
          zbook-lmstudio:
            url: http://127.0.0.1:1234
            provider: lmstudio
            roles: [chat]
          zbook-ollama:
            url: http://127.0.0.1:11434
            provider: ollama
            roles: [embed]
            default_embed_model: qwen3-embedding:8b

        chat:
          endpoint: zbook-lmstudio

        embed:
          endpoint: zbook-ollama
          model: qwen3-embedding:8b

        db:
          host: localhost
          port: 5433
          name: aletheia
          user: aletheia
          password: aletheia
    """)
    cfg = tmp_path / "aletheia.yaml"
    cfg.write_text(content, encoding="utf-8")
    return cfg


def test_load_config_file(yaml_config_file: Path):
    config = load_config_file(yaml_config_file)
    assert config is not None
    assert config["profile"] == "zbook-single"
    assert "zbook-lmstudio" in config["endpoints"]
    assert "zbook-ollama" in config["endpoints"]
    assert config["chat"]["endpoint"] == "zbook-lmstudio"
    assert config["embed"]["endpoint"] == "zbook-ollama"


def test_load_config_file_missing_raises():
    with pytest.raises(ValueError, match="Config file not found"):
        load_config_file("/nonexistent/aletheia.yaml")


def test_load_config_file_auto_search_returns_none(tmp_path: Path, monkeypatch):
    """Returns None when no config file found in CWD."""
    monkeypatch.chdir(tmp_path)
    result = load_config_file(None)
    assert result is None


def test_load_config_file_auto_search_finds_yaml(yaml_config_file: Path, monkeypatch):
    """Auto-search finds aletheia.yaml in CWD."""
    monkeypatch.chdir(yaml_config_file.parent)
    result = load_config_file(None)
    assert result is not None
    assert result["profile"] == "zbook-single"


def test_endpoints_from_config(yaml_config_file: Path):
    config = load_config_file(yaml_config_file)
    parsed = _endpoints_from_config(config)

    endpoints = parsed["endpoints"]
    assert "zbook-lmstudio" in endpoints
    assert "zbook-ollama" in endpoints
    assert endpoints["zbook-lmstudio"].url == "http://127.0.0.1:1234"
    assert endpoints["zbook-lmstudio"].provider_type == "lmstudio"
    assert endpoints["zbook-ollama"].url == "http://127.0.0.1:11434"
    assert endpoints["zbook-ollama"].provider_type == "ollama"

    assert parsed["chat_endpoint"] == "zbook-lmstudio"
    assert parsed["embed_endpoint"] == "zbook-ollama"

    env = parsed["env_overrides"]
    assert env["ALETHEIA_LLM_BASE_URL"] == "http://127.0.0.1:1234"
    assert env["ALETHEIA_EMBED_BASE_URL"] == "http://127.0.0.1:11434"
    assert env["ALETHEIA_EMBED_MODEL"] == "qwen3-embedding:8b"
    assert env["ALETHEIA_DB_PORT"] == "5433"


def test_endpoints_from_config_db_section():
    config = {
        "db": {
            "host": "dbhost.local",
            "port": 5432,
            "name": "mydb",
            "user": "myuser",
            "password": "secret",
        }
    }
    parsed = _endpoints_from_config(config)
    env = parsed["env_overrides"]
    assert env["ALETHEIA_DB_HOST"] == "dbhost.local"
    assert env["ALETHEIA_DB_PORT"] == "5432"
    assert env["ALETHEIA_DB_NAME"] == "mydb"
    assert env["ALETHEIA_DB_USER"] == "myuser"
    assert env["ALETHEIA_DB_PASSWORD"] == "secret"


def test_endpoints_from_config_empty():
    parsed = _endpoints_from_config({})
    assert parsed["endpoints"] == {}
    assert parsed["env_overrides"] == {}


def test_resolve_profile_with_yaml_config(yaml_config_file: Path):
    """YAML config values layer over profile defaults."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ALETHEIA_")}
    resolved = resolve_runtime_profile(
        config_file=yaml_config_file,
        env=clean_env,
    )
    # YAML should have set these
    assert resolved.values["ALETHEIA_LLM_BASE_URL"] == "http://127.0.0.1:1234"
    assert resolved.values["ALETHEIA_EMBED_BASE_URL"] == "http://127.0.0.1:11434"
    assert resolved.values["ALETHEIA_EMBED_MODEL"] == "qwen3-embedding:8b"
    assert resolved.values["ALETHEIA_DB_PORT"] == "5433"
    assert resolved.source_by_key["ALETHEIA_EMBED_BASE_URL"] == "yaml-config"


def test_resolve_profile_cli_overrides_yaml(yaml_config_file: Path):
    """CLI args take precedence over YAML config."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ALETHEIA_")}
    resolved = resolve_runtime_profile(
        config_file=yaml_config_file,
        cli_overrides={"ALETHEIA_DB_PORT": "9999"},
        env=clean_env,
    )
    assert resolved.values["ALETHEIA_DB_PORT"] == "9999"
    assert resolved.source_by_key["ALETHEIA_DB_PORT"] == "cli"


def test_resolve_profile_env_overrides_yaml(yaml_config_file: Path):
    """Environment variables take precedence over YAML config."""
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("ALETHEIA_")
    }
    env["ALETHEIA_EMBED_MODEL"] = "from-env"
    resolved = resolve_runtime_profile(
        config_file=yaml_config_file,
        env=env,
    )
    assert resolved.values["ALETHEIA_EMBED_MODEL"] == "from-env"
    assert resolved.source_by_key["ALETHEIA_EMBED_MODEL"] == "env"


def test_resolve_profile_no_yaml_backward_compat():
    """Without YAML config, behavior is identical to before."""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("ALETHEIA_")}
    resolved = resolve_runtime_profile(env=clean_env)
    # Should get profile defaults
    assert resolved.values["ALETHEIA_LLM_BASE_URL"] == "http://127.0.0.1:1234"
    assert resolved.config_file is None


def test_endpoint_with_api_key():
    config = {
        "endpoints": {
            "cloud": {
                "url": "https://api.openai.com",
                "provider": "openai_compat",
                "roles": ["chat"],
                "api_key": "sk-test123",
            }
        },
        "chat": {"endpoint": "cloud"},
    }
    parsed = _endpoints_from_config(config)
    assert parsed["endpoints"]["cloud"].api_key == "sk-test123"
    assert parsed["env_overrides"]["ALETHEIA_LLM_API_KEY"] == "sk-test123"


def test_endpoint_chat_model_override():
    config = {
        "endpoints": {
            "local": {
                "url": "http://localhost:1234",
                "provider": "lmstudio",
                "roles": ["chat"],
            }
        },
        "chat": {"endpoint": "local", "model": "custom-model"},
    }
    parsed = _endpoints_from_config(config)
    assert parsed["endpoints"]["local"].default_chat_model == "custom-model"
    assert parsed["env_overrides"]["ALETHEIA_LLM_MODEL"] == "custom-model"


# ---------------------------------------------------------------------------
# Provider registry integration
# ---------------------------------------------------------------------------


def test_register_endpoints():
    from aletheia.providers import (
        register_endpoints,
        get_configured_endpoints,
        _active_chat_endpoint,
        _active_embed_endpoint,
    )
    from aletheia.providers.base import Endpoint

    ep1 = Endpoint(name="ep1", url="http://host1:1234", provider_type="lmstudio", roles=["chat"])
    ep2 = Endpoint(name="ep2", url="http://host2:11434", provider_type="ollama", roles=["embed"])

    register_endpoints(
        {"ep1": ep1, "ep2": ep2},
        chat_endpoint="ep1",
        embed_endpoint="ep2",
    )

    configured = get_configured_endpoints()
    assert "ep1" in configured
    assert "ep2" in configured
    assert _active_chat_endpoint() is ep1
    assert _active_embed_endpoint() is ep2

    # Clean up
    register_endpoints({})
