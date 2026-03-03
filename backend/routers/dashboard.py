from fastapi import APIRouter
from typing import Optional
from services.supabase_service import supabase, get_ui_cache
import os
import asyncio
from concurrent.futures import ThreadPoolExecutor
import logging

executor = ThreadPoolExecutor(max_workers=20)
logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["dashboard"])

@router.get("/dashboard/stats")
async def get_dashboard_stats(empresa_id: Optional[int] = None, agent_id: Optional[int] = None, campaign_id: Optional[int] = None):
    if not supabase: return {"error": "Database not connected"}
    
    def fetch_total():
        q = supabase.table("encuestas").select("id", count="exact")
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        r = q.execute()
        return r.count if r.count is not None else 0

    def fetch_completed():
        q = supabase.table("encuestas").select("id", count="exact").eq("completada", 1)
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        r = q.execute()
        return r.count if r.count is not None else 0

    def fetch_pending():
        if empresa_id:
            camps_res = supabase.table("campaigns").select("id").eq("empresa_id", empresa_id).execute()
            camp_ids = [c['id'] for c in camps_res.data]
            if camp_ids:
                r = supabase.table("campaign_leads").select("id", count="exact").eq("status", "pending").in_("campaign_id", camp_ids).execute()
                return r.count if r.count is not None else 0
            return 0
        r = supabase.table("campaign_leads").select("id", count="exact").eq("status", "pending").execute()
        return r.count if r.count is not None else 0

    def fetch_scores():
        q = supabase.table("encuestas").select("puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez").not_.is_("puntuacion_comercial", "null")
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        return q.execute().data

    def check_question_based():
        try:
            target_agent_id = agent_id
            if not target_agent_id and campaign_id:
                camp_res = supabase.table("campaigns").select("agent_id").eq("id", campaign_id).limit(1).execute()
                if camp_res.data and len(camp_res.data) > 0: target_agent_id = camp_res.data[0].get("agent_id")
            if target_agent_id:
                agent_res = supabase.table("agent_config").select("instructions").eq("id", target_agent_id).limit(1).execute()
                if agent_res.data and len(agent_res.data) > 0:
                    inst = agent_res.data[0].get("instructions", "").lower()
                    has_preguntas = "pregunta 1" in inst or "pregunta 2" in inst or "pregunta:" in inst
                    is_numeric = "1 al 10" in inst or "del uno al diez" in inst or "numérica" in inst or "puntuación" in inst
                    return has_preguntas and not is_numeric
        except: pass
        return False

    try:
        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            loop.run_in_executor(executor, fetch_total),
            loop.run_in_executor(executor, fetch_completed),
            loop.run_in_executor(executor, fetch_pending),
            loop.run_in_executor(executor, fetch_scores),
            loop.run_in_executor(executor, check_question_based)
        )
        total_calls, completed_calls, pending_calls, scores_data, is_question_based = results

        avg_comercial = 0; avg_instalador = 0; avg_rapidez = 0; avg_overall = 0
        count = len(scores_data)
        if count > 0:
            sum_com = sum(r['puntuacion_comercial'] or 0 for r in scores_data)
            sum_ins = sum(r['puntuacion_instalador'] or 0 for r in scores_data)
            sum_rap = sum(r['puntuacion_rapidez'] or 0 for r in scores_data)
            avg_comercial = sum_com / count
            avg_instalador = sum_ins / count
            avg_rapidez = sum_rap / count
            avg_overall = (avg_comercial + avg_instalador + avg_rapidez) / 3

        return {
            "total_calls": total_calls, "completed_calls": completed_calls, "pending_calls": pending_calls,
            "is_question_based": is_question_based,
            "avg_scores": {
                "comercial": round(float(avg_comercial), 1),
                "instalador": round(float(avg_instalador), 1),
                "rapidez": round(float(avg_rapidez), 1),
                "overall": round(float(avg_overall), 1)
            }
        }
    except Exception as e:
        logger.error(f"Error stats: {e}")
        return {"total_calls": 0, "completed_calls": 0, "pending_calls": 0, "avg_scores": {}}

