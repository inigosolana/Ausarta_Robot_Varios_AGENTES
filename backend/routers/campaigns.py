from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional, List
from services.supabase_service import supabase
from models.schemas import CampaignModel, CampaignLeadModel
from datetime import datetime
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

executor = ThreadPoolExecutor(max_workers=20)
logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["campaigns"])

@router.delete("/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        supabase.table("campaign_leads").delete().eq("campaign_id", campaign_id).execute()
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
            status_final = 'active'

        camp_data = {
            "name": campaign.name,
            "agent_id": campaign.agent_id,
            "empresa_id": campaign.empresa_id,
            "status": status_final,
            "scheduled_time": campaign.scheduled_time.isoformat() if campaign.scheduled_time else None,
            "retries_count": campaign.retries_count,
            "retry_interval": campaign.retry_interval * 60,
            "created_at": datetime.utcnow().isoformat()
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
        loop = asyncio.get_event_loop()
        res_camp, res_leads = await asyncio.gather(
            loop.run_in_executor(executor, supabase.table("campaigns").select("*").eq("id", campaign_id).execute),
            loop.run_in_executor(executor, supabase.table("campaign_leads").select("*").eq("campaign_id", campaign_id).execute)
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
                cols = "id, status, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios"
                res_surveys = await loop.run_in_executor(executor, supabase.table("encuestas").select(cols).in_("id", call_ids).execute)
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
