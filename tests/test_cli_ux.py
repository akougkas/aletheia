import asyncio

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


# --- Ingest CLI parser tests ---


def test_ingest_url_parser():
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "url", "https://example.com/doc.pdf"])
    assert args.command == "ingest"
    assert args.ingest_action == "url"
    assert args.target == "https://example.com/doc.pdf"
    assert args.dry_run is False
    assert args.materialize is False


def test_ingest_dir_parser():
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "dir", "/tmp/docs"])
    assert args.command == "ingest"
    assert args.ingest_action == "dir"
    assert args.path == "/tmp/docs"


def test_ingest_marina_parser():
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "marina"])
    assert args.command == "ingest"
    assert args.ingest_action == "marina"


def test_ingest_dry_run_flag():
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "--dry-run", "url", "https://example.com"])
    assert args.dry_run is True
    assert args.ingest_action == "url"


def test_ingest_materialize_flag():
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "--materialize", "dir", "/tmp/docs"])
    assert args.materialize is True
    assert args.ingest_action == "dir"


def test_ingest_combined_flags():
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "--dry-run", "--materialize", "marina"])
    assert args.dry_run is True
    assert args.materialize is True
    assert args.ingest_action == "marina"


def test_ingest_no_action_returns_exit_2(capsys):
    """Missing ingest action should return exit code 2."""
    parser = cli._build_parser()
    args = parser.parse_args(["ingest"])
    assert args.command == "ingest"
    assert getattr(args, "ingest_action", None) is None
    # Verify dispatch returns 2
    ui = TerminalUI(plain=True)
    code = cli._run_ingest(ui, args)
    assert code == 2


def test_ingest_normalize_argv_preserves_ingest():
    assert cli._normalize_argv(["ingest", "url", "https://x.com"])[0] == "ingest"


def test_ingest_dir_nonexistent_returns_exit_2():
    """Ingest dir with nonexistent path should return exit code 2."""
    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "dir", "/nonexistent/path/abc123"])
    ui = TerminalUI(plain=True)
    code = cli._run_ingest(ui, args)
    assert code == 2


# --- Ingest handler dispatch tests (mock backend) ---


def test_ingest_url_dispatches_to_backend(monkeypatch):
    """URL handler calls ingest_single_url and returns 0 on success."""
    called = {}

    async def fake_ingest(url, *, dry_run=False):
        called["url"] = url
        called["dry_run"] = dry_run
        return {
            "url": url, "fetched": True, "content_type": "text/html",
            "text_length": 500, "chunks_expected": 3,
            "documents_written": 1, "chunks_written": 3, "error": None,
        }

    import aletheia.ingest as _mod
    monkeypatch.setattr(_mod, "ingest_single_url", fake_ingest)

    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "url", "https://example.com/paper.pdf"])
    ui = TerminalUI(plain=True)
    code = cli._run_ingest(ui, args)
    assert code == 0
    assert called["url"] == "https://example.com/paper.pdf"
    assert called["dry_run"] is False


def test_ingest_url_dry_run_shows_preview(monkeypatch):
    """Dry-run URL handler reports expected chunks without writing."""
    import aletheia.ingest as _mod

    async def fake_ingest(url, *, dry_run=False):
        return {
            "url": url, "fetched": True, "content_type": "text/html",
            "text_length": 4200, "chunks_expected": 4,
            "documents_written": 0, "chunks_written": 0, "error": None,
        }

    monkeypatch.setattr(_mod, "ingest_single_url", fake_ingest)

    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "--dry-run", "url", "https://example.com"])
    ui = TerminalUI(plain=True)
    code = cli._run_ingest(ui, args)
    assert code == 0


def test_ingest_url_fetch_error_returns_2(monkeypatch):
    """URL handler returns 2 when fetch fails."""
    import aletheia.ingest as _mod

    async def fake_ingest(url, *, dry_run=False):
        return {
            "url": url, "fetched": False, "content_type": None,
            "text_length": 0, "chunks_expected": 0,
            "documents_written": 0, "chunks_written": 0,
            "error": "Connection refused",
        }

    monkeypatch.setattr(_mod, "ingest_single_url", fake_ingest)

    parser = cli._build_parser()
    args = parser.parse_args(["ingest", "url", "https://dead.example.com"])
    ui = TerminalUI(plain=True)
    code = cli._run_ingest(ui, args)
    assert code == 2


def test_ingest_dir_dry_run_scans_files(tmp_path):
    """Dry-run dir handler scans files without DB access."""
    (tmp_path / "a.pdf").write_bytes(b"%PDF-fake")
    (tmp_path / "b.md").write_text("hello")
    (tmp_path / "c.jpg").write_bytes(b"\xff\xd8")  # unsupported

    from aletheia.ingest import ingest_local_directory
    stats = asyncio.run(ingest_local_directory(tmp_path, dry_run=True))
    assert stats["files_seen"] == 2  # pdf + md, not jpg
    assert stats["files_ingested"] == 0
    assert stats["chunks_written"] == 0
