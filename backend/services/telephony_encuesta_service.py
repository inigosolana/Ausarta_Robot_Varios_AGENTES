"""Persistencia de encuestas y propagación de estado post-llamada."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import BackgroundTasks
from fastapi.responses import JSONResponse

from models.schemas import EncuestaData
from services.call_results_service import (
    build_encuesta_results_update,
    prepare_narrative_text_for_storage,
    prepare_transcription_for_storage,
)
from services.supabase_service import sb_query, supabase
from services.telephony_lead_propagation import propagate_to_lead
from services.telephony_post_call_service import notify_n8n_post_call
from utils.inbound_call import create_inbound_encuesta_record, find_recent_inbound_encuesta

logger = logging.getLogger("api-backend")

STATUS_MAP = {
    "completed": "completed",
    "failed": "failed",
    "incomplete": "incomplete",
    "unreached": "unreached",
    "rejected_opt_out": "rejected_opt_out",
    "rejected": "rejected_opt_out",
    "calling": "calling",
    "pending": "pending",
    "called": "called",
    "completada": "completed",
    "fallida": "failed",
    "parcial": "incomplete",
    "no_contesta": "failed",
    "rechazada": "rejected_opt_out",
    "busy": "failed",
    "ocupado": "failed",
    "voicemail": "failed",
    "buzon": "failed",
    "buzón": "failed",
}

PROPAGABLE_STATUSES = {"completed", "rejected_opt_out", "incomplete", "failed", "unreached"}


async def resolve_or_create_inbound_encuesta_id(datos: EncuestaData) -> int:
    """Crea fila en encuestas para llamadas entrantes cuando aún no hay id numérico."""
    if datos.id_encuesta > 0:
        return datos.id_encuesta

    extra = datos.datos_extra if isinstance(datos.datos_extra, dict) else {}
    if str(extra.get("call_direction") or "").lower() != "inbound":
        return datos.id_encuesta

    empresa_id = int(extra.get("empresa_id") or 0)
    agent_id = extra.get("agent_id")
    telefono = str(extra.get("telefono") or extra.get("caller") or "desconocido").strip()
    room_name = str(extra.get("room_name") or "").strip()
    agent_type = extra.get("agent_type")

    existing = await find_recent_inbound_encuesta(empresa_id, room_name, telefono)
    if existing:
        return existing

    status = datos.status or "in_progress"
    encuesta_id = await create_inbound_encuesta_record(
        empresa_id=empresa_id,
        agent_id=int(agent_id) if agent_id is not None else None,
        telefono=telefono,
        room_name=room_name,
        agent_type=str(agent_type) if agent_type else None,
        status=status,
        datos_extra=extra,
    )
    if encuesta_id:
        logger.info(
            "📞 [guardar-encuesta] Llamada inbound registrada como encuesta %s (tel=%s, room=%s)",
            encuesta_id,
            telefono,
            room_name,
        )
    return encuesta_id


async def guardar_encuesta(datos: EncuestaData, background_tasks: BackgroundTasks):
    if not supabase:
        return {"status": "error", "message": "No DB connection"}

    datos.id_encuesta = await resolve_or_create_inbound_encuesta_id(datos)

    logger.info("📥 [guardar-encuesta] encuesta=%s: %s", datos.id_encuesta, datos.dict(exclude_none=True))

    update_data: dict[str, Any] = {}
    if datos.transcription is not None:
        update_data["transcription"] = prepare_transcription_for_storage(datos.transcription)
    if datos.seconds_used is not None:
        update_data["seconds_used"] = datos.seconds_used
    if datos.llm_model is not None:
        update_data["llm_model"] = datos.llm_model
    if datos.datos_extra is not None:
        update_data["datos_extra"] = datos.datos_extra

    if isinstance(datos.datos_extra, dict):
        resumen = datos.datos_extra.get("resumen_narrativo")
        if resumen and isinstance(resumen, str) and resumen.strip():
            update_data["resumen_llamada"] = (
                prepare_narrative_text_for_storage(resumen.strip()[:2000]) or ""
            )

    curr = await sb_query(
        lambda: supabase.table("encuestas")
        .select("status, empresa_id, telefono, agent_type, agent_results")
        .eq("id", datos.id_encuesta)
        .execute()
    )
    curr_data = curr.data[0] if curr.data else {}

    resolved_agent_type = (
        curr_data.get("agent_type")
        or (
            (datos.datos_extra or {}).get("agent_type")
            if isinstance(datos.datos_extra, dict)
            else None
        )
    )
    results_update = build_encuesta_results_update(
        agent_type=resolved_agent_type,
        existing_agent_results=curr_data.get("agent_results"),
        nota_comercial=datos.nota_comercial,
        nota_instalador=datos.nota_instalador,
        nota_rapidez=datos.nota_rapidez,
        comentarios=datos.comentarios,
        datos_extra=datos.datos_extra if isinstance(datos.datos_extra, dict) else None,
        agent_results_patch=getattr(datos, "agent_results", None),
    )
    update_data.update(results_update)

    normalized_status = STATUS_MAP.get((datos.status or "").strip().lower()) if datos.status else None

    if not update_data and not normalized_status:
        return {"status": "ignored", "message": "No data to update"}

    if normalized_status:
        update_data["status"] = normalized_status
        if normalized_status == "completed":
            update_data["completada"] = 1

    logger.info("📝 [guardar-encuesta] UPDATE encuesta %s: %s", datos.id_encuesta, update_data)
    try:
        await sb_query(
            lambda: supabase.table("encuestas").update(update_data).eq("id", datos.id_encuesta).execute()
        )
        logger.info("✅ [guardar-encuesta] Encuesta %s actualizada", datos.id_encuesta)
    except Exception as exc:
        logger.error("❌ [guardar-encuesta] Error DB: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})

    if normalized_status in PROPAGABLE_STATUSES:
        background_tasks.add_task(
            propagate_to_lead,
            datos.id_encuesta,
            normalized_status,
            curr_data,
        )

    if normalized_status in ("completed", "rejected_opt_out", "failed") and curr_data.get("empresa_id"):
        result_data = {
            "nota_comercial": datos.nota_comercial,
            "nota_instalador": datos.nota_instalador,
            "nota_rapidez": datos.nota_rapidez,
            "comentarios": prepare_narrative_text_for_storage(datos.comentarios),
            "transcription": update_data.get("transcription", datos.transcription),
            "seconds_used": datos.seconds_used,
            "llm_model": datos.llm_model,
            "datos_extra": datos.datos_extra,
        }
        background_tasks.add_task(
            notify_n8n_post_call,
            datos.id_encuesta,
            normalized_status,
            result_data,
            curr_data["empresa_id"],
            curr_data.get("telefono", ""),
        )

    return {"status": "ok", "updated": update_data}
