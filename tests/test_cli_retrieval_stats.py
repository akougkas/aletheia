from cli import format_retrieval_stats


def test_format_retrieval_stats_includes_cache_and_runs():
    text = format_retrieval_stats(
        {
            "window_hours": 24,
            "summary": {
                "total_runs": 5,
                "completed_runs": 4,
                "non_completed_runs": 1,
                "provider_budget_skips": 3,
                "linked_docs": 20,
                "cache_hits": 8,
                "cache_hit_rate": 0.4,
                "distinct_sources": 3,
                "avg_aggregate_confidence": 0.71,
            },
            "sources": [
                {"source_id": "web_fallback", "doc_count": 6, "cache_hits": 2, "avg_confidence": 0.61}
            ],
            "recent_runs": [
                {
                    "id": 42,
                    "claim_dataset": "EU-LFS",
                    "claim_indicator": "unemployment rate",
                    "status": "completed",
                    "evidence_count": 5,
                    "fallback_used": True,
                    "deep_research_used": False,
                    "provider_budget_skips": 1,
                    "aggregate_confidence": 0.73,
                }
            ],
        }
    )
    assert "cache_hit_rate=40.0%" in text
    assert "runs=5" in text
    assert "deep_research=False" in text
    assert "provider_budget_skips=3" in text


def test_format_retrieval_stats_error_includes_diagnosis_hints():
    text = format_retrieval_stats(
        {
            "error": "password authentication failed",
            "diagnosis": {
                "db_url_redacted": "postgres://user:***@localhost:5432/aletheia",
                "hints": ["Credentials mismatch", "Recreate local volume if reset is acceptable"],
            },
        }
    )
    assert "retrieval stats unavailable" in text
    assert "db_url:" in text
    assert "Credentials mismatch" in text
