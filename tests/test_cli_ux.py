import cli
from aletheia.tui import TerminalUI


def test_normalize_argv_defaults_to_interactive():
    assert cli._normalize_argv([]) == ["interactive"]


def test_normalize_argv_backcompat_claim_mode():
    assert cli._normalize_argv(["EU unemployment fell"]) == ["claim", "EU unemployment fell"]


def test_normalize_argv_preserves_known_command():
    assert cli._normalize_argv(["retrieval-stats", "--hours", "48"]) == [
        "retrieval-stats",
        "--hours",
        "48",
    ]


def test_parser_accepts_plain_after_subcommand():
    parser = cli._build_parser()
    args = parser.parse_args(cli._normalize_argv(["onboarding", "--plain"]))
    assert args.command == "onboarding"
    assert args.plain is True


def test_capability_rows_include_core_entries():
    rows = cli._capability_rows()
    names = {name for name, _, _ in rows}
    assert "local_llm" in names
    assert "web_search_duckduckgo" in names
    assert "crawl4ai_fallback" in names


def test_render_capabilities_plain_does_not_raise():
    ui = TerminalUI(plain=True)
    cli._render_capabilities(ui)
