from cli import format_capability_matrix


def test_capability_matrix_shows_optional_and_enabled(monkeypatch):
    monkeypatch.delenv("GOOGLE_CSE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_CSE_CX", raising=False)
    monkeypatch.delenv("BRAVE_SEARCH_API_KEY", raising=False)
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)
    monkeypatch.setenv("ALETHEIA_LLM_BASE_URL", "http://mini:8080")
    text = format_capability_matrix()
    assert "local_llm" in text
    assert "web_search_duckduckgo" in text
    assert "scholar_serpapi" in text


def test_capability_matrix_reflects_enabled_keys(monkeypatch):
    monkeypatch.setenv("SERPAPI_API_KEY", "x")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "y")
    text = format_capability_matrix()
    assert "scholar_serpapi: " in text
    assert "web_search_brave: " in text
