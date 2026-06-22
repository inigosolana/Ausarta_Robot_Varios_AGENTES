"""Autenticación para webhooks server-to-server (n8n, integraciones)."""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from services.auth import _resolve_api_key, get_current_user
from services.api_key_service import has_scope
from services.tenant_context import set_current_empresa_id
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("api-backend")

_API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)
_BEARER = HTTPBearer(auto_error=False)


def verify_n8n_secret(provided: str | None) -> bool:
    expected = (os.getenv("N8N_PROXY_SECRET") or "").strip()
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


async def require_integration_webhook_auth(
    request: Request,
    x_n8n_secret: str | None = Header(None, alias="X-N8N-Secret"),
    api_key: str | None = Security(_API_KEY_HEADER),
    creds: HTTPAuthorizationCredentials | None = Security(_BEARER),
) -> str:
    """
    Autoriza webhooks de integración:
      1. X-N8N-Secret válido
      2. X-API-Key válida (api_keys por tenant o legacy env)
      3. JWT admin/superadmin
    """
    if verify_n8n_secret(x_n8n_secret):
        return "n8n-secret"

    resolved = await _resolve_api_key(api_key)
    if resolved and has_scope(resolved.scopes, "webhook"):
        if resolved.empresa_id:
            set_current_empresa_id(resolved.empresa_id)
        return "api-key"

    if creds and creds.credentials:
        user = await get_current_user(creds=creds)
        if user.role in {"superadmin", "admin"}:
            return "jwt"

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso no autorizado. Se requiere X-N8N-Secret, X-API-Key o JWT admin.",
    )
