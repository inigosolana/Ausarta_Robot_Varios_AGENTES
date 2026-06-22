"""
Motor de campañas — goteo controlado (drip) por lead.
"""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timedelta, timezone

from livekit import api as lk_api

from services.agent_router import build_outbound_room_metadata
from services.campaign_dispatch_service import resolve_campaign_dispatch_agent
from services.campaign_locks import (
    COOLDOWN_MAX,
    COOLDOWN_MIN,
    acquire_empresa_lock,
    get_active_call_count,
    is_empresa_locked,
    release_empresa_lock,
)
from services.livekit_service import create_isolated_room, dispatch_agent_explicit, lkapi
from services.sip_call_service import (
    create_sip_participant_with_retry,
    mark_call_failed,
    sip_retry_max_attempts,
)
from services.supabase_service import supabase
from services.trunk_service import resolve_outbound_trunk_id

logger = logging.getLogger("api-backend")


async def dispatch_single_lead_drip(
    lead: dict,
    campaign: dict,
    *,
    lock_token: str | None = None,
) -> None:
    """
    Lanza UNA llamada SIP para un lead y gestiona el drip lock de la empresa.

    El lock ya debe haberse adquirido en el scheduler antes de llamar a esta función.
    """
    lead_id = lead["id"]
    phone = lead["phone_number"]
    empresa_id = campaign.get("empresa_id") or 0
    campaign_id = campaign["id"]
    agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip() or "default_agent"
    sip_trunk_id = await resolve_outbound_trunk_id(int(empresa_id) if empresa_id else None)

    encuesta_id = None

    try:
        logger.info(f"☎️  [Drip] Iniciando lead {lead_id} ({phone}) → empresa={empresa_id} camp={campaign_id}")

        if empresa_id:
            from services.billing_limits_service import (
                TenantSpendingLimitExceeded,
                enforce_tenant_spending_limit,
            )

            try:
                await enforce_tenant_spending_limit(int(empresa_id), raise_http=False)
            except TenantSpendingLimitExceeded as limit_exc:
                logger.warning(
                    "[Drip] Lead %s bloqueado por límite de gasto empresa %s: %s",
                    lead_id,
                    empresa_id,
                    limit_exc.message,
                )
                await asyncio.to_thread(
                    supabase.table("campaign_leads")
                    .update({
                        "status": "failed",
                        "error_msg": limit_exc.message[:500],
                    })
                    .eq("id", lead_id)
                    .execute
                )
                return

        resolved = await resolve_campaign_dispatch_agent(campaign, int(lead_id))
        resolved_agent_id = resolved["agent_id"]
        resolved_agent_type = resolved["agent_type"]
        ab_variant = resolved.get("ab_variant")
        logger.info(
            "🤖 [Drip] Agente resuelto id=%s tipo=%s camp=%s variante=%s",
            resolved_agent_id,
            resolved_agent_type,
            campaign_id,
            ab_variant,
        )

        try:
            enc_res = await asyncio.to_thread(
                supabase.table("encuestas").insert({
                    "telefono": phone,
                    "nombre_cliente": lead.get("customer_name", "Cliente"),
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "status": "initiated",
                    "completada": 0,
                    "agent_id": resolved_agent_id,
                    "agent_type": resolved_agent_type,
                    "empresa_id": empresa_id,
                    "campaign_id": campaign_id,
                    "campaign_name": campaign.get("name"),
                    "ab_variant": ab_variant,
                }).execute
            )
            encuesta_id = enc_res.data[0]["id"]
            await asyncio.to_thread(
                supabase.table("campaign_leads").update({
                    "call_id": encuesta_id,
                    "status": "calling",
                    "last_call_at": datetime.now(timezone.utc).isoformat(),
                    "ab_variant": ab_variant,
                }).eq("id", lead_id).execute
            )
        except Exception as e:
            logger.error(f"❌ [Drip] Error creando encuesta para lead {lead_id}: {e}")
            await asyncio.to_thread(
                supabase.table("campaign_leads").update(
                    {"status": "failed", "error_msg": str(e)}
                ).eq("id", lead_id).execute
            )
            return

        room_name = f"llamada_ausarta_empresa_{empresa_id}_campana_{campaign_id}_contacto_{lead_id}_encuesta_{encuesta_id}"
        room_metadata = build_outbound_room_metadata(
            empresa_id=int(empresa_id or 0),
            survey_id=int(encuesta_id),
            agent_id=int(resolved_agent_id),
            agent_type=resolved_agent_type,
            campaign_id=int(campaign_id),
            contacto_id=int(lead_id),
            extra={"ab_variant": ab_variant} if ab_variant else None,
        )

        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as room_err:
            logger.warning(f"⚠️ [Drip] Aviso creando sala {room_name}: {room_err}")

        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            logger.info(
                f"🚀 [Drip] Agente '{agent_name_dispatch}' (tipo={resolved_agent_type}) despachado a {room_name}"
            )
            await asyncio.sleep(float(os.getenv("DRIP_AGENT_JOIN_DELAY_SECONDS", "3")))
        except Exception as dispatch_err:
            logger.warning(f"⚠️ [Drip] Dispatch explícito fallido (auto-dispatch como fallback): {dispatch_err}")

        try:
            await create_sip_participant_with_retry(
                lk_api.CreateSIPParticipantRequest(
                    sip_trunk_id=sip_trunk_id,
                    sip_call_to=phone,
                    room_name=room_name,
                    participant_identity=f"user_{phone}_{encuesta_id}",
                    participant_name="Cliente",
                ),
                empresa_id=int(empresa_id) if empresa_id else None,
                phone=str(phone),
                source="campaign_drip",
            )
            logger.info(f"☎️ [Drip] SIP lanzado: {phone} → {room_name}")
        except Exception as sip_err:
            logger.error(f"❌ [Drip] Error SIP lead {lead_id}: {sip_err}")
            await mark_call_failed(
                int(encuesta_id),
                str(sip_err),
                error_code="sip_dispatch_failed",
                source="campaign_drip",
                empresa_id=int(empresa_id) if empresa_id else None,
                phone=str(phone),
                room_name=room_name,
                sip_attempts=sip_retry_max_attempts(),
            )
            await apply_retry_after_failure(lead_id=lead_id, campaign=campaign)
            return

        TERMINAL = {"completed", "failed", "unreached", "incomplete", "rejected_opt_out"}
        MAX_WAIT_SECONDS = 300
        ANSWER_TIMEOUT_SECONDS = int(os.getenv("DRIP_ANSWER_TIMEOUT_SECONDS", "30"))
        POLL_INTERVAL_S = 2
        waited = 0
        answer_timeout_applied = False
        while waited < MAX_WAIT_SECONDS:
            await asyncio.sleep(POLL_INTERVAL_S)
            waited += POLL_INTERVAL_S
            try:
                enc_check = await asyncio.to_thread(
                    supabase.table("encuestas").select("status")
                    .eq("id", encuesta_id).limit(1).execute
                )
                current = enc_check.data[0].get("status") if enc_check.data else None
                if current in TERMINAL:
                    logger.info(f"✅ [Drip] Encuesta {encuesta_id} terminal ('{current}') tras {waited}s de espera")
                    break
                if waited >= ANSWER_TIMEOUT_SECONDS and current in (None, "", "initiated", "calling", "pending"):
                    answer_timeout_applied = True
                    logger.warning(
                        f"⏱️ [Drip] Timeout {ANSWER_TIMEOUT_SECONDS}s sin respuesta (encuesta {encuesta_id}). "
                        "Marcando failed y cerrando sala."
                    )
                    try:
                        await lkapi.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
                    except Exception:
                        pass
                    await asyncio.to_thread(
                        supabase.table("encuestas").update({"status": "failed"}).eq("id", encuesta_id).execute
                    )
                    await apply_retry_after_failure(lead_id=lead_id, campaign=campaign)
                    break
            except Exception as poll_err:
                logger.warning(f"[Drip] Error en poll de estado encuesta {encuesta_id}: {poll_err}")

        if answer_timeout_applied:
            logger.info(f"📵 [Drip] Lead {lead_id} marcado fallido por no contestar en tiempo.")

        cooldown = random.randint(COOLDOWN_MIN, COOLDOWN_MAX)
        logger.info(f"⏳ [Drip] Cooldown {cooldown}s para empresa {empresa_id} antes del siguiente lead...")
        await asyncio.sleep(cooldown)

    finally:
        await release_empresa_lock(empresa_id, lock_token)
        logger.info(f"🔓 [Drip] Lock liberado para empresa {empresa_id}")


