from aletheia import vectorizer


def test_resolve_embedding_base_url_appends_v1(monkeypatch):
    monkeypatch.setenv("ALETHEIA_EMBED_BASE_URL", "http://127.0.0.1:11434")
    assert vectorizer._resolve_embedding_base_url() == "http://127.0.0.1:11434/v1"


def test_resolve_embedding_base_url_keeps_existing_v1(monkeypatch):
    monkeypatch.setenv("ALETHEIA_EMBED_BASE_URL", "http://127.0.0.1:11434/v1")
    assert vectorizer._resolve_embedding_base_url() == "http://127.0.0.1:11434/v1"


def test_resolve_embedding_config_reads_env_at_call_time(monkeypatch):
    monkeypatch.setenv("ALETHEIA_EMBED_MODEL", "qwen3-embedding:8b")
    monkeypatch.setenv("ALETHEIA_EMBED_DIM", "4096")
    monkeypatch.setenv("ALETHEIA_EMBED_BASE_URL", "http://localhost:1234")

    model, dim, base_url = vectorizer._resolve_embedding_config()
    assert model == "qwen3-embedding:8b"
    assert dim == 4096
    assert base_url == "http://localhost:1234/v1"


def test_resolve_embedding_config_handles_bad_dim(monkeypatch):
    monkeypatch.setenv("ALETHEIA_EMBED_DIM", "not-an-int")
    _, dim, _ = vectorizer._resolve_embedding_config()
    assert dim == vectorizer.DEFAULT_EMBED_DIM
