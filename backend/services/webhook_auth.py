"""Autenticación para webhooks server-to-server (n8n, integraciones)."""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer

from services.auth import _resolve_api_key, get_current_user
from services.api_key_service import has_scope
from services.tenant_context import set_current_empresa_id
from services.webhook_signature import (
    verify_webhook_signature,
    verify_webhook_timestamp,
    webhook_hmac_required,
)

logger = logging.getLogger("api-backend")

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)


def verify_n8n_secret(provided: str | None) -> bool:
    expected = (os.getenv("N8N_PROXY_SECRET") or "").strip()
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


def _webhook_secret(env_name: str, fallback_env: str | None = None) -> str:
    secret = (os.getenv(env_name) or "").strip()
    if secret:
        return secret
    if fallback_env:
        return (os.getenv(fallback_env) or "").strip()
    return ""


async def _read_body(request: Request) -> bytes:
    cached = getattr(request.state, "verified_webhook_body", None)
    if isinstance(cached, (bytes, bytearray)):
        return bytes(cached)
    body = await request.body()
    request.state.verified_webhook_body = body
    return body


async def verify_inbound_webhook_hmac(
    request: Request,
    *,
    secret_env: str,
    fallback_secret_env: str | None = "N8N_PROXY_SECRET",
    x_signature: str | None = None,
    x_webhook_timestamp: str | None = None,
) -> bool:
    """Valida X-Signature sobre el cuerpo crudo. Devuelve True si la firma es válida."""
    secret = _webhook_secret(secret_env, fallback_secret_env)
    if not secret:
        return False

    body = await _read_body(request)
    if not verify_webhook_timestamp(x_webhook_timestamp):
        logger.warning("[Webhook] Timestamp inválido o expirado")
        return False

    if verify_webhook_signature(secret, body, x_signature):
        return True
    return False


async def require_campaign_webhook_auth(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_timestamp: str | None = Header(None, alias="X-Webhook-Timestamp"),
    x_n8n_secret: str | None = Header(None, alias="X-N8N-Secret"),
    api_key: str | None = Security(_API_KEY_HEADER),
    creds: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> str:
    """
    Webhook de campañas: prioridad HMAC del payload, luego métodos legacy.
    """
    if await verify_inbound_webhook_hmac(
        request,
        secret_env="CAMPAIGN_WEBHOOK_SECRET",
        fallback_secret_env="N8N_PROXY_SECRET",
        x_signature=x_signature,
        x_webhook_timestamp=x_webhook_timestamp,
    ):
        return "hmac"

    if webhook_hmac_required():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma HMAC obligatoria (X-Signature sobre el body crudo).",
        )

    if verify_n8n_secret(x_n8n_secret):
        await _read_body(request)
        logger.warning("[Webhook] Auth legacy X-N8N-Secret — migrar a X-Signature")
        return "n8n-secret-legacy"

    resolved = await _resolve_api_key(api_key)
    if resolved and has_scope(resolved.scopes, "webhook"):
        await _read_body(request)
        if resolved.empresa_id:
            set_current_empresa_id(resolved.empresa_id)
        return "api-key"

    if creds and creds.credentials:
        user = await get_current_user(creds=creds)
        if user.role in {"superadmin", "admin"}:
            await _read_body(request)
            return "jwt"

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso no autorizado. Se requiere X-Signature, X-N8N-Secret, X-API-Key o JWT admin.",
    )


async def require_yeastar_webhook_auth(
    request: Request,
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_timestamp: str | None = Header(None, alias="X-Webhook-Timestamp"),
) -> str:
    """Webhook Yeastar Event Push — HMAC con YEASTAR_WEBHOOK_SECRET."""
    if await verify_inbound_webhook_hmac(
        request,
        secret_env="YEASTAR_WEBHOOK_SECRET",
        fallback_secret_env=None,
        x_signature=x_signature,
        x_webhook_timestamp=x_webhook_timestamp,
    ):
        return "hmac"

    if webhook_hmac_required() and (os.getenv("YEASTAR_WEBHOOK_SECRET") or "").strip():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Firma HMAC inválida o ausente para webhook Yeastar.",
        )

    await _read_body(request)
    logger.warning("[Yeastar Webhook] Sin X-Signature — solo permitido si WEBHOOK_REQUIRE_HMAC=false")
    return "unsigned-dev"


async def require_integration_webhook_auth(
    request: Request,
    x_n8n_secret: str | None = Header(None, alias="X-N8N-Secret"),
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_timestamp: str | None = Header(None, alias="X-Webhook-Timestamp"),
    api_key: str | None = Security(_API_KEY_HEADER),
    creds: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> str:
    """Alias de compatibilidad — delega en require_campaign_webhook_auth."""
    return await require_campaign_webhook_auth(
        request,
        x_signature=x_signature,
        x_webhook_timestamp=x_webhook_timestamp,
        x_n8n_secret=x_n8n_secret,
        api_key=api_key,
        creds=creds,
    )


async def require_n8n_proxy_auth(
    request: Request,
    x_n8n_secret: str | None = Header(None, alias="X-N8N-Secret"),
    x_signature: str | None = Header(None, alias="X-Signature"),
    x_webhook_timestamp: str | None = Header(None, alias="X-Webhook-Timestamp"),
) -> None:
    """Proxy /api/n8n/* — JWT Bearer o HMAC; legacy secret solo fuera de prod estricto."""
    if await verify_inbound_webhook_hmac(
        request,
        secret_env="N8N_PROXY_SECRET",
        fallback_secret_env=None,
        x_signature=x_signature,
        x_webhook_timestamp=x_webhook_timestamp,
    ):
        return

    if verify_n8n_secret(x_n8n_secret):
        await _read_body(request)
        if webhook_hmac_required():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="X-N8N-Secret sin firma ya no permitido en producción. Usa X-Signature.",
            )
        logger.warning("[n8n proxy] Auth legacy X-N8N-Secret")
        return

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from fastapi.security import HTTPAuthorizationCredentials

        try:
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
            await get_current_user(creds=creds)
            await _read_body(request)
            return
        except Exception:
            pass

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso no autorizado. Se requiere JWT válido o X-Signature.",
    )
