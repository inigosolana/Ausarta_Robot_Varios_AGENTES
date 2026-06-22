"""Tests RAG híbrido (RRF) y re-ranking."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from config import clear_settings_cache
from services.rag_hybrid import KnowledgeChunk, reciprocal_rank_fusion, tokenize_query
from services.reranker_service import HeuristicReranker, get_reranker


@pytest.fixture(autouse=True)
def _reset_settings():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_tokenize_query_spanish():
    tokens = tokenize_query("Tarifas de fibra óptica 100Mb")
    assert "tarifas" in tokens
    assert "fibra" in tokens
    assert "optica" in tokens


def test_rrf_merges_vector_and_keyword_lists():
    vector_rows = [
        {"id": 1, "titulo": "Precios", "contenido": "Fibra 1Gb", "similarity": 0.91},
        {"id": 2, "titulo": "Soporte", "contenido": "Horario", "similarity": 0.80},
    ]
    keyword_rows = [
        {"id": 2, "titulo": "Soporte", "contenido": "Horario", "keyword_score": 0.77},
        {"id": 3, "titulo": "Instalación", "contenido": "Técnico fibra", "keyword_score": 0.66},
    ]

    fused = reciprocal_rank_fusion(
        [vector_rows, keyword_rows],
        list_labels=["vector", "keyword"],
    )

    assert len(fused) == 3
    assert fused[0].id in {1, 2}
    chunk2 = next(item for item in fused if item.id == 2)
    assert "vector" in chunk2.sources and "keyword" in chunk2.sources
    assert chunk2.rrf_score > 0


@pytest.mark.asyncio
async def test_heuristic_reranker_prefers_title_match():
    reranker = HeuristicReranker()
    chunks = [
        KnowledgeChunk(
            id=1,
            titulo="Política devoluciones",
            contenido="Plazos generales",
            similarity=0.7,
            rrf_score=0.03,
        ),
        KnowledgeChunk(
            id=2,
            titulo="Tarifas móviles",
            contenido="Plan 20GB datos",
            similarity=0.65,
            rrf_score=0.02,
        ),
    ]

    ranked = await reranker.rerank("tarifas móviles", chunks, top_k=2)
    assert ranked[0].id == 2


@pytest.mark.asyncio
async def test_search_knowledge_hybrid_path(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_ENABLED", "true")

    vector_rows = [
        {"id": 10, "titulo": "A", "contenido": "vector chunk", "similarity": 0.9},
    ]
    keyword_rows = [
        {"id": 11, "titulo": "B", "contenido": "keyword chunk", "keyword_score": 0.8},
    ]

    with (
        patch(
            "services.embedding_service._search_knowledge_vector",
            AsyncMock(return_value=vector_rows),
        ),
        patch(
            "services.embedding_service._search_knowledge_keyword",
            AsyncMock(return_value=keyword_rows),
        ),
        patch("services.reranker_service.get_reranker", return_value=HeuristicReranker()),
    ):
        from services.embedding_service import search_knowledge

        results = await search_knowledge(1, "tarifas fibra", limit=2, threshold=0.5)

    assert len(results) <= 2
    assert {row["id"] for row in results}.issubset({10, 11})


@pytest.mark.asyncio
async def test_search_knowledge_vector_only_when_hybrid_disabled(monkeypatch):
    monkeypatch.setenv("RAG_HYBRID_ENABLED", "false")
    vector_mock = AsyncMock(return_value=[{"id": 5, "titulo": "X", "contenido": "Y", "similarity": 0.88}])

    with patch("services.embedding_service._search_knowledge_vector", vector_mock):
        from services.embedding_service import search_knowledge

        results = await search_knowledge(2, "consulta", limit=1, threshold=0.7)

    vector_mock.assert_awaited_once()
    assert results[0]["id"] == 5


def test_get_reranker_none_mode(monkeypatch):
    monkeypatch.setenv("RAG_RERANKER", "none")
    clear_settings_cache()
    reranker = get_reranker()
    assert reranker.__class__.__name__ == "NoOpReranker"
