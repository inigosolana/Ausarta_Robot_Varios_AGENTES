"""Propagación de estado de encuesta a campaign_leads."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")


async def propagate_to_lead(encuesta_id: int, final_status: str, enc_curr_data: dict) -> None:
    if encuesta_id <= 0:
        logger.info("⏭️ Skip propagate lead: encuesta_id inválido (%s)", encuesta_id)
        return

    extra = enc_curr_data.get("datos_extra") or {}
    if isinstance(extra, dict) and str(extra.get("call_direction") or "").lower() == "inbound":
        logger.info("⏭️ Skip propagate lead: llamada inbound encuesta %s", encuesta_id)
        return

    try:
        enc_row = await sb_query(
            lambda eid=encuesta_id: supabase.table("encuestas")
            .select("campaign_id")
            .eq("id", eid)
            .limit(1)
            .execute()
        )
        if not enc_row.data or not enc_row.data[0].get("campaign_id"):
            logger.info("⏭️ Skip propagate lead: encuesta %s sin campaña", encuesta_id)
            return
    except Exception as exc:
        logger.warning("No se pudo verificar campaña de encuesta %s: %s", encuesta_id, exc)
        return

    lead_update: dict = {"status": final_status}

    if final_status == "rejected_opt_out":
        lead_update["no_reintentar"] = True
    elif final_status in ("incomplete", "failed", "unreached"):
        retry_seconds = 3600
        max_retries = 3
        current_retries = 0
        try:
            lead_res = await sb_query(
                lambda: supabase.table("campaign_leads")
                .select("campaign_id, retries_attempted")
                .eq("call_id", encuesta_id)
                .limit(1)
                .execute()
            )
            if lead_res.data:
                current_retries = lead_res.data[0].get("retries_attempted", 0) or 0
                camp_id = lead_res.data[0]["campaign_id"]
                camp_res = await sb_query(
                    lambda: supabase.table("campaigns")
                    .select("retry_interval, retries_count")
                    .eq("id", camp_id)
                    .limit(1)
                    .execute()
                )
                if camp_res.data:
                    ri = camp_res.data[0].get("retry_interval")
                    max_retries = camp_res.data[0].get("retries_count", 3) or 3
                    if ri and ri > 0:
                        retry_seconds = ri
        except Exception as exc:
            logger.error("Error leyendo config de reintentos para encuesta %s: %s", encuesta_id, exc)

        new_retries = current_retries + 1
        lead_update["retries_attempted"] = new_retries
        if new_retries < max_retries:
            lead_update["status"] = "pending"
            next_retry = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
            lead_update["next_retry_at"] = next_retry
            logger.info(
                "🔄 Reintento %s/%s programado para encuesta %s → %s",
                new_retries,
                max_retries,
                encuesta_id,
                next_retry,
            )
        else:
            logger.info(
                "🚫 Máx. reintentos alcanzado (%s/%s) para encuesta %s",
                new_retries,
                max_retries,
                encuesta_id,
            )

    try:
        result = await sb_query(
            lambda: supabase.table("campaign_leads").update(lead_update).eq("call_id", encuesta_id).execute()
        )
        rows = len(result.data) if result.data else 0
        logger.info("📊 Lead actualizado (call_id=%s): %s filas | %s", encuesta_id, rows, lead_update)

        if rows == 0 and enc_curr_data.get("telefono"):
            logger.warning("⚠️ Fallback por teléfono para encuesta %s", encuesta_id)
            enc_full = await sb_query(
                lambda: supabase.table("encuestas")
                .select("campaign_id, telefono")
                .eq("id", encuesta_id)
                .execute()
            )
            if enc_full.data and enc_full.data[0].get("campaign_id"):
                camp_id = enc_full.data[0]["campaign_id"]
                tel = enc_full.data[0].get("telefono", "")
                await sb_query(
                    lambda: supabase.table("campaign_leads")
                    .update({**lead_update, "call_id": encuesta_id})
                    .eq("campaign_id", camp_id)
                    .eq("phone_number", tel)
                    .execute()
                )
    except Exception as exc:
        logger.error("❌ Error propagando lead para encuesta %s: %s", encuesta_id, exc)
