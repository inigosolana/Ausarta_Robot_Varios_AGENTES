"""
queue_service.py — Cliente ARQ compartido para encolar tareas desde la API.
"""
from __future__ import annotations

import os
from typing import Any, Optional

from arq.connections import ArqRedis, RedisSettings, create_pool

_arq_pool: Optional[ArqRedis] = None


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        return RedisSettings.from_dsn(url)
    except AttributeError:
        # Fallback para versiones antiguas de arq
        return RedisSettings()


async def get_arq_pool() -> ArqRedis:
    global _arq_pool
    if _arq_pool is None:
        _arq_pool = await create_pool(_redis_settings())
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


async def _enqueue(job_name: str, *args: Any, **kwargs: Any) -> str | None:
    """Encola un job ARQ sin bloquear en HTTP al backend."""
    try:
        pool = await get_arq_pool()
        job = await pool.enqueue_job(job_name, *args, **kwargs)
        return getattr(job, "job_id", None)
    except Exception as exc:
        import logging

        logging.getLogger("agent-dynamic").error(
            "❌ No se pudo encolar %s: %s", job_name, exc
        )
        return None


async def enqueue_guardar_encuesta(payload: dict) -> str | None:
    return await _enqueue("agent_post_guardar_encuesta", payload)


async def enqueue_colgar_sala(room_name: str) -> str | None:
    return await _enqueue("agent_post_colgar", room_name)


async def enqueue_transfer_to_human(payload: dict) -> str | None:
    return await _enqueue("agent_post_transfer", payload)
