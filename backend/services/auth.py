"""
auth.py — Dependencias de autenticación/autorización para FastAPI.

Incluye:
- API Key auth (compatibilidad con endpoints legacy).
- JWT auth (Supabase) para control de roles y aislamiento multi-tenant.
- Verificación de token de impersonation (HMAC-SHA256).
"""
import os
import hmac
import json
import time
import hashlib
import base64
import binascii
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import jwt as pyjwt
from fastapi import Security, HTTPException, status, Depends, Header
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    user_id: str
    email: Optional[str]
    role: str
    empresa_id: Optional[int]


def _canonical_role(raw_role: Optional[str]) -> str:
    role = (raw_role or "").strip().lower()
    if role == "superadmin":
        return "superadmin"
    # Compatibilidad: "admin_empresa" => "admin"
    if role in ("admin", "admin_empresa"):
        return "admin"
    # Compatibilidad: "viewer" => "user"
    if role in ("user", "viewer"):
        return "user"
    return role


def _get_valid_keys() -> set[str]:
    raw = os.getenv("AUSARTA_API_KEY", "")
    if not raw:
        return set()
    return {k.strip() for k in raw.split(",") if k.strip()}


def _is_development_env() -> bool:
    return (os.getenv("ENVIRONMENT") or "").strip().lower() == "development"


async def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> str:
    valid_keys = _get_valid_keys()
    if not valid_keys:
        if _is_development_env():
            logger.warning(
                "[Auth] AUSARTA_API_KEY no configurada — permitido solo con ENVIRONMENT=development."
            )
            return "dev-mode"
        logger.error("[Auth] AUSARTA_API_KEY no configurada en entorno no-development — rechazando.")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API key authentication not configured (set AUSARTA_API_KEY)",
        )

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    if api_key not in valid_keys:
        logger.warning(f"[Auth] API Key inválida recibida: {api_key[:8]}...")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )
    return api_key


def _get_user_from_supabase_jwt(token: str) -> dict:
    """
    Valida el JWT de Supabase de forma local usando SUPABASE_JWT_SECRET (HS256).
    Evita una petición HTTP a Supabase por cada request, eliminando latencia
    y el riesgo de Rate Limit contra la Auth API.
    """
    jwt_secret = os.getenv("SUPABASE_JWT_SECRET", "")
    if not jwt_secret:
        raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET no configurada")

    try:
        payload = pyjwt.decode(
            token,
            jwt_secret,
            algorithms=["HS256"],
            # Supabase usa "authenticated" como audience; lo verificamos opcionalmente.
            options={"verify_aud": False},
        )
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expirado")
    except pyjwt.InvalidTokenError as exc:
        logger.warning(f"[Auth] JWT inválido: {exc}")
        raise HTTPException(status_code=401, detail="Token inválido o expirado")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin user_id (sub)")

    return {"id": user_id, "email": payload.get("email")}


def _b64url_decode(s: str) -> bytes:
    padding = 4 - len(s) % 4
    if padding != 4:
        s += "=" * padding
    try:
        return base64.urlsafe_b64decode(s)
    except (binascii.Error, ValueError):
        raise HTTPException(status_code=403, detail="Token de impersonation malformado") from None


def _verify_impersonation_token(token: str) -> dict:
    """
    Valida un token de impersonation firmado con HMAC-SHA256.
    Formato esperado: base64url(json_payload).base64url(signature)
    Debe coincidir exactamente con la firma generada en admin.py.
    """
    secret = os.getenv("IMPERSONATION_SECRET") or os.getenv("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not secret:
        raise HTTPException(status_code=500, detail="IMPERSONATION_SECRET no configurado")

    parts = token.split(".")
    if len(parts) != 2:
        raise HTTPException(status_code=403, detail="Token de impersonation malformado")

    raw_payload = _b64url_decode(parts[0])
    provided_sig = _b64url_decode(parts[1])

    expected_sig = hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).digest()
    if not hmac.compare_digest(provided_sig, expected_sig):
        raise HTTPException(status_code=403, detail="Token de impersonation: firma inválida")

    try:
        payload = json.loads(raw_payload)
    except (json.JSONDecodeError, ValueError):
        raise HTTPException(status_code=403, detail="Token de impersonation: payload inválido")

    if payload.get("type") != "impersonation":
        raise HTTPException(status_code=403, detail="Token de impersonation: tipo incorrecto")

    exp = payload.get("exp")
    if not exp or int(time.time()) > exp:
        raise HTTPException(status_code=403, detail="Token de impersonation expirado")

    return payload


