"""Detalle de campaña, métricas de leads y transcripciones."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from services.supabase_service import supabase

logger = logging.getLogger("api-backend")

_SURVEY_COLS = (
    "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, "
    "comentarios, transcription, datos_extra, tipo_resultados, fecha, llm_model"
)
_SURVEY_COLS_FALLBACK = (
    "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, "
    "comentarios, transcription, datos_extra, fecha, llm_model"
)


def _detect_question_based_agent(agent_id: int | None) -> bool:
    if not agent_id or not supabase:
        return False
    try:
        agent_res = supabase.table("agent_config").select("instructions").eq("id", agent_id).execute()
        if not agent_res.data:
            return False
        inst_lower = agent_res.data[0].get("instructions", "").lower()
        return "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower
    except Exception as err:
        logger.warning("No se pudo detectar tipo de agente para campaña: %s", err)
        return False


async def _fetch_surveys_map(call_ids: list[int]) -> dict[int, dict[str, Any]]:
    if not call_ids or not supabase:
        return {}
    try:
        res_surveys = await asyncio.to_thread(
            supabase.table("encuestas").select(_SURVEY_COLS).in_("id", call_ids).execute
        )
        return {row["id"]: row for row in (res_surveys.data or [])}
    except Exception as err:
        if "tipo_resultados" not in str(err):
            logger.error("Error fetching surveys for campaign: %s", err)
            return {}
        try:
            res_surveys = await asyncio.to_thread(
                supabase.table("encuestas").select(_SURVEY_COLS_FALLBACK).in_("id", call_ids).execute
            )
            logger.warning("encuestas.tipo_resultados no existe; usando select fallback sin esa columna.")
            return {row["id"]: row for row in (res_surveys.data or [])}
        except Exception as fallback_err:
            logger.error("Error fetching surveys for campaign (fallback): %s", fallback_err)
            return {}


def enrich_campaign_leads(
    leads: list[dict[str, Any]],
    surveys_map: dict[int, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, int]]:
    sum_com = 0.0
    sum_ins = 0.0
    sum_rap = 0.0
    count_com = 0
    count_ins = 0
    count_rap = 0
    status_counts: dict[str, int] = {}
    enriched_leads: list[dict[str, Any]] = []

    for lead in leads:
        status = lead.get("status") or "pending"
        status_counts[status] = status_counts.get(status, 0) + 1

        survey = surveys_map.get(lead.get("call_id"))
        lead["encuesta"] = survey
        if survey:
            lead["puntuacion_comercial"] = survey.get("puntuacion_comercial")
            lead["puntuacion_instalador"] = survey.get("puntuacion_instalador")
            lead["puntuacion_rapidez"] = survey.get("puntuacion_rapidez")
            lead["comentarios"] = survey.get("comentarios")
            lead["transcription_preview"] = survey.get("transcription")
            if survey.get("puntuacion_comercial") is not None:
                sum_com += float(survey["puntuacion_comercial"])
                count_com += 1
            if survey.get("puntuacion_instalador") is not None:
                sum_ins += float(survey["puntuacion_instalador"])
                count_ins += 1
            if survey.get("puntuacion_rapidez") is not None:
                sum_rap += float(survey["puntuacion_rapidez"])
                count_rap += 1
        enriched_leads.append(lead)

    metrics = {
        "avg_comercial": round(sum_com / count_com, 1) if count_com else 0.0,
        "avg_instalador": round(sum_ins / count_ins, 1) if count_ins else 0.0,
        "avg_rapidez": round(sum_rap / count_rap, 1) if count_rap else 0.0,
        "avg_overall": round((sum_com + sum_ins + sum_rap) / (count_com + count_ins + count_rap), 1)
        if (count_com + count_ins + count_rap)
        else 0.0,
    }
    return enriched_leads, metrics, status_counts


def apply_lead_status_summary(campaign: dict[str, Any], leads: list[dict[str, Any]], status_counts: dict[str, int]) -> None:
    total_leads = len(leads)
    pending = status_counts.get("pending", 0)
    calling = status_counts.get("calling", 0)
    completed = status_counts.get("completed", 0) + status_counts.get("completada", 0)
    failed = status_counts.get("failed", 0) + status_counts.get("fallida", 0)
    unreached = status_counts.get("unreached", 0) + status_counts.get("no_contesta", 0)
    incomplete = status_counts.get("incomplete", 0) + status_counts.get("parcial", 0)
    rejected = (
        status_counts.get("rejected_opt_out", 0)
        + status_counts.get("rechazada", 0)
        + status_counts.get("rejected", 0)
    )

    campaign["total_leads"] = total_leads
    campaign["called_leads"] = max(0, total_leads - pending - calling)
    campaign["failed_leads"] = failed + unreached + incomplete
    campaign["pending_leads"] = pending + calling
    campaign["completed_leads"] = completed
    campaign["rejected_leads"] = rejected


async def fetch_campaign_details(campaign_id: int) -> dict[str, Any] | None:
    if not supabase:
        return None

    res_camp, res_leads = await asyncio.gather(
        asyncio.to_thread(supabase.table("campaigns").select("*").eq("id", campaign_id).execute),
        asyncio.to_thread(supabase.table("campaign_leads").select("*").eq("campaign_id", campaign_id).execute),
    )
    if not res_camp.data:
        return None

    campaign = res_camp.data[0]
    leads = res_leads.data or []
    campaign["is_question_based"] = _detect_question_based_agent(campaign.get("agent_id"))

    call_ids = [lead["call_id"] for lead in leads if lead.get("call_id")]
    surveys_map = await _fetch_surveys_map(call_ids)
    enriched_leads, metrics, status_counts = enrich_campaign_leads(leads, surveys_map)
    apply_lead_status_summary(campaign, leads, status_counts)

    return {"campaign": campaign, "metrics": metrics, "leads": enriched_leads}


def fetch_result_transcription(result_id: int) -> tuple[str | None, int | None]:
    if not supabase:
        return None, None
    res = supabase.table("encuestas").select("transcription, empresa_id").eq("id", result_id).limit(1).execute()
    if not res.data:
        return None, None
    row = res.data[0]
    return row.get("transcription"), row.get("empresa_id")
