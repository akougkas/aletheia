import asyncio
from types import SimpleNamespace

import cli
from aletheia.tui import TerminalUI


def test_normalize_argv_defaults_to_interactive():
    assert cli._normalize_argv([]) == ["interactive"]


def test_normalize_argv_backcompat_claim_mode():
    assert cli._normalize_argv(["EU unemployment fell"]) == [
        "claim",
        "EU unemployment fell",
    ]


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
            "url": url,
            "fetched": True,
            "content_type": "text/html",
            "text_length": 500,
            "chunks_expected": 3,
            "documents_written": 1,
            "chunks_written": 3,
            "error": None,
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
            "url": url,
            "fetched": True,
            "content_type": "text/html",
            "text_length": 4200,
            "chunks_expected": 4,
            "documents_written": 0,
            "chunks_written": 0,
            "error": None,
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
            "url": url,
            "fetched": False,
            "content_type": None,
            "text_length": 0,
            "chunks_expected": 0,
            "documents_written": 0,
            "chunks_written": 0,
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


def test_batch_parser_accepts_claims_file_and_output_flag():
    parser = cli._build_parser()
    args = parser.parse_args(["batch", "claims.csv", "--output", "eval.json"])
    assert args.command == "batch"
    assert args.claims_file == "claims.csv"
    assert args.output == "eval.json"
    assert args.benchmark is False


def test_batch_requires_input_or_benchmark():
    parser = cli._build_parser()
    args = parser.parse_args(["batch"])
    ui = TerminalUI(plain=True)
    code = cli._run_batch(ui, args)
    assert code == 2


def test_batch_reads_csv_claims_and_emits_structured_json(
    tmp_path, monkeypatch, capsys
):
    claims_csv = tmp_path / "claims.csv"
    claims_csv.write_text("claim\nEU unemployment fell in 2021\nUS CPI rose in 2022\n")

    class _FakeOrchestrator:
        async def process_claim(self, claim, **kwargs):
            return SimpleNamespace(
                status=SimpleNamespace(value="SUPPORTED"),
                confidence=0.81,
                severity=SimpleNamespace(value="MINOR"),
                comparability=SimpleNamespace(value="COMPARABLE"),
                summary="ok",
                breaks_found=[],
            )

        async def close(self):
            return None

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):
            if "CREATE batch" in sql:
                return [{"result": [{"id": "batch:test"}]}]
            return [{"result": []}]

    monkeypatch.setattr(cli, "OrchestratorAgent", _FakeOrchestrator)
    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())

    parser = cli._build_parser()
    args = parser.parse_args(["batch", str(claims_csv)])
    ui = TerminalUI(plain=True)
    code = cli._run_batch(ui, args)
    assert code == 0

    rendered = capsys.readouterr().out
    assert '"mode": "file"' in rendered
    assert '"summary"' in rendered


def test_case_parser_accepts_create_and_show_actions():
    parser = cli._build_parser()
    create_args = parser.parse_args(
        ["case", "create", "Acme v Beta", "--description", "Patent matter"]
    )
    assert create_args.command == "case"
    assert create_args.case_action == "create"
    assert create_args.name == "Acme v Beta"

    show_args = parser.parse_args(["case", "show", "case:abc123"])
    assert show_args.command == "case"
    assert show_args.case_action == "show"
    assert show_args.case_id == "case:abc123"


def test_case_parser_accepts_history_and_export_actions():
    parser = cli._build_parser()
    history_args = parser.parse_args(
        ["case", "history", "abc123", "--limit", "15", "--json"]
    )
    assert history_args.command == "case"
    assert history_args.case_action == "history"
    assert history_args.case_id == "abc123"
    assert history_args.limit == 15
    assert history_args.json is True

    export_args = parser.parse_args(
        ["case", "export", "case:abc123", "--format", "md", "--output", "case.md"]
    )
    assert export_args.command == "case"
    assert export_args.case_action == "export"
    assert export_args.case_id == "case:abc123"
    assert export_args.format == "md"
    assert export_args.output == "case.md"

    reconcile_args = parser.parse_args(["case", "reconcile", "abc123"])
    assert reconcile_args.command == "case"
    assert reconcile_args.case_action == "reconcile"
    assert reconcile_args.case_id == "abc123"


