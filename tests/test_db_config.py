from aletheia.db import diagnose_connection_failure, get_db_settings, get_db_url


def test_db_settings_reads_surreal_env(monkeypatch):
    monkeypatch.setenv("ALETHEIA_DB_URL", "ws://db.internal:8000/rpc")
    monkeypatch.setenv("ALETHEIA_DB_NS", "test_ns")
    monkeypatch.setenv("ALETHEIA_DB_NAME", "test_db")
    monkeypatch.setenv("ALETHEIA_DB_USER", "alice")
    monkeypatch.setenv("ALETHEIA_DB_PASS", "secret")

    settings = get_db_settings()
    assert settings.url == "ws://db.internal:8000/rpc"
    assert settings.ns == "test_ns"
    assert settings.db_name == "test_db"
    assert settings.user == "alice"
    assert settings.password == "secret"


def test_db_settings_defaults(monkeypatch):
    monkeypatch.delenv("ALETHEIA_DB_URL", raising=False)
    monkeypatch.delenv("ALETHEIA_DB_NS", raising=False)
    monkeypatch.delenv("ALETHEIA_DB_NAME", raising=False)
    monkeypatch.delenv("ALETHEIA_DB_USER", raising=False)
    monkeypatch.delenv("ALETHEIA_DB_PASS", raising=False)

    settings = get_db_settings()
    assert "ws://" in settings.url
    assert settings.ns == "aletheia"
    assert settings.db_name == "main"
    assert settings.user == "root"
    assert settings.password == "root"


def test_db_url_display_redacted(monkeypatch):
    monkeypatch.setenv("ALETHEIA_DB_URL", "ws://localhost:8000/rpc")
    monkeypatch.setenv("ALETHEIA_DB_USER", "admin")
    monkeypatch.setenv("ALETHEIA_DB_PASS", "topsecret")

    redacted = get_db_url(redacted=True)
    clear = get_db_url(redacted=False)
    assert "topsecret" not in redacted
    assert "topsecret" in clear
    assert "admin" in redacted


def test_diagnose_connection_failure_detects_auth_issue():
    exc = RuntimeError("authentication failed: invalid credentials")
    diag = diagnose_connection_failure(exc)
    assert diag["category"] == "auth_failed"
    assert any("authentication" in hint.lower() for hint in diag["hints"])


def test_diagnose_connection_failure_detects_connection_refused():
    exc = RuntimeError("connection refused")
    diag = diagnose_connection_failure(exc)
    assert diag["category"] == "connection_refused"
    assert any("docker compose" in hint.lower() for hint in diag["hints"])


def test_diagnose_connection_failure_detects_missing_namespace():
    exc = RuntimeError("namespace not found")
    diag = diagnose_connection_failure(exc)
    assert diag["category"] == "missing_namespace"
    assert any("schema" in hint.lower() or "import" in hint.lower() for hint in diag["hints"])


def test_diagnose_connection_failure_unknown():
    exc = RuntimeError("something completely unexpected happened")
    diag = diagnose_connection_failure(exc)
    assert diag["category"] == "unknown"
    assert len(diag["hints"]) > 0
