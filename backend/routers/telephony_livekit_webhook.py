"""Webhook de eventos LiveKit."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from services.rate_limiter import limiter
from services.telephony_livekit_webhook_service import process_livekit_webhook_event

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])


@limiter.exempt
@router.post("/api/livekit/webhook")
async def livekit_webhook(request: Request):
    body_bytes = await request.body()
    auth_token = request.headers.get("Authorization", "")
    try:
        return await process_livekit_webhook_event(body_bytes, auth_token)
    except Exception as exc:
        logger.warning("🛡️ [LK Webhook] Firma inválida o payload malformado: %s", exc)
        return JSONResponse(status_code=401, content={"error": "Invalid signature"})
