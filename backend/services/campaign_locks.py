"""
Drip locks multitenant y utilidades de concurrencia para campañas.
"""
from __future__ import annotations

import asyncio
import logging
import os

from config import get_settings
from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

_empresas_en_llamada_fallback: set[int] = set()

COOLDOWN_MIN = int(os.getenv("DRIP_COOLDOWN_MIN_SECONDS", str(get_settings().drip_cooldown_min)))
COOLDOWN_MAX = int(os.getenv("DRIP_COOLDOWN_MAX_SECONDS", str(get_settings().drip_cooldown_max)))
EMPRESA_LOCK_TTL = COOLDOWN_MAX + 300 + 60


async def acquire_empresa_lock(empresa_id: int) -> str | None:
    """Intenta adquirir el drip lock para una empresa. Devuelve token de propiedad."""
    try:
        from services.redis_service import acquire_lock

        return await acquire_lock(f"empresa:{empresa_id}", ttl_seconds=EMPRESA_LOCK_TTL)
    except Exception:
        if empresa_id in _empresas_en_llamada_fallback:
            return None
        _empresas_en_llamada_fallback.add(empresa_id)
        return f"local-fallback:{empresa_id}"


async def release_empresa_lock(empresa_id: int, token: str | None = None) -> None:
    """Libera el drip lock de una empresa (solo si el token coincide en Redis)."""
    try:
        from services.redis_service import release_lock

        if token and not str(token).startswith("local-fallback:"):
            await release_lock(f"empresa:{empresa_id}", token)
        elif token is None:
            await release_lock(f"empresa:{empresa_id}")
    except Exception:
        pass
    _empresas_en_llamada_fallback.discard(empresa_id)


async def is_empresa_locked(empresa_id: int) -> bool:
    """Comprueba si una empresa tiene lock activo."""
    try:
        from services.redis_service import is_locked

        return await is_locked(f"empresa:{empresa_id}")
    except Exception:
        return empresa_id in _empresas_en_llamada_fallback


async def get_active_call_count() -> int:
    """Retorna el número de empresas con llamada activa (distribuido)."""
    try:
        from services.redis_service import get_active_call_count as redis_active_count

        return await redis_active_count()
    except Exception:
        return len(_empresas_en_llamada_fallback)


async def get_active_call_count_for_empresa(empresa_id: int) -> int:
    """
    Retorna el número de llamadas activas (status calling/initiated/called)
    para una empresa específica. Usado por el rate limiter por empresa.
    """
    if not supabase or not empresa_id:
        return 0
    try:
        res = await asyncio.to_thread(
            supabase.table("encuestas")
            .select("id", count="exact")
            .eq("empresa_id", empresa_id)
            .in_("status", ["calling", "initiated", "called"])
            .execute
        )
        return res.count or 0
    except Exception as e:
        logger.warning(f"[RateLimit] Error contando llamadas activas para empresa {empresa_id}: {e}")
        return 0


async def enqueue_scheduler_tick() -> None:
    """
    Encola una ejecución inmediata del scheduler ARQ.
    Se usa al iniciar/reintentar campañas para no esperar al próximo cron (:00/:30).
    """
    try:
        from services.queue_service import get_arq_pool

        arq = await get_arq_pool()
        await arq.enqueue_job("campaign_scheduler_task")
    except Exception as e:
        logger.warning(f"No se pudo encolar campaign_scheduler_task: {e}")
