from aletheia.db import diagnose_connection_failure, get_db_settings, get_db_url


def test_db_url_builds_from_component_env(monkeypatch):
    monkeypatch.delenv("ALETHEIA_DB_URL", raising=False)
    monkeypatch.setenv("ALETHEIA_DB_HOST", "db.internal")
    monkeypatch.setenv("ALETHEIA_DB_PORT", "5439")
    monkeypatch.setenv("ALETHEIA_DB_NAME", "aletheia_dev")
    monkeypatch.setenv("ALETHEIA_DB_USER", "alice")
    monkeypatch.setenv("ALETHEIA_DB_PASSWORD", "secret")
    monkeypatch.setenv("ALETHEIA_DB_SSLMODE", "disable")
    monkeypatch.setenv("ALETHEIA_DB_CONNECT_TIMEOUT", "11")

    settings = get_db_settings()
    assert settings.host == "db.internal"
    assert settings.port == 5439
    assert "alice:secret@" in get_db_url(redacted=False)
    assert "alice:***@" in get_db_url(redacted=True)
    assert "sslmode=disable" in get_db_url()
    assert "connect_timeout=11" in get_db_url()


def test_db_url_redacts_override_password(monkeypatch):
    monkeypatch.setenv(
        "ALETHEIA_DB_URL",
        "postgres://bob:supersecret@localhost:5432/aletheia?sslmode=disable",
    )
    redacted = get_db_url(redacted=True)
    clear = get_db_url(redacted=False)
    assert "supersecret" in clear
    assert "supersecret" not in redacted
    assert ("***" in redacted) or ("%2A%2A%2A" in redacted)


def test_diagnose_connection_failure_detects_auth_issue():
    exc = RuntimeError("FATAL:  password authentication failed for user \"aletheia\"")
    diag = diagnose_connection_failure(exc)
    assert diag["category"] == "auth_failed"
    assert any("Credentials mismatch" in hint for hint in diag["hints"])


def test_diagnose_connection_failure_detects_unusable_connection():
    exc = RuntimeError("connection is bad: no error details available")
    diag = diagnose_connection_failure(exc)
    assert diag["category"] == "connection_unusable"
    assert any("ALETHEIA_DB_PORT" in hint for hint in diag["hints"])
