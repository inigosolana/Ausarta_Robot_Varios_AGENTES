"""
Utilidades compartidas para llamadas entrantes (inbound SIP).

No todos los agentes son encuestas numéricas: SOPORTE_CLIENTE, CUALIFICACION_LEAD, etc.
persisten datos de forma distinta pero comparten la tabla `encuestas` como registro de llamada.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

INBOUND_ENCUESTA_AGENT_TYPES = frozenset({
    "ENCUESTA_NUMERICA",
    "ENCUESTA_MIXTA",
    "PREGUNTAS_ABIERTAS",
})


def is_inbound_call(agent_config: dict | None) -> bool:
    if not agent_config:
        return False
    return str(agent_config.get("call_direction") or "").lower() == "inbound"


def parse_inbound_caller_from_room(room_name: str) -> str:
    if "__" in room_name:
        tail = room_name.split("__", 1)[1]
        caller = tail.split("_", 1)[0] if tail else ""
        if caller.isdigit():
            return caller
    for part in room_name.split("_"):
        if part.isdigit() and len(part) >= 9:
            return part
    return ""


def build_inbound_datos_extra(
    agent_config: dict,
    room_name: str,
    base: dict | None = None,
) -> dict:
    extra = dict(base or {})
    extra["call_direction"] = "inbound"
    extra.setdefault("empresa_id", agent_config.get("empresa_id"))
    extra.setdefault("agent_id", agent_config.get("id") or agent_config.get("agent_id"))
    extra.setdefault("agent_type", agent_config.get("agent_type"))
    extra.setdefault("telefono", parse_inbound_caller_from_room(room_name))
    extra.setdefault("room_name", room_name)
    return extra


def has_user_speech_in_transcript(transcript: str) -> bool:
    """True si hay indicios de interacción humana real (no solo saludo del agente)."""
    if not transcript:
        return False
    user_lines = 0
    for line in transcript.splitlines():
        stripped = line.strip().lower()
        if stripped.startswith(("usuario:", "user:", "cliente:")):
            content = line.split(":", 1)[-1].strip()
            if len(content) >= 2:
                user_lines += 1
    if user_lines >= 1:
        return True
    # Transcripción corta pero con contenido mixto (p. ej. buffer de eventos)
    return len(transcript.strip()) >= 40 and "agente:" in transcript.lower()


def normalize_inbound_disposition(
    disposition: str | None,
    transcript: str,
    data_saved: bool,
    agent_type: str,
) -> str:
    """
    Corrige disposiciones del LLM en inbound: con conversación real no puede ser no_contesta.
    """
    _ = agent_type  # reservado para reglas por tipo en el futuro
    if has_user_speech_in_transcript(transcript):
        if disposition in (None, "", "no_contesta"):
            return "completada" if data_saved else "parcial"
        return disposition
    if disposition in (None, ""):
        return "no_contesta"
    return disposition


def build_inbound_fallback_comentarios(
    disposition: str,
    datos_extra: dict | None,
    agent_type: str,
) -> str:
    extra = datos_extra or {}
    resumen = extra.get("resumen_narrativo")
    if isinstance(resumen, str) and resumen.strip():
        return resumen.strip()[:2000]

    puntos = extra.get("puntos_clave")
    if isinstance(puntos, list) and puntos:
        return "; ".join(str(p) for p in puntos[:5])[:2000]

    if agent_type == "SOPORTE_CLIENTE":
        motivo = extra.get("motivo_llamada") or extra.get("motivo")
        if motivo:
            return f"Soporte entrante ({disposition}): {motivo}"[:2000]
        return f"Llamada entrante de soporte — {disposition}"

    if agent_type in INBOUND_ENCUESTA_AGENT_TYPES:
        return f"Encuesta entrante — {disposition}"

    return f"Llamada entrante ({agent_type}) — {disposition}"


async def create_inbound_encuesta_record(
    *,
    empresa_id: int,
    agent_id: int | None,
    telefono: str,
    room_name: str,
    agent_type: str | None = None,
    status: str = "calling",
    datos_extra: dict | None = None,
) -> int:
    """Inserta fila en encuestas para una llamada entrante. Devuelve id o 0 si falla."""
    if not empresa_id:
        return 0

    from services.supabase_service import supabase, sb_query

    if not supabase:
        return 0

    tel = (telefono or "desconocido").strip() or "desconocido"
    merged_extra = {
        "call_direction": "inbound",
        "room_name": room_name,
        "agent_type": agent_type,
    }
    if isinstance(datos_extra, dict):
        merged_extra.update(datos_extra)

    insert_payload: dict[str, Any] = {
        "telefono": tel,
        "nombre_cliente": tel,
        "fecha": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "completada": 0,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "empresa_id": empresa_id,
        "campaign_id": None,
        "datos_extra": merged_extra,
    }

    try:
        res = await sb_query(
            lambda payload=insert_payload: supabase.table("encuestas").insert(payload).execute()
        )
        encuesta_id = int(res.data[0]["id"])
        logger.info(
            "📞 Inbound registrada encuesta=%s tel=%s room=%s type=%s",
            encuesta_id,
            tel,
            room_name,
            agent_type,
        )
        return encuesta_id
    except Exception as exc:
        logger.error("❌ No se pudo crear encuesta inbound: %s", exc)
        return 0


async def find_recent_inbound_encuesta(
    empresa_id: int,
    room_name: str,
    telefono: str,
) -> int:
    """Evita duplicar registro si la misma sala ya tiene encuesta reciente."""
    from services.supabase_service import supabase, sb_query

    if not supabase or not empresa_id:
        return 0

    try:
        res = await sb_query(
            lambda eid=empresa_id, tel=telefono: supabase.table("encuestas")
            .select("id, datos_extra, status, fecha")
            .eq("empresa_id", eid)
            .eq("telefono", tel)
            .is_("campaign_id", "null")
            .order("id", desc=True)
            .limit(5)
            .execute()
        )
        for row in res.data or []:
            extra = row.get("datos_extra") if isinstance(row.get("datos_extra"), dict) else {}
            if str(extra.get("room_name") or "") == room_name:
                return int(row["id"])
    except Exception as exc:
        logger.warning("find_recent_inbound_encuesta: %s", exc)
    return 0
