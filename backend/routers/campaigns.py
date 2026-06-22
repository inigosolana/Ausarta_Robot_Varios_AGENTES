"""
Motor de Campañas — Goteo Controlado (Drip) Multitenant.

Arquitectura:
- Un único scheduler loop corre como background task en el arranque de la app.
- GOTEO ESTRICTO: nunca se lanza más de una llamada simultánea por empresa.
  El sistema mantiene un 'drip lock' por empresa_id. Mientras una empresa
  tiene una llamada activa (incluyendo el cooldown post-llamada), sus otros
  leads esperan al siguiente ciclo del scheduler.
- Diferentes empresas sí procesan sus leads de forma independiente y concurrente.
- El estado de las llamadas se actualiza vía webhook de LiveKit (/api/livekit/webhook).
- Salas con naming aislado: empresa_{id}_camp_{camp_id}_call_{enc_id}.
"""
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from typing import Optional, List
from services.supabase_service import supabase
from services.audit import log_audit_event
from services.auth import CurrentUser, get_current_user, require_admin
from services.livekit_service import lkapi, create_isolated_room, dispatch_agent_explicit
from services.trunk_service import resolve_outbound_trunk_id
from services.agent_router import build_outbound_room_metadata
from services.campaign_dispatch_service import resolve_campaign_dispatch_agent
from services.sip_call_service import create_sip_participant_with_retry, mark_call_failed, sip_retry_max_attempts
from services.webhook_auth import require_campaign_webhook_auth
from livekit import api as lk_api
from pydantic import BaseModel
from models.schemas import CampaignModel, CampaignLeadModel
from datetime import datetime, timezone, timedelta
import asyncio
import random
import os
import logging
from config import settings

logger = logging.getLogger("api-backend")
DEFAULT_AUSARTA_VOICE_ID = settings.default_cartesia_voice

router = APIRouter(prefix="/api", tags=["campaigns"])


def _load_empresa_kb_settings(empresa_id: int | None) -> dict:
    """Contexto de empresa y flag de búsqueda en internet."""
    if not empresa_id or not supabase:
        return {"company_context": "", "kb_allow_internet_search": False}
    try:
        res = (
            supabase.table("empresas")
            .select("company_context, kb_allow_internet_search")
            .eq("id", empresa_id)
            .limit(1)
            .execute()
        )
        if not res.data:
            return {"company_context": "", "kb_allow_internet_search": False}
        row = res.data[0]
        return {
            "company_context": row.get("company_context") or "",
            "kb_allow_internet_search": bool(row.get("kb_allow_internet_search")),
        }
    except Exception as exc:
        logger.warning("No se pudo cargar KB settings empresa %s: %s", empresa_id, exc)
        return {"company_context": "", "kb_allow_internet_search": False}


def _resolve_empresa(user: CurrentUser, empresa_id_param: int | None = None) -> int | None:
    if user.role == "superadmin" and empresa_id_param:
        return empresa_id_param
    return int(user.empresa_id or 0) if user.empresa_id else None


def _raise_not_found_if_cross_tenant(user: CurrentUser, empresa_id: int | None) -> None:
    if user.role != "superadmin" and int(empresa_id or 0) != int(user.empresa_id or 0):
        raise HTTPException(status_code=404, detail="Not found")