@router.get("/dashboard/recent-calls")
async def get_recent_calls(empresa_id: Optional[int] = None, agent_id: Optional[int] = None, campaign_id: Optional[int] = None):
    if not supabase: return []
    try:
        cols = "id, telefono, campaign_name, nombre_cliente, fecha, status, llm_model, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez"
        query = supabase.table("encuestas").select(cols)
        if empresa_id: query = query.eq("empresa_id", empresa_id)
        if agent_id: query = query.eq("agent_id", agent_id)
        if campaign_id: query = query.eq("campaign_id", campaign_id)
        response = query.order("fecha", desc=True).limit(50).execute()
        mapped = []
        for r in (response.data or []):
            mapped.append({
                "id": r.get("id"),
                "phone": r.get("telefono", ""),
                "campaign": r.get("campaign_name", r.get("nombre_cliente", "—")),
                "date": r.get("fecha", ""),
                "status": r.get("status", "pending"),
                "llm_model": r.get("llm_model"),
                "agent_id": r.get("agent_id"),
                "scores": {
                    "comercial": r.get("puntuacion_comercial"),
                    "instalador": r.get("puntuacion_instalador"),
                    "rapidez": r.get("puntuacion_rapidez")
                }
            })
        
        try:
            agents_res = supabase.table("agent_config").select("id, tipo_resultados").execute()
            t_map = {str(a["id"]): a.get("tipo_resultados") for a in (agents_res.data or [])}
            for m in mapped:
                aid = str(m.get("agent_id"))
                m["tipo_resultados"] = t_map.get(aid)
        except: pass
        
        return mapped
    except Exception as e:
        logger.error(f"Error recent calls: {e}")
        return []

@router.get("/results")
async def get_all_results(empresa_id: Optional[int] = None, agent_id: Optional[int] = None, campaign_id: Optional[int] = None):
    if not supabase: return []
    try:
        cols = "id, telefono, fecha, completada, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, campaign_id, campaign_name, agent_id, status, llm_model, seconds_used, empresa_id"
        query = supabase.table("encuestas").select(cols)
        if empresa_id: query = query.eq("empresa_id", empresa_id)
        if agent_id: query = query.eq("agent_id", agent_id)
        if campaign_id: query = query.eq("campaign_id", campaign_id)
        response = query.order("fecha", desc=True).execute()
        results = response.data
        
        try:
            agents_res = supabase.table("agent_config").select("id, instructions, critical_rules, survey_type, tipo_resultados").execute()
            qs_agents = set()
            agent_types = {}
            agent_critical_rules = {}
            for a in (agents_res.data or []):
                aid = str(a["id"])
                t_res = a.get("tipo_resultados")
                agent_types[aid] = t_res
                
                if t_res:
                    if t_res in ['PREGUNTAS_ABIERTAS', 'CUALIFICACION_LEAD', 'AGENDAMIENTO_CITA', 'SOPORTE_CLIENTE']:
                        qs_agents.add(aid)
                else:
                    s_type = a.get("survey_type")
                    if s_type:
                        if s_type in ['open_questions', 'mixed']:
                            qs_agents.add(aid)
                    else:
                        # Fallback
                        inst_lower = a.get("instructions", "").lower()
                        has_preguntas = "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower
                        is_numeric = "1 al 10" in inst_lower or "del uno al diez" in inst_lower or "numérica" in inst_lower or "puntuación" in inst_lower
                        if has_preguntas and not is_numeric:
                            qs_agents.add(aid)
                
                if a.get("critical_rules"):
                    agent_critical_rules[aid] = a["critical_rules"]
            for res in results:
                aid_res = str(res.get("agent_id"))
                res["is_question_based"] = aid_res in qs_agents
                res["tipo_resultados"] = agent_types.get(aid_res)
                res["agent_critical_rules"] = agent_critical_rules.get(aid_res)
        except Exception as e_agent:
            logger.error(f"Error enriching query based question agents: {e_agent}")
        return results
    except Exception as e:
        logger.error(f"Error getting results: {e}")
        return []

@router.get("/users")
async def get_users_list():
    cached = await get_ui_cache("users_list")
    if cached: return cached
    if not supabase: return []
    try:
        res = supabase.table("user_profiles").select("*, empresas(*)").order("created_at", desc=True).execute()
        return res.data
    except Exception as e:
        logger.error(f"Error users list: {e}")
        return []

@router.get("/empresas")
async def get_empresas_list():
    cached = await get_ui_cache("empresas_list")
    if cached: return cached
    if not supabase: return []
    try:
        res = supabase.table("empresas").select("*").order("nombre").execute()
        return res.data
    except Exception as e:
        logger.error(f"Error empresas list: {e}")
        return []

