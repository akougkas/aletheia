from aletheia.source_registry import SourceRegistry


def test_is_trusted_url_matches_exact_domain_and_subdomain():
    registry = SourceRegistry.default()
    assert registry.is_trusted_url(
        "methodology_kb",
        "https://bls.gov/cpi/covid-19-impact.htm",
    )
    assert registry.is_trusted_url(
        "methodology_kb",
        "https://www.bls.gov/news.release/empsit.nr0.htm",
    )


def test_is_trusted_url_rejects_domain_tokens_in_query_or_path():
    registry = SourceRegistry.default()
    assert not registry.is_trusted_url(
        "methodology_kb",
        "https://evil.example/report?src=bls.gov",
    )
    assert not registry.is_trusted_url(
        "methodology_kb",
        "https://evil.example/bls.gov/fake",
    )


def test_is_trusted_url_rejects_invalid_and_missing_urls():
    registry = SourceRegistry.default()
    assert not registry.is_trusted_url("methodology_kb", None)
    assert not registry.is_trusted_url("methodology_kb", "not-a-url")
