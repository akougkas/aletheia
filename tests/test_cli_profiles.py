import pytest

import cli
from aletheia.runtime_profiles import ResolvedRuntimeProfile
from aletheia.tui import TerminalUI


def test_parser_accepts_profile_flag_after_subcommand():
    parser = cli._build_parser()
    args = parser.parse_args(cli._normalize_argv(["onboarding", "--profile", "homelab-dev"]))
    assert args.command == "onboarding"
    assert args.profile == "homelab-dev"


@pytest.mark.asyncio
async def test_onboarding_reports_chat_ok_embeddings_unsupported(monkeypatch, capsys):
    async def _fake_db():
        return {"ok": True, "db_url_redacted": "postgres://user:***@localhost:5432/aletheia"}

    async def _fake_llm():
        return {
            "chat_ok": True,
            "embeddings_ok": False,
            "chat": {
                "endpoint": "http://127.0.0.1:1234",
                "errors": [],
                "hints": [],
            },
            "embeddings": {
                "endpoint": "http://192.168.86.141:8080",
                "errors": ["embeddings:501 Not Implemented"],
                "hints": [],
                "unsupported": True,
            },
        }

    monkeypatch.setattr(cli, "test_connection", _fake_db)
    monkeypatch.setattr(cli, "_check_llm_health", _fake_llm)

    ui = TerminalUI(plain=True)
    exit_code = await cli.show_onboarding(ui)
    rendered = capsys.readouterr().out

    assert exit_code == 2
    assert "doesn't support embeddings" in rendered or "unsupported" in rendered.lower()


def test_profile_context_renders_sources(capsys):
    ui = TerminalUI(plain=True)
    resolved = ResolvedRuntimeProfile(
        name="zbook-single",
        values={
            "ALETHEIA_LLM_BASE_URL": "http://127.0.0.1:1234",
            "ALETHEIA_EMBED_BASE_URL": "http://127.0.0.1:1234",
        },
        source_by_key={
            "ALETHEIA_LLM_BASE_URL": "profile-default",
            "ALETHEIA_EMBED_BASE_URL": "env",
        },
        profile_file=None,
    )
    cli._render_profile_context(ui, resolved)
    rendered = capsys.readouterr().out
    assert "Configuration" in rendered
    assert "zbook-single" in rendered
