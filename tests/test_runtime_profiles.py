from pathlib import Path

import pytest

from aletheia.runtime_profiles import resolve_runtime_profile


def test_profile_defaults_for_zbook_single():
    resolved = resolve_runtime_profile(
        profile="zbook-single",
        env={},
    )
    assert resolved.name == "zbook-single"
    assert resolved.values["ALETHEIA_LLM_BASE_URL"] == "http://127.0.0.1:1234"
    assert resolved.source_for("ALETHEIA_LLM_BASE_URL") == "profile-default"


def test_profile_precedence_cli_over_env_over_file_over_defaults(tmp_path: Path):
    profile_file = tmp_path / "profile.env"
    profile_file.write_text(
        "\n".join(
            [
                "ALETHEIA_LLM_BASE_URL=http://file:9999",
                "ALETHEIA_EMBED_BASE_URL=http://file:8888",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    resolved = resolve_runtime_profile(
        profile="zbook-single",
        profile_file=profile_file,
        cli_overrides={"ALETHEIA_LLM_BASE_URL": "http://cli:1234"},
        env={"ALETHEIA_LLM_BASE_URL": "http://env:1234", "ALETHEIA_EMBED_BASE_URL": "http://env:7777"},
    )
    assert resolved.values["ALETHEIA_LLM_BASE_URL"] == "http://cli:1234"
    assert resolved.source_for("ALETHEIA_LLM_BASE_URL") == "cli"

    assert resolved.values["ALETHEIA_EMBED_BASE_URL"] == "http://env:7777"
    assert resolved.source_for("ALETHEIA_EMBED_BASE_URL") == "env"


def test_profile_file_missing_raises_value_error():
    with pytest.raises(ValueError, match="Profile file not found"):
        resolve_runtime_profile(
            profile="zbook-single",
            profile_file="/tmp/does-not-exist-profile.env",
            env={},
        )


def test_unknown_profile_raises_value_error():
    with pytest.raises(ValueError, match="Unknown profile"):
        resolve_runtime_profile(
            profile="not-a-profile",
            env={},
        )
