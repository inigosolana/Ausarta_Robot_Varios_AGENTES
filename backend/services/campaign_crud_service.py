"""CRUD y arranque de campañas outbound."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from models.schemas import CampaignLeadModel, CampaignModel
from services.audit import log_audit_event
from services.auth import CurrentUser
from services.campaign_ab_service import validate_ab_campaign_payload
from services.campaign_locks import enqueue_scheduler_tick
from services.supabase_service import supabase

logger = logging.getLogger("api-backend")


def _retry_interval_seconds(interval: int, unit: str) -> int:
    raw = interval
    if unit == "minutes":
        raw *= 60
    elif unit == "hours":
        raw *= 3600
    elif unit == "days":
        raw *= 86400
    return raw


async def delete_campaign_record(campaign_id: int, current_user: CurrentUser) -> dict[str, str]:
    if not supabase:
        return {"error": "No DB"}
    supabase.table("campaign_leads").delete().eq("campaign_id", campaign_id).execute()
    supabase.table("encuestas").delete().eq("campaign_id", campaign_id).execute()
    supabase.table("campaigns").delete().eq("id", campaign_id).execute()
    await log_audit_event(
        user_id=current_user.user_id,
        action="delete_campaign",
        target_type="campaign",
        target_id=str(campaign_id),
        metadata={"cascade": ["campaign_leads", "encuestas"]},
    )
    return {"status": "ok", "message": f"Campaña {campaign_id} eliminada"}


async def create_campaign_record(
    campaign: CampaignModel,
    leads: list[CampaignLeadModel],
    current_user: CurrentUser,
) -> dict[str, Any]:
    if not supabase:
        return {"error": "No DB"}

    status_final = campaign.status
    if not campaign.scheduled_time and status_final == "pending":
        status_final = "running"

    camp_data = {
        "name": campaign.name,
        "agent_id": campaign.agent_id,
        "empresa_id": campaign.empresa_id,
        "status": status_final,
        "scheduled_time": campaign.scheduled_time.isoformat() if campaign.scheduled_time else None,
        "retries_count": campaign.retries_count,
        "retry_interval": _retry_interval_seconds(campaign.retry_interval, campaign.retry_unit),
        "retry_unit": campaign.retry_unit,
        "interval_minutes": campaign.interval_minutes,
        "extraction_schema": [s.model_dump() for s in campaign.extraction_schema] if campaign.extraction_schema else [],
        "ab_test_enabled": campaign.ab_test_enabled,
        "agent_id_b": campaign.agent_id_b,
        "ab_split_ratio": campaign.ab_split_ratio,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    res_camp = supabase.table("campaigns").insert(camp_data).execute()
    campaign_id = res_camp.data[0]["id"]

    leads_data = [
        {
            "campaign_id": campaign_id,
            "phone_number": lead.phone_number,
            "customer_name": lead.customer_name,
            "status": "pending",
            "retries_attempted": 0,
        }
        for lead in leads
    ]
    if leads_data:
        supabase.table("campaign_leads").insert(leads_data).execute()

    await log_audit_event(
        user_id=current_user.user_id,
        action="create_campaign",
        target_type="campaign",
        target_id=str(campaign_id),
        metadata={
            "empresa_id": campaign.empresa_id,
            "agent_id": campaign.agent_id,
            "leads_count": len(leads_data),
        },
    )
    return {"id": campaign_id, "message": f"Campaña creada con {len(leads_data)} leads"}


async def update_campaign_record(
    campaign_id: int,
    payload: dict[str, Any],
    current_user: CurrentUser,
) -> dict[str, str] | JSONResponse:
    if not supabase:
        return {"error": "No DB"}

    ab_error = validate_ab_campaign_payload(payload)
    if ab_error:
        return JSONResponse(status_code=400, content={"error": ab_error})

    if "retry_interval" in payload and "retry_unit" in payload:
        payload["retry_interval"] = _retry_interval_seconds(
            int(payload["retry_interval"]),
            str(payload["retry_unit"]),
        )

    supabase.table("campaigns").update(payload).eq("id", campaign_id).execute()
    await log_audit_event(
        user_id=current_user.user_id,
        action="update_campaign",
        target_type="campaign",
        target_id=str(campaign_id),
        metadata={"fields": list(payload.keys())},
    )
    return {"status": "ok"}


def list_campaigns_for_user(empresa_id: int | None) -> list[dict[str, Any]]:
    if not supabase:
        return []

    query = supabase.table("campaigns").select("*, empresas:empresa_id(nombre)")
    if empresa_id:
        query = query.eq("empresa_id", empresa_id)
    res = query.order("created_at", desc=True).limit(100).execute()
    campaigns = res.data or []

    for campaign in campaigns:
        try:
            total_r = (
                supabase.table("campaign_leads")
                .select("id", count="exact")
                .eq("campaign_id", campaign["id"])
                .execute()
            )
            total_leads = total_r.count if total_r.count is not None else 0
            campaign["total_leads"] = total_leads
            pending_r = (
                supabase.table("campaign_leads")
                .select("id", count="exact")
                .eq("campaign_id", campaign["id"])
                .in_("status", ["pending", "calling"])
                .execute()
            )
            pending_calling = pending_r.count if pending_r.count is not None else 0
            campaign["called_leads"] = max(0, total_leads - pending_calling)
        except Exception:
            campaign["total_leads"] = 0
            campaign["called_leads"] = 0
    return campaigns


async def start_campaign_record(campaign_id: int) -> dict[str, str]:
    if not supabase:
        return {"error": "No DB"}

    res = supabase.table("campaigns").select("*").eq("id", campaign_id).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    supabase.table("campaigns").update({
        "status": "active",
        "paused_by_health_check": False,
        "paused_reason": None,
        "status_before_health_pause": None,
        "health_paused_at": None,
    }).eq("id", campaign_id).execute()

    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        await redis.delete(f"ausarta:campaign:cancel:{campaign_id}")
    except Exception:
        pass

    await enqueue_scheduler_tick()
    return {
        "status": "ok",
        "message": "Campaña marcada como activa. El scheduler la procesará en el próximo ciclo.",
    }
