"""Lógica de negocio para webhook de campañas (n8n / CRM)."""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from models.schemas import CampaignWebhookRequest
from services.agent_router import resolve_outbound_agent
from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")

MAX_LEADS = int(os.getenv("CAMPAIGN_WEBHOOK_MAX_LEADS", "500"))


def _normalize_phone(raw: str) -> str:
    return "".join(ch for ch in (raw or "").strip() if ch.isdigit() or ch == "+")


def _normalize_leads(leads: list) -> list[dict[str, str]]:
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for lead in leads:
        phone = _normalize_phone(lead.phone_number)
        if not phone or phone in seen:
            continue
        seen.add(phone)
        name = (lead.customer_name or "Cliente").strip() or "Cliente"
        out.append({"phone_number": phone, "customer_name": name})
    return out


async def _validate_empresa(empresa_id: int) -> None:
    if not supabase:
        raise HTTPException(status_code=503, detail="No DB connection")
    res = await sb_query(
        lambda: supabase.table("empresas").select("id").eq("id", empresa_id).limit(1).execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail=f"Empresa {empresa_id} no encontrada")


async def _resolve_agent_id(empresa_id: int, body: CampaignWebhookRequest) -> int:
    if body.agent_id:
        res = await sb_query(
            lambda: supabase.table("agent_config")
            .select("id, empresa_id")
            .eq("id", body.agent_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            raise HTTPException(status_code=404, detail=f"Agente {body.agent_id} no encontrado")
        agent_empresa = int(res.data[0].get("empresa_id") or 0)
        if agent_empresa != empresa_id:
            raise HTTPException(status_code=403, detail="El agente no pertenece a la empresa")
        return int(body.agent_id)

    resolved = await resolve_outbound_agent(
        empresa_id=empresa_id,
        agent_type=body.agent_type,
        call_purpose=body.call_purpose,
    )
    return int(resolved["agent_id"])


async def _load_campaign_for_empresa(campaign_id: int, empresa_id: int) -> dict[str, Any]:
    res = await sb_query(
        lambda: supabase.table("campaigns")
        .select("*")
        .eq("id", campaign_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail=f"Campaña {campaign_id} no encontrada")
    campaign = res.data[0]
    if int(campaign.get("empresa_id") or 0) != empresa_id:
        raise HTTPException(status_code=404, detail=f"Campaña {campaign_id} no encontrada")
    return campaign


async def _insert_leads(campaign_id: int, leads: list[dict[str, str]]) -> int:
    if not leads:
        return 0
    rows = [
        {
            "campaign_id": campaign_id,
            "phone_number": lead["phone_number"],
            "customer_name": lead["customer_name"],
            "status": "pending",
            "retries_attempted": 0,
        }
        for lead in leads
    ]
    await sb_query(lambda: supabase.table("campaign_leads").insert(rows).execute())
    return len(rows)


async def _create_campaign_record(
    *,
    empresa_id: int,
    agent_id: int,
    body: CampaignWebhookRequest,
    status: str,
) -> int:
    interval_raw = body.retry_interval
    if body.retry_unit == "minutes":
        interval_raw *= 60
    elif body.retry_unit == "hours":
        interval_raw *= 3600
    elif body.retry_unit == "days":
        interval_raw *= 86400

    camp_data = {
        "name": body.name,
        "agent_id": agent_id,
        "empresa_id": empresa_id,
        "status": status,
        "scheduled_time": body.scheduled_time.isoformat() if body.scheduled_time else None,
        "retries_count": body.retries_count,
        "retry_interval": interval_raw,
        "retry_unit": body.retry_unit,
        "interval_minutes": body.interval_minutes,
        "extraction_schema": [s.model_dump() for s in body.extraction_schema]
        if body.extraction_schema
        else [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res = await sb_query(lambda: supabase.table("campaigns").insert(camp_data).execute())
    return int(res.data[0]["id"])


async def _start_campaign(campaign_id: int) -> None:
    await sb_query(
        lambda: supabase.table("campaigns")
        .update(
            {
                "status": "active",
                "paused_by_health_check": False,
                "paused_reason": None,
                "status_before_health_pause": None,
                "health_paused_at": None,
            }
        )
        .eq("id", campaign_id)
        .execute()
    )
    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        await redis.delete(f"ausarta:campaign:cancel:{campaign_id}")
    except Exception:
        pass


async def trigger_campaign_scheduler() -> None:
    try:
        from services.queue_service import get_arq_pool

        arq = await get_arq_pool()
        await arq.enqueue_job("campaign_scheduler_task")
    except Exception as exc:
        logger.warning("📣 [webhook/campaign] No se pudo encolar scheduler: %s", exc)


async def process_campaign_webhook(body: CampaignWebhookRequest) -> dict[str, Any]:
    """Ejecuta create / add_leads / start según action."""
    if not supabase:
        raise HTTPException(status_code=503, detail="No DB connection")

    empresa_id = int(body.empresa_id)
    await _validate_empresa(empresa_id)

    leads = _normalize_leads(body.leads)
    if len(body.leads) > MAX_LEADS:
        raise HTTPException(
            status_code=400,
            detail=f"Máximo {MAX_LEADS} leads por webhook",
        )

    action = body.action

    if action in {"create", "create_and_start"}:
        if not body.name or not body.name.strip():
            raise HTTPException(status_code=400, detail="name es obligatorio para crear campaña")
        if not leads:
            raise HTTPException(status_code=400, detail="Se requiere al menos un lead")

        agent_id = await _resolve_agent_id(empresa_id, body)
        status = body.status or ("active" if action == "create_and_start" else "pending")
        if action == "create_and_start":
            status = "active"

        campaign_id = await _create_campaign_record(
            empresa_id=empresa_id,
            agent_id=agent_id,
            body=body,
            status=status,
        )
        inserted = await _insert_leads(campaign_id, leads)

        if action == "create_and_start" or status == "active":
            await trigger_campaign_scheduler()

        logger.info(
            "📣 [webhook/campaign] Creada campaña %s empresa=%s leads=%s action=%s",
            campaign_id,
            empresa_id,
            inserted,
            action,
        )
        return {
            "status": "ok",
            "action": action,
            "campaign_id": campaign_id,
            "empresa_id": empresa_id,
            "agent_id": agent_id,
            "leads_inserted": inserted,
            "campaign_status": status,
        }

    if action == "add_leads":
        if not body.campaign_id:
            raise HTTPException(status_code=400, detail="campaign_id es obligatorio para add_leads")
        if not leads:
            raise HTTPException(status_code=400, detail="Se requiere al menos un lead")

        campaign = await _load_campaign_for_empresa(body.campaign_id, empresa_id)
        inserted = await _insert_leads(body.campaign_id, leads)
        if body.auto_start and campaign.get("status") not in {"active", "running"}:
            await _start_campaign(body.campaign_id)
            await trigger_campaign_scheduler()

        logger.info(
            "📣 [webhook/campaign] Añadidos %s leads a campaña %s",
            inserted,
            body.campaign_id,
        )
        return {
            "status": "ok",
            "action": action,
            "campaign_id": body.campaign_id,
            "empresa_id": empresa_id,
            "leads_inserted": inserted,
        }

    if action == "start":
        if not body.campaign_id:
            raise HTTPException(status_code=400, detail="campaign_id es obligatorio para start")
        await _load_campaign_for_empresa(body.campaign_id, empresa_id)
        await _start_campaign(body.campaign_id)
        await trigger_campaign_scheduler()
        logger.info("📣 [webhook/campaign] Campaña %s iniciada", body.campaign_id)
        return {
            "status": "ok",
            "action": action,
            "campaign_id": body.campaign_id,
            "empresa_id": empresa_id,
            "campaign_status": "active",
        }

    raise HTTPException(status_code=400, detail=f"action no soportada: {action}")
