"""Webhook legacy de resultados de llamada (compatibilidad n8n antiguo)."""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from services.supabase_service import supabase
from services.webhook_auth import require_campaign_webhook_auth
from services.webhook_event_service import log_webhook_event, mark_webhook_event_processed

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaigns"])


class CallResultWebhook(BaseModel):
    lead_id: int
    status: str
    duration: int | None = 0
    transcription: str | None = ""


@router.post("/campaigns/webhook/call-result")
async def receive_call_result(
    request: Request,
    auth_method: str = Depends(require_campaign_webhook_auth),
):
    """Recibe resultados de n8n para actualizar el lead (compatibilidad legacy)."""
    raw = getattr(request.state, "verified_webhook_body", b"") or b"{}"
    event_id = await log_webhook_event(
        source="campaign",
        event_type="call-result",
        payload=json.loads(raw) if raw else {},
    )
    result = CallResultWebhook.model_validate_json(raw)
    logger.info(
        "📥 [Webhook-legacy] Resultado para lead %s: %s (%s)",
        result.lead_id,
        result.status,
        auth_method,
    )
    try:
        lead_update = {
            "status": result.status,
            "error_msg": None
            if result.status in ("completed", "completada")
            else f"Incidencia: {result.status}",
        }
        await asyncio.to_thread(
            supabase.table("campaign_leads").update(lead_update).eq("id", result.lead_id).execute
        )
        if event_id:
            await mark_webhook_event_processed(event_id)
        return {"status": "ok"}
    except Exception as err:
        logger.error("❌ [Webhook-legacy] Error: %s", err)
        if event_id:
            await mark_webhook_event_processed(event_id, failed=True)
        return JSONResponse(status_code=500, content={"error": "Error procesando webhook"})
