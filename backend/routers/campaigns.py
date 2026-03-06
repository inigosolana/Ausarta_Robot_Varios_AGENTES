"""
Motor de Campañas Asíncrono y Multitenant.

Arquitectura:
- Un único scheduler loop corre como background task en el arranque de la app.
- Por cada campaña activa, el scheduler despacha las llamadas en paralelo
  usando asyncio.gather(), respetando un semáforo por empresa para no saturar
  los canales SIP de un solo cliente.
- El estado de las llamadas ya NO se obtiene por polling. Se actualiza cuando
  el webhook de LiveKit notifica que la sala se cerró (/api/livekit/webhook).
"""
from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import JSONResponse
from typing import Optional, List
from services.supabase_service import supabase
from services.livekit_service import lkapi
from livekit import api as lk_api
from pydantic import BaseModel
from models.schemas import CampaignModel, CampaignLeadModel
from datetime import datetime, timezone, timedelta
import asyncio
import os
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaigns"])

# ──────────────────────────────────────────────
# CONTROL DE CONCURRENCIA MULTITENANT
# Semáforos por empresa: máximo N llamadas simultáneas por cliente.
# ──────────────────────────────────────────────
MAX_CONCURRENT_CALLS_PER_COMPANY = int(os.getenv("MAX_CONCURRENT_CALLS_PER_COMPANY", "3"))
_company_semaphores: dict[int, asyncio.Semaphore] = {}

def _get_company_semaphore(empresa_id: int) -> asyncio.Semaphore:
    """Devuelve (y crea si no existe) el semáforo de concurrencia para una empresa."""
    if empresa_id not in _company_semaphores:
        _company_semaphores[empresa_id] = asyncio.Semaphore(MAX_CONCURRENT_CALLS_PER_COMPANY)
    return _company_semaphores[empresa_id]


# ──────────────────────────────────────────────
# CRUD básico de campañas
# ──────────────────────────────────────────────

@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        supabase.table("campaign_leads").delete().eq("campaign_id", campaign_id).execute()
        supabase.table("encuestas").delete().eq("campaign_id", campaign_id).execute()
        supabase.table("campaigns").delete().eq("id", campaign_id).execute()
        return {"status": "ok", "message": f"Campaña {campaign_id} eliminada"}
    except Exception as e:
        logger.error(f"Error deleting campaign: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns")
