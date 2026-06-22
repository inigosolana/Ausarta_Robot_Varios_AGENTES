"""
n8n_proxy.py — Proxy hacia webhooks de n8n.

Seguridad:
  - JWT Bearer (frontend) o HMAC X-Signature sobre el body (server-to-server).
  - X-N8N-Secret legacy solo fuera de producción estricta.
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
import json
import logging

import aiohttp

from services.rate_limiter import limiter
from services.password_reset_service import send_password_reset_email
from services.n8n_webhook_service import n8n_outbound_headers, n8n_webhook_base_url
from services.webhook_auth import require_n8n_proxy_auth
from services.webhook_signature import serialize_webhook_json

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/n8n", tags=["n8n"])


@router.post("/invite")
async def proxy_n8n_invite(
    request: Request,
    _: None = Depends(require_n8n_proxy_auth),
):
    """Proxy a n8n para invitación de usuarios. Requiere auth."""
    raw = getattr(request.state, "verified_webhook_body", b"") or b"{}"
    payload = json.loads(raw)

    safe_payload = {
        k: payload[k]
        for k in ("email", "full_name", "role", "empresa_id", "redirect_to")
        if k in payload
    }
    body_bytes = serialize_webhook_json(safe_payload)

    webhook_url = f"{n8n_webhook_base_url()}/d0952789-a4a1-4eae-b0db-494356a9e3fa"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                webhook_url,
                data=body_bytes,
                headers=n8n_outbound_headers(body=body_bytes),
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                data = await resp.json() if resp.content_type == "application/json" else await resp.text()
                if not isinstance(data, dict):
                    data = {"message": data}
                return JSONResponse(status_code=resp.status, content=data)
    except Exception as e:
        logger.error(f"❌ Error en proxy n8n invite: {e}")
        return JSONResponse(status_code=500, content={"error": "Error en proxy de invitación"})


@router.post("/recover")
@limiter.limit("8/minute")
async def proxy_n8n_recover(request: Request):
    """Recuperación de contraseña (público). Misma plantilla que /api/auth/password-reset."""
    payload = await request.json()
    email = (payload.get("email") or "").strip()
    if not email:
        return JSONResponse(status_code=400, content={"error": "email es obligatorio"})
    try:
        await send_password_reset_email(email, payload.get("redirect_to"))
    except ValueError:
        return JSONResponse(status_code=400, content={"error": "Email inválido"})
    except Exception as e:
        logger.error(f"❌ Error en recover: {e}")
        return JSONResponse(status_code=503, content={"error": "No se pudo enviar el email"})
    return {
        "status": "ok",
        "message": "Si el email está registrado, recibirás las instrucciones en breve.",
    }
