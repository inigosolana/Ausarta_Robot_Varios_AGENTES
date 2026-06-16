"""
campaign_orchestrator.py — Orquestador nativo de campañas (Cron ARQ cada minuto).

Arquitectura fanout:
  1. El cron `campaign_orchestrator` escanea campañas activas y encola un job
     `process_campaign_empresa` por cada (campaign_id, empresa_id). Así cada
     empresa se procesa en paralelo por ARQ sin bloquearse mutuamente.
  2. `process_campaign_empresa` reclama los leads de esa campaña y lanza las
     llamadas SIP con concurrencia limitada por `asyncio.Semaphore`.

Extraído de worker.py para mantener WorkerSettings limpio.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from utils.call_schedule import is_call_allowed
from services.agent_router import build_outbound_room_metadata, resolve_outbound_agent

logger = logging.getLogger("arq-worker")


# ──────────────────────────────────────────────────────────────────────────────
# Cron: fanout por empresa/campaña
# ──────────────────────────────────────────────────────────────────────────────

async def campaign_orchestrator(ctx: dict[str, Any]) -> None:
    """
    Cron ARQ cada minuto: lee campañas activas y encola un job
    `process_campaign_empresa` por cada una, para procesamiento paralelo.
    """
    from services.supabase_service import supabase, sb_query

    if not supabase:
        logger.warning("[Orchestrator] Supabase no disponible. Skipping ciclo.")
        return

    try:
        camp_res = await sb_query(
            lambda: supabase.table("campaigns")
            .select(
                "id, empresa_id, name, agent_id, call_start_hour, call_end_hour, "
                "call_timezone, forbidden_weekdays"
            )
            .eq("status", "active")
            .execute()
        )
        campaigns = camp_res.data or []
    except Exception as e:
        logger.error("[Orchestrator] Error leyendo campañas activas: %s", e)
        return

    if not campaigns:
        logger.info("[Orchestrator] Sin campañas activas. Fin de ciclo.")
        return

    logger.info("[Orchestrator] %s campaña(s) activa(s) → fanout.", len(campaigns))

    # Encolamos un job independiente por campaña; ARQ los procesa en paralelo.
    redis: Any = ctx.get("redis")
    if redis is None:
        logger.error("[Orchestrator] No hay cliente ARQ Redis en ctx.")
        return

    for camp in campaigns:
        try:
            await redis.enqueue_job(
                "process_campaign_empresa",
                camp,
                _job_id=f"camp_{camp['id']}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            )
            logger.info(
                "[Orchestrator] Job encolado campaña=%s empresa=%s",
                camp["id"], camp.get("empresa_id"),
            )
        except Exception as enq_err:
            logger.error(
                "[Orchestrator] Error encolando job campaña=%s: %s", camp["id"], enq_err
            )


# ──────────────────────────────────────────────────────────────────────────────
# Job por empresa: claims + dispatch SIP
# ──────────────────────────────────────────────────────────────────────────────

async def process_campaign_empresa(ctx: dict[str, Any], campaign: dict) -> None:
    """
    Job ARQ (encolado por `campaign_orchestrator`): procesa una sola campaña.
    Reclama leads de forma atómica y lanza llamadas SIP con concurrencia limitada.
    """
    from services.supabase_service import supabase, sb_query
    from services.livekit_service import lkapi, create_isolated_room, dispatch_agent_explicit, wait_for_agent_ready
    from services.trunk_service import resolve_outbound_trunk_id
    from livekit import api as lk_api

    if not supabase:
        logger.warning("[CampEmpresa] Supabase no disponible. Skipping.")
        return

    camp_id = campaign["id"]
    empresa_id = campaign.get("empresa_id") or 0
    agent_id = campaign.get("agent_id") or "1"
    camp_name = campaign.get("name", "")
    batch_size = int(os.getenv("ORCHESTRATOR_BATCH_SIZE", "10"))
    max_parallel = int(os.getenv("ORCHESTRATOR_MAX_PARALLEL", "5"))

    now_iso = datetime.now(timezone.utc).isoformat()

    logger.info("[CampEmpresa] Procesando campaña=%s empresa=%s batch=%s", camp_id, empresa_id, batch_size)

    # ── 1. Extraer leads pendientes ──────────────────────────────────────────
    try:
        leads_res = await sb_query(
            lambda: supabase.table("campaign_leads")
            .select("id, phone_number, campaign_id, empresa_id")
            .eq("campaign_id", camp_id)
            .eq("status", "pending")
            .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
            .order("next_retry_at", desc=False, nullsfirst=True)
            .limit(batch_size)
            .execute()
        )
        leads = leads_res.data or []
    except Exception as e:
        logger.error("[CampEmpresa] Error leyendo leads campaña %s: %s", camp_id, e)
        return

    if not leads:
        logger.info("[CampEmpresa] Sin leads pendientes para campaña=%s.", camp_id)
        return

    for lead in leads:
        lead["_campaign_agent_id"] = agent_id
        lead["_campaign_name"] = camp_name

    # ── 2. Claim atómico por lead ────────────────────────────────────────────
    tz_name = campaign.get("call_timezone") or "Europe/Madrid"
    allowed_hours = (
        int(campaign.get("call_start_hour") or 9),
        int(campaign.get("call_end_hour") or 21),
    )
    forbidden_days = set(campaign.get("forbidden_weekdays") or {6})

    claimed_leads: list[dict] = []
    now_utc = datetime.now(timezone.utc)

    for lead in leads:
        lead_id = lead["id"]
        can_call, reason = is_call_allowed(
            now=now_utc,
            timezone_str=tz_name,
            allowed_hours=allowed_hours,
            forbidden_weekdays=forbidden_days,
        )
        if not can_call:
            logger.info("[CampEmpresa] Lead %s saltado por horario: %s", lead_id, reason)
            continue

        try:
            claim_res = await sb_query(
                lambda: supabase.table("campaign_leads")
                .update({"status": "calling", "last_call_at": now_utc.isoformat()})
                .eq("id", lead_id)
                .eq("status", "pending")
                .execute()
            )
            if not (claim_res.data or []):
                logger.info("[CampEmpresa] Lead %s ya reclamado. Skipping.", lead_id)
                continue
            claimed_leads.append(lead)
        except Exception as claim_err:
            logger.error("[CampEmpresa] Error claim lead %s: %s", lead_id, claim_err)

    if not claimed_leads:
        logger.info("[CampEmpresa] Sin leads reclamados en campaña=%s.", camp_id)
        return

    logger.info("[CampEmpresa] %s lead(s) reclamados en campaña=%s.", len(claimed_leads), camp_id)

    # ── 3. Dispatch con concurrencia limitada ────────────────────────────────
    semaphore = asyncio.Semaphore(max_parallel)

    async def _dispatch_one(lead: dict) -> None:
        lead_id = lead["id"]
        phone = lead.get("phone_number", "")
        _camp_id = lead.get("campaign_id")
        _empresa_id = lead.get("empresa_id") or 0
        _agent_id = lead.get("_campaign_agent_id") or "1"
        _camp_name = lead.get("_campaign_name", "")

        if not phone:
            logger.warning("[CampEmpresa] Lead %s sin teléfono. Skipping.", lead_id)
            return

        async with semaphore:
            try:
                resolved = await resolve_outbound_agent(
                    empresa_id=int(_empresa_id) if _empresa_id else None,
                    campaign_agent_id=_agent_id,
                )
                resolved_agent_id = resolved["agent_id"]
                resolved_agent_type = resolved["agent_type"]

                enc_res = await sb_query(
                    lambda: supabase.table("encuestas").insert({
                        "telefono": phone,
                        "fecha": datetime.now(timezone.utc).isoformat(),
                        "status": "initiated",
                        "completada": 0,
                        "agent_id": resolved_agent_id,
                        "agent_type": resolved_agent_type,
                        "empresa_id": _empresa_id,
                        "campaign_id": _camp_id,
                        "campaign_name": _camp_name,
                    }).execute()
                )
                encuesta_id = enc_res.data[0]["id"]

                await sb_query(
                    lambda: supabase.table("campaign_leads")
                    .update({"call_id": encuesta_id})
                    .eq("id", lead_id)
                    .execute()
                )

                room_name = (
                    f"llamada_ausarta_empresa_{_empresa_id}"
                    f"_campana_{_camp_id}"
                    f"_contacto_{lead_id}"
                    f"_encuesta_{encuesta_id}"
                )
                room_metadata = build_outbound_room_metadata(
                    empresa_id=int(_empresa_id),
                    survey_id=int(encuesta_id),
                    agent_id=int(resolved_agent_id),
                    agent_type=resolved_agent_type,
                    campaign_id=int(_camp_id or 0),
                    contacto_id=int(lead_id),
                )

                await create_isolated_room(room_name, metadata=room_metadata)

                agent_name = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
                await dispatch_agent_explicit(
                    room_name=room_name,
                    agent_name=agent_name,
                    metadata=room_metadata,
                )
                logger.info(
                    "[CampEmpresa] Agente despachado lead=%s tipo=%s sala=%s",
                    lead_id,
                    resolved_agent_type,
                    room_name,
                )

                agent_ready = await wait_for_agent_ready(room_name)
                if not agent_ready:
                    logger.error(
                        "[CampEmpresa] Agente no listo lead=%s sala=%s. Revirtiendo.", lead_id, room_name
                    )
                    await sb_query(
                        lambda: supabase.table("campaign_leads")
                        .update({"status": "pending"})
                        .eq("id", lead_id)
                        .execute()
                    )
                    return

                sip_trunk_id = await resolve_outbound_trunk_id(int(_empresa_id) if _empresa_id else None)
                await lkapi.sip.create_sip_participant(
                    lk_api.CreateSIPParticipantRequest(
                        sip_trunk_id=sip_trunk_id,
                        sip_call_to=phone,
                        room_name=room_name,
                        participant_identity=f"user_{phone}_{encuesta_id}",
                        participant_name="Cliente",
                    )
                )
                logger.info("✅ [CampEmpresa] Llamada SIP iniciada lead=%s → %s", lead_id, phone)

            except Exception as e:
                logger.error("❌ [CampEmpresa] Error despachando lead=%s (%s): %s", lead_id, phone, e)
                try:
                    await sb_query(
                        lambda: supabase.table("campaign_leads")
                        .update({"status": "pending"})
                        .eq("id", lead_id)
                        .execute()
                    )
                except Exception as revert_err:
                    logger.error("[CampEmpresa] Error revirtiendo lead=%s: %s", lead_id, revert_err)

    await asyncio.gather(*[_dispatch_one(lead) for lead in claimed_leads])
    logger.info("[CampEmpresa] ◀ Campaña=%s procesada.", camp_id)