def test_claim_parser_accepts_case_flag():
    parser = cli._build_parser()
    args = parser.parse_args(["claim", "EU unemployment fell", "--case", "abc123"])
    assert args.command == "claim"
    assert args.case_id == "abc123"


def test_batch_parser_accepts_case_flag():
    parser = cli._build_parser()
    args = parser.parse_args(["batch", "claims.csv", "--case", "case:abc123"])
    assert args.command == "batch"
    assert args.case_id == "case:abc123"


def test_batch_rejects_missing_case_id(monkeypatch, tmp_path):
    claims_file = tmp_path / "claims.txt"
    claims_file.write_text("Claim one\n")

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            if "SELECT id FROM $case LIMIT 1" in sql:
                return [{"result": []}]
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    args = parser.parse_args(["batch", str(claims_file), "--case", "missing"])
    ui = TerminalUI(plain=True)
    code = cli._run_batch(ui, args)
    assert code == 2


def test_claim_rejects_missing_case_id(monkeypatch):
    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            if "SELECT id FROM $case LIMIT 1" in sql:
                return [{"result": []}]
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    monkeypatch.setattr(
        cli.sys,
        "argv",
        ["aletheia", "claim", "EU", "unemployment", "fell", "--case", "missing"],
    )
    # Execute main path because case validation occurs there.
    code = cli.main()
    assert code == 2


def test_case_history_json_happy_path(monkeypatch, capsys):
    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            if "SELECT id FROM $case LIMIT 1" in sql:
                return [{"result": [{"id": "case:abc"}]}]
            if "SELECT * FROM $case LIMIT 1" in sql:
                return [
                    {
                        "result": [
                            {
                                "id": "case:abc",
                                "name": "Acme",
                                "status": "active",
                                "created_at": "2026-02-22T10:00:00Z",
                            }
                        ]
                    }
                ]
            if "FROM $case->has_session->session" in sql:
                return [
                    {
                        "result": [
                            {
                                "id": "session:1",
                                "status": "completed",
                                "claim_text": "EU unemployment fell",
                                "started_at": "2026-02-22T11:00:00Z",
                                "completed_at": "2026-02-22T11:01:00Z",
                                "metadata": {"aggregate_confidence": 0.84},
                            }
                        ]
                    }
                ]
            if "FROM $case->has_batch->batch" in sql:
                return [
                    {
                        "result": [
                            {
                                "id": "batch:1",
                                "name": "file-2",
                                "status": "completed",
                                "total_claims": 2,
                                "completed_claims": 2,
                                "started_at": "2026-02-22T12:00:00Z",
                                "completed_at": "2026-02-22T12:03:00Z",
                                "results": {
                                    "succeeded": 2,
                                    "failed": 0,
                                    "avg_confidence": 0.81,
                                },
                            }
                        ]
                    }
                ]
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    args = parser.parse_args(["case", "history", "abc", "--json"])
    ui = TerminalUI(plain=True)
    code = cli._run_case(ui, args)
    assert code == 0

    payload = cli.json.loads(capsys.readouterr().out)
    assert payload["case"]["id"] == "case:abc"
    assert payload["rollup"]["total_sessions"] == 1
    assert payload["rollup"]["total_batches"] == 1
    assert payload["activity"][0]["type"] == "session"
    assert payload["activity"][1]["type"] == "batch"