async def apply_retry_after_failure(lead_id: int, campaign: dict) -> None:
    """Programa el siguiente reintento para fallos/no respuesta según la campaña."""
    retry_seconds = int(campaign.get("retry_interval") or 3600)
    max_retries = int(campaign.get("retries_count") or 3)
    try:
        lr = await asyncio.to_thread(
            supabase.table("campaign_leads").select("retries_attempted").eq("id", lead_id).limit(1).execute
        )
        current_retries = (lr.data[0].get("retries_attempted") if lr.data else 0) or 0
    except Exception:
        current_retries = 0

    new_retries = current_retries + 1
    lead_update = {"status": "failed", "retries_attempted": new_retries}
    if new_retries < max_retries:
        lead_update["status"] = "pending"
        lead_update["next_retry_at"] = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
    try:
        await asyncio.to_thread(
            supabase.table("campaign_leads").update(lead_update).eq("id", lead_id).execute
        )
    except Exception as e:
        logger.error(f"[Drip] Error programando reintento lead {lead_id}: {e}")


async def check_campaign_completion(campaign_id: int) -> bool:
    """Retorna True si no quedan leads en estado pendiente/calling."""
    try:
        res = await asyncio.to_thread(
            supabase.table("campaign_leads")
            .select("id")
            .eq("campaign_id", campaign_id)
            .in_("status", ["pending", "calling"])
            .limit(1)
            .execute
        )
        return len(res.data) == 0
    except Exception:
        return False


