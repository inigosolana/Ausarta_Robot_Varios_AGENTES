"""
auth.py — Dependencias de autenticación/autorización para FastAPI.

Incluye:
- API Key auth (compatibilidad con endpoints legacy).
- JWT auth (Supabase) para control de roles y aislamiento multi-tenant.
"""
import os
import logging
from dataclasses import dataclass
from typing import Optional

import aiohttp
from fastapi import Security, HTTPException, status, Depends
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


async def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> str:
    valid_keys = _get_valid_keys()
    if not valid_keys:
        logger.debug("[Auth] AUSARTA_API_KEY no configurada — modo abierto (desarrollo).")
        return "dev-mode"

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


async def _get_user_from_supabase_jwt(token: str) -> dict:
    supabase_url = (os.getenv("SUPABASE_URL") or "").rstrip("/")
    if not supabase_url:
        raise HTTPException(status_code=500, detail="SUPABASE_URL no configurada")

    apikey = (
        os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or ""
    )
    if not apikey:
        raise HTTPException(status_code=500, detail="Supabase API key no configurada")

    headers = {
        "Authorization": f"Bearer {token}",
        "apikey": apikey,
    }
    url = f"{supabase_url}/auth/v1/user"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status == 200:
                return await resp.json()
            if resp.status in (401, 403):
                raise HTTPException(status_code=401, detail="Token inválido o expirado")
            body = await resp.text()
            logger.error(f"[Auth] Error validando JWT en Supabase ({resp.status}): {body[:300]}")
            raise HTTPException(status_code=500, detail="No se pudo validar el token")


async def get_current_user(
    creds: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> CurrentUser:
    if not creds or not creds.credentials:
        raise HTTPException(status_code=401, detail="Missing Bearer token")

    if not supabase:
        raise HTTPException(status_code=500, detail="No hay conexión con Supabase")

    token = creds.credentials
    auth_user = await _get_user_from_supabase_jwt(token)
    user_id = auth_user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token sin user_id")

    try:
        prof_res = (
            supabase.table("user_profiles")
            .select("id,email,role,empresa_id")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
    except Exception as e:
        logger.error(f"[Auth] Error consultando user_profiles para {user_id}: {e}")
        raise HTTPException(status_code=500, detail="Error cargando perfil de usuario")

    if not prof_res.data:
        raise HTTPException(status_code=403, detail="Perfil no encontrado en user_profiles")

    profile = prof_res.data[0]
    canonical = _canonical_role(profile.get("role"))
    if canonical not in {"superadmin", "admin", "user"}:
        raise HTTPException(status_code=403, detail="Rol no permitido")

    return CurrentUser(
        user_id=user_id,
        email=profile.get("email"),
        role=canonical,
        empresa_id=profile.get("empresa_id"),
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