def test_case_history_empty_case_activity(monkeypatch, capsys):
    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            if "SELECT id FROM $case LIMIT 1" in sql:
                return [{"result": [{"id": "case:empty"}]}]
            if "SELECT * FROM $case LIMIT 1" in sql:
                return [
                    {
                        "result": [
                            {"id": "case:empty", "name": "Empty", "status": "active"}
                        ]
                    }
                ]
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    args = parser.parse_args(["case", "history", "case:empty"])
    ui = TerminalUI(plain=True)
    code = cli._run_case(ui, args)
    assert code == 0
    rendered = capsys.readouterr().out
    assert "No case activity found." in rendered


def test_case_history_invalid_case_id(monkeypatch, capsys):
    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    args = parser.parse_args(["case", "history", "missing"])
    ui = TerminalUI(plain=True)
    code = cli._run_case(ui, args)
    assert code == 2
    assert "Case not found: case:missing" in capsys.readouterr().out


def test_case_export_formats_json_jsonl_md(monkeypatch, capsys):
    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            if "SELECT id FROM $case LIMIT 1" in sql:
                return [{"result": [{"id": "case:abc"}]}]
            if "SELECT * FROM $case LIMIT 1" in sql:
                return [
                    {
                        "result": [
                            {
                                "id": "case:abc",
                                "name": "Acme",
                                "status": "active",
                                "created_at": "2026-02-22T10:00:00Z",
                            }
                        ]
                    }
                ]
            if "FROM $case->has_session->session" in sql:
                return [
                    {
                        "result": [
                            {
                                "id": "session:1",
                                "status": "completed",
                                "claim_text": "Claim A",
                                "started_at": "2026-02-22T10:01:00Z",
                                "completed_at": "2026-02-22T10:02:00Z",
                                "verdict": {"confidence": 0.8},
                                "metadata": {"aggregate_confidence": 0.8},
                            }
                        ]
                    }
                ]
            if "FROM $case->has_batch->batch" in sql:
                return [
                    {
                        "result": [
                            {
                                "id": "batch:1",
                                "name": "file-1",
                                "status": "completed",
                                "total_claims": 1,
                                "completed_claims": 1,
                                "started_at": "2026-02-22T10:03:00Z",
                                "completed_at": "2026-02-22T10:04:00Z",
                                "results": {
                                    "succeeded": 1,
                                    "failed": 0,
                                    "avg_confidence": 0.8,
                                },
                            }
                        ]
                    }
                ]
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    ui = TerminalUI(plain=True)

    json_args = parser.parse_args(["case", "export", "abc", "--format", "json"])
    assert cli._run_case(ui, json_args) == 0
    payload = cli.json.loads(capsys.readouterr().out)
    assert payload["case"]["id"] == "case:abc"
    assert len(payload["sessions"]) == 1
    assert len(payload["batches"]) == 1

    jsonl_args = parser.parse_args(["case", "export", "abc", "--format", "jsonl"])
    assert cli._run_case(ui, jsonl_args) == 0
    jsonl_output = capsys.readouterr().out.strip().splitlines()
    assert len(jsonl_output) == 3
    assert cli.json.loads(jsonl_output[0])["type"] == "case"
    assert cli.json.loads(jsonl_output[1])["type"] == "session"
    assert cli.json.loads(jsonl_output[2])["type"] == "batch"

    md_args = parser.parse_args(["case", "export", "abc", "--format", "md"])
    assert cli._run_case(ui, md_args) == 0
    md_output = capsys.readouterr().out
    assert "# Case Report:" in md_output
    assert "## Sessions" in md_output
    assert "## Batches" in md_output


def test_case_export_invalid_case_id(monkeypatch, capsys):
    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    args = parser.parse_args(["case", "export", "missing", "--format", "json"])
    ui = TerminalUI(plain=True)
    code = cli._run_case(ui, args)
    assert code == 2
    assert "Case not found: case:missing" in capsys.readouterr().out


