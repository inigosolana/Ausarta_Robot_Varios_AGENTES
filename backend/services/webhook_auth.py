"""Autenticación para webhooks server-to-server (n8n, integraciones)."""
from __future__ import annotations

import hmac
import logging
import os

from fastapi import Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from services.auth import _get_valid_keys, get_current_user
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
      2. X-API-Key válida (AUSARTA_API_KEY)
      3. JWT admin/superadmin
    """
    if verify_n8n_secret(x_n8n_secret):
        return "n8n-secret"

    valid_keys = _get_valid_keys()
    if api_key and api_key in valid_keys:
        return "api-key"

    if creds and creds.credentials:
        user = await get_current_user(creds=creds)
        if user.role in {"superadmin", "admin"}:
            return "jwt"

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Acceso no autorizado. Se requiere X-N8N-Secret, X-API-Key o JWT admin.",
    )
