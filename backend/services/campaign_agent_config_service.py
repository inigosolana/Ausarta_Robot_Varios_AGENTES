"""Resolución de configuración de agente para llamadas outbound/inbound."""
from __future__ import annotations

import logging
from typing import Any

from config import get_settings
from routers.campaign_access import load_external_db_allowed_queries
from services.supabase_service import supabase
from utils.kb_settings import load_empresa_kb_settings

logger = logging.getLogger("api-backend")
DEFAULT_AUSARTA_VOICE_ID = get_settings().default_cartesia_voice


def _default_survey_agent_payload(empresa_id: int | None) -> dict[str, Any]:
    return {
        "name": "Bot",
        "greeting": "Buenas, le llamo...",
        "instructions": "Eres un asistente.",
        "voice_id": DEFAULT_AUSARTA_VOICE_ID,
        "llm_model": "llama-3.3-70b-versatile",
        "company_context": "",
        "enthusiasm_level": "Normal",
        "speaking_speed": 1.0,
        "empresa_id": empresa_id,
    }


def _load_extraction_schema(campaign_id: int | None) -> list:
    if not campaign_id or not supabase:
        return []
    try:
        camp_res = (
            supabase.table("campaigns")
            .select("extraction_schema")
            .eq("id", campaign_id)
            .limit(1)
            .execute()
        )
        if camp_res.data and camp_res.data[0].get("extraction_schema"):
            return camp_res.data[0]["extraction_schema"]
    except Exception as schema_err:
        logger.warning("No se pudo cargar extraction_schema de campaña %s: %s", campaign_id, schema_err)
    return []


def _build_agent_payload(
    *,
    agent_data: dict[str, Any],
    ai_data: dict[str, Any],
    empresa_id: int | None,
    nombre_cliente: str | None = None,
    extraction_schema: list | None = None,
    call_direction: str | None = None,
    default_agent_type: str = "ENCUESTA_NUMERICA",
) -> dict[str, Any]:
    empresa_kb = load_empresa_kb_settings(empresa_id, supabase_client=supabase)
    empresa_context = empresa_kb["company_context"]
    greeting_default = (
        "Buenas, ¿tiene un momento?"
        if call_direction != "inbound"
        else "Hola, has llamado a Ausarta."
    )
    greeting = agent_data.get("greeting", greeting_default)
    if nombre_cliente is not None:
        greeting = greeting.replace("{nombre}", nombre_cliente or "Cliente")

    resolved_agent_type = (
        agent_data.get("agent_type")
        or agent_data.get("tipo_resultados")
        or default_agent_type
    )

    payload: dict[str, Any] = {
        "name": agent_data.get("name", "Bot"),
        "greeting": greeting,
        "instructions": agent_data.get("instructions", "Eres un asistente"),
        "critical_rules": agent_data.get("critical_rules", ""),
        "voice_id": agent_data.get("voice_id") or ai_data.get("tts_voice") or DEFAULT_AUSARTA_VOICE_ID,
        "tts_model": ai_data.get("tts_model") or get_settings().default_tts_model,
        "llm_model": ai_data.get("llm_model") or "llama-3.3-70b-versatile",
        "language": ai_data.get("language") or "es",
        "stt_provider": ai_data.get("stt_provider") or "deepgram",
        "stt_model": ai_data.get("stt_model") or get_settings().default_stt_model,
        "extraction_schema": extraction_schema or [],
        "company_context": agent_data.get("company_context") or empresa_context or "",
        "kb_allow_internet_search": agent_data.get("kb_allow_internet_search"),
        "empresa_kb_allow_internet_search": empresa_kb["kb_allow_internet_search"],
        "enthusiasm_level": agent_data.get("enthusiasm_level") or "Normal",
        "speaking_speed": agent_data.get("speaking_speed") or 1.0,
        "agent_type": resolved_agent_type,
        "tipo_resultados": agent_data.get("tipo_resultados") or resolved_agent_type,
        "empresa_id": empresa_id or agent_data.get("empresa_id"),
        "agent_id": agent_data.get("id"),
        "config_updated_at": agent_data.get("updated_at") or ai_data.get("updated_at"),
        "agent_mode": agent_data.get("agent_mode") or "prompt",
        "workflow_definition": agent_data.get("workflow_definition"),
        "workflow_variables": agent_data.get("workflow_variables") or {},
        "external_db_allowed_queries": load_external_db_allowed_queries(
            empresa_id or agent_data.get("empresa_id")
        ),
    }
    if call_direction:
        payload["call_direction"] = call_direction
    return payload


def resolve_agent_config_by_survey(survey_id: int) -> dict[str, Any]:
    if not supabase:
        raise RuntimeError("Supabase not connected")

    res_survey = (
        supabase.table("encuestas")
        .select("agent_id, nombre_cliente, empresa_id, campaign_id")
        .eq("id", survey_id)
        .execute()
    )
    if not res_survey.data:
        raise LookupError("Survey not found")

    row = res_survey.data[0]
    agent_id = row.get("agent_id")
    nombre_cliente = row.get("nombre_cliente")
    empresa_id = row.get("empresa_id")
    campaign_id = row.get("campaign_id")

    if not agent_id:
        return _default_survey_agent_payload(empresa_id)

    res_agent = supabase.table("agent_config").select("*").eq("id", agent_id).execute()
    if not res_agent.data:
        raise LookupError("Agent not found")

    agent_data = res_agent.data[0]
    res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
    ai_data = res_ai.data[0] if res_ai.data else {}

    return _build_agent_payload(
        agent_data=agent_data,
        ai_data=ai_data,
        empresa_id=empresa_id or agent_data.get("empresa_id"),
        nombre_cliente=nombre_cliente,
        extraction_schema=_load_extraction_schema(campaign_id),
    )


def resolve_agent_config_by_agent(agent_id: int, empresa_id: int | None = None) -> dict[str, Any]:
    if not supabase:
        raise RuntimeError("Supabase not connected")

    query = supabase.table("agent_config").select("*").eq("id", agent_id).limit(1)
    if empresa_id:
        query = query.eq("empresa_id", empresa_id)
    res_agent = query.execute()
    if not res_agent.data:
        raise LookupError("Agent not found")

    agent_data = res_agent.data[0]
    res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
    ai_data = res_ai.data[0] if res_ai.data else {}

    return _build_agent_payload(
        agent_data=agent_data,
        ai_data=ai_data,
        empresa_id=agent_data.get("empresa_id"),
        call_direction="inbound",
        default_agent_type="SOPORTE_CLIENTE",
    )
