"""
rate_limiter.py — Rate limiting por empresa_id (multi-tenant) + fallback por IP.

Estrategia:
1. Si la petición tiene empresa_id en el ContextVar (tenant autenticado), se aplica
   el límite configurado para esa empresa (de Redis cache o Supabase tabla empresa_limits).
2. Si no hay empresa_id (endpoint público / no autenticado), se cae a límite global por IP.

Límites por defecto (configurable en .env):
  RATE_LIMIT_DEFAULT_PER_MINUTE=120    # req/min por empresa
  RATE_LIMIT_BURST_MULTIPLIER=2        # burst momentáneo (no implementado en slowapi, se deja como config)

Tabla Supabase `empresa_limits` (schema sugerido):
  empresa_id  integer  PRIMARY KEY REFERENCES empresas(id)
  rpm         integer  NOT NULL DEFAULT 120   -- requests por minuto
  burst       integer  NOT NULL DEFAULT 240   -- límite pico momentáneo

Para cambiar el límite de una empresa específica:
  INSERT INTO empresa_limits (empresa_id, rpm) VALUES (42, 60)
  ON CONFLICT (empresa_id) DO UPDATE SET rpm = 60;

  (El cambio es efectivo en la siguiente request tras expirar la caché Redis, ~60s)

Uso en un router:
  from services.rate_limiter import limiter

  @router.get("/endpoint")
  @limiter.limit(get_empresa_rate_limit)   # límite dinámico por empresa
  async def endpoint(request: Request, ...):
      ...
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

logger = logging.getLogger("api-backend")

# ── Valores por defecto ────────────────────────────────────────────────────────
_DEFAULT_RPM = int(os.getenv("RATE_LIMIT_DEFAULT_PER_MINUTE", "120"))


async def _fetch_empresa_rpm(empresa_id: int) -> int:
    """
    Consulta Redis (caché) y luego Supabase para obtener el RPM de la empresa.
    Devuelve _DEFAULT_RPM si no hay config específica.
    """
    redis_key = f"rate_limit:empresa:{empresa_id}:rpm"
    redis = None

    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        cached = await redis.get(redis_key)
        if cached is not None:
            return int(cached)
    except Exception:
        pass

    try:
        from services.supabase_service import supabase, sb_query
        if supabase:
            res = await sb_query(
                lambda eid=empresa_id: supabase.table("empresa_limits")
                .select("rpm")
                .eq("empresa_id", eid)
                .limit(1)
                .execute()
            )
            if res and res.data:
                rpm = int(res.data[0].get("rpm", _DEFAULT_RPM))
                if redis is not None:
                    try:
                        await redis.set(redis_key, str(rpm), ex=60)
                    except Exception:
                        pass
                return rpm
    except Exception as exc:
        logger.debug("rate_limiter: no se pudo leer empresa_limits para %s: %s", empresa_id, exc)

    return _DEFAULT_RPM


def _key_func_empresa(request: Request) -> str:
    """
    Key function para slowapi: usa empresa_id si está autenticado, IP en caso contrario.

    NOTA: la obtención del límite dinámico (async) no puede ocurrir aquí porque
    slowapi llama a key_func de forma síncrona. El límite se inyecta en la cadena
    de limite con get_empresa_rate_limit() para uso en decoradores.
    """
    try:
        from services.tenant_context import get_current_empresa_id
        eid = get_current_empresa_id()
        if eid is not None:
            return f"empresa:{eid}"
    except Exception:
        pass
    return get_remote_address(request)


# ── Instancia principal de slowapi ─────────────────────────────────────────────
limiter = Limiter(
    key_func=_key_func_empresa,
    default_limits=[f"{_DEFAULT_RPM}/minute"],
)


async def get_empresa_rate_limit(empresa_id: Optional[int] = None) -> str:
    """
    Devuelve el string de límite slowapi para una empresa: "Nrpm/minute".

    Uso en endpoints que necesitan límite dinámico por empresa:
        limit_str = await get_empresa_rate_limit(empresa_id)

    El limite base viene de empresa_limits en Supabase (cacheado 60s en Redis).
    Si no hay config, usa RATE_LIMIT_DEFAULT_PER_MINUTE.
    """
    if empresa_id is None:
        return f"{_DEFAULT_RPM}/minute"
    rpm = await _fetch_empresa_rpm(empresa_id)
    return f"{rpm}/minute"


def get_default_rate_limit() -> str:
    """Devuelve el límite global por defecto como string slowapi."""
    return f"{_DEFAULT_RPM}/minute"
