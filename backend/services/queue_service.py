"""
queue_service.py — Cliente ARQ compartido para encolar tareas desde la API.
"""
from __future__ import annotations

import os
import time
from typing import Any, Optional

from arq.connections import ArqRedis, RedisSettings, create_pool

_arq_pool: Optional[ArqRedis] = None
# FIX 2: timestamp del último uso del pool para limitar la frecuencia de pings
_last_pool_use: float = 0.0
_POOL_PING_INTERVAL = 30.0  # segundos sin usar el pool antes de ejecutar ping de salud


def _redis_settings() -> RedisSettings:
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        return RedisSettings.from_dsn(url)
    except AttributeError:
        # Fallback para versiones antiguas de arq
        return RedisSettings()


async def get_arq_pool() -> ArqRedis:
    """
    FIX 2 — ARQ pool sin health check.

    Problema: si Redis se desconecta y reconecta, _arq_pool queda en estado
    inválido pero _arq_pool is not None sigue siendo True, por lo que nunca
    se reinicializa. Las llamadas a enqueue_* fallan silenciosamente.

    Solución: ping de salud si el pool lleva >30 s sin usarse. Si falla,
    se descarta y se crea uno nuevo antes de devolver.
    """
    global _arq_pool, _last_pool_use
    import logging as _logging
    now = time.monotonic()

    if _arq_pool is not None and (now - _last_pool_use) > _POOL_PING_INTERVAL:
        try:
            await _arq_pool.ping()
        except Exception:
            _logging.getLogger("api-backend").warning(
                "⚠️ ARQ pool ping fallido — estado inválido tras desconexión Redis. Recreando pool."
            )
            _arq_pool = None

    if _arq_pool is None:
        _arq_pool = await create_pool(_redis_settings())

    _last_pool_use = now
    return _arq_pool


async def close_arq_pool() -> None:
    global _arq_pool
    if _arq_pool is not None:
        await _arq_pool.close()
        _arq_pool = None


async def _enqueue(job_name: str, *args: Any, **kwargs: Any) -> str | None:
    """Encola un job ARQ sin bloquear en HTTP al backend."""
    try:
        from utils.tracing import inject_carrier_into_kwargs

        pool = await get_arq_pool()
        job = await pool.enqueue_job(job_name, *args, **inject_carrier_into_kwargs(kwargs))
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


async def enqueue_transfer_briefing(payload: dict) -> str | None:
    return await _enqueue("generate_transfer_briefing_task", payload)


async def enqueue_briefing(encuesta_id: int, transcript: str, empresa_id: int) -> str | None:
    return await enqueue_transfer_briefing(
        {
            "encuesta_id": encuesta_id,
            "transcript": transcript,
            "empresa_id": empresa_id,
            "extension": "",
            "room_name": "",
        }
    )


async def enqueue_telegram_alert(message: str) -> str | None:
    return await _enqueue("send_telegram_alert_task", message)