async def create_campaign(campaign: CampaignModel, leads: List[CampaignLeadModel]):
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

        return {"id": campaign_id, "message": f"Campaña creada con {len(leads_data)} leads"}
    except Exception as e:
        logger.error(f"Error creando campaña: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.put("/campaigns/{campaign_id}")
async def update_campaign(campaign_id: int, payload: dict):
    if not supabase: return {"error": "No DB"}
    try:
        if "retry_interval" in payload and "retry_unit" in payload:
            raw = payload["retry_interval"]
            unit = payload["retry_unit"]
            if unit == "minutes":  raw *= 60
            elif unit == "hours":  raw *= 3600
            elif unit == "days":   raw *= 86400
            payload["retry_interval"] = raw
        supabase.table("campaigns").update(payload).eq("id", campaign_id).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/campaigns")
async def list_campaigns(empresa_id: Optional[int] = None):
    if not supabase: return []
    try:
        query = supabase.table("campaigns").select("*, empresas:empresa_id(nombre)")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        res = query.order("created_at", desc=True).limit(100).execute()
        return res.data
    except Exception as e:
        logger.error(f"Error listing campaigns: {e}")
        return []

@router.get("/campaigns/{campaign_id}")
async def get_campaign_details(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        res_camp, res_leads = await asyncio.gather(
            asyncio.to_thread(lambda: supabase.table("campaigns").select("*").eq("id", campaign_id).execute()),
            asyncio.to_thread(lambda: supabase.table("campaign_leads").select("*").eq("campaign_id", campaign_id).execute())
        )
        if not res_camp.data:
            return JSONResponse(status_code=404, content={"error": "Campaign not found"})

        campaign = res_camp.data[0]
        leads = res_leads.data

        # Detectar si el agente es de tipo pregunta-abierta
        is_question_based = False
        try:
            agent_res = supabase.table("agent_config").select("instructions").eq("id", campaign["agent_id"]).execute()
            if agent_res.data:
                inst_lower = agent_res.data[0].get("instructions", "").lower()
                if "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower:
                    is_question_based = True
        except: pass
        campaign["is_question_based"] = is_question_based

        # Cargar surveys relacionadas
        call_ids = [l["call_id"] for l in leads if l.get("call_id")]
        surveys_map = {}
        if call_ids:
            try:
                cols = "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, transcription"
                res_surveys = await asyncio.to_thread(
                    lambda: supabase.table("encuestas").select(cols).in_("id", call_ids).execute()
                )
                surveys_map = {s["id"]: s for s in res_surveys.data}
            except Exception as e:
                logger.error(f"Error fetching surveys for campaign: {e}")

        # Agregar datos de encuesta a cada lead y calcular métricas
        sum_com = sum_ins = sum_rap = 0
        count_com = count_ins = count_rap = 0
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
                    sum_com += survey["puntuacion_comercial"]; count_com += 1
                if survey.get("puntuacion_instalador") is not None:
                    sum_ins += survey["puntuacion_instalador"]; count_ins += 1
                if survey.get("puntuacion_rapidez") is not None:
                    sum_rap += survey["puntuacion_rapidez"]; count_rap += 1
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
            "avg_comercial": round(sum_com / count_com, 1) if count_com else 0,
            "avg_instalador": round(sum_ins / count_ins, 1) if count_ins else 0,
            "avg_rapidez": round(sum_rap / count_rap, 1) if count_rap else 0,
            "avg_overall": round(
                (sum_com + sum_ins + sum_rap) / (count_com + count_ins + count_rap), 1
            ) if (count_com + count_ins + count_rap) else 0,
        }

        return {"campaign": campaign, "metrics": metrics, "leads": enriched_leads}
    except Exception as e:
        logger.error(f"Error getting campaign details {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/results/{result_id}/transcription")
async def get_result_transcription(result_id: int):
    if not supabase: return {"error": "Database not connected"}
    try:
        res = supabase.table("encuestas").select("transcription").eq("id", result_id).limit(1).execute()
        return {"transcription": res.data[0].get("transcription") if res.data else None}
    except Exception as e:
        return {"error": str(e)}

@router.get("/agent_config_by_survey/{survey_id}")
async def get_agent_config_by_survey(survey_id: int):
    if not supabase: return JSONResponse(status_code=500, content={"error": "Supabase not connected"})
    try:
        res_survey = supabase.table("encuestas").select("agent_id, nombre_cliente").eq("id", survey_id).execute()
        if not res_survey.data:
            return JSONResponse(status_code=404, content={"error": "Survey not found"})

        agent_id = res_survey.data[0].get("agent_id")
        nombre_cliente = res_survey.data[0].get("nombre_cliente")

        if not agent_id:
            return {"name": "Bot", "greeting": "Buenas, le llamo...", "instructions": "Eres un asistente.", "voice_id": "cefcb124-080b-4655-b31f-932f3ee743de", "llm_model": "llama-3.3-70b-versatile"}

        res_agent = supabase.table("agent_config").select("*").eq("id", agent_id).execute()
        if not res_agent.data:
            return JSONResponse(status_code=404, content={"error": "Agent not found"})

        agent_data = res_agent.data[0]
        res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
        ai_data = res_ai.data[0] if res_ai.data else {}

        greeting = agent_data.get("greeting", "Buenas, ¿tiene un momento?").replace("{nombre}", nombre_cliente or "Cliente")

        return {
            "name": agent_data.get("name", "Bot"),
            "greeting": greeting,
            "instructions": agent_data.get("instructions", "Eres un asistente"),
            "critical_rules": agent_data.get("critical_rules", ""),
            "voice_id": ai_data.get("tts_voice") or "cefcb124-080b-4655-b31f-932f3ee743de",
            "llm_model": ai_data.get("llm_model") or "llama-3.3-70b-versatile",
            "language": ai_data.get("language") or "es",
            "stt_provider": ai_data.get("stt_provider") or "deepgram",
        }
    except Exception as e:
        logger.error(f"Error agent config by survey: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/{campaign_id}/retry")
async def retry_campaign(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        res = supabase.table("campaign_leads").update({
            "status": "pending", "retries_attempted": 0,
            "error_msg": None, "next_retry_at": None
        }).eq("campaign_id", campaign_id).in_("status", ["failed", "unreached", "incomplete"]).execute()
        supabase.table("campaigns").update({"status": "active"}).eq("id", campaign_id).execute()
        return {"status": "success", "retried_count": len(res.data)}
    except Exception as e:
        logger.error(f"Error retrying campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/leads/{lead_id}/retry")
async def retry_lead(lead_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        res = supabase.table("campaign_leads").update({
            "status": "pending", "retries_attempted": 0,
            "error_msg": None, "next_retry_at": None
        }).eq("id", lead_id).execute()
        if res.data:
            camp_id = res.data[0].get("campaign_id")
            if camp_id:
                supabase.table("campaigns").update({"status": "active"}).eq("id", camp_id).execute()
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error retrying lead {lead_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        supabase.table("campaigns").update({"status": "paused"}).eq("id", campaign_id).execute()
        return {"status": "ok", "message": "Campaña pausada"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# MOTOR ASÍNCRONO DE CAMPAÑAS
# ──────────────────────────────────────────────

async def _dispatch_single_lead(lead: dict, campaign: dict) -> None:
    """
    Lanza una llamada SIP para un único lead y registra la encuesta en BD.
    Esta función se ejecuta concurrentemente vía asyncio.gather() respetando
    el semáforo de la empresa.

    El estado post-llamada se actualiza vía webhook de LiveKit, NO aquí.
    """
    lead_id = lead["id"]
    phone = lead["phone_number"]
    empresa_id = campaign.get("empresa_id") or 0
    agent_name_dispatch = os.getenv("AGENT_NAME_DISPATCH", "default_agent")
    sip_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")

    sem = _get_company_semaphore(empresa_id)
    async with sem:
        logger.info(f"📞 [Motor] Lanzando lead {lead_id} ({phone}) para campaña {campaign['id']}")

        # 1. Crear encuesta en BD y vincular al lead
        encuesta_id = None
        try:
            enc_res = await asyncio.to_thread(
                lambda: supabase.table("encuestas").insert({
                    "telefono": phone,
                    "nombre_cliente": lead.get("customer_name", "Cliente"),
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "status": "initiated",
                    "completada": 0,
                    "agent_id": campaign.get("agent_id"),
                    "empresa_id": campaign.get("empresa_id"),
                    "campaign_id": campaign["id"],
                    "campaign_name": campaign.get("name"),
                }).execute()
            )
            encuesta_id = enc_res.data[0]["id"]

            await asyncio.to_thread(
                lambda: supabase.table("campaign_leads").update({
                    "call_id": encuesta_id,
                    "status": "calling",
                    "last_call_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", lead_id).execute()
            )
        except Exception as e:
            logger.error(f"❌ [Motor] Error creando encuesta para lead {lead_id}: {e}")
            await asyncio.to_thread(
                lambda: supabase.table("campaign_leads").update({
                    "status": "failed", "error_msg": str(e)
                }).eq("id", lead_id).execute()
            )
            return

        room_name = f"{agent_name_dispatch}_encuesta_{encuesta_id}"

        # 2. Crear sala y lanzar SIP
        try:
            await lkapi.room.create_room(lk_api.CreateRoomRequest(name=room_name))
        except Exception as room_err:
            logger.warning(f"⚠️ [Motor] Aviso al crear sala {room_name}: {room_err}")

        try:
            await lkapi.sip.create_sip_participant(lk_api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"user_{phone}_{encuesta_id}",
                participant_name="Cliente",
            ))
            logger.info(f"☎️ [Motor] SIP iniciado: {phone} → sala {room_name}")
        except Exception as sip_err:
            logger.error(f"❌ [Motor] Error SIP para lead {lead_id}: {sip_err}")
            await asyncio.to_thread(
                lambda: supabase.table("campaign_leads").update({
                    "status": "failed", "error_msg": str(sip_err)
                }).eq("id", lead_id).execute()
            )
            await asyncio.to_thread(
                lambda: supabase.table("encuestas").update({"status": "failed"}).eq("id", encuesta_id).execute()
            )
            return

        # 3. Despachar agente explícitamente
        try:
            await lkapi.agent_dispatch.create_dispatch(
                lk_api.CreateAgentDispatchRequest(
                    room_name=room_name,
                    agent_name=agent_name_dispatch,
                )
            )
            logger.info(f"🚀 [Motor] Agente {agent_name_dispatch} despachado a {room_name}")
        except Exception as dispatch_err:
            # No es fatal: el auto-dispatch de LiveKit actúa como fallback
            logger.warning(f"⚠️ [Motor] Dispatch explícito fallido (fallback auto-dispatch): {dispatch_err}")


async def _process_campaign_batch(campaign: dict) -> int:
    """
    Para una campaña dada, obtiene todos los leads disponibles y los despacha
    en paralelo respetando el semáforo por empresa.
    Retorna el número de leads procesados.
    """
    campaign_id = campaign["id"]
    now_iso = datetime.utcnow().isoformat()

    try:
        leads_res = await asyncio.to_thread(
            lambda: supabase.table("campaign_leads")
                .select("*")
                .eq("campaign_id", campaign_id)
                .eq("status", "pending")
                .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
                .execute()
        )
    except Exception as e:
        logger.error(f"[Motor] Error leyendo leads de campaña {campaign_id}: {e}")
        return 0

    leads = leads_res.data
    if not leads:
        return 0

    logger.info(f"📋 [Motor] Campaña {campaign_id}: {len(leads)} leads disponibles para despacho")

    # Despachar todos los leads en paralelo (el semáforo limita la concurrencia real)
    await asyncio.gather(*[_dispatch_single_lead(lead, campaign) for lead in leads])
    return len(leads)


async def _check_campaign_completion(campaign_id: int) -> bool:
    """Retorna True si no quedan leads en estado pendiente/calling."""
    try:
        res = await asyncio.to_thread(
            lambda: supabase.table("campaign_leads")
                .select("id")
                .eq("campaign_id", campaign_id)
                .in_("status", ["pending", "calling"])
                .limit(1)
                .execute()
        )
        return len(res.data) == 0
    except Exception:
        return False


async def campaign_scheduler_loop():
    """
    Loop principal del motor de campañas. Se ejecuta como background task
    en el arranque de la aplicación.

    Cada POLL_INTERVAL segundos:
      1. Lee todas las campañas en estado 'active' o 'running'.
      2. Para cada campaña, despacha los leads disponibles.
      3. Si una campaña ya no tiene leads pendientes, la marca como 'completed'.
    """
    POLL_INTERVAL = int(os.getenv("CAMPAIGN_POLL_INTERVAL_SECONDS", "30"))
    logger.info(f"🔄 [Scheduler] Motor de campañas iniciado (poll cada {POLL_INTERVAL}s)")

    while True:
        try:
            active_campaigns = await asyncio.to_thread(
                lambda: supabase.table("campaigns")
                    .select("*")
                    .in_("status", ["active", "running"])
                    .execute()
            )

            campaigns = active_campaigns.data
            if campaigns:
                logger.info(f"[Scheduler] {len(campaigns)} campañas activas encontradas.")

                # Procesar todas las campañas concurrentemente
                results = await asyncio.gather(*[
                    _process_campaign_batch(camp) for camp in campaigns
                ], return_exceptions=True)

                # Post-procesado: marcar campañas terminadas
                for camp, result in zip(campaigns, results):
                    if isinstance(result, Exception):
                        logger.error(f"[Scheduler] Error procesando campaña {camp['id']}: {result}")
                        continue
                    # Si no se despachó ningún lead, comprobar si la campaña está completa
                    if result == 0:
                        is_done = await _check_campaign_completion(camp["id"])
                        if is_done:
                            await asyncio.to_thread(
                                lambda: supabase.table("campaigns")
                                    .update({"status": "completed"})
                                    .eq("id", camp["id"])
                                    .execute()
                            )
                            logger.info(f"✅ [Scheduler] Campaña {camp['id']} completada.")

        except Exception as e:
            logger.error(f"❌ [Scheduler] Error en loop principal: {e}")

        await asyncio.sleep(POLL_INTERVAL)


# ──────────────────────────────────────────────
# Endpoint de arranque manual de campaña (UI)
# ──────────────────────────────────────────────

@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int):
    """Marca la campaña como 'active' para que el scheduler la procese."""
    if not supabase: return {"error": "No DB"}
    try:
        res = supabase.table("campaigns").select("*").eq("id", campaign_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Campaña no encontrada")
        supabase.table("campaigns").update({"status": "active"}).eq("id", campaign_id).execute()
        return {"status": "ok", "message": "Campaña marcada como activa. El scheduler la procesará en el próximo ciclo."}
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
async def receive_call_result(result: CallResultWebhook):
    """Recibe resultados de n8n para actualizar el lead (compatibilidad legacy)."""
    logger.info(f"📥 [Webhook-legacy] Resultado para lead {result.lead_id}: {result.status}")
    try:
        lead_update = {
            "status": result.status,
            "error_msg": None if result.status in ("completed", "completada") else f"Incidencia: {result.status}"
        }
        await asyncio.to_thread(
            lambda: supabase.table("campaign_leads").update(lead_update).eq("id", result.lead_id).execute()
        )
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"❌ [Webhook-legacy] Error: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
