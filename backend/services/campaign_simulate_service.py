"""Simulación dry-run de campañas (sin llamadas reales)."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from utils.call_schedule import is_call_allowed


async def simulate_campaign_dispatch(campaign: dict) -> dict[str, Any]:
    """
    Previsualiza el próximo ciclo del scheduler sin despachar llamadas.
    """
    from services.supabase_service import supabase

    if not supabase:
        return {"error": "No DB", "eligible_leads": 0}

    campaign_id = int(campaign["id"])
    empresa_id = int(campaign.get("empresa_id") or 0)
    now_utc = datetime.now(timezone.utc)

    allowed_hours = (
        int(campaign.get("call_start_hour") or 9),
        int(campaign.get("call_end_hour") or 21),
    )
    tz_name = campaign.get("call_timezone") or "Europe/Madrid"
    forbidden_days = set(campaign.get("forbidden_weekdays") or {6})
    can_call, schedule_reason = is_call_allowed(
        now=now_utc,
        timezone_str=tz_name,
        allowed_hours=allowed_hours,
        forbidden_weekdays=forbidden_days,
    )

    pending_res = await asyncio.to_thread(
        lambda: supabase.table("campaign_leads")
        .select("id, telefono, status", count="exact")
        .eq("campaign_id", campaign_id)
        .in_("status", ["pending", "calling"])
        .limit(20)
        .execute()
    )
    pending_count = int(pending_res.count or len(pending_res.data or []))
    sample_leads = [
        {"id": r.get("id"), "telefono": r.get("telefono"), "status": r.get("status")}
        for r in (pending_res.data or [])[:5]
    ]

    agent_preview: dict[str, Any] = {}
    try:
        from services.campaign_dispatch_service import resolve_campaign_dispatch_agent

        if pending_res.data:
            lead_id = int(pending_res.data[0]["id"])
            resolved = await resolve_campaign_dispatch_agent(campaign, lead_id)
            agent_preview = {
                "agent_id": resolved.get("agent_id"),
                "agent_type": resolved.get("agent_type"),
                "agent_name": resolved.get("agent_name"),
                "ab_variant": resolved.get("ab_variant"),
            }
    except Exception:
        agent_preview = {"note": "No se pudo resolver agente para el primer lead"}

    max_per_empresa = campaign.get("max_concurrent_calls")
    if max_per_empresa is None:
        from services.empresa_limits_service import get_empresa_max_concurrent_calls

        max_per_empresa = await get_empresa_max_concurrent_calls(empresa_id)

    return {
        "campaign_id": campaign_id,
        "empresa_id": empresa_id,
        "campaign_status": campaign.get("status"),
        "schedule_allowed_now": can_call,
        "schedule_reason": schedule_reason,
        "call_window": {
            "timezone": tz_name,
            "start_hour": allowed_hours[0],
            "end_hour": allowed_hours[1],
            "forbidden_weekdays": sorted(forbidden_days),
        },
        "eligible_leads": pending_count,
        "sample_leads": sample_leads,
        "agent_preview": agent_preview,
        "max_concurrent_calls_empresa": max_per_empresa,
        "dry_run": True,
        "would_dispatch": can_call and pending_count > 0 and campaign.get("status") in ("active", "running"),
    }
