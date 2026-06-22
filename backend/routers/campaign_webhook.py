"""Webhook para crear o lanzar campañas desde n8n / CRM."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from models.schemas import CampaignWebhookRequest
from services.audit import log_audit_event
from services.campaign_webhook_service import process_campaign_webhook
from services.rate_limiter import limiter
from services.webhook_auth import require_integration_webhook_auth

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["webhooks"])


@router.post("/webhook/campaign")
@limiter.limit("30/minute")
async def campaign_webhook(
    request: Request,
    auth_method: str = Depends(require_integration_webhook_auth),
):
    """
    Crea campañas o añade leads desde automatizaciones externas (n8n).

    Autenticación: `X-Signature` (HMAC-SHA256 del body crudo), `X-N8N-Secret` legacy,
    `X-API-Key` o JWT admin.

    Acciones:
    - `create` — crea campaña + leads (status pending por defecto)
    - `create_and_start` — crea y activa el scheduler (defecto)
    - `add_leads` — añade leads a campaña existente (`campaign_id`)
    - `start` — activa campaña existente
    """
    raw = getattr(request.state, "verified_webhook_body", b"") or b"{}"
    body = CampaignWebhookRequest.model_validate_json(raw)

    try:
        result = await process_campaign_webhook(body)
        await log_audit_event(
            user_id=None,
            action=f"webhook_campaign_{body.action}",
            target_type="campaign",
            target_id=str(result.get("campaign_id", body.campaign_id or "")),
            metadata={
                "auth_method": auth_method,
                "empresa_id": body.empresa_id,
                "leads_count": len(body.leads),
                "action": body.action,
            },
        )
        return result
    except Exception as exc:
        from fastapi import HTTPException

        if isinstance(exc, HTTPException):
            raise
        logger.error("❌ [webhook/campaign] Error: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})
