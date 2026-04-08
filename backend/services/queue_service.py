"""
queue_service.py — Cliente ARQ compartido para encolar tareas desde la API.
"""
from __future__ import annotations

import os
from typing import Optional

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
