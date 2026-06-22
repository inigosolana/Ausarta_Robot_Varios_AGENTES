"""
Programación de seguimientos desde nodos `schedule` del workflow de voz.
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from services.supabase_service import supabase

logger = logging.getLogger("agent-dynamic")

_TEMPLATE_RE = re.compile(r"\{\{(\w+)\}\}")


def resolve_workflow_template(value: str, variables: dict[str, Any], context: dict[str, Any]) -> str:
    """Sustituye placeholders {{var}} por variables del workflow o contexto de llamada."""

    def _repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in variables and variables[key] is not None:
            return str(variables[key])
        if key in context and context[key] is not None:
            return str(context[key])
        return match.group(0)

    return _TEMPLATE_RE.sub(_repl, value or "")


def _parse_campaign_id(raw: str | int | None) -> int | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.startswith("{{"):
        return None
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


async def schedule_workflow_follow_up(
    *,
    survey_id: int,
    empresa_id: int,
    campaign_id_ref: str,
    lead_id: int | None,
    delay_days: int,
    workflow_variables: dict[str, Any] | None = None,
    call_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Programa un lead de campaña para reintento/segumiento en `delay_days` días.

    Actualiza un lead existente (contacto_id) o crea uno nuevo a partir de la encuesta.
    """
    if not supabase:
        return {"ok": False, "error": "supabase_unavailable"}

    delay_days = max(1, int(delay_days or 1))
    variables = workflow_variables or {}
    context = dict(call_context or {})
    retry_at = (datetime.now(timezone.utc) + timedelta(days=delay_days)).isoformat()

    resolved_ref = resolve_workflow_template(campaign_id_ref or "{{campaign_id}}", variables, context)
    campaign_id = _parse_campaign_id(resolved_ref) or _parse_campaign_id(context.get("campaign_id"))

    encuesta_row: dict[str, Any] | None = None
    if survey_id:
        try:
            enc_res = await asyncio.to_thread(
                supabase.table("encuestas")
                .select("id, telefono, nombre_cliente, empresa_id, campaign_id")
                .eq("id", survey_id)
                .limit(1)
                .execute
            )
            encuesta_row = enc_res.data[0] if enc_res.data else None
        except Exception as exc:
            logger.warning("[workflow_schedule] Error leyendo encuesta %s: %s", survey_id, exc)

    if not campaign_id and encuesta_row:
        campaign_id = _parse_campaign_id(encuesta_row.get("campaign_id"))

    if not empresa_id and encuesta_row:
        empresa_id = int(encuesta_row.get("empresa_id") or 0)

    phone = (encuesta_row or {}).get("telefono") or ""
    customer_name = (encuesta_row or {}).get("nombre_cliente") or "Cliente"

    if not campaign_id:
        return {"ok": False, "error": "campaign_id_unresolved", "retry_at": retry_at}

    lead_update = {
        "status": "pending",
        "next_retry_at": retry_at,
        "error_msg": None,
    }

    try:
        if lead_id:
            await asyncio.to_thread(
                supabase.table("campaign_leads").update(lead_update).eq("id", lead_id).execute
            )
            target_lead_id = lead_id
        elif phone:
            existing = await asyncio.to_thread(
                supabase.table("campaign_leads")
                .select("id")
                .eq("campaign_id", campaign_id)
                .eq("phone_number", phone)
                .limit(1)
                .execute
            )
            if existing.data:
                target_lead_id = existing.data[0]["id"]
                await asyncio.to_thread(
                    supabase.table("campaign_leads").update(lead_update).eq("id", target_lead_id).execute
                )
            else:
                ins = await asyncio.to_thread(
                    supabase.table("campaign_leads").insert({
                        "campaign_id": campaign_id,
                        "phone_number": phone,
                        "customer_name": customer_name,
                        "status": "pending",
                        "retries_attempted": 0,
                        "next_retry_at": retry_at,
                        "call_id": survey_id or None,
                    }).execute
                )
                target_lead_id = ins.data[0]["id"] if ins.data else None
        else:
            return {"ok": False, "error": "missing_phone", "campaign_id": campaign_id}

        await asyncio.to_thread(
            supabase.table("campaigns").update({"status": "active"}).eq("id", campaign_id).execute
        )

        try:
            from services.campaign_locks import enqueue_scheduler_tick

            await enqueue_scheduler_tick()
        except Exception as tick_exc:
            logger.debug("[workflow_schedule] enqueue_scheduler_tick: %s", tick_exc)

        logger.info(
            "[workflow_schedule] Seguimiento programado lead=%s camp=%s en %s días (%s)",
            target_lead_id,
            campaign_id,
            delay_days,
            retry_at,
        )
        return {
            "ok": True,
            "lead_id": target_lead_id,
            "campaign_id": campaign_id,
            "retry_at": retry_at,
            "delay_days": delay_days,
        }
    except Exception as exc:
        logger.error("[workflow_schedule] Error programando seguimiento: %s", exc)
        return {"ok": False, "error": str(exc), "campaign_id": campaign_id}
