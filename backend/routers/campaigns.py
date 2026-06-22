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
from services.campaign_locks import enqueue_scheduler_tick
from services.webhook_auth import require_campaign_webhook_auth
from pydantic import BaseModel
from models.schemas import CampaignModel, CampaignLeadModel
from datetime import datetime, timezone
import asyncio
import json
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaigns"])

from routers.campaign_access import (
    raise_not_found_if_cross_tenant as _raise_not_found_if_cross_tenant,
    resolve_campaign_empresa as _resolve_empresa,
)


def _load_campaign_or_404(campaign_id: int, user: CurrentUser) -> dict:
    res = supabase.table("campaigns").select("*").eq("id", campaign_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=404, detail="Campaign not found")
    campaign = res.data[0]
    _raise_not_found_if_cross_tenant(user, campaign.get("empresa_id"))
    return campaign



class ScheduleRetryRequest(BaseModel):
    retry_at: str


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


@router.post("/campaigns/{campaign_id}/simulate")
async def simulate_campaign(
    campaign_id: int,
    current_user: CurrentUser = Depends(require_admin),
):
    """Dry-run: cuántos leads se procesarían sin lanzar llamadas."""
    from services.campaign_simulate_service import simulate_campaign_dispatch

    camp = _load_campaign_or_404(campaign_id, current_user)
    return await simulate_campaign_dispatch(camp)


@router.get("/campaigns/{campaign_id}/export")
async def export_campaign_results(
    campaign_id: int,
    format: str = "csv",
    current_user: CurrentUser = Depends(get_current_user),
):
    """Exporta resultados de la campaña (CSV)."""
    from fastapi.responses import PlainTextResponse
    from services.campaign_export_service import build_campaign_results_csv

    _load_campaign_or_404(campaign_id, current_user)
    if format.lower() not in ("csv",):
        raise HTTPException(status_code=400, detail="format debe ser csv")

    res = await asyncio.to_thread(
        lambda: supabase.table("encuestas")
        .select(
            "id, telefono, fecha, status, seconds_used, comentarios, datos_extra, agent_results"
        )
        .eq("campaign_id", campaign_id)
        .order("fecha", desc=True)
        .execute()
    )
    csv_body = build_campaign_results_csv(res.data or [])
    return PlainTextResponse(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="campaign_{campaign_id}_results.csv"'},
    )


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
        await enqueue_scheduler_tick()
        return {"status": "ok", "message": "Campaña marcada como activa. El scheduler la procesará en el próximo ciclo."}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al iniciar campaña: {e}")
        return JSONResponse(status_code=500, content={"error": "Error al iniciar campaña"})


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
    from services.webhook_event_service import log_webhook_event, mark_webhook_event_processed

    event_id = await log_webhook_event(
        source="campaign",
        event_type="call-result",
        payload=json.loads(raw) if raw else {},
    )
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
        if event_id:
            await mark_webhook_event_processed(event_id)
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ [Webhook-legacy] Error: {e}")
        if event_id:
            await mark_webhook_event_processed(event_id, failed=True)
        return JSONResponse(status_code=500, content={"error": "Error procesando webhook"})

# Re-exports para compatibilidad con tasks ARQ y código legacy
from services.campaign_locks import (  # noqa: E402
    acquire_empresa_lock as _acquire_empresa_lock,
    get_active_call_count as _get_active_call_count,
    get_active_call_count_for_empresa as _get_active_call_count_for_empresa,
    is_empresa_locked as _is_empresa_locked,
    release_empresa_lock as _release_empresa_lock,
)
from services.campaign_drip import (  # noqa: E402
    apply_retry_after_failure as _apply_retry_after_failure,
    campaign_scheduler_loop,
    check_campaign_completion as _check_campaign_completion,
    dispatch_single_lead_drip as _dispatch_single_lead_drip,
)