_USER_PROFILE_CACHE_TTL = max(5, int(os.getenv("USER_PROFILE_CACHE_TTL_SECONDS", "60")))
_MEM_PROFILE_CACHE: dict[str, tuple[float, dict]] = {}
_MEM_PROFILE_LOCK = asyncio.Lock()

_USER_PROFILE_CACHE_PREFIX = "ausarta:user_profile:"


async def _fetch_user_profile_row(user_id: str) -> dict:
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
        logger.error(f"[Auth] Error consultando user_profiles para {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Error cargando perfil de usuario") from e

    if not prof_res.data:
        raise HTTPException(status_code=403, detail="Perfil no encontrado en user_profiles")

    return prof_res.data[0]


def _profile_row_cache_blob(row: dict) -> str:
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


def _profile_from_cache_blob(raw: str) -> dict:
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("cache shape")
    return data


async def get_user_profile_cached(user_id: str) -> dict:
    """
    Carga user_profiles con caché Redis (si existe) y fallback en memoria con TTL,
    para reducir presión sobre Supabase/Postgres bajo alto tráfico.
    """
    now = time.monotonic()

    try:
        from services.redis_service import get_redis

        r = await get_redis()
        key = f"{_USER_PROFILE_CACHE_PREFIX}{user_id}"
        cached = await r.get(key)
        if cached:
            try:
                return _profile_from_cache_blob(cached)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                await r.delete(key)
    except Exception:
        pass

    async with _MEM_PROFILE_LOCK:
        hit = _MEM_PROFILE_CACHE.get(user_id)
        if hit is not None:
            expires_at, row = hit
            if now < expires_at:
                return row

    row = await asyncio.to_thread(_fetch_user_profile_row, user_id)

    try:
        from services.redis_service import get_redis

        r = await get_redis()
        key = f"{_USER_PROFILE_CACHE_PREFIX}{user_id}"
        await r.set(key, _profile_row_cache_blob(row), ex=_USER_PROFILE_CACHE_TTL)
    except Exception:
        pass

    async with _MEM_PROFILE_LOCK:
        _MEM_PROFILE_CACHE[user_id] = (now + float(_USER_PROFILE_CACHE_TTL), row)

    return row


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Security(_BEARER),
    x_impersonate_token: Optional[str] = Header(None, alias="X-Impersonate-Token"),
) -> CurrentUser:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    if not supabase:
        raise HTTPException(status_code=500, detail="No hay conexión con Supabase")

    token = creds.credentials
    auth_user = _get_user_from_supabase_jwt(token)
    user_id = auth_user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin user_id")

    profile = await get_user_profile_cached(user_id)

    if profile.get("is_active") is False:
        raise HTTPException(status_code=403, detail="Usuario desactivado")

    canonical = _canonical_role(profile.get("role"))
    if canonical not in {"superadmin", "admin", "user"}:
        raise HTTPException(status_code=403, detail="Rol no permitido")

    effective_role = canonical
    effective_empresa_id = profile.get("empresa_id")

    if x_impersonate_token and canonical in {"superadmin", "admin"}:
        try:
            imp = _verify_impersonation_token(x_impersonate_token)
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("[Auth] Token de impersonation no procesable: %s", exc)
            raise HTTPException(
                status_code=403, detail="Token de impersonation inválido"
            ) from None
        effective_role = imp.get("target_role", canonical)
        effective_empresa_id = imp.get("target_empresa_id", effective_empresa_id)
        logger.info(
            f"[Auth] Impersonation activa: user={user_id} -> "
            f"role={effective_role}, empresa_id={effective_empresa_id}"
        )

    return CurrentUser(
        user_id=user_id,
        email=profile.get("email"),
        role=effective_role,
        empresa_id=effective_empresa_id,
    )


async def require_superadmin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin required")
    return current_user


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Permite superadmin y admin; bloquea user."""
    if current_user.role not in {"superadmin", "admin"}:
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user


# Alias de compatibilidad para código existente.
async def require_admin_empresa(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return await require_admin(current_user)
