"""
Embedding Service — generación y búsqueda semántica con pgvector.
Usa OpenAI text-embedding-3-small (1536 dims) con caché Redis 24h.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from typing import Any

import aiohttp

logger = logging.getLogger("api-backend")

_EMBEDDING_MODEL = "text-embedding-3-small"
_EMBEDDING_DIMS = 1536
_CACHE_TTL = 86400  # 24h


async def get_embedding(text: str) -> list[float] | None:
    """
    Genera el embedding de un texto.
    Prioridad: OpenAI text-embedding-3-small (1536 dims).
    Cache en Redis (sha256 del texto, TTL 24h).
    Timeout 10s, 2 reintentos.
    """
    if not text or not text.strip():
        return None

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not openai_key:
        logger.warning("[embedding] OPENAI_API_KEY no configurada — embeddings desactivados")
        return None

    # Cache key basada en sha256 del texto normalizado
    text_hash = hashlib.sha256(text.strip().encode()).hexdigest()
    cache_key = f"ausarta:embedding:{text_hash}"

    # Intentar leer del cache Redis
    try:
        from services.redis_service import get_redis
        r = await get_redis()
        cached = await r.get(cache_key)
        if cached:
            return json.loads(cached)
    except Exception:
        pass

    # Llamar a OpenAI con 2 reintentos
    for attempt in range(2):
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.openai.com/v1/embeddings",
                    json={"model": _EMBEDDING_MODEL, "input": text[:8000]},
                    headers={
                        "Authorization": f"Bearer {openai_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        embedding: list[float] = data["data"][0]["embedding"]

                        # Guardar en Redis
                        try:
                            from services.redis_service import get_redis
                            r = await get_redis()
                            await r.set(cache_key, json.dumps(embedding), ex=_CACHE_TTL)
                        except Exception:
                            pass

                        return embedding

                    body = await resp.text()
                    logger.warning(
                        "[embedding] OpenAI HTTP %s: %s", resp.status, body[:200]
                    )
                    return None

        except Exception as e:
            if attempt == 1:
                logger.error("[embedding] Error al generar embedding: %s", e)
            else:
                await asyncio.sleep(0.5)

    return None


async def search_knowledge(
    empresa_id: int,
    query: str,
    limit: int = 5,
    threshold: float = 0.75,
    agent_id: int | None = None,
) -> list[dict]:
    """
    Busca chunks relevantes en la base de conocimiento de una empresa.
    Retorna lista de {id, titulo, contenido, similarity}.
    Si falla por cualquier razón, devuelve [] sin propagar la excepción.
    """
    from services.supabase_service import supabase, sb_query

    if not supabase:
        return []

    try:
        embedding = await asyncio.wait_for(get_embedding(query), timeout=10)
        if not embedding:
            return []

        rpc_args: dict = {
            "p_empresa_id": empresa_id,
            "p_embedding": embedding,
            "p_limit": limit,
            "p_threshold": threshold,
        }
        if agent_id is not None:
            rpc_args["p_agent_id"] = agent_id

        result = await sb_query(
            lambda args=rpc_args: supabase.rpc("search_knowledge_base", args).execute()
        )
        return result.data or []

    except Exception as e:
        logger.warning("[knowledge] search_knowledge falló para empresa %s: %s", empresa_id, e)
        return []


def _split_into_chunks(text: str, max_tokens: int = 800, overlap: int = 100) -> list[str]:
    """
    Divide texto en chunks por palabras con solapamiento.
    Aproximación: 1 token ≈ 0.75 palabras (inglés/español).
    """
    # Convertimos tokens → palabras aproximadas
    max_words = int(max_tokens * 0.75)
    overlap_words = int(overlap * 0.75)

    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = min(start + max_words, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk.strip())
        if end >= len(words):
            break
        start = end - overlap_words

    return chunks
