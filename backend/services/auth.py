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
import logging
from dataclasses import dataclass
from typing import Optional

from utils.env_validation import get_impersonation_secret

import jwt as pyjwt
from jwt import PyJWKClient
from fastapi import Security, HTTPException, status, Depends, Header
from fastapi.security import APIKeyHeader, HTTPBearer, HTTPAuthorizationCredentials

from services.supabase_service import supabase
from services.tenant_context import set_current_empresa_id
from services.api_key_service import (
    ValidatedApiKey,
    validate_api_key_from_db,
    has_scope,
)
from services.profile_cache import get_user_profile_cached, invalidate_user_profile_cache

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


def _legacy_env_keys_enabled() -> bool:
    return (os.getenv("AUSARTA_API_KEY_LEGACY", "false").strip().lower() in ("1", "true", "yes"))


async def _resolve_api_key(raw_key: str | None) -> ValidatedApiKey | None:
    """Valida API key: primero BD por tenant, luego fallback legacy env (deprecado)."""
    if not raw_key or not str(raw_key).strip():
        return None

    key = str(raw_key).strip()
    db_key = await validate_api_key_from_db(key)
    if db_key:
        return db_key

    if _legacy_env_keys_enabled() and key in _get_valid_keys():
        logger.warning(
            "[Auth] API key legacy de entorno usada (sin aislamiento tenant). "
            "Migra a api_keys en BD y desactiva AUSARTA_API_KEY_LEGACY."
        )
        return ValidatedApiKey(
            key_id="legacy-env",
            empresa_id=0,
            scopes=("admin",),
            source="legacy_env",
        )
    return None


async def require_api_key(api_key: str | None = Security(_API_KEY_HEADER)) -> str:
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing X-API-Key header",
        )

    resolved = await _resolve_api_key(api_key)
    if not resolved:
        logger.warning("[Auth] API Key inválida recibida: %s...", api_key[:8])
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    if resolved.empresa_id:
        set_current_empresa_id(resolved.empresa_id)
    return api_key


def get_supabase_jwt_secret() -> str:
    """
    JWT Secret HS256 del proyecto (Supabase → Settings → API → JWT Secret).
    Orden: variable SUPABASE_JWT_SECRET, o contenido del archivo SUPABASE_JWT_SECRET_FILE
    (útil con Docker / Portainer y montajes de secretos).
    """
    raw = os.getenv("SUPABASE_JWT_SECRET", "").strip()
    if raw:
        return raw
    path = os.getenv("SUPABASE_JWT_SECRET_FILE", "").strip()
    if path and os.path.isfile(path):
        try:
            with open(path, encoding="utf-8") as f:
                return f.read().strip()
        except OSError as e:
            logger.warning("[Auth] No se pudo leer SUPABASE_JWT_SECRET_FILE %s: %s", path, e)
    return ""


def _get_jwks_client() -> PyJWKClient | None:
    url = (os.getenv("SUPABASE_URL") or "").strip().rstrip("/")
    if not url:
        return None
    return PyJWKClient(f"{url}/auth/v1/.well-known/jwks.json", cache_keys=True)


_jwks_client: PyJWKClient | None = None


def _jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        client = _get_jwks_client()
        if client is None:
            raise HTTPException(status_code=500, detail="SUPABASE_URL no configurada para JWKS")
        _jwks_client = client
    return _jwks_client


def _get_user_from_supabase_jwt(token: str) -> dict:
    """
    Valida el JWT de Supabase localmente.
    - HS256: SUPABASE_JWT_SECRET (legacy)
    - ES256/RS256: claves públicas JWKS del proyecto (Supabase JWT Signing Keys)
    """
    jwt_secret = get_supabase_jwt_secret()
    audience = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    decode_kwargs = {"algorithms": [], "audience": audience}

    try:
        header = pyjwt.get_unverified_header(token)
        alg = header.get("alg", "HS256")

        if alg == "HS256":
            if not jwt_secret:
                raise HTTPException(status_code=500, detail="SUPABASE_JWT_SECRET no configurada")
            decode_kwargs["algorithms"] = ["HS256"]
            payload = pyjwt.decode(token, jwt_secret, **decode_kwargs)
        elif alg in ("ES256", "RS256"):
            signing_key = _jwks().get_signing_key_from_jwt(token)
            decode_kwargs["algorithms"] = [alg]
            payload = pyjwt.decode(
                token,
                signing_key.key,
                **decode_kwargs,
            )
        else:
            raise HTTPException(status_code=401, detail=f"Algoritmo JWT no soportado: {alg}")
    except HTTPException:
        raise
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
    try:
        secret = get_impersonation_secret()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
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

    user = CurrentUser(
        user_id=user_id,
        email=profile.get("email"),
        role=effective_role,
        empresa_id=effective_empresa_id,
    )
    set_current_empresa_id(user.empresa_id)
    return user


async def require_superadmin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if current_user.role != "superadmin":
        raise HTTPException(status_code=403, detail="Superadmin required")
    return current_user


async def require_admin(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """Permite superadmin y admin; bloquea user."""
    if current_user.role not in {"superadmin", "admin"}:
        raise HTTPException(status_code=403, detail="Admin required")
    return current_user


async def require_platform_admin(current_user: CurrentUser = Depends(require_admin)) -> CurrentUser:
    """Solo superadmin o admin de la empresa Ausarta."""
    from services.platform_access import has_global_access

    if not has_global_access(current_user):
        raise HTTPException(
            status_code=403,
            detail="Solo superadmin o administrador de Ausarta puede acceder",
        )
    return current_user


async def require_outbound_auth(
    creds: HTTPAuthorizationCredentials | None = Security(_BEARER),
    api_key: str | None = Security(_API_KEY_HEADER),
    x_impersonate_token: Optional[str] = Header(None, alias="X-Impersonate-Token"),
) -> str:
    """
    Para integraciones: X-API-Key válida (tabla api_keys por tenant, o legacy env).
    Para el SPA: Authorization Bearer (sesión Supabase).
    """
    if api_key is not None and str(api_key).strip() != "":
        resolved = await _resolve_api_key(api_key)
        if resolved and has_scope(resolved.scopes, "outbound_call"):
            if resolved.empresa_id:
                set_current_empresa_id(resolved.empresa_id)
            return "api-key"
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API Key",
        )

    if creds and creds.credentials:
        user = await get_current_user(creds=creds, x_impersonate_token=x_impersonate_token)
        if user.role not in {"superadmin", "admin"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin required for outbound calls",
            )
        return "jwt"

    if _is_development_env():
        logger.warning("[Auth] Outbound sin credenciales — permitido solo en development.")
        return "dev-mode"

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Missing X-API-Key header or Authorization Bearer token",
    )



# Alias de compatibilidad para código existente.
async def require_admin_empresa(current_user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    return await require_admin(current_user)
