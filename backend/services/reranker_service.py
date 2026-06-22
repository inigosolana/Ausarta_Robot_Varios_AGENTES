"""Re-ranking de chunks KB tras fusión híbrida (heurístico o Groq opcional)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Any

import aiohttp

from config import get_settings
from services.rag_hybrid import KnowledgeChunk, _normalize_for_match, tokenize_query

logger = logging.getLogger("api-backend")

_GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


class BaseReranker(ABC):
    @abstractmethod
    async def rerank(
        self,
        query: str,
        chunks: list[KnowledgeChunk],
        *,
        top_k: int,
    ) -> list[KnowledgeChunk]:
        raise NotImplementedError


class HeuristicReranker(BaseReranker):
    """Boost por coincidencia léxica en título/contenido + score RRF."""

    async def rerank(
        self,
        query: str,
        chunks: list[KnowledgeChunk],
        *,
        top_k: int,
    ) -> list[KnowledgeChunk]:
        if not chunks:
            return []

        terms = tokenize_query(query)
        if not terms:
            return chunks[:top_k]

        scored: list[KnowledgeChunk] = []
        max_rrf = max((c.rrf_score for c in chunks), default=1.0) or 1.0

        for chunk in chunks:
            title = _normalize_for_match(chunk.titulo)
            body = _normalize_for_match(chunk.contenido)
            term_hits = sum(1 for term in terms if term in title or term in body)
            title_hits = sum(1 for term in terms if term in title)
            lexical = term_hits / len(terms)
            title_boost = title_hits / len(terms)
            vector_part = chunk.similarity * 0.25
            keyword_part = min(chunk.keyword_score, 1.0) * 0.15
            rrf_part = (chunk.rrf_score / max_rrf) * 0.35
            lexical_part = lexical * 0.15 + title_boost * 0.10
            final_score = min(1.0, vector_part + keyword_part + rrf_part + lexical_part)

            scored.append(
                KnowledgeChunk(
                    id=chunk.id,
                    titulo=chunk.titulo,
                    contenido=chunk.contenido,
                    similarity=final_score,
                    keyword_score=chunk.keyword_score,
                    rrf_score=chunk.rrf_score,
                    sources=chunk.sources,
                )
            )

        scored.sort(key=lambda item: item.similarity, reverse=True)
        return scored[:top_k]


class GroqReranker(BaseReranker):
    """Re-ranker LLM ligero (fallback a heurístico si falla o timeout)."""

    def __init__(self, *, model: str | None = None, timeout_s: float | None = None) -> None:
        settings = get_settings()
        self._model = model or settings.rag_reranker_model
        self._timeout_s = timeout_s or (settings.rag_reranker_timeout_ms / 1000.0)
        self._fallback = HeuristicReranker()
        self._api_key = os.getenv("GROQ_API_KEY", "").strip()

    async def rerank(
        self,
        query: str,
        chunks: list[KnowledgeChunk],
        *,
        top_k: int,
    ) -> list[KnowledgeChunk]:
        if not chunks:
            return []
        if not self._api_key or len(chunks) == 1:
            return await self._fallback.rerank(query, chunks, top_k=top_k)

        payload_docs = [
            {
                "id": chunk.id,
                "titulo": chunk.titulo[:200],
                "contenido": chunk.contenido[:600],
            }
            for chunk in chunks[:12]
        ]
        system_prompt = (
            "Eres un reranker de recuperación documental. "
            "Devuelve SOLO JSON: {\"ranking\":[{\"id\":number,\"score\":0.0-1.0}]} "
            "ordenado de mayor a menor relevancia para la consulta del usuario."
        )
        user_prompt = json.dumps({"query": query, "documents": payload_docs}, ensure_ascii=False)

        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout_s)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    _GROQ_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": self._model,
                        "temperature": 0.0,
                        "max_tokens": 256,
                        "response_format": {"type": "json_object"},
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                    },
                ) as resp:
                    if resp.status != 200:
                        logger.warning("Groq reranker HTTP %s", resp.status)
                        return await self._fallback.rerank(query, chunks, top_k=top_k)
                    data = await resp.json()
        except (asyncio.TimeoutError, aiohttp.ClientError) as exc:
            logger.warning("Groq reranker failed, using heuristic: %s", exc)
            return await self._fallback.rerank(query, chunks, top_k=top_k)

        try:
            ranking = json.loads(data["choices"][0]["message"]["content"])["ranking"]
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return await self._fallback.rerank(query, chunks, top_k=top_k)

        by_id = {chunk.id: chunk for chunk in chunks}
        reranked: list[KnowledgeChunk] = []
        seen: set[int] = set()
        for item in ranking:
            if not isinstance(item, dict):
                continue
            chunk_id = int(item.get("id") or 0)
            if chunk_id not in by_id or chunk_id in seen:
                continue
            seen.add(chunk_id)
            score = float(item.get("score") or 0.0)
            base = by_id[chunk_id]
            reranked.append(
                KnowledgeChunk(
                    id=base.id,
                    titulo=base.titulo,
                    contenido=base.contenido,
                    similarity=max(0.0, min(score, 1.0)),
                    keyword_score=base.keyword_score,
                    rrf_score=base.rrf_score,
                    sources=base.sources,
                )
            )

        if not reranked:
            return await self._fallback.rerank(query, chunks, top_k=top_k)

        for chunk in chunks:
            if chunk.id in seen:
                continue
            reranked.append(chunk)

        return reranked[:top_k]


class NoOpReranker(BaseReranker):
    async def rerank(
        self,
        query: str,
        chunks: list[KnowledgeChunk],
        *,
        top_k: int,
    ) -> list[KnowledgeChunk]:
        return chunks[:top_k]


def get_reranker() -> BaseReranker:
    mode = (get_settings().rag_reranker or "heuristic").strip().lower()
    if mode == "none":
        return NoOpReranker()
    if mode == "groq":
        return GroqReranker()
    return HeuristicReranker()