def _load_campaign_or_404(campaign_id: int, user: CurrentUser) -> dict:
    res = supabase.table("campaigns").select("*").eq("id", campaign_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = res.data[0]
    _raise_not_found_if_cross_tenant(user, campaign.get("empresa_id"))
    return campaign


def _load_external_db_allowed_queries(empresa_id: int | None) -> list[str]:
    """Lista blanca de queries CRM/ERP permitidos para consultar_cliente."""
    if not empresa_id or not supabase:
        return []
    try:
        res = (
            supabase.table("empresa_external_db")
            .select("queries")
            .eq("empresa_id", empresa_id)
            .eq("activo", True)
            .limit(1)
            .execute()
        )
        if not res.data:
            return []
        queries = res.data[0].get("queries") or {}
        if isinstance(queries, dict):
            return [str(k).strip() for k in queries.keys() if str(k).strip()]
    except Exception as err:
        logger.warning(
            "No se pudo cargar external_db_allowed_queries para empresa %s: %s",
            empresa_id,
            err,
        )
    return []


class ScheduleRetryRequest(BaseModel):
    retry_at: str

# ──────────────────────────────────────────────
# DRIP LOCK MULTITENANT (Redis distribuido)
#
# Cada empresa tiene un lock en Redis con TTL como safety net.
# Si Redis no está disponible, se usa un set local como fallback.
# ──────────────────────────────────────────────
_empresas_en_llamada_fallback: set[int] = set()

# Rango de cooldown entre llamadas de la misma empresa (segundos)
_COOLDOWN_MIN = int(os.getenv("DRIP_COOLDOWN_MIN_SECONDS", str(settings.drip_cooldown_min)))
_COOLDOWN_MAX = int(os.getenv("DRIP_COOLDOWN_MAX_SECONDS", str(settings.drip_cooldown_max)))

# TTL del lock de empresa: cooldown máximo + tiempo máximo de llamada + margen
_EMPRESA_LOCK_TTL = _COOLDOWN_MAX + 300 + 60  # ~540s


async def _acquire_empresa_lock(empresa_id: int) -> str | None:
    """Intenta adquirir el drip lock para una empresa. Devuelve token de propiedad."""
    try:
        from services.redis_service import acquire_lock

        return await acquire_lock(f"empresa:{empresa_id}", ttl_seconds=_EMPRESA_LOCK_TTL)
    except Exception:
        if empresa_id in _empresas_en_llamada_fallback:
            return None
        _empresas_en_llamada_fallback.add(empresa_id)
        return f"local-fallback:{empresa_id}"


async def _release_empresa_lock(empresa_id: int, token: str | None = None) -> None:
    """Libera el drip lock de una empresa (solo si el token coincide en Redis)."""
    try:
        from services.redis_service import release_lock

        if token and not str(token).startswith("local-fallback:"):
            await release_lock(f"empresa:{empresa_id}", token)
        elif token is None:
            await release_lock(f"empresa:{empresa_id}")
    except Exception:
        pass
    _empresas_en_llamada_fallback.discard(empresa_id)


async def _is_empresa_locked(empresa_id: int) -> bool:
    """Comprueba si una empresa tiene lock activo."""
    try:
        from services.redis_service import is_locked
        return await is_locked(f"empresa:{empresa_id}")
    except Exception:
        return empresa_id in _empresas_en_llamada_fallback


async def _get_active_call_count() -> int:
    """Retorna el número de empresas con llamada activa (distribuido)."""
    try:
        from services.redis_service import get_active_call_count
        return await get_active_call_count()
    except Exception:
        return len(_empresas_en_llamada_fallback)


async def _get_active_call_count_for_empresa(empresa_id: int) -> int:
    """
    Retorna el número de llamadas activas (status calling/initiated/called)
    para una empresa específica. Usado por el rate limiter por empresa.
    """
    if not supabase or not empresa_id:
        return 0
    try:
        res = await asyncio.to_thread(
            supabase.table("encuestas")
                .select("id", count="exact")
                .eq("empresa_id", empresa_id)
                .in_("status", ["calling", "initiated", "called"])
                .execute
        )
        return res.count or 0
    except Exception as e:
        logger.warning(f"[RateLimit] Error contando llamadas activas para empresa {empresa_id}: {e}")
        return 0


async def _enqueue_scheduler_tick() -> None:
    """
    Encola una ejecución inmediata del scheduler ARQ.
    Se usa al iniciar/reintentar campañas para no esperar al próximo cron (:00/:30).
    """
    try:
        from services.queue_service import get_arq_pool
        arq = await get_arq_pool()
        await arq.enqueue_job("campaign_scheduler_task")
    except Exception as e:
        logger.warning(f"No se pudo encolar campaign_scheduler_task: {e}")


# ──────────────────────────────────────────────
# CRUD básico de campañas
# ──────────────────────────────────────────────

@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        supabase.table("campaign_leads").delete().eq("campaign_id", campaign_id).execute()
        supabase.table("encuestas").delete().eq("campaign_id", campaign_id).execute()
        supabase.table("campaigns").delete().eq("id", campaign_id).execute()
        await log_audit_event(
            user_id=current_user.user_id,
            action="delete_campaign",
            target_type="campaign",
            target_id=str(campaign_id),
            metadata={"cascade": ["campaign_leads", "encuestas"]},
        )
        return {"status": "ok", "message": f"Campaña {campaign_id} eliminada"}
    except Exception as e:
        logger.error(f"Error deleting campaign: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns")
async def create_campaign(campaign: CampaignModel, leads: List[CampaignLeadModel], current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        status_final = campaign.status
        if not campaign.scheduled_time and status_final == "pending":
            status_final = "running"

        interval_raw = campaign.retry_interval
        if campaign.retry_unit == "minutes":  interval_raw *= 60
        elif campaign.retry_unit == "hours":  interval_raw *= 3600
        elif campaign.retry_unit == "days":   interval_raw *= 86400

        camp_data = {
            "name": campaign.name,
            "agent_id": campaign.agent_id,
            "empresa_id": campaign.empresa_id,
            "status": status_final,
            "scheduled_time": campaign.scheduled_time.isoformat() if campaign.scheduled_time else None,
            "retries_count": campaign.retries_count,
            "retry_interval": interval_raw,
            "retry_unit": campaign.retry_unit,
            "interval_minutes": campaign.interval_minutes,
            "extraction_schema": [s.model_dump() for s in campaign.extraction_schema] if campaign.extraction_schema else [],
            "ab_test_enabled": campaign.ab_test_enabled,
            "agent_id_b": campaign.agent_id_b,
            "ab_split_ratio": campaign.ab_split_ratio,
            "created_at": datetime.now(timezone.utc).isoformat()
        }
        res_camp = supabase.table("campaigns").insert(camp_data).execute()
        campaign_id = res_camp.data[0]["id"]

        leads_data = [{
            "campaign_id": campaign_id,
            "phone_number": lead.phone_number,
            "customer_name": lead.customer_name,
            "status": "pending",
            "retries_attempted": 0
        } for lead in leads]

        if leads_data:
            supabase.table("campaign_leads").insert(leads_data).execute()
        await log_audit_event(
            user_id=current_user.user_id,
            action="create_campaign",
            target_type="campaign",
            target_id=str(campaign_id),
            metadata={"empresa_id": campaign.empresa_id, "agent_id": campaign.agent_id, "leads_count": len(leads_data)},
        )

        return {"id": campaign_id, "message": f"Campaña creada con {len(leads_data)} leads"}
    except Exception as e:
        logger.error(f"Error creando campaña: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: int, payload: dict, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        from services.campaign_ab_service import validate_ab_campaign_payload

        ab_error = validate_ab_campaign_payload(payload)
        if ab_error:
            return JSONResponse(status_code=400, content={"error": ab_error})

        if "retry_interval" in payload and "retry_unit" in payload:
            raw = payload["retry_interval"]
            unit = payload["retry_unit"]
            if unit == "minutes":  raw *= 60
            elif unit == "hours":  raw *= 3600
            elif unit == "days":   raw *= 86400
            payload["retry_interval"] = raw
        supabase.table("campaigns").update(payload).eq("id", campaign_id).execute()
        await log_audit_event(
            user_id=current_user.user_id,
            action="update_campaign",
            target_type="campaign",
            target_id=str(campaign_id),
            metadata={"fields": list(payload.keys())},
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/campaigns")
async def list_campaigns(
    empresa_id: Optional[int] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase: return []
    try:
        query = supabase.table("campaigns").select("*, empresas:empresa_id(nombre)")
        empresa_id = _resolve_empresa(current_user, empresa_id)
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        res = query.order("created_at", desc=True).limit(100).execute()
        campaigns = res.data or []
        for c in campaigns:
            try:
                total_r = supabase.table("campaign_leads").select("id", count="exact").eq("campaign_id", c["id"]).execute()
                total_leads = total_r.count if total_r.count is not None else 0
                c["total_leads"] = total_leads
                pending_r = supabase.table("campaign_leads").select("id", count="exact").eq("campaign_id", c["id"]).in_("status", ["pending", "calling"]).execute()
                pending_calling = pending_r.count if pending_r.count is not None else 0
                c["called_leads"] = max(0, total_leads - pending_calling)
            except Exception:
                c["total_leads"] = 0
                c["called_leads"] = 0
        return campaigns
    except Exception as e:
        logger.error(f"Error listing campaigns: {e}")
        return []


@router.get("/campaigns/{campaign_id}/ab-stats")
async def get_campaign_ab_stats(
    campaign_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """Métricas de conversión por variante A/B de una campaña."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    camp_res = supabase.table("campaigns").select(
        "id, empresa_id, name, agent_id, agent_id_b, ab_test_enabled, ab_split_ratio"
    ).eq("id", campaign_id).limit(1).execute()
    if not camp_res.data:
        raise HTTPException(status_code=404, detail="Campaña no encontrada")

    campaign = camp_res.data[0]
    empresa_id = campaign.get("empresa_id")
    if current_user.role != "superadmin" and empresa_id != current_user.empresa_id:
        raise HTTPException(status_code=403, detail="Sin permiso para esta campaña")

    enc_res = supabase.table("encuestas").select(
        "id, ab_variant, status, agent_id, puntuacion_comercial, agent_results"
    ).eq("campaign_id", campaign_id).execute()
    rows = enc_res.data or []

    completed_statuses = {"completed", "transferred"}
    stats: dict[str, dict] = {
        "A": {"calls": 0, "completed": 0, "completion_rate": 0.0, "avg_score": None, "agent_id": campaign.get("agent_id")},
        "B": {"calls": 0, "completed": 0, "completion_rate": 0.0, "avg_score": None, "agent_id": campaign.get("agent_id_b")},
    }

    score_sums: dict[str, float] = {"A": 0.0, "B": 0.0}
    score_counts: dict[str, int] = {"A": 0, "B": 0}

    for row in rows:
        variant = (row.get("ab_variant") or "A").upper()
        if variant not in stats:
            variant = "A"
        stats[variant]["calls"] += 1
        status = (row.get("status") or "").lower()
        if status in completed_statuses:
            stats[variant]["completed"] += 1

        score = row.get("puntuacion_comercial")
        if score is None and isinstance(row.get("agent_results"), dict):
            scores = row["agent_results"].get("scores") or {}
            score = scores.get("comercial")
        if isinstance(score, (int, float)):
            score_sums[variant] += float(score)
            score_counts[variant] += 1

    for variant, data in stats.items():
        calls = data["calls"]
        if calls:
            data["completion_rate"] = round(data["completed"] / calls, 4)
        if score_counts[variant]:
            data["avg_score"] = round(score_sums[variant] / score_counts[variant], 2)

    return {
        "campaign_id": campaign_id,
        "ab_test_enabled": bool(campaign.get("ab_test_enabled")),
        "ab_split_ratio": campaign.get("ab_split_ratio"),
        "variants": stats,
        "total_calls": len(rows),
    }

@router.get("/campaigns/{campaign_id}")
async def get_campaign_details(
    campaign_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase: return {"error": "No DB"}
    try:
        res_camp, res_leads = await asyncio.gather(
            asyncio.to_thread(supabase.table("campaigns").select("*").eq("id", campaign_id).execute), # type: ignore
            asyncio.to_thread(supabase.table("campaign_leads").select("*").eq("campaign_id", campaign_id).execute) # type: ignore
        )
        if not res_camp.data:
            return JSONResponse(status_code=404, content={"error": "Campaign not found"})

        campaign = res_camp.data[0]
        _raise_not_found_if_cross_tenant(current_user, campaign.get("empresa_id"))
        leads = res_leads.data

        # Detectar si el agente es de tipo pregunta-abierta
        is_question_based = False
        try:
            agent_res = supabase.table("agent_config").select("instructions").eq("id", campaign["agent_id"]).execute()
            if agent_res.data:
                inst_lower = agent_res.data[0].get("instructions", "").lower()
                if "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower:
                    is_question_based = True
        except Exception as e:
            logger.warning(f"⚠️ [campaigns] No se pudo detectar tipo de agente para campaña: {e}")
        campaign["is_question_based"] = is_question_based

        # Cargar surveys relacionadas
        call_ids = [l["call_id"] for l in leads if l.get("call_id")]
        surveys_map = {}
        if call_ids:
            try:
                cols = "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, transcription, datos_extra, tipo_resultados, fecha, llm_model"
                res_surveys = await asyncio.to_thread(
                    supabase.table("encuestas").select(cols).in_("id", call_ids).execute
                )
                surveys_map = {s["id"]: s for s in res_surveys.data}
            except Exception as e:
                # Compatibilidad con BDs antiguas sin columna tipo_resultados
                if "tipo_resultados" in str(e):
                    try:
                        fallback_cols = "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, transcription, datos_extra, fecha, llm_model"
                        res_surveys = await asyncio.to_thread(
                            supabase.table("encuestas").select(fallback_cols).in_("id", call_ids).execute
                        )
                        surveys_map = {s["id"]: s for s in res_surveys.data}
                        logger.warning("encuestas.tipo_resultados no existe; usando select fallback sin esa columna.")
                    except Exception as fallback_err:
                        logger.error(f"Error fetching surveys for campaign (fallback): {fallback_err}")
                else:
                    logger.error(f"Error fetching surveys for campaign: {e}")

        # Agregar datos de encuesta a cada lead y calcular métricas
        sum_com: float = 0.0
        sum_ins: float = 0.0
        sum_rap: float = 0.0
        count_com: int = 0
        count_ins: int = 0
        count_rap: int = 0
        status_counts: dict[str, int] = {}
        enriched_leads = []

        for l in leads:
            s = (l.get("status") or "pending")
            status_counts[s] = status_counts.get(s, 0) + 1

            survey = surveys_map.get(l.get("call_id"))
            l["encuesta"] = survey
            if survey:
                l["puntuacion_comercial"] = survey.get("puntuacion_comercial")
                l["puntuacion_instalador"] = survey.get("puntuacion_instalador")
                l["puntuacion_rapidez"] = survey.get("puntuacion_rapidez")
                l["comentarios"] = survey.get("comentarios")
                l["transcription_preview"] = survey.get("transcription")
                if survey.get("puntuacion_comercial") is not None:
                    sum_com = sum_com + float(survey["puntuacion_comercial"]) # type: ignore
                    count_com = count_com + 1 # type: ignore
                if survey.get("puntuacion_instalador") is not None:
                    sum_ins = sum_ins + float(survey["puntuacion_instalador"]) # type: ignore
                    count_ins = count_ins + 1 # type: ignore
                if survey.get("puntuacion_rapidez") is not None:
                    sum_rap = sum_rap + float(survey["puntuacion_rapidez"]) # type: ignore
                    count_rap = count_rap + 1 # type: ignore
            enriched_leads.append(l)

        total_leads = len(leads)
        pending    = status_counts.get("pending", 0)
        calling    = status_counts.get("calling", 0)
        completed  = status_counts.get("completed", 0) + status_counts.get("completada", 0)
        failed     = status_counts.get("failed", 0) + status_counts.get("fallida", 0)
        unreached  = status_counts.get("unreached", 0) + status_counts.get("no_contesta", 0)
        incomplete = status_counts.get("incomplete", 0) + status_counts.get("parcial", 0)
        rejected   = status_counts.get("rejected_opt_out", 0) + status_counts.get("rechazada", 0) + status_counts.get("rejected", 0)

        campaign["total_leads"]     = total_leads
        campaign["called_leads"]    = max(0, total_leads - pending - calling)
        campaign["failed_leads"]    = failed + unreached + incomplete
        campaign["pending_leads"]   = pending + calling
        campaign["completed_leads"] = completed
        campaign["rejected_leads"]  = rejected

        metrics = {
            "avg_comercial": round(float(sum_com / count_com), 1) if count_com else 0.0, # type: ignore
            "avg_instalador": round(float(sum_ins / count_ins), 1) if count_ins else 0.0, # type: ignore
            "avg_rapidez": round(float(sum_rap / count_rap), 1) if count_rap else 0.0, # type: ignore
            "avg_overall": round( # type: ignore
                float((sum_com + sum_ins + sum_rap) / (count_com + count_ins + count_rap)), 1 # type: ignore
            ) if (count_com + count_ins + count_rap) else 0.0, # type: ignore
        }

        return {"campaign": campaign, "metrics": metrics, "leads": enriched_leads}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting campaign details {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/results/{result_id}/transcription")
async def get_result_transcription(
    result_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase: return {"error": "Database not connected"}
    try:
        res = supabase.table("encuestas").select("transcription, empresa_id").eq("id", result_id).limit(1).execute()
        if res.data:
            _raise_not_found_if_cross_tenant(current_user, res.data[0].get("empresa_id"))
        return {"transcription": res.data[0].get("transcription") if res.data else None}
    except HTTPException:
        raise
    except Exception as e:
        return {"error": str(e)}

@router.get("/agent_config_by_survey/{survey_id}")
async def get_agent_config_by_survey(
    survey_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase: return JSONResponse(status_code=500, content={"error": "Supabase not connected"})
    try:
        res_survey = supabase.table("encuestas").select(
            "agent_id, nombre_cliente, empresa_id, campaign_id"
        ).eq("id", survey_id).execute()
        if not res_survey.data:
            return JSONResponse(status_code=404, content={"error": "Survey not found"})
        _raise_not_found_if_cross_tenant(current_user, res_survey.data[0].get("empresa_id"))

        agent_id = res_survey.data[0].get("agent_id")
        nombre_cliente = res_survey.data[0].get("nombre_cliente")
        empresa_id = res_survey.data[0].get("empresa_id")
        campaign_id = res_survey.data[0].get("campaign_id")

        extraction_schema: list = []
        if campaign_id:
            try:
                camp_res = supabase.table("campaigns").select("extraction_schema").eq("id", campaign_id).limit(1).execute()
                if camp_res.data and camp_res.data[0].get("extraction_schema"):
                    extraction_schema = camp_res.data[0]["extraction_schema"]
            except Exception as schema_err:
                logger.warning(f"No se pudo cargar extraction_schema de campaña {campaign_id}: {schema_err}")

        if not agent_id:
            return {
                "name": "Bot", 
                "greeting": "Buenas, le llamo...", 
                "instructions": "Eres un asistente.", 
                "voice_id": DEFAULT_AUSARTA_VOICE_ID, 
                "llm_model": "llama-3.3-70b-versatile",
                "company_context": "",
                "enthusiasm_level": "Normal",
                "speaking_speed": 1.0,
                "empresa_id": empresa_id
            }

        res_agent = supabase.table("agent_config").select("*").eq("id", agent_id).execute()
        if not res_agent.data:
            return JSONResponse(status_code=404, content={"error": "Agent not found"})

        agent_data = res_agent.data[0]
        agent_empresa_id = agent_data.get("empresa_id")
        empresa_kb = _load_empresa_kb_settings(empresa_id or agent_empresa_id)
        empresa_context = empresa_kb["company_context"]

        res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
        ai_data = res_ai.data[0] if res_ai.data else {}

        greeting = agent_data.get("greeting", "Buenas, ¿tiene un momento?").replace("{nombre}", nombre_cliente or "Cliente")

        resolved_agent_type = (
            agent_data.get("agent_type")
            or agent_data.get("tipo_resultados")
            or "ENCUESTA_NUMERICA"
        )

        payload = {
            "name": agent_data.get("name", "Bot"),
            "greeting": greeting,
            "instructions": agent_data.get("instructions", "Eres un asistente"),
            "critical_rules": agent_data.get("critical_rules", ""),
            "voice_id": agent_data.get("voice_id") or ai_data.get("tts_voice") or DEFAULT_AUSARTA_VOICE_ID,
            "tts_model": ai_data.get("tts_model") or settings.default_tts_model,
            "llm_model": ai_data.get("llm_model") or "llama-3.3-70b-versatile",
            "language": ai_data.get("language") or "es",
            "stt_provider": ai_data.get("stt_provider") or "deepgram",
            "stt_model": ai_data.get("stt_model") or settings.default_stt_model,
            "extraction_schema": extraction_schema,
            "company_context": agent_data.get("company_context") or empresa_context or "",
            "kb_allow_internet_search": agent_data.get("kb_allow_internet_search"),
            "empresa_kb_allow_internet_search": empresa_kb["kb_allow_internet_search"],
            "enthusiasm_level": agent_data.get("enthusiasm_level") or "Normal",
            "speaking_speed": agent_data.get("speaking_speed") or 1.0,
            "agent_type": resolved_agent_type,
            "tipo_resultados": agent_data.get("tipo_resultados") or resolved_agent_type,
            "empresa_id": empresa_id or agent_empresa_id,
            "agent_id": agent_id,
            "config_updated_at": agent_data.get("updated_at") or ai_data.get("updated_at"),
            # PARTE 5: campos de workflow (necesarios para que agent.py compile el workflow)
            "agent_mode": agent_data.get("agent_mode") or "prompt",
            "workflow_definition": agent_data.get("workflow_definition"),
            "workflow_variables": agent_data.get("workflow_variables") or {},
            "external_db_allowed_queries": _load_external_db_allowed_queries(
                empresa_id or agent_empresa_id
            ),
        }
        # Evita cualquier cache intermedio: tras editar, la siguiente llamada debe leer esto sí o sí.
        return JSONResponse(
            status_code=200,
            content=payload,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
    except Exception as e:
        logger.error(f"Error agent config by survey: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/{campaign_id}/retry")
async def retry_campaign(campaign_id: int, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        _load_campaign_or_404(campaign_id, current_user)
        res = supabase.table("campaign_leads").update({
            "status": "pending", "retries_attempted": 0,
            "error_msg": None, "next_retry_at": None
        }).eq("campaign_id", campaign_id).in_("status", ["failed", "unreached", "incomplete"]).execute()
        supabase.table("campaigns").update({"status": "active"}).eq("id", campaign_id).execute()
        try:
            from services.redis_service import get_redis
            redis = await get_redis()
            await redis.delete(f"ausarta:campaign:cancel:{campaign_id}")
        except Exception:
            pass
        await _enqueue_scheduler_tick()
        return {"status": "success", "retried_count": len(res.data)}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/leads/{lead_id}/retry")
async def retry_lead(lead_id: int, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        lead_res = supabase.table("campaign_leads").select("campaign_id").eq("id", lead_id).limit(1).execute()
        if not lead_res.data:
            raise HTTPException(status_code=404, detail="Lead not found")
        _load_campaign_or_404(int(lead_res.data[0]["campaign_id"]), current_user)
        res = supabase.table("campaign_leads").update({
            "status": "pending", "retries_attempted": 0,
            "error_msg": None, "next_retry_at": None
        }).eq("id", lead_id).execute()
        if res.data:
            camp_id = res.data[0].get("campaign_id")
            if camp_id:
                supabase.table("campaigns").update({"status": "active"}).eq("id", camp_id).execute()
                try:
                    from services.redis_service import get_redis
                    redis = await get_redis()
                    await redis.delete(f"ausarta:campaign:cancel:{camp_id}")
                except Exception:
                    pass
                await _enqueue_scheduler_tick()
        return {"status": "success"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrying lead {lead_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.post("/campaigns/{campaign_id}/schedule-retry")
async def schedule_campaign_retry(
    campaign_id: int,
    payload: ScheduleRetryRequest,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Programa reintento manual para leads no exitosos de una campaña
    en una fecha/hora concreta (ISO).
    """
    if not supabase:
        return {"error": "No DB"}
    _load_campaign_or_404(campaign_id, current_user)
    try:
        retry_at_dt = datetime.fromisoformat(payload.retry_at.replace("Z", "+00:00"))
        retry_at_iso = retry_at_dt.astimezone(timezone.utc).isoformat()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "retry_at inválido. Usa ISO datetime."})

    try:
        res = supabase.table("campaign_leads").update({
            "status": "pending",
            "error_msg": None,
            "next_retry_at": retry_at_iso,
        }).eq("campaign_id", campaign_id).in_("status", ["failed", "unreached", "incomplete"]).execute()
        supabase.table("campaigns").update({"status": "active"}).eq("id", campaign_id).execute()
        try:
            from services.redis_service import get_redis
            redis = await get_redis()
            await redis.delete(f"ausarta:campaign:cancel:{campaign_id}")
        except Exception:
            pass
        await _enqueue_scheduler_tick()
        return {"status": "success", "scheduled_count": len(res.data or []), "retry_at": retry_at_iso}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error scheduling retry for campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        _load_campaign_or_404(campaign_id, current_user)
        supabase.table("campaigns").update({
            "status": "paused",
            "paused_by_health_check": False,
            "paused_reason": None,
            "status_before_health_pause": None,
            "health_paused_at": None,
        }).eq("id", campaign_id).execute()
        try:
            from services.redis_service import get_redis
            redis = await get_redis()
            # Marca de cancelación para que jobs encolados se autodescarten.
            await redis.set(f"ausarta:campaign:cancel:{campaign_id}", "1", ex=86400)
        except Exception:
            pass
        return {"status": "ok", "message": "Campaña pausada"}
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@router.get("/agent_config_by_agent/{agent_id}")
async def get_agent_config_by_agent(
    agent_id: int,
    empresa_id: Optional[int] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Config interna para llamadas entrantes SIP, donde no existe encuesta previa."""
    if not supabase:
        return JSONResponse(status_code=500, content={"error": "Supabase not connected"})
    try:
        query = supabase.table("agent_config").select("*").eq("id", agent_id).limit(1)
        empresa_id = _resolve_empresa(current_user, empresa_id)
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        res_agent = query.execute()
        if not res_agent.data:
            return JSONResponse(status_code=404, content={"error": "Agent not found"})

        agent_data = res_agent.data[0]
        empresa_id_resolved = agent_data.get("empresa_id")
        empresa_kb = _load_empresa_kb_settings(empresa_id_resolved)
        empresa_context = empresa_kb["company_context"]
        res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
        ai_data = res_ai.data[0] if res_ai.data else {}
        resolved_agent_type = (
            agent_data.get("agent_type")
            or agent_data.get("tipo_resultados")
            or "SOPORTE_CLIENTE"
        )
        payload = {
            "name": agent_data.get("name", "Bot"),
            "greeting": agent_data.get("greeting", "Hola, has llamado a Ausarta."),
            "instructions": agent_data.get("instructions", "Eres un asistente."),
            "critical_rules": agent_data.get("critical_rules", ""),
            "voice_id": agent_data.get("voice_id") or ai_data.get("tts_voice") or DEFAULT_AUSARTA_VOICE_ID,
            "tts_model": ai_data.get("tts_model") or settings.default_tts_model,
            "llm_model": ai_data.get("llm_model") or "llama-3.3-70b-versatile",
            "language": ai_data.get("language") or "es",
            "stt_provider": ai_data.get("stt_provider") or "deepgram",
            "stt_model": ai_data.get("stt_model") or settings.default_stt_model,
            "extraction_schema": [],
            "company_context": agent_data.get("company_context") or empresa_context or "",
            "kb_allow_internet_search": agent_data.get("kb_allow_internet_search"),
            "empresa_kb_allow_internet_search": empresa_kb["kb_allow_internet_search"],
            "enthusiasm_level": agent_data.get("enthusiasm_level") or "Normal",
            "speaking_speed": agent_data.get("speaking_speed") or 1.0,
            "agent_type": resolved_agent_type,
            "tipo_resultados": agent_data.get("tipo_resultados") or resolved_agent_type,
            "empresa_id": agent_data.get("empresa_id"),
            "agent_id": agent_id,
            "call_direction": "inbound",
            "config_updated_at": agent_data.get("updated_at") or ai_data.get("updated_at"),
            "agent_mode": agent_data.get("agent_mode") or "prompt",
            "workflow_definition": agent_data.get("workflow_definition"),
            "workflow_variables": agent_data.get("workflow_variables") or {},
            "external_db_allowed_queries": _load_external_db_allowed_queries(
                agent_data.get("empresa_id")
            ),
        }
        return JSONResponse(
            status_code=200,
            content=payload,
            headers={
                "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
                "Pragma": "no-cache",
            },
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# MOTOR DE CAMPAÑAS — GOTEO CONTROLADO (DRIP)
# ──────────────────────────────────────────────

async def _dispatch_single_lead_drip(
    lead: dict,
    campaign: dict,
    *,
    lock_token: str | None = None,
) -> None:
    """
    Lanza UNA llamada SIP para un lead y gestiona el drip lock de la empresa.

    Flujo:
      1. Adquiere el drip lock de la empresa (exclusión mutua estricta).
      2. Crea encuesta en BD, asigna nombre de sala aislado, lanza SIP + dispatch agente.
      3. Hace polling ligero (cada 15s) esperando que el estado en BD sea terminal.
      4. Una vez terminal (o timeout de 5min), aplica cooldown de 120-180s antes
         de liberar el lock, para respetar el goteo estricto.
    """
    lead_id = lead["id"]
    phone = lead["phone_number"]
    empresa_id = campaign.get("empresa_id") or 0
    campaign_id = campaign["id"]
    agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip() or "default_agent"
    sip_trunk_id = await resolve_outbound_trunk_id(int(empresa_id) if empresa_id else None)

    # El lock ( _empresas_en_llamada.add(empresa_id) ) ya ha sido adquirido síncronamente
    # en el campaign_scheduler_loop antes de llamar a esta función para evitar race conditions.
    
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

        # 1. Crear encuesta en BD y vincular al lead
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

        # 2. Nombre de sala aislado estricto
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

        # 3. Dispatch agente PRIMERO para que esté en la sala cuando el cliente conteste
        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            logger.info(
                f"🚀 [Drip] Agente '{agent_name_dispatch}' (tipo={resolved_agent_type}) despachado a {room_name}"
            )
            # Breve espera para que el agente entre antes de iniciar la llamada SIP
            await asyncio.sleep(float(os.getenv("DRIP_AGENT_JOIN_DELAY_SECONDS", "3")))
        except Exception as dispatch_err:
            logger.warning(f"⚠️ [Drip] Dispatch explícito fallido (auto-dispatch como fallback): {dispatch_err}")

        # 4. Lanzar SIP (cliente escuchará al agente al descolgar)
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
            await _apply_retry_after_failure(lead_id=lead_id, campaign=campaign)
            return

        # 5. Polling ligero hasta status terminal (el webhook también actuará en paralelo)
        # Requisito negocio: máximo 30s para que descuelgue; si no, fallida reintentable.
        TERMINAL = {"completed", "failed", "unreached", "incomplete", "rejected_opt_out"}
        MAX_WAIT_SECONDS = 300   # 5 minutos como techo
        ANSWER_TIMEOUT_SECONDS = int(os.getenv("DRIP_ANSWER_TIMEOUT_SECONDS", "30"))
        POLL_INTERVAL_S  = 2
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
                    logger.warning(f"⏱️ [Drip] Timeout {ANSWER_TIMEOUT_SECONDS}s sin respuesta (encuesta {encuesta_id}). Marcando failed y cerrando sala.")
                    try:
                        await lkapi.room.delete_room(lk_api.DeleteRoomRequest(room=room_name))
                    except Exception:
                        pass
                    await asyncio.to_thread(
                        supabase.table("encuestas").update({"status": "failed"}).eq("id", encuesta_id).execute
                    )
                    await _apply_retry_after_failure(lead_id=lead_id, campaign=campaign)
                    break
            except Exception as poll_err:
                logger.warning(f"[Drip] Error en poll de estado encuesta {encuesta_id}: {poll_err}")

        if answer_timeout_applied:
            logger.info(f"📵 [Drip] Lead {lead_id} marcado fallido por no contestar en tiempo.")

        # 6. Cooldown obligatorio antes de liberar el lock
        cooldown = random.randint(_COOLDOWN_MIN, _COOLDOWN_MAX)
        logger.info(f"⏳ [Drip] Cooldown {cooldown}s para empresa {empresa_id} antes del siguiente lead...")
        await asyncio.sleep(cooldown)

    finally:
        await _release_empresa_lock(empresa_id, lock_token)
        logger.info(f"🔓 [Drip] Lock liberado para empresa {empresa_id}")


async def _apply_retry_after_failure(lead_id: int, campaign: dict) -> None:
    """
    Programa el siguiente reintento para fallos/no respuesta según la campaña.
    """
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


async def _check_campaign_completion(campaign_id: int) -> bool:
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


async def campaign_scheduler_loop():
    """
    Loop principal del motor de campañas. Se ejecuta como background task
    en el arranque de la aplicación.

    Lógica de goteo:
      - Cada POLL_INTERVAL segundos lee campañas activas.
      - Por cada campaña, si la empresa NO tiene lock activo, obtiene UN lead
        y lanza _dispatch_single_lead_drip() como asyncio.create_task().
      - Distintas empresas corren sus tareas de goteo de forma independiente.
      - Una misma empresa nunca tiene más de una llamada activa simultánea.
    """
    POLL_INTERVAL = int(os.getenv("CAMPAIGN_POLL_INTERVAL_SECONDS", "30"))
    logger.info(f"🔄 [Scheduler] Motor Drip iniciado (poll cada {POLL_INTERVAL}s, cooldown {_COOLDOWN_MIN}-{_COOLDOWN_MAX}s)")

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
            
            MAX_CONCURRENT_CALLS = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))
            
            active_count = await _get_active_call_count()
            if active_count >= MAX_CONCURRENT_CALLS:
                logger.warning(f"Límite global de canales SIP alcanzado ({MAX_CONCURRENT_CALLS}). Esperando...")
                await asyncio.sleep(POLL_INTERVAL)
                continue

            for camp in campaigns:
                empresa_id = camp.get("empresa_id") or 0

                # Si la empresa ya tiene un goteo en curso, no lanzamos más
                if await _is_empresa_locked(empresa_id):
                    logger.debug(f"[Scheduler] Empresa {empresa_id} en llamada activa, skipping campaña {camp['id']}.")
                    continue

                # Obtener el siguiente lead disponible (el más antiguo / con retry más próximo)
                try:
                    # Usamos variable local explícita para evitar cierre sobre 'camp' que puede mutar
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
                    # Sin leads disponibles: comprobar si terminó la campaña
                    is_done = await _check_campaign_completion(camp["id"])
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
                
                # BLOQUEO DISTRIBUÍDO INMEDIATO:
                # Evita que la siguiente campaña de esta misma empresa
                # lance una llamada en este mismo ciclo del bucle.
                lock_token = await _acquire_empresa_lock(empresa_id)
                if not lock_token:
                    logger.debug(f"[Scheduler] Lock empresa {empresa_id} ya adquirido por otra instancia, skipping.")
                    continue

                asyncio.create_task(_dispatch_single_lead_drip(lead, camp, lock_token=lock_token))

        except Exception as e:
            logger.error(f"❌ [Scheduler] Error en loop principal: {e}")

        await asyncio.sleep(POLL_INTERVAL)




# ──────────────────────────────────────────────
# Endpoint de arranque manual de campaña (UI)
# ──────────────────────────────────────────────

@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int, current_user: CurrentUser = Depends(require_admin)):
    """Marca la campaña como 'active' para que el scheduler la procese."""
    if not supabase: return {"error": "No DB"}
    try:
        _load_campaign_or_404(campaign_id, current_user)
        res = supabase.table("campaigns").select("*").eq("id", campaign_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Campaña no encontrada")
        supabase.table("campaigns").update({
            "status": "active",
            "paused_by_health_check": False,
            "paused_reason": None,
            "status_before_health_pause": None,
            "health_paused_at": None,
        }).eq("id", campaign_id).execute()
        try:
            from services.redis_service import get_redis
            redis = await get_redis()
            await redis.delete(f"ausarta:campaign:cancel:{campaign_id}")
        except Exception:
            pass
        await _enqueue_scheduler_tick()
        return {"status": "ok", "message": "Campaña marcada como activa. El scheduler la procesará en el próximo ciclo."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al iniciar campaña: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# Webhook legacy (compatibilidad con n8n antiguo)
# ──────────────────────────────────────────────

class CallResultWebhook(BaseModel):
    lead_id: int
    status: str
    duration: Optional[int] = 0
    transcription: Optional[str] = ""

@router.post("/campaigns/webhook/call-result")
async def receive_call_result(
    request: Request,
    auth_method: str = Depends(require_campaign_webhook_auth),
):
    """Recibe resultados de n8n para actualizar el lead (compatibilidad legacy)."""
    raw = getattr(request.state, "verified_webhook_body", b"") or b"{}"
    result = CallResultWebhook.model_validate_json(raw)
    logger.info(
        f"📥 [Webhook-legacy] Resultado para lead {result.lead_id}: {result.status} ({auth_method})"
    )
    try:
        lead_update = {
            "status": result.status,
            "error_msg": None if result.status in ("completed", "completada") else f"Incidencia: {result.status}"
        }
        await asyncio.to_thread(
            supabase.table("campaign_leads").update(lead_update).eq("id", result.lead_id).execute
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ [Webhook-legacy] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
