"""Webhook de eventos Yeastar PBX."""
from __future__ import annotations

import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from services.queue_service import get_arq_pool
from services.rate_limiter import limiter
from services.webhook_auth import require_yeastar_webhook_auth

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])

YEASTAR_IP_WHITELIST = os.getenv("YEASTAR_IP_WHITELIST", "").split(",")


async def validate_yeastar_ip(request: Request) -> None:
    """Valida que la petición provenga de una IP PBX Yeastar autorizada."""
    if not YEASTAR_IP_WHITELIST or YEASTAR_IP_WHITELIST == [""]:
        return

    client_ip = request.client.host
    if client_ip not in YEASTAR_IP_WHITELIST:
        logger.warning("🛡️ [Security] Blocked unauthorized webhook attempt from IP: %s", client_ip)
        raise HTTPException(status_code=403, detail="Unauthorized IP")


@limiter.exempt
@router.post("/webhooks/yeastar")
async def yeastar_webhook(
    request: Request,
    _=Depends(validate_yeastar_ip),
    _auth: str = Depends(require_yeastar_webhook_auth),
):
    """Recibe eventos de la centralita Yeastar y los encola en ARQ."""
    try:
        raw = getattr(request.state, "verified_webhook_body", b"") or b"{}"
        payload = json.loads(raw)

        arq_pool = await get_arq_pool()
        job = await arq_pool.enqueue_job("process_yeastar_webhook", payload)

        return {
            "status": "ok",
            "message": "Event queued",
            "job_id": getattr(job, "job_id", None),
        }
    except Exception as exc:
        logger.error("❌ Error recibiendo webhook de Yeastar: %s", exc)
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})
