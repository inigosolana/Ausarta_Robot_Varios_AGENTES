"""
profile_cache.py — Caché de perfiles de usuario (memoria L1 + Redis L2).

Reduce presión sobre Supabase/Postgres bajo alto tráfico de autenticación JWT.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any

from fastapi import HTTPException

from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

_USER_PROFILE_CACHE_TTL = max(5, int(os.getenv("USER_PROFILE_CACHE_TTL_SECONDS", "60")))
_MEM_PROFILE_CACHE_MAX = max(100, int(os.getenv("USER_PROFILE_CACHE_MAX_ENTRIES", "1000")))
_MEM_PROFILE_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_MEM_PROFILE_LOCK = asyncio.Lock()
_CACHE_GEN: dict[str, int] = {}

_USER_PROFILE_CACHE_PREFIX = "ausarta:user_profile:"

# Singleflight: una sola consulta a BD por user_id ante ráfagas concurrentes.
_IN_FLIGHT: dict[str, asyncio.Future[dict[str, Any]]] = {}
_IN_FLIGHT_LOCK = asyncio.Lock()


def _cache_key(user_id: str) -> str:
    return f"{_USER_PROFILE_CACHE_PREFIX}{user_id}"


def _decode_redis_value(raw: Any) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="replace")
    return str(raw)


def _fetch_user_profile_row(user_id: str) -> dict[str, Any]:
    if not supabase:
        raise HTTPException(status_code=500, detail="No hay conexión con Supabase")
    try:
        prof_res = (
            supabase.table("user_profiles")
            .select("id,email,role,empresa_id,is_active")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error("[ProfileCache] Error consultando user_profiles para %s: %s", user_id, e)
        raise HTTPException(status_code=500, detail="Error cargando perfil de usuario") from e

    if not prof_res.data:
        raise HTTPException(status_code=403, detail="Perfil no encontrado en user_profiles")

    return prof_res.data[0]


def _profile_row_cache_blob(row: dict[str, Any]) -> str:
    return json.dumps(
        {
            "id": row.get("id"),
            "email": row.get("email"),
            "role": row.get("role"),
            "empresa_id": row.get("empresa_id"),
            "is_active": row.get("is_active"),
        },
        separators=(",", ":"),
    )


def _profile_from_cache_blob(raw: str) -> dict[str, Any]:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("cache shape")
    return data


def _mem_cache_get(user_id: str, now: float) -> dict[str, Any] | None:
    hit = _MEM_PROFILE_CACHE.get(user_id)
    if hit is None:
        return None
    expires_at, row = hit
    if now >= expires_at:
        return None
    return row


def _mem_cache_evict_if_needed(now: float) -> None:
    if len(_MEM_PROFILE_CACHE) < _MEM_PROFILE_CACHE_MAX:
        return
    expired_keys = [
        cache_key for cache_key, (exp, _) in _MEM_PROFILE_CACHE.items() if now >= exp
    ]
    for cache_key in expired_keys:
        del _MEM_PROFILE_CACHE[cache_key]
    if len(_MEM_PROFILE_CACHE) < _MEM_PROFILE_CACHE_MAX:
        return
    oldest_key = min(_MEM_PROFILE_CACHE, key=lambda k: _MEM_PROFILE_CACHE[k][0])
    del _MEM_PROFILE_CACHE[oldest_key]


def _mem_cache_set(user_id: str, row: dict[str, Any], now: float) -> None:
    _MEM_PROFILE_CACHE[user_id] = (now + float(_USER_PROFILE_CACHE_TTL), row)


async def _redis_get_profile(user_id: str) -> dict[str, Any] | None:
    try:
        from services.redis_service import get_redis

        r = await get_redis()
        cached = await r.get(_cache_key(user_id))
        decoded = _decode_redis_value(cached)
        if not decoded:
            return None
        return _profile_from_cache_blob(decoded)
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        try:
            from services.redis_service import get_redis

            r = await get_redis()
            await r.delete(_cache_key(user_id))
        except Exception:
            pass
        return None
    except Exception as exc:
        logger.debug("[ProfileCache] Redis GET omitido para %s: %s", user_id, exc)
        return None


async def _redis_set_profile(user_id: str, row: dict[str, Any]) -> None:
    try:
        from services.redis_service import get_redis

        r = await get_redis()
        await r.set(_cache_key(user_id), _profile_row_cache_blob(row), ex=_USER_PROFILE_CACHE_TTL)
    except Exception as exc:
        logger.debug("[ProfileCache] Redis SET omitido para %s: %s", user_id, exc)


async def _load_profile_from_db(user_id: str) -> dict[str, Any]:
    async with _MEM_PROFILE_LOCK:
        gen_at_start = _CACHE_GEN.get(user_id, 0)

    row = await asyncio.to_thread(_fetch_user_profile_row, user_id)

    async with _MEM_PROFILE_LOCK:
        if _CACHE_GEN.get(user_id, 0) != gen_at_start:
            logger.debug(
                "[ProfileCache] Sin escribir caché para %s (invalidada durante la carga)",
                user_id,
            )
            return row
        now = time.monotonic()
        _mem_cache_evict_if_needed(now)
        _mem_cache_set(user_id, row, now)

    await _redis_set_profile(user_id, row)
    return row


async def _singleflight_load(user_id: str) -> dict[str, Any]:
    """Evita thundering herd: N peticiones concurrentes comparten una sola carga a BD."""
    async with _IN_FLIGHT_LOCK:
        existing = _IN_FLIGHT.get(user_id)
        if existing is not None:
            waiter = existing
            is_leader = False
        else:
            loop = asyncio.get_running_loop()
            waiter = loop.create_future()
            _IN_FLIGHT[user_id] = waiter
            is_leader = True

    if not is_leader:
        return await waiter

    try:
        row = await _load_profile_from_db(user_id)
        if not waiter.done():
            waiter.set_result(row)
        return row
    except Exception as exc:
        if not waiter.done():
            waiter.set_exception(exc)
        raise
    finally:
        async with _IN_FLIGHT_LOCK:
            if _IN_FLIGHT.get(user_id) is waiter:
                del _IN_FLIGHT[user_id]


async def get_user_profile_cached(user_id: str) -> dict[str, Any]:
    """
    Carga user_profiles con caché L1 (memoria) → L2 (Redis) → BD (singleflight).
  """
    now = time.monotonic()

    async with _MEM_PROFILE_LOCK:
        mem_hit = _mem_cache_get(user_id, now)
    if mem_hit is not None:
        return mem_hit

    redis_hit = await _redis_get_profile(user_id)
    if redis_hit is not None:
        async with _MEM_PROFILE_LOCK:
            _mem_cache_evict_if_needed(now)
            _mem_cache_set(user_id, redis_hit, now)
        return redis_hit

    return await _singleflight_load(user_id)


async def invalidate_user_profile_cache(user_id: str) -> None:
    """
    Invalida la caché de perfil de un usuario en Redis y en memoria.

    Llamar siempre que se elimine o modifique un usuario para revocar acceso
    inmediatamente, sin esperar a que expire el TTL de caché (por defecto 60s).
    """
    async with _MEM_PROFILE_LOCK:
        _CACHE_GEN[user_id] = _CACHE_GEN.get(user_id, 0) + 1
        if user_id in _MEM_PROFILE_CACHE:
            del _MEM_PROFILE_CACHE[user_id]
            logger.info("[ProfileCache] Caché memoria invalidada para user_id=%s", user_id)

    try:
        from services.redis_service import get_redis

        r = await get_redis()
        deleted = await r.delete(_cache_key(user_id))
        if deleted:
            logger.info("[ProfileCache] Caché Redis invalidada para user_id=%s", user_id)
    except Exception as e:
        logger.warning(
            "[ProfileCache] No se pudo invalidar caché Redis para user_id=%s: %s",
            user_id,
            e,
        )
