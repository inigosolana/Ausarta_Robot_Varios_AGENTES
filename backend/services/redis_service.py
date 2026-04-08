"""
redis_service.py — Servicio centralizado de Redis.

Proporciona:
  - Conexión singleton (pool asíncrono) reutilizable en toda la app.
  - Distributed Lock con TTL para reemplazar sets en memoria.
  - Helpers para sets distribuidos (reemplazo de _processing_rooms).

Configuración vía variable de entorno REDIS_URL (default: redis://redis:6379/0).
"""
import os
import logging
from typing import Optional

import redis.asyncio as aioredis

logger = logging.getLogger("api-backend")

# ──────────────────────────────────────────────
# Conexión singleton
# ──────────────────────────────────────────────

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> aioredis.Redis:
    """Retorna el cliente Redis singleton. Crea la conexión en la primera llamada."""
    global _redis_client
    if _redis_client is None:
        url = os.getenv("REDIS_URL", "redis://redis:6379/0")
        _redis_client = aioredis.from_url(
            url,
            decode_responses=True,
            max_connections=20,
        )
        # Verificar conectividad
        try:
            await _redis_client.ping()
            logger.info(f"✅ [Redis] Conectado a {url}")
        except Exception as e:
            logger.error(f"❌ [Redis] No se pudo conectar a {url}: {e}")
            raise
    return _redis_client


async def close_redis() -> None:
    """Cierra la conexión Redis limpiamente (llamar en shutdown)."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("🔒 [Redis] Conexión cerrada.")


# ──────────────────────────────────────────────
# Distributed Lock (TTL-based)
#
# Reemplaza los sets en memoria (_empresas_en_llamada,
# _processing_rooms) por locks atómicos en Redis con
# expiración automática para evitar deadlocks.
# ──────────────────────────────────────────────

LOCK_PREFIX = "ausarta:lock:"


async def acquire_lock(key: str, ttl_seconds: int = 600) -> bool:
    """
    Intenta adquirir un lock distribuido.

    Args:
        key: Identificador único del lock (ej: "empresa:42", "room:sala_xyz").
        ttl_seconds: Tiempo máximo que el lock se mantiene antes de expirar
                     automáticamente (safety net contra crashes).

    Returns:
        True si se adquirió el lock, False si ya existe (otro proceso lo tiene).
    """
    r = await get_redis()
    full_key = f"{LOCK_PREFIX}{key}"
    # SET NX = solo si no existe; EX = con expiración
    acquired = await r.set(full_key, "1", nx=True, ex=ttl_seconds)
    return acquired is not None and acquired is not False


async def release_lock(key: str) -> None:
    """Libera un lock distribuido."""
    r = await get_redis()
    full_key = f"{LOCK_PREFIX}{key}"
    await r.delete(full_key)


async def is_locked(key: str) -> bool:
    """Comprueba si un lock está activo sin modificarlo."""
    r = await get_redis()
    full_key = f"{LOCK_PREFIX}{key}"
    return await r.exists(full_key) > 0


async def refresh_lock(key: str, ttl_seconds: int = 600) -> bool:
    """
    Renueva el TTL de un lock existente (heartbeat).
    Útil para operaciones de larga duración como el drip de campañas.

    Returns:
        True si el lock existía y se renovó, False si ya no existe.
    """
    r = await get_redis()
    full_key = f"{LOCK_PREFIX}{key}"
    return await r.expire(full_key, ttl_seconds)


# ──────────────────────────────────────────────
# Set distribuido (para contar locks activos)
# ──────────────────────────────────────────────

ACTIVE_CALLS_KEY = "ausarta:active_calls"


async def get_active_call_count() -> int:
    """Retorna el número de empresas con llamada activa."""
    r = await get_redis()
    # Contar todas las keys que matchean el patrón de lock de empresa
    keys = []
    async for key in r.scan_iter(match=f"{LOCK_PREFIX}empresa:*"):
        keys.append(key)
    return len(keys)
