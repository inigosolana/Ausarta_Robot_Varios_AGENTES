"""Notificaciones post-llamada a webhooks de automatización y CRM."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")


async def notify_n8n_post_call(
    encuesta_id: int,
    status: str,
    result_data: dict,
    empresa_id: int,
    telefono: str,
) -> None:
    """
    Envía los datos post-llamada a:
      1. webhook_url  (Zapier / Make — payload limpio y aplanado)
      2. crm_webhook_url  (CRM específico — HubSpot / Salesforce / n8n)
    """
    try:
        emp_res = await sb_query(
            lambda: supabase.table("empresas")
            .select("crm_webhook_url, crm_type, webhook_url")
            .eq("id", empresa_id)
            .execute()
        )
        emp_cfg = emp_res.data[0] if emp_res.data else {}
    except Exception as exc:
        logger.warning("⚠️ No se pudo leer config de empresa %s: %s", empresa_id, exc)
        emp_cfg = {}

    datos_extra: dict = result_data.get("datos_extra") or {}

    automation_url = emp_cfg.get("webhook_url")
    if automation_url:
        try:
            automation_payload = {
                "event": (
                    "call.completed"
                    if status == "completed"
                    else ("call.rejected" if status == "rejected_opt_out" else "call.failed")
                ),
                "call_id": encuesta_id,
                "phone": telefono,
                "status": status,
                "date": datetime.now(timezone.utc).isoformat(),
                "campaign_name": result_data.get("campaign_name"),
                "transcription": result_data.get("transcription"),
                "seconds_used": result_data.get("seconds_used"),
                "datos_extra": datos_extra,
                **{k: v for k, v in datos_extra.items()},
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    automation_url,
                    json=automation_payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    logger.info("📡 Automation Webhook [%s] → %s (%s)", status, automation_url, resp.status)
        except Exception as exc:
            logger.warning("⚠️ Error en Automation Webhook: %s", exc)

    if emp_cfg.get("crm_webhook_url"):
        try:
            crm_payload = {
                "event": (
                    "call_completed"
                    if status == "completed"
                    else ("call_rejected" if status == "rejected_opt_out" else "call_failed")
                ),
                "encuesta_id": encuesta_id,
                "empresa_id": empresa_id,
                "status": status,
                "lead": {"phone": telefono},
                "results": result_data,
                "crm_type": emp_cfg.get("crm_type", "custom"),
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    emp_cfg["crm_webhook_url"],
                    json=crm_payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    logger.info(
                        "📡 CRM Webhook [%s] → %s (%s)",
                        status,
                        emp_cfg["crm_webhook_url"],
                        resp.status,
                    )
        except Exception as exc:
            logger.warning("⚠️ Error en CRM Webhook: %s", exc)