async def campaign_scheduler_loop() -> None:
    """
    Loop principal del motor de campañas (legacy in-process).
    Preferir campaign_scheduler_task en ARQ para producción.
    """
    POLL_INTERVAL = int(os.getenv("CAMPAIGN_POLL_INTERVAL_SECONDS", "30"))
    logger.info(f"🔄 [Scheduler] Motor Drip iniciado (poll cada {POLL_INTERVAL}s, cooldown {COOLDOWN_MIN}-{COOLDOWN_MAX}s)")

    while True:
        try:
            active_res = await asyncio.to_thread(
                supabase.table("campaigns")
                .select("*")
                .in_("status", ["active", "running"])
                .execute
            )
            campaigns = active_res.data or []

            if campaigns:
                logger.info(f"[Scheduler] {len(campaigns)} campañas activas.")

            now_iso = datetime.utcnow().isoformat()
            max_concurrent_calls = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))

            active_count = await get_active_call_count()
            if active_count >= max_concurrent_calls:
                logger.warning(f"Límite global de canales SIP alcanzado ({max_concurrent_calls}). Esperando...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for camp in campaigns:
                empresa_id = camp.get("empresa_id") or 0

                if await is_empresa_locked(empresa_id):
                    logger.debug(f"[Scheduler] Empresa {empresa_id} en llamada activa, skipping campaña {camp['id']}.")
                    continue

                try:
                    camp_id_local = camp["id"]
                    leads_res = await asyncio.to_thread(
                        supabase.table("campaign_leads")
                        .select("*")
                        .eq("campaign_id", camp_id_local)
                        .eq("status", "pending")
                        .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
                        .order("next_retry_at", desc=False, nullsfirst=True)
                        .limit(1)
                        .execute
                    )
                except Exception as fetch_err:
                    logger.error(f"[Scheduler] Error leyendo leads campaña {camp['id']}: {fetch_err}")
                    continue

                if not leads_res.data:
                    is_done = await check_campaign_completion(camp["id"])
                    if is_done:
                        try:
                            camp_id_done = camp["id"]
                            await asyncio.to_thread(
                                supabase.table("campaigns")
                                .update({"status": "completed"})
                                .eq("id", camp_id_done)
                                .execute
                            )
                            logger.info(f"✅ [Scheduler] Campaña {camp['id']} completada.")
                        except Exception as done_err:
                            logger.error(f"[Scheduler] Error marcando campaña {camp['id']} como completada: {done_err}")
                    continue

                lead = leads_res.data[0]
                lock_token = await acquire_empresa_lock(empresa_id)
                if not lock_token:
                    logger.debug(f"[Scheduler] Lock empresa {empresa_id} ya adquirido por otra instancia, skipping.")
                    continue

                asyncio.create_task(dispatch_single_lead_drip(lead, camp, lock_token=lock_token))

        except Exception as e:
            logger.error(f"❌ [Scheduler] Error en loop principal: {e}")

        await asyncio.sleep(POLL_INTERVAL)
