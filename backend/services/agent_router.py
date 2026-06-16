"""Resuelve qué agente usar en llamadas outbound y construye metadata de sala LiveKit."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

ALLOWED_AGENT_TYPES = frozenset(
    {
        "ENCUESTA_NUMERICA",
        "ENCUESTA_MIXTA",
        "PREGUNTAS_ABIERTAS",
        "CUALIFICACION_LEAD",
        "AGENDAMIENTO_CITA",
        "SOPORTE_CLIENTE",
    }
)

CALL_PURPOSE_ALIASES: dict[str, str] = {
    "encuesta": "ENCUESTA_NUMERICA",
    "survey": "ENCUESTA_NUMERICA",
    "numeric": "ENCUESTA_NUMERICA",
    "mixed": "ENCUESTA_MIXTA",
    "mixta": "ENCUESTA_MIXTA",
    "open": "PREGUNTAS_ABIERTAS",
    "abierta": "PREGUNTAS_ABIERTAS",
    "preguntas_abiertas": "PREGUNTAS_ABIERTAS",
    "venta": "CUALIFICACION_LEAD",
    "ventas": "CUALIFICACION_LEAD",
    "lead": "CUALIFICACION_LEAD",
    "comercial": "CUALIFICACION_LEAD",
    "sales": "CUALIFICACION_LEAD",
    "cualificacion": "CUALIFICACION_LEAD",
    "cita": "AGENDAMIENTO_CITA",
    "agenda": "AGENDAMIENTO_CITA",
    "agendamiento": "AGENDAMIENTO_CITA",
    "appointment": "AGENDAMIENTO_CITA",
    "soporte": "SOPORTE_CLIENTE",
    "support": "SOPORTE_CLIENTE",
    "atencion": "SOPORTE_CLIENTE",
    "inbound": "SOPORTE_CLIENTE",
}


def normalize_call_purpose(purpose: str | None) -> str | None:
    if not purpose:
        return None
    key = purpose.strip().lower().replace("-", "_").replace(" ", "_")
    upper = key.upper()
    if upper in ALLOWED_AGENT_TYPES:
        return upper
    return CALL_PURPOSE_ALIASES.get(key)


def _resolve_agent_type(agent_row: dict) -> str:
    return (
        agent_row.get("agent_type")
        or agent_row.get("tipo_resultados")
        or "ENCUESTA_NUMERICA"
    )


def _fetch_agent_by_id(agent_id: int | str, empresa_id: int | None) -> dict | None:
    if not supabase:
        return None
    res = (
        supabase.table("agent_config")
        .select("id,empresa_id,name,agent_type,tipo_resultados,voice_id")
        .eq("id", agent_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    if empresa_id and row.get("empresa_id") and int(row["empresa_id"]) != int(empresa_id):
        logger.warning(
            "🤖 [agent_router] agente %s no pertenece a empresa %s",
            agent_id,
            empresa_id,
        )
        return None
    return row


def _fetch_agent_by_type(empresa_id: int, agent_type: str) -> dict | None:
    if not supabase:
        return None
    for col in ("agent_type", "tipo_resultados"):
        res = (
            supabase.table("agent_config")
            .select("id,empresa_id,name,agent_type,tipo_resultados,voice_id")
            .eq("empresa_id", empresa_id)
            .eq(col, agent_type)
            .order("updated_at", desc=True)
            .limit(1)
            .execute()
        )
        if res.data:
            return res.data[0]
    return None


def _fetch_default_agent(empresa_id: int) -> dict | None:
    if not supabase:
        return None
    res = (
        supabase.table("agent_config")
        .select("id,empresa_id,name,agent_type,tipo_resultados,voice_id")
        .eq("empresa_id", empresa_id)
        .order("updated_at", desc=True)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


def resolve_outbound_agent_sync(
    *,
    empresa_id: int | None,
    agent_id: int | str | None = None,
    agent_type: str | None = None,
    call_purpose: str | None = None,
    campaign_agent_id: int | str | None = None,
) -> dict[str, Any]:
    """Devuelve agent_id, agent_type, agent_name y voice_id con fallbacks seguros."""
    eid = int(empresa_id) if empresa_id else None
    row: dict | None = None

    for candidate in (agent_id, campaign_agent_id):
        if candidate:
            row = _fetch_agent_by_id(candidate, eid)
            if row:
                break

    if not row:
        at = normalize_call_purpose(agent_type) or normalize_call_purpose(call_purpose)
        if at and eid:
            row = _fetch_agent_by_type(eid, at)

    if not row and eid:
        row = _fetch_default_agent(eid)

    if row:
        return {
            "agent_id": int(row["id"]),
            "agent_type": _resolve_agent_type(row),
            "agent_name": row.get("name") or "Bot",
            "voice_id": row.get("voice_id"),
        }

    fallback_id = int(agent_id or campaign_agent_id or 1)
    fallback_type = (
        normalize_call_purpose(agent_type)
        or normalize_call_purpose(call_purpose)
        or "ENCUESTA_NUMERICA"
    )
    logger.warning(
        "🤖 [agent_router] Sin agente en BD; fallback agent_id=%s tipo=%s",
        fallback_id,
        fallback_type,
    )
    return {
        "agent_id": fallback_id,
        "agent_type": fallback_type,
        "agent_name": "Bot",
        "voice_id": None,
    }


async def resolve_outbound_agent(
    *,
    empresa_id: int | None,
    agent_id: int | str | None = None,
    agent_type: str | None = None,
    call_purpose: str | None = None,
    campaign_agent_id: int | str | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(
                resolve_outbound_agent_sync,
                empresa_id=empresa_id,
                agent_id=agent_id,
                agent_type=agent_type,
                call_purpose=call_purpose,
                campaign_agent_id=campaign_agent_id,
            ),
            timeout=5,
        )
    except Exception as exc:
        logger.warning("🤖 [agent_router] Error resolviendo agente: %s", exc)
        return {
            "agent_id": int(agent_id or campaign_agent_id or 1),
            "agent_type": "ENCUESTA_NUMERICA",
            "agent_name": "Bot",
            "voice_id": None,
        }


def build_outbound_room_metadata(
    *,
    empresa_id: int,
    survey_id: int,
    agent_id: int,
    agent_type: str,
    campaign_id: int = 0,
    contacto_id: int = 0,
    lead_id: int | None = None,
    extra: dict | None = None,
) -> dict[str, Any]:
    cid = int(contacto_id or lead_id or 0)
    meta: dict[str, Any] = {
        "call_direction": "outbound",
        "empresa_id": int(empresa_id or 0),
        "campaign_id": int(campaign_id or 0),
        "campana_id": int(campaign_id or 0),
        "contacto_id": cid,
        "client_id": cid,
        "lead_id": cid,
        "survey_id": int(survey_id),
        "agent_id": int(agent_id),
        "agent_type": agent_type,
    }
    if extra:
        meta.update(extra)
    return meta
