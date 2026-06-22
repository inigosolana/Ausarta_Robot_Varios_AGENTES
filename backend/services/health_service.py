"""Comprobaciones de salud de dependencias."""

from __future__ import annotations

import asyncio
import os
from typing import Any

from services.livekit_service import lkapi
from services.queue_service import get_arq_pool
from services.redis_service import get_redis
from services.supabase_service import supabase


async def collect_health_dependencies() -> tuple[str, dict[str, dict[str, Any]]]:
    deps: dict[str, dict[str, Any]] = {}

    try:
        if not supabase:
            raise RuntimeError("cliente no inicializado")
        await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase.table("empresas").select("id").limit(1).execute(),
            ),
            timeout=5,
        )
        deps["supabase"] = {"status": "ok"}
    except Exception as exc:
        deps["supabase"] = {"status": "down", "detail": str(exc)[:120]}

    try:
        redis = await asyncio.wait_for(get_redis(), timeout=3)
        await asyncio.wait_for(redis.ping(), timeout=3)
        deps["redis"] = {"status": "ok"}
    except Exception as exc:
        deps["redis"] = {"status": "down", "detail": str(exc)[:120]}

    try:
        pool = await asyncio.wait_for(get_arq_pool(), timeout=3)
        await asyncio.wait_for(pool.ping(), timeout=3)
        deps["arq"] = {"status": "ok"}
    except Exception as exc:
        deps["arq"] = {"status": "degraded", "detail": str(exc)[:120]}

    lk_url = os.getenv("LIVEKIT_URL", "")
    lk_key = os.getenv("LIVEKIT_API_KEY", "")
    if lk_url and lk_key and lkapi:
        deps["livekit"] = {"status": "ok", "note": "credenciales configuradas"}
    else:
        deps["livekit"] = {"status": "degraded", "note": "credenciales no configuradas o cliente no disponible"}

    critical_down = any(deps[k]["status"] == "down" for k in ("supabase", "redis"))
    overall = (
        "down"
        if critical_down
        else ("degraded" if any(v["status"] == "degraded" for v in deps.values()) else "ok")
    )
    return overall, deps
