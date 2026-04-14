"""
n8n_proxy.py — Proxy hacia webhooks de n8n.

Seguridad (doble capa):
  - Opción A: request autenticado con JWT de usuario (apiFetch del frontend).
  - Opción B: secret compartido vía header X-N8N-Secret (para llamadas server-to-server).

Si ninguna capa pasa, se devuelve 403.
"""
from fastapi import APIRouter, Request, HTTPException, Header
from fastapi.responses import JSONResponse
from typing import Optional
import os
import hmac
import aiohttp
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/n8n", tags=["n8n"])


def _verify_n8n_secret(provided: Optional[str]) -> bool:
    """
    Compara con timing-safe el secret enviado en X-N8N-Secret.
    Si N8N_PROXY_SECRET no está configurado, este método de auth está desactivado.
    """
    expected = os.getenv("N8N_PROXY_SECRET", "")
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode(), provided.encode())


async def _require_auth(request: Request, x_n8n_secret: Optional[str]) -> None:
    """
    Valida que la petición viene de una fuente autorizada:
      1. JWT Bearer válido (usuario autenticado desde el frontend)
      2. O header X-N8N-Secret correcto (llamada server-to-server desde n8n)
    """
    # Opción B: secret compartido (server-to-server)
    if _verify_n8n_secret(x_n8n_secret):
        return

    # Opción A: Bearer JWT — delegamos validación al middleware de auth
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        from services.auth import get_current_user
        from fastapi.security import HTTPAuthorizationCredentials
        try:
            creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=auth_header[7:])
            # Llamada directa a la función de auth (no usa Depends aquí)
            await get_current_user(creds=creds)
            return
        except Exception:
            pass  # Caerá al error de abajo

    raise HTTPException(
        status_code=403,
        detail="Acceso no autorizado. Se requiere JWT válido o X-N8N-Secret.",
    )


@router.post("/invite")
async def proxy_n8n_invite(
    request: Request,
    x_n8n_secret: Optional[str] = Header(None, alias="X-N8N-Secret"),
):
    """Proxy a n8n para invitación de usuarios. Requiere auth."""
    await _require_auth(request, x_n8n_secret)

    payload = await request.json()

    # Sanitizar: solo campos esperados para evitar inyección
    safe_payload = {k: payload[k] for k in ("email", "password", "full_name", "role", "empresa_id", "redirect_to") if k in payload}

    base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
    webhook_url = f"{base_url.rstrip('/')}/d0952789-a4a1-4eae-b0db-494356a9e3fa"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=safe_payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json() if resp.content_type == "application/json" else await resp.text()
                if not isinstance(data, dict):
                    data = {"message": data}
                return JSONResponse(status_code=resp.status, content=data)
    except Exception as e:
        logger.error(f"❌ Error en proxy n8n invite: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/recover")
async def proxy_n8n_recover(
    request: Request,
    x_n8n_secret: Optional[str] = Header(None, alias="X-N8N-Secret"),
):
    """Proxy a n8n para recuperación de contraseña. Requiere auth."""
    await _require_auth(request, x_n8n_secret)

    payload = await request.json()

    # Solo reenviar el email
    safe_payload = {"email": payload.get("email", "")}
    if not safe_payload["email"]:
        return JSONResponse(status_code=400, content={"error": "email es obligatorio"})

    base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
    webhook_url = f"{base_url.rstrip('/')}/fbdb6333-c473-493a-a1da-6c1756d5ae04"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(webhook_url, json=safe_payload, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                data = await resp.json() if resp.content_type == "application/json" else await resp.text()
                if not isinstance(data, dict):
                    data = {"message": data}
                return JSONResponse(status_code=resp.status, content=data)
    except Exception as e:
        logger.error(f"❌ Error en proxy n8n recover: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
