from __future__ import annotations

import asyncio
import logging
from typing import Any

from arq.connections import ArqRedis

logger = logging.getLogger("arq-worker")

async def dispatch_lead_drip_task(ctx: dict[str, Any], lead_id: int, campaign_id: int) -> None:
    """
    Tarea persistida en Redis: ejecuta UNA llamada SIP para un lead.

    Reemplaza asyncio.create_task(_dispatch_single_lead_drip()) del scheduler.
    Al ser un job ARQ, su ejecución sobrevive reinicios del proceso API.

    Argumentos recibidos del job:
        lead_id:     ID del lead en campaign_leads.
        campaign_id: ID de la campaña padre.
    """
    import asyncio
    from services.supabase_service import supabase
    from routers.campaigns import _dispatch_single_lead_drip, _release_empresa_lock

    redis: ArqRedis = ctx["redis"]
    if not supabase:
        logger.warning("[ARQ] Supabase no disponible en dispatch task")
        return

    cancel_key = f"ausarta:campaign:cancel:{campaign_id}"
    if await redis.exists(cancel_key):
        try:
            lead_row = await asyncio.to_thread(
                supabase.table("campaign_leads").select("id, campaign_id").eq("id", lead_id).limit(1).execute
            )
            if lead_row.data:
                camp_row = await asyncio.to_thread(
                    supabase.table("campaigns").select("empresa_id").eq("id", campaign_id).limit(1).execute
                )
                empresa_id = (camp_row.data[0].get("empresa_id") if camp_row.data else 0) or 0
                await _release_empresa_lock(empresa_id)
        except Exception:
            pass
        logger.info(f"[ARQ] Campaña {campaign_id} cancelada, skipping lead {lead_id}")
        return

    lead_res = await asyncio.to_thread(
        supabase.table("campaign_leads").select("*").eq("id", lead_id).limit(1).execute
    )
    campaign_res = await asyncio.to_thread(
        supabase.table("campaigns").select("*").eq("id", campaign_id).limit(1).execute
    )

    if not lead_res.data or not campaign_res.data:
        logger.warning(f"[ARQ] Datos incompletos para dispatch lead={lead_id}, campaign={campaign_id}")
        return

    lead = lead_res.data[0]
    campaign = campaign_res.data[0]

    if campaign.get("status") not in ("active", "running"):
        logger.info(f"[ARQ] Campaña {campaign_id} no activa ({campaign.get('status')}), skipping lead {lead_id}")
        empresa_id = campaign.get("empresa_id") or 0
        await _release_empresa_lock(empresa_id)
        return

    await _dispatch_single_lead_drip(lead, campaign)