@router.get("/alerts")
async def get_alerts(empresa_id: Optional[int] = None):
    if not supabase: return []
    try:
        query = supabase.table("encuestas").select("*").eq("status", "failed")
        if empresa_id: query = query.eq("empresa_id", empresa_id)
        res = query.order("fecha", desc=True).limit(5).execute()
        alerts = []
        for r in res.data:
            alerts.append({
                "id": f"alert_{r['id']}",
                "type": "CALL_FAILED",
                "message": f"Llamada fallida al número {r['telefono']}",
                "created_at": r['fecha']
            })
        return alerts
    except Exception as e:
        logger.error(f"Error get_alerts: {e}")
        return []

@router.get("/dashboard/integrations")
async def get_integrations():
    integrations = [
        {"name": "LLM Engine", "provider": "Groq", "active": bool(os.getenv("GROQ_API_KEY")), "model": "Llama 3.3 70B"},
        {"name": "LLM Backup", "provider": "OpenAI", "active": bool(os.getenv("OPENAI_API_KEY")), "model": "GPT-4o"},
        {"name": "LLM Google", "provider": "Google", "active": bool(os.getenv("GOOGLE_API_KEY")), "model": "Gemini 1.5 Pro"},
        {"name": "TTS Engine", "provider": "Cartesia", "active": bool(os.getenv("CARTESIA_API_KEY")), "model": "Sonic Multilingual"},
        {"name": "TTS Backup", "provider": "ElevenLabs", "active": bool(os.getenv("ELEVEN_API_KEY")), "model": "Multilingual v2"},
        {"name": "STT Engine", "provider": "Deepgram", "active": bool(os.getenv("DEEPGRAM_API_KEY")), "model": "Nova-2"},
        {"name": "Real-time", "provider": "LiveKit", "active": bool(os.getenv("LIVEKIT_API_KEY")), "url": os.getenv("LIVEKIT_URL")}
    ]
    return integrations

@router.get("/dashboard/usage-stats")
async def get_usage_stats(empresa_id: Optional[int] = None):
    if not supabase: return {"total_tokens": 0, "total_minutes": 0, "per_model_stats": []}
    try:
        query = supabase.table("encuestas").select("llm_model, seconds_used, status")
        if empresa_id: query = query.eq("empresa_id", empresa_id)
        
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(executor, query.execute)
        
        total_seconds = sum(r.get('seconds_used') or 0 for r in res.data)
        model_stats = {}
        for r in res.data:
            model = r.get('llm_model') or "Standard"
            if model not in model_stats:
                model_stats[model] = {"llm_model": model, "calls": 0, "tokens": 0, "seconds": 0}
            model_stats[model]["calls"] += 1
            model_stats[model]["seconds"] += r.get('seconds_used') or 0
            model_stats[model]["tokens"] += (r.get('seconds_used') or 0) * 15
            
        total_tokens = sum(s["tokens"] for s in model_stats.values())
        return {
            "total_tokens": total_tokens,
            "total_minutes": round(total_seconds / 60, 1),
            "per_model_stats": list(model_stats.values())
        }
    except Exception as e:
        logger.error(f"Error usage stats: {e}")
        return {"total_tokens": 0, "total_minutes": 0, "per_model_stats": []}

@router.get("/ai/limits")
async def get_ai_limits():
    cached_all = await get_ui_cache("api_limits_all", max_age_minutes=60)
    if cached_all: return cached_all

    default_limits = {
        "groq_models": {"llama-3.3-70b-versatile": {"tokens_remaining": 60000, "tokens_limit": 100000, "requests_remaining": 950, "requests_limit": 1000}},
        "openai": {"status": "Active", "usage_usd": 0, "limit_usd": 5},
        "deepgram": {"balances": [{"amount": "0.00", "units": "USD"}]},
        "cartesia": {"tokens_used": 0, "tokens_limit": 100000},
        "elevenlabs": {"character_count": 0, "character_limit": 10000}
    }

    if not supabase: return default_limits
    try:
        res = supabase.table("api_usage_cache").select("*").execute()
        if res.data:
            cache_map = {item["service_name"]: item["data"] for item in res.data}
            for svc, data in cache_map.items():
                if svc == "groq": default_limits["groq_models"] = data
                elif svc in default_limits: default_limits[svc] = data
        return default_limits
    except Exception as e:
        logger.error(f"Error fetching AI limits: {e}")
        return default_limits
