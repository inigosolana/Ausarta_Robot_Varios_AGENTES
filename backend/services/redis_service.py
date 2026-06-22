"""
redis_service.py — Servicio centralizado de Redis.

Proporciona:
  - Conexión singleton (pool asíncrono) reutilizable en toda la app.
  - Distributed Lock con TTL y token de propiedad (release seguro vía Lua).
  - Helpers para sets distribuidos (reemplazo de _processing_rooms).

Configuración vía variable de entorno REDIS_URL (default: redis://redis:6379/0).
"""
import os
import logging
import secrets
from typing import Optional

import redis.asyncio as aioredis

from services.tenant_context import get_current_empresa_id

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
#
# TODO escalado horizontal:
#   acquire_lock / release_lock son seguros para múltiples procesos/réplicas
#   porque usan Redis como coordinador central (SET NX atómico).
#   SIN EMBARGO, si en algún punto del código se reutilizara un lock o set
#   en memoria (dict, set de Python), ese mecanismo es ÚNICAMENTE seguro
#   con una sola instancia del backend. Con réplicas, cada pod tendría su
#   propio dict/set → descoordinación y condiciones de carrera.
#
#   Para desplegar réplicas horizontales de ausarta-backend:
#     1. Eliminar cualquier fallback a dict/set en memoria para coordinación.
#     2. Usar exclusivamente acquire_lock() / release_lock() de este módulo.
#     3. Revisar también _processing_rooms (agent_lifecycle.py) y cualquier
#        variable global de estado que no sea Redis.
#     4. Configurar Redis con persistencia AOF o réplica para evitar
#        pérdida de locks en reinicios.
#     5. Evaluar uso de Redlock (redis-py-lock) para garantías más fuertes
#        en entornos con partición de red.
# ──────────────────────────────────────────────

LOCK_PREFIX = "ausarta:lock:"

_RELEASE_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("del", KEYS[1])
else
    return 0
end
"""

_EXTEND_LOCK_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
    return redis.call("expire", KEYS[1], ARGV[2])
else
    return 0
end
"""


def _full_lock_key(key: str) -> str:
    return f"{LOCK_PREFIX}{key}"


async def acquire_lock(key: str, ttl_seconds: int = 600) -> str | None:
    """
    Intenta adquirir un lock distribuido con token de propiedad.

    Returns:
        Token de propiedad si se adquirió el lock; None si otro proceso lo tiene.
    """
    r = await get_redis()
    token = secrets.token_urlsafe(16)
    acquired = await r.set(_full_lock_key(key), token, nx=True, ex=ttl_seconds)
    if acquired:
        return token
    return None


async def release_lock(key: str, token: str | None = None) -> bool:
    """
    Libera un lock distribuido.

    Con token: solo borra si el lock sigue siendo del mismo propietario (Lua).
    Sin token: borrado directo (legacy — evitar en código nuevo).
    """
    r = await get_redis()
    full_key = _full_lock_key(key)
    if token:
        released = await r.eval(_RELEASE_LOCK_SCRIPT, 1, full_key, token)
        return bool(released)
    await r.delete(full_key)
    return True


async def is_locked(key: str) -> bool:
    """Comprueba si un lock está activo sin modificarlo."""
    r = await get_redis()
    return await r.exists(_full_lock_key(key)) > 0


async def refresh_lock(key: str, token: str, ttl_seconds: int = 600) -> bool:
    """
    Renueva el TTL solo si el token de propiedad coincide.
    """
    r = await get_redis()
    extended = await r.eval(_EXTEND_LOCK_SCRIPT, 1, _full_lock_key(key), token, str(ttl_seconds))
    return bool(extended)


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


# ──────────────────────────────────────────────
# Caché distribuida (valores con TTL)
# ──────────────────────────────────────────────

CACHE_PREFIX = "ausarta:cache:"
GLOBAL_PREFIX = "global:"


def build_tenant_redis_key(key: str, empresa_id: Optional[int] = None) -> str:
    """
    Prefija la clave con tenant_{empresa_id}: para aislamiento OWASP.
    Sin tenant en contexto ni parámetro → prefijo global: (infra compartida).
    """
    eid = empresa_id if empresa_id is not None else get_current_empresa_id()
    if eid is not None:
        try:
            eid_int = int(eid)
            if eid_int > 0:
                return f"tenant_{eid_int}:{key}"
        except (TypeError, ValueError):
            pass
    return f"{GLOBAL_PREFIX}{key}"


async def tenant_redis_get(
    key: str,
    *,
    empresa_id: Optional[int] = None,
) -> Optional[str]:
    """GET con prefijo de tenant automático (ContextVar o empresa_id explícito)."""
    r = await get_redis()
    return await r.get(build_tenant_redis_key(key, empresa_id))


async def tenant_redis_set(
    key: str,
    value: str,
    ttl_seconds: Optional[int] = None,
    *,
    empresa_id: Optional[int] = None,
) -> None:
    """SET con prefijo de tenant automático."""
    r = await get_redis()
    full_key = build_tenant_redis_key(key, empresa_id)
    if ttl_seconds is not None:
        await r.set(full_key, value, ex=int(ttl_seconds))
    else:
        await r.set(full_key, value)


async def cache_get(key: str, *, empresa_id: Optional[int] = None) -> Optional[str]:
    """Lee caché distribuida con aislamiento por tenant."""
    return await tenant_redis_get(f"{CACHE_PREFIX}{key}", empresa_id=empresa_id)


async def cache_set(
    key: str,
    value: str,
    ttl_seconds: int,
    *,
    empresa_id: Optional[int] = None,
) -> None:
    """Guarda caché distribuida con TTL y prefijo de tenant."""
    await tenant_redis_set(
        f"{CACHE_PREFIX}{key}",
        value,
        ttl_seconds,
        empresa_id=empresa_id,
    )


async def cache_delete(key: str, *, empresa_id: Optional[int] = None) -> None:
    """Elimina una entrada de cache respetando el aislamiento por tenant."""
    r = await get_redis()
    full_key = build_tenant_redis_key(f"{CACHE_PREFIX}{key}", empresa_id)
    await r.delete(full_key)