def test_case_reconcile_links_case_id_records(monkeypatch, capsys):
    state = {"session_linked": False, "batch_linked": False}

    class _FakeConn:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def query(self, sql, params=None):  # noqa: ARG002
            if "SELECT id FROM $case LIMIT 1" in sql:
                return [{"result": [{"id": "case:abc"}]}]
            if "FROM session" in sql and "WHERE case_id = $case" in sql:
                return [{"result": [{"id": "session:fallback"}]}]
            if "FROM batch" in sql and "WHERE case_id = $case" in sql:
                return [{"result": [{"id": "batch:fallback"}]}]
            if "FROM $case->has_session->session" in sql:
                if state["session_linked"]:
                    return [{"result": [{"id": "session:fallback"}]}]
                return [{"result": []}]
            if "FROM $case->has_batch->batch" in sql:
                if state["batch_linked"]:
                    return [{"result": [{"id": "batch:fallback"}]}]
                return [{"result": []}]
            if "RELATE $case->has_session->$session" in sql:
                state["session_linked"] = True
                return [{"result": []}]
            if "RELATE $case->has_batch->$batch" in sql:
                state["batch_linked"] = True
                return [{"result": []}]
            return [{"result": []}]

    monkeypatch.setattr("aletheia.db.get_connection", lambda: _FakeConn())
    parser = cli._build_parser()
    args = parser.parse_args(["case", "reconcile", "abc"])
    ui = TerminalUI(plain=True)
    code = cli._run_case(ui, args)
    assert code == 0
    rendered = capsys.readouterr().out
    assert "sessions=1" in rendered
    assert "batches=1" in rendered


def test_graph_timeline_parser_and_help_shape():
    parser = cli._build_parser()
    args = parser.parse_args(["graph", "timeline", "EU-LFS"])
    assert args.command == "graph"
    assert args.graph_action == "timeline"
    assert args.dataset_code == "EU-LFS"

    recall_args = parser.parse_args(
        [
            "graph",
            "recall",
            "--dataset",
            "EU-LFS",
            "--indicator",
            "unemployment",
            "--limit",
            "5",
        ]
    )
    assert recall_args.command == "graph"
    assert recall_args.graph_action == "recall"
    assert recall_args.dataset_code == "EU-LFS"
    assert recall_args.indicator == "unemployment"
    assert recall_args.limit == 5


def test_graph_provenance_renders_chain(monkeypatch, capsys):
    class _FakeArchivist:
        async def provenance_chain(self, session_id):  # noqa: ARG002
            return {
                "session": {
                    "id": "session:1",
                    "case_id": "case:1",
                    "status": "completed",
                    "started_at": "2026-02-22T10:00:00Z",
                    "completed_at": "2026-02-22T10:01:00Z",
                },
                "documents": [
                    {"id": "document:1", "title": "Doc A", "url": "https://example.org"}
                ],
                "methodology_changes": [
                    {
                        "id": "methodology_change:1",
                        "change_type": "definition_change",
                        "effective_date": "2021-01-01T00:00:00Z",
                        "description": "Definition shift",
                        "impact_estimate": "0.3pp",
                    }
                ],
                "datasets": [
                    {
                        "id": "dataset:1",
                        "code": "EU-LFS",
                        "name": "EU Labour Force Survey",
                    }
                ],
                "agencies": [
                    {"id": "agency:1", "code": "EUROSTAT", "name": "Eurostat"}
                ],
            }

    monkeypatch.setattr("aletheia.agents.archivist.ArchivistAgent", _FakeArchivist)
    parser = cli._build_parser()
    args = parser.parse_args(["graph", "provenance", "session:1"])
    ui = TerminalUI(plain=True)
    code = cli._run_graph(ui, args)
    assert code == 0
    rendered = capsys.readouterr().out
    assert "Evidence Documents" in rendered
    assert "Methodology Changes" in rendered
    assert "Datasets" in rendered
    assert "Agencies" in rendered


