from fastapi import APIRouter, BackgroundTasks, HTTPException, Body
from fastapi.responses import JSONResponse
from typing import Optional, List
from services.supabase_service import supabase
from pydantic import BaseModel
from models.schemas import CampaignModel, CampaignLeadModel, EncuestaData
from datetime import datetime, timezone
import asyncio
import httpx
import os
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaigns"])

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
        if not campaign.scheduled_time and status_final == 'pending':
            status_final = 'running'

        # Multiply by unit
        interval_raw = campaign.retry_interval
        if campaign.retry_unit == 'minutes':
            interval_raw *= 60
        elif campaign.retry_unit == 'hours':
            interval_raw *= 3600
        elif campaign.retry_unit == 'days':
            interval_raw *= 86400

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
        campaign_id = res_camp.data[0]['id']
        
        leads_data = []
        for lead in leads:
            leads_data.append({
                "campaign_id": campaign_id,
                "phone_number": lead.phone_number,
                "customer_name": lead.customer_name,
                "status": "pending",
                "retries_attempted": 0
            })
        
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
            if unit == 'minutes': raw *= 60
            elif unit == 'hours': raw *= 3600
            elif unit == 'days': raw *= 86400
            payload["retry_interval"] = raw

        supabase.table("campaigns").update(payload).eq("id", campaign_id).execute()
        return {"status": "ok"}
    except Exception as e:
        logger.error(f"Error updating campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.get("/results/{result_id}/transcription")
async def get_result_transcription(result_id: int):
    if not supabase: return {"error": "Database not connected"}
    try:
        res = supabase.table("encuestas").select("transcription").eq("id", result_id).limit(1).execute()
        if res.data and len(res.data) > 0:
            return {"transcription": res.data[0].get("transcription")}
        return {"transcription": None}
    except Exception as e:
        logger.error(f"Error fetching transcription: {e}")
        return {"error": str(e)}

@router.get("/campaigns")
async def list_campaigns(empresa_id: Optional[int] = None):
    if not supabase: return []
    try:
        # Join with empresas to get the company name
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
        # Usamos asyncio.to_thread para no bloquear el loop con llamadas síncronas de supabase-py
        res_camp, res_leads = await asyncio.gather(
            asyncio.to_thread(lambda: supabase.table("campaigns").select("*").eq("id", campaign_id).execute()),
            asyncio.to_thread(lambda: supabase.table("campaign_leads").select("*").eq("campaign_id", campaign_id).execute())
        )
        
        if not res_camp.data:
            return JSONResponse(status_code=404, content={"error": "Campaign not found"})
        
        campaign = res_camp.data[0]
        leads = res_leads.data
        
        is_question_based = False
        try:
            agent_res = supabase.table("agent_config").select("instructions").eq("id", campaign["agent_id"]).execute()
            if agent_res.data:
                inst_lower = agent_res.data[0].get("instructions", "").lower()
                if "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower:
                    is_question_based = True
        except: pass
            
        campaign["is_question_based"] = is_question_based
        
        call_ids = [l['call_id'] for l in leads if l.get('call_id')]
        surveys_map = {}
        if call_ids:
            try:
                cols = "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, transcription"
                res_surveys = await asyncio.to_thread(lambda: supabase.table("encuestas").select(cols).in_("id", call_ids).execute())
                for s in res_surveys.data:
                    surveys_map[s['id']] = s
            except Exception as e:
                logger.error(f"Error fetching surveys for campaign: {e}")

        stats = {
            "total": len(leads), "pending": 0, "calling": 0, "called": 0,
            "completada": 0, "parcial": 0, "rechazada": 0, "fallida": 0, "no_contesta": 0,
            # Legacy compatibility
            "completed": 0, "failed": 0, "incomplete": 0
        }
        
        sum_com = 0; count_com = 0
        sum_ins = 0; count_ins = 0
        sum_rap = 0; count_rap = 0
        
        enriched_leads = []
        for l in leads:
            status = l['status']
            if status in stats:
                stats[status] += 1
            else:
                stats["pending"] += 1
            
            call_id = l.get("call_id")
            survey = surveys_map.get(call_id)
            
            l["encuesta"] = survey
            
            if survey:
                l['puntuacion_comercial'] = survey.get('puntuacion_comercial')
                l['puntuacion_instalador'] = survey.get('puntuacion_instalador')
                l['puntuacion_rapidez'] = survey.get('puntuacion_rapidez')
                l['comentarios'] = survey.get('comentarios')
                l['transcription_preview'] = survey.get('transcription')

                if survey.get('puntuacion_comercial') is not None:
                    sum_com += survey['puntuacion_comercial']
                    count_com += 1
                if survey.get('puntuacion_instalador') is not None:
                    sum_ins += survey['puntuacion_instalador']
                    count_ins += 1
                if survey.get('puntuacion_rapidez') is not None:
                    sum_rap += survey['puntuacion_rapidez']
                    count_rap += 1
            
            enriched_leads.append(l)

        metrics = {
            "avg_comercial": round(sum_com / count_com, 1) if count_com > 0 else 0,
            "avg_instalador": round(sum_ins / count_ins, 1) if count_ins > 0 else 0,
            "avg_rapidez": round(sum_rap / count_rap, 1) if count_rap > 0 else 0,
            "avg_overall": round((sum_com + sum_ins + sum_rap) / (count_com + count_ins + count_rap), 1) if (count_com + count_ins + count_rap) > 0 else 0
        }

        # Enriquecer campaña con contadores para que el frontend pueda pintar cards/progreso
        try:
            status_counts = {}
            for l in leads:
                s = (l.get("status") or "pending")
                status_counts[s] = status_counts.get(s, 0) + 1

            total_leads = len(leads)
            pending = status_counts.get("pending", 0)
            calling = status_counts.get("calling", 0)
            completed = status_counts.get("completed", 0) + status_counts.get("completada", 0)
            failed = status_counts.get("failed", 0) + status_counts.get("fallida", 0)
            unreached = status_counts.get("unreached", 0) + status_counts.get("no_contesta", 0)
            incomplete = status_counts.get("incomplete", 0) + status_counts.get("parcial", 0)
            rejected = status_counts.get("rejected_opt_out", 0) + status_counts.get("rechazada", 0) + status_counts.get("rejected", 0)

            called = max(0, total_leads - pending - calling)

            campaign["total_leads"] = total_leads
            campaign["called_leads"] = called
            # En UI, "Failed" suele englobar fallidas + no contesta + incompletas (rechazadas se muestran aparte)
            campaign["failed_leads"] = failed + unreached + incomplete
            campaign["pending_leads"] = pending + calling
            campaign["completed_leads"] = completed
            campaign["rejected_leads"] = rejected
        except Exception as e_counts:
            logger.error(f"Error computing campaign counters: {e_counts}")
        
        return {
            "campaign": campaign,
            "stats": stats,
            "metrics": metrics,
            "leads": enriched_leads
        }
        
    except Exception as e:
        logger.error(f"Error getting campaign details {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

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
            return {"name": "Bot", "greeting": "Buenas, le llamo...", "instructions": "Eres un asistente...", "voice_id": "cefcb124-080b-4655-b31f-932f3ee743de", "llm_model": "llama-3.3-70b-versatile"}
            
        res_agent = supabase.table("agent_config").select("*").eq("id", agent_id).execute()
        if not res_agent.data:
            return JSONResponse(status_code=404, content={"error": "Agent not found"})
            
        agent_data = res_agent.data[0]
        
        res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
        ai_data = res_ai.data[0] if res_ai.data else {}

        # res_lead = supabase.table("campaign_leads").select("comentarios").eq("call_id", survey_id).execute()
        contexto_adicional = ""
        # if res_lead.data and res_lead.data[0].get("comentarios"):
        #     contexto_adicional = f"\nDATOS CRM DEL CLIENTE: {res_lead.data[0].get('comentarios')}"

        greeting_processed = agent_data.get("greeting", "Buenas, ¿tiene un momento?").replace("{nombre}", nombre_cliente or "Cliente")
        instructions_base = agent_data.get("instructions", "Eres un asistente")

        return {
            "name": agent_data.get("name", "Bot"),
            "greeting": greeting_processed,
            "instructions": f"{instructions_base}{contexto_adicional}",
            "critical_rules": agent_data.get("critical_rules", ""),
            "voice_id": ai_data.get("tts_voice") or "cefcb124-080b-4655-b31f-932f3ee743de",
            "llm_model": ai_data.get("llm_model") or "llama-3.3-70b-versatile",
            "language": ai_data.get("language") or "es",
            "stt_provider": ai_data.get("stt_provider") or "deepgram"
        }
            
    except Exception as e:
        logger.error(f"Error agent config by survey: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/{campaign_id}/retry")
async def retry_campaign(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        # Reintentar todos los leads fallidos (failed, unreached, incomplete)
        statuses_to_retry = ['failed', 'unreached', 'incomplete']
        res = supabase.table("campaign_leads").update({
            "status": "pending",
            "retries_attempted": 0,
            "error_msg": None,
            "next_retry_at": None
        }).eq("campaign_id", campaign_id).in_("status", statuses_to_retry).execute()
        
        # También reactivar la campaña
        supabase.table("campaigns").update({"status": "running"}).eq("id", campaign_id).execute()
        
        return {"status": "success", "retried_count": len(res.data)}
    except Exception as e:
        logger.error(f"Error retrying campaign {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
@router.post("/campaigns/leads/{lead_id}/retry")
async def retry_lead(lead_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        res = supabase.table("campaign_leads").update({
            "status": "pending",
            "retries_attempted": 0,
            "error_msg": None,
            "next_retry_at": None
        }).eq("id", lead_id).execute()
        
        if res.data:
            camp_id = res.data[0].get("campaign_id")
            if camp_id:
                # Si reintentamos un lead, aseguramos que la campaña no esté en error
                supabase.table("campaigns").update({"status": "running"}).eq("id", camp_id).execute()
        
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error retrying lead {lead_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- NUEVA LÓGICA DE DRIP CAMPAIGN (GOTEO) ---

async def process_campaign_drip(campaign_id: int, agent_id: int, interval_minutes: int):
    """Procesa una campaña enviando leads uno a uno con una espera entre ellos."""
    logger.info(f"🚀 [Drip] Iniciando procesado de campaña {campaign_id} (intervalo: {interval_minutes}min)")
    
    try:
        # 1. Obtener leads pendientes
        res = await asyncio.to_thread(lambda: supabase.table("campaign_leads")
            .select("*")
            .eq("campaign_id", campaign_id)
            .eq("status", "pending")
            .execute())
        
        leads = res.data
        if not leads:
            logger.info(f"🏁 [Drip] No hay leads pendientes para la campaña {campaign_id}. Finalizando.")
            await asyncio.to_thread(lambda: supabase.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute())
            return

        n8n_base_url = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
        n8n_url = f"{n8n_base_url}/classify-agent" # Usaremos la ruta del orquestador

        async with httpx.AsyncClient() as client:
            for i, lead in enumerate(leads):
                # 2. Verificar estado de la campaña antes de cada lead
                camp_res = await asyncio.to_thread(lambda: supabase.table("campaigns").select("status").eq("id", campaign_id).execute())
                if not camp_res.data or camp_res.data[0]['status'] != 'active':
                    logger.info(f"⏸️ [Drip] Campaña {campaign_id} pausada o detenida. Saliendo del bucle.")
                    break

                lead_id = lead['id']
                phone = lead['phone_number']
                logger.info(f"📞 [Drip] Procesando lead {lead_id} ({phone}) - {i+1}/{len(leads)}")

                # 3. Marcar lead como en progreso
                await asyncio.to_thread(lambda: supabase.table("campaign_leads").update({
                    "status": "calling",
                    "last_call_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", lead_id).execute())

                # 4. Enviar a n8n
                payload = {
                    "phoneNumber": phone,
                    "leadId": lead_id,
                    "agentId": agent_id,
                    "campaignId": campaign_id,
                    "customerName": lead.get("customer_name", "Cliente")
                }

                try:
                    resp = await client.post(n8n_url, json=payload, timeout=10)
                    logger.info(f"📡 [Drip] n8n respondió {resp.status_code} para lead {lead_id}")
                except Exception as e:
                    logger.error(f"❌ [Drip] Error llamando a n8n para lead {lead_id}: {e}")
                    # En caso de error de red, podríamos marcarlo como fallido o dejarlo pendiente
                
                # 5. Esperar el intervalo (excepto en el último lead del bucle)
                if i < len(leads) - 1:
                    logger.info(f"⏳ [Drip] Esperando {interval_minutes} minutos para el siguiente lead...")
                    await asyncio.sleep(interval_minutes * 60)

        # Verificar si todos se procesaron para marcar campaña como completada
        final_check = await asyncio.to_thread(lambda: supabase.table("campaign_leads")
            .select("id")
            .eq("campaign_id", campaign_id)
            .eq("status", "pending")
            .execute())
        
        if not final_check.data:
            await asyncio.to_thread(lambda: supabase.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute())
            logger.info(f"✅ [Drip] Campaña {campaign_id} terminada con éxito.")

    except Exception as e:
        logger.error(f"❌ [Drip] Error crítico procesando campaña {campaign_id}: {e}")
        await asyncio.to_thread(lambda: supabase.table("campaigns").update({"status": "failed"}).eq("id", campaign_id).execute())

@router.post("/campaigns/{campaign_id}/start")
async def start_campaign(campaign_id: int, background_tasks: BackgroundTasks):
    """Inicia la ejecución de la campaña."""
    if not supabase: return {"error": "No DB"}
    
    try:
        # Obtener datos de la campaña
        res = supabase.table("campaigns").select("*").eq("id", campaign_id).execute()
        if not res.data:
            raise HTTPException(status_code=404, detail="Campaña no encontrada")
        
        campaign = res.data[0]
        
        # Cambiar estado a activo
        supabase.table("campaigns").update({"status": "active"}).eq("id", campaign_id).execute()
        
        # Lanzar tarea en segundo plano
        background_tasks.add_task(
            process_campaign_drip, 
            campaign_id, 
            campaign['agent_id'], 
            campaign.get('interval_minutes', 2)
        )
        
        return {"status": "ok", "message": "Campaña iniciada por goteo"}
    except Exception as e:
        logger.error(f"Error al iniciar campaña: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/campaigns/{campaign_id}/stop")
async def stop_campaign(campaign_id: int):
    """Detiene o pausa la campaña."""
    if not supabase: return {"error": "No DB"}
    try:
        supabase.table("campaigns").update({"status": "paused"}).eq("id", campaign_id).execute()
        return {"status": "ok", "message": "Campaña pausada"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- WEBHOOK DE RETORNO PARA RESULTADOS ---

class CallResultWebhook(BaseModel):
    lead_id: int
    status: str
    duration: Optional[int] = 0
    transcription: Optional[str] = ""

@router.post("/campaigns/webhook/call-result")
async def receive_call_result(result: CallResultWebhook):
    """Recibe los resultados finales de n8n para actualizar el lead."""
    logger.info(f"📥 [Webhook] Recibido resultado para lead {result.lead_id}: {result.status}")
    
    try:
        # 1. Actualizar el lead
        # Mapeamos 'completed' a 'completed' para consistencia con el frontend
        lead_update = {
            "status": result.status,
            "transcription": result.transcription,
            "seconds_used": result.duration, # Usamos seconds_used por consistencia con encuestas
            "error_msg": None if result.status in ("completed", "completada") else f"Incidencia: {result.status}"
        }
        
        await asyncio.to_thread(lambda: supabase.table("campaign_leads")
            .update(lead_update)
            .eq("id", result.lead_id)
            .execute())
        
        return {"status": "ok", "message": "Lead actualizado correctamente"}
    except Exception as e:
        logger.error(f"❌ [Webhook] Error procesando resultado de llamada: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

