import pytest

from aletheia.agents.archivist import ArchivistAgent


@pytest.mark.asyncio
async def test_semantic_search_falls_back_to_lexical_when_embedding_fails(monkeypatch):
    archivist = ArchivistAgent()

    async def _boom_embed(text: str):  # noqa: ARG001
        raise RuntimeError("embed unavailable")

    async def _fake_lexical(query: str, limit: int):  # noqa: ARG001
        return [{"title": "lexical-doc", "distance": None}]

    monkeypatch.setattr(archivist.llm, "embed", _boom_embed)
    monkeypatch.setattr(archivist, "_lexical_document_search", _fake_lexical)

    rows = await archivist.semantic_search("labor methodology", limit=3)
    assert rows == [{"title": "lexical-doc", "distance": None}]
    assert archivist.last_doc_search_mode == "lexical_fallback"


@pytest.mark.asyncio
async def test_semantic_break_search_falls_back_to_lexical_when_embedding_fails(monkeypatch):
    archivist = ArchivistAgent()

    async def _boom_embed(text: str):  # noqa: ARG001
        raise RuntimeError("embed unavailable")

    async def _fake_break_lexical(query: str, limit: int):  # noqa: ARG001
        return [{"id": 99, "description": "lexical-break", "distance": None}]

    monkeypatch.setattr(archivist.llm, "embed", _boom_embed)
    monkeypatch.setattr(archivist, "_lexical_break_search", _fake_break_lexical)

    rows = await archivist.semantic_search_breaks("bls unemployment break", limit=4)
    assert rows == [{"id": 99, "description": "lexical-break", "distance": None}]
    assert archivist.last_break_search_mode == "lexical_fallback"