def test_graph_impacts_renders_tables(monkeypatch, capsys):
    class _FakeArchivist:
        async def change_impacts(self, change_id):  # noqa: ARG002
            return {
                "change": {
                    "id": "methodology_change:1",
                    "change_type": "reweighting",
                    "description": "Weights updated",
                },
                "indicators": [
                    {
                        "id": "indicator:1",
                        "code": "UNEMP",
                        "name": "Unemployment",
                        "unit": "%",
                    }
                ],
                "datasets": [
                    {
                        "id": "dataset:1",
                        "code": "CPS",
                        "name": "Current Population Survey",
                    }
                ],
                "agencies": [
                    {
                        "id": "agency:1",
                        "code": "BLS",
                        "name": "Bureau of Labor Statistics",
                    }
                ],
            }

    monkeypatch.setattr("aletheia.agents.archivist.ArchivistAgent", _FakeArchivist)
    parser = cli._build_parser()
    args = parser.parse_args(["graph", "impacts", "methodology_change:1"])
    ui = TerminalUI(plain=True)
    code = cli._run_graph(ui, args)
    assert code == 0
    rendered = capsys.readouterr().out
    assert "Affected Indicators" in rendered
    assert "Linked Datasets" in rendered
    assert "Publishing Agencies" in rendered


def test_graph_timeline_renders_table(monkeypatch, capsys):
    class _FakeArchivist:
        async def dataset_timeline(self, dataset_code):  # noqa: ARG002
            return {
                "dataset": {
                    "id": "dataset:1",
                    "code": "EU-LFS",
                    "name": "EU Labour Force Survey",
                },
                "changes": [
                    {
                        "id": "methodology_change:1",
                        "effective_date": "2021-01-01T00:00:00Z",
                        "change_type": "definition_change",
                        "severity": "moderate",
                        "comparability": "partially_comparable",
                        "description": "Definition adjustment",
                    }
                ],
            }

    monkeypatch.setattr("aletheia.agents.archivist.ArchivistAgent", _FakeArchivist)
    parser = cli._build_parser()
    args = parser.parse_args(["graph", "timeline", "EU-LFS"])
    ui = TerminalUI(plain=True)
    code = cli._run_graph(ui, args)
    assert code == 0
    rendered = capsys.readouterr().out
    assert "Dataset" in rendered
    assert "Methodology Timeline" in rendered


def test_graph_recall_renders_prior_sessions(monkeypatch, capsys):
    class _FakeArchivist:
        async def prior_verification_recall(
            self, *, dataset=None, indicator=None, session_id=None, limit=10
        ):
            assert dataset == "EU-LFS"
            assert indicator == "unemployment"
            assert session_id is None
            assert limit == 2
            return {
                "query": {
                    "dataset": "EU-LFS",
                    "indicator": "unemployment",
                    "source_session_id": None,
                },
                "matches": [
                    {
                        "session": {
                            "id": "session:1",
                            "case_id": "case:1",
                            "claim_dataset": "EU-LFS",
                            "claim_indicator": "unemployment",
                            "started_at": "2026-02-22T11:00:00Z",
                        },
                        "verdict": {"status": "SUPPORTED", "confidence": 0.83},
                        "methodology_changes": [
                            {"id": "methodology_change:1"},
                            {"id": "methodology_change:2"},
                        ],
                    }
                ],
            }

    monkeypatch.setattr("aletheia.agents.archivist.ArchivistAgent", _FakeArchivist)
    parser = cli._build_parser()
    args = parser.parse_args(
        [
            "graph",
            "recall",
            "--dataset",
            "EU-LFS",
            "--indicator",
            "unemployment",
            "--limit",
            "2",
        ]
    )
    ui = TerminalUI(plain=True)
    code = cli._run_graph(ui, args)
    assert code == 0
    rendered = capsys.readouterr().out
    assert "Recall Query" in rendered
    assert "Prior Verification Recall" in rendered
