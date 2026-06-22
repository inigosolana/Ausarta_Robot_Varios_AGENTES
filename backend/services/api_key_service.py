"""API keys por tenant: generación, validación y gestión."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from services.supabase_service import supabase, sb_query

logger = logging.getLogger("api-backend")

API_KEY_PREFIX = "ausarta_"
VALID_SCOPES = frozenset({"outbound_call", "webhook", "read", "admin"})
CACHE_TTL_SECONDS = 300
CACHE_INVALID = "INVALID"


@dataclass(frozen=True)
class ValidatedApiKey:
    key_id: str
    empresa_id: int
    scopes: tuple[str, ...]
    source: str  # "db" | "legacy_env"


def hash_api_key(raw_key: str) -> str:
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def generate_api_key() -> str:
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"


def key_prefix(raw_key: str) -> str:
    return raw_key[:16] if len(raw_key) >= 16 else raw_key


def has_scope(scopes: tuple[str, ...] | list[str], required: str) -> bool:
    scope_set = set(scopes)
    return "admin" in scope_set or "*" in scope_set or required in scope_set


def _normalize_scopes(scopes: list[str] | None) -> list[str]:
    if not scopes:
        return ["outbound_call"]
    normalized = [s.strip() for s in scopes if s and s.strip()]
    invalid = [s for s in normalized if s not in VALID_SCOPES]
    if invalid:
        raise ValueError(f"Scopes no válidos: {', '.join(invalid)}")
    return normalized


def _is_expired(expires_at: str | None) -> bool:
    if not expires_at:
        return False
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        return exp <= datetime.now(timezone.utc)
    except (TypeError, ValueError):
        return True


async def _cache_get(key_hash: str) -> Optional[dict[str, Any] | str]:
    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        cached = await redis.get(f"ausarta:api_key:{key_hash}")
        return cached
    except Exception:
        return None


async def _cache_set(key_hash: str, value: str) -> None:
    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        await redis.set(f"ausarta:api_key:{key_hash}", value, ex=CACHE_TTL_SECONDS)
    except Exception:
        pass


async def _touch_last_used(key_hash: str) -> None:
    if not supabase:
        return

    def _update():
        supabase.table("api_keys").update(
            {"last_used_at": datetime.now(timezone.utc).isoformat()}
        ).eq("key_hash", key_hash).execute()

    try:
        await asyncio.to_thread(_update)
    except Exception as exc:
        logger.debug("[ApiKey] No se pudo actualizar last_used_at: %s", exc)


async def validate_api_key_from_db(raw_key: str) -> ValidatedApiKey | None:
    """Valida una API key contra la BD (con caché Redis)."""
    if not raw_key or not raw_key.strip():
        return None

    key_hash = hash_api_key(raw_key.strip())
    cached = await _cache_get(key_hash)
    if cached == CACHE_INVALID:
        return None
    if cached and isinstance(cached, str) and cached != CACHE_INVALID:
        try:
            payload = json.loads(cached)
            return ValidatedApiKey(
                key_id=payload["key_id"],
                empresa_id=int(payload["empresa_id"]),
                scopes=tuple(payload.get("scopes") or ("outbound_call",)),
                source="db",
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            pass

    if not supabase:
        return None

    def _query():
        return (
            supabase.table("api_keys")
            .select("id,empresa_id,scopes,is_active,expires_at")
            .eq("key_hash", key_hash)
            .eq("is_active", True)
            .limit(1)
            .execute()
        )

    res = await sb_query(_query)
    if not res.data:
        await _cache_set(key_hash, CACHE_INVALID)
        return None

    row = res.data[0]
    if _is_expired(row.get("expires_at")):
        await _cache_set(key_hash, CACHE_INVALID)
        return None

    scopes = tuple(row.get("scopes") or ["outbound_call"])
    payload = {
        "key_id": str(row["id"]),
        "empresa_id": int(row["empresa_id"]),
        "scopes": list(scopes),
    }
    await _cache_set(key_hash, json.dumps(payload))
    asyncio.create_task(_touch_last_used(key_hash))

    return ValidatedApiKey(
        key_id=payload["key_id"],
        empresa_id=payload["empresa_id"],
        scopes=scopes,
        source="db",
    )


async def create_api_key(
    *,
    empresa_id: int,
    description: str,
    scopes: list[str] | None,
    expires_at: datetime | None,
    created_by: str | None,
) -> dict[str, Any]:
    """Crea una API key y devuelve el valor en claro (solo una vez)."""
    if not supabase:
        raise RuntimeError("Sin conexión a Supabase")

    normalized_scopes = _normalize_scopes(scopes)
    raw_key = generate_api_key()
    key_hash = hash_api_key(raw_key)
    prefix = key_prefix(raw_key)

    insert_data: dict[str, Any] = {
        "empresa_id": empresa_id,
        "key_hash": key_hash,
        "key_prefix": prefix,
        "description": (description or "").strip()[:200],
        "scopes": normalized_scopes,
        "is_active": True,
    }
    if expires_at:
        insert_data["expires_at"] = expires_at.isoformat()
    if created_by:
        insert_data["created_by"] = created_by

    def _insert():
        return supabase.table("api_keys").insert(insert_data).execute()

    res = await sb_query(_insert)
    if not res.data:
        raise RuntimeError("No se pudo crear la API key")

    row = res.data[0]
    return {
        "id": str(row["id"]),
        "key": raw_key,
        "empresa_id": empresa_id,
        "key_prefix": prefix,
        "scopes": normalized_scopes,
        "expires_at": row.get("expires_at"),
    }


async def list_api_keys(*, empresa_id: int | None = None, active_only: bool = True) -> list[dict[str, Any]]:
    if not supabase:
        return []

    def _query():
        qb = (
            supabase.table("api_keys")
            .select(
                "id,empresa_id,key_prefix,description,scopes,is_active,"
                "expires_at,created_at,last_used_at"
            )
            .order("created_at", desc=True)
        )
        if empresa_id is not None:
            qb = qb.eq("empresa_id", empresa_id)
        if active_only:
            qb = qb.eq("is_active", True)
        return qb.execute()

    res = await sb_query(_query)
    return res.data or []


async def revoke_api_key(key_id: str, *, empresa_id: int | None = None) -> bool:
    if not supabase:
        return False

    def _revoke():
        qb = supabase.table("api_keys").update({"is_active": False}).eq("id", key_id)
        if empresa_id is not None:
            qb = qb.eq("empresa_id", empresa_id)
        return qb.execute()

    res = await sb_query(_revoke)
    return bool(res.data)
