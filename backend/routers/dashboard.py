from fastapi import APIRouter, Depends, HTTPException
from typing import Optional, Any
from collections import defaultdict
from services.supabase_service import supabase, get_ui_cache, sb_query
from services.livekit_service import lkapi
from services.auth import CurrentUser, get_current_user, require_admin
import os
import asyncio
import aiohttp
import time
from concurrent.futures import ThreadPoolExecutor
import logging

executor = ThreadPoolExecutor(max_workers=20)
logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api", tags=["dashboard"])


def _resolve_empresa(user: CurrentUser, empresa_id_param: Optional[int]) -> Optional[int]:
    if user.role == "superadmin":
        return empresa_id_param
    return int(user.empresa_id or 0)


def _apply_tenant_filter(query, user: CurrentUser, empresa_id_param: Optional[int] = None):
    eid = _resolve_empresa(user, empresa_id_param)
    if eid:
        return query.eq("empresa_id", eid)
    return query


async def _assert_room_allowed(room_name: str, user: CurrentUser) -> None:
    if user.role == "superadmin":
        return
    if not supabase:
        raise HTTPException(status_code=503, detail="Database not connected")
    import re

    encuesta_match = re.search(r"encuesta_(\d+)", room_name)
    if not encuesta_match:
        raise HTTPException(status_code=403, detail="Sala no autorizada")
    encuesta_id = int(encuesta_match.group(1))
    res = await sb_query(
        lambda eid=encuesta_id: supabase.table("encuestas")
        .select("empresa_id")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not res.data or int(res.data[0].get("empresa_id") or 0) != int(user.empresa_id or 0):
        raise HTTPException(status_code=403, detail="Sala no autorizada")

@router.get("/dashboard/stats")
async def get_dashboard_stats(
    empresa_id: Optional[int] = None, 
    agent_id: Optional[int] = None, 
    campaign_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    empresa_id = _resolve_empresa(current_user, empresa_id)
    if not supabase: return {"error": "Database not connected"}
    
    def fetch_total():
        q = supabase.table("encuestas").select("id", count="exact")
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        if start_date: q = q.gte("fecha", start_date)
        if end_date: q = q.lte("fecha", end_date)
        r = q.execute()
        return r.count if r.count is not None else 0

    def fetch_completed():
        q = supabase.table("encuestas").select("id", count="exact").eq("completada", 1)
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        if start_date: q = q.gte("fecha", start_date)
        if end_date: q = q.lte("fecha", end_date)
        r = q.execute()
        return r.count if r.count is not None else 0

    def fetch_pending():
        if empresa_id:
            camps_res = supabase.table("campaigns").select("id").eq("empresa_id", empresa_id).execute()
            camp_ids = [c['id'] for c in camps_res.data]
            if camp_ids:
                q = supabase.table("campaign_leads").select("id", count="exact").eq("status", "pending").in_("campaign_id", camp_ids)
                if start_date: q = q.gte("created_at", start_date)
                if end_date: q = q.lte("created_at", end_date)
                r = q.execute()
                return r.count if r.count is not None else 0
            return 0
        q = supabase.table("campaign_leads").select("id", count="exact").eq("status", "pending")
        if start_date: q = q.gte("created_at", start_date)
        if end_date: q = q.lte("created_at", end_date)
        r = q.execute()
        return r.count if r.count is not None else 0

    def fetch_scores():
        q = supabase.table("encuestas").select("puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, datos_extra")
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        if start_date: q = q.gte("fecha", start_date)
        if end_date: q = q.lte("fecha", end_date)
        return q.execute().data

    def fetch_status_breakdown():
        q = supabase.table("encuestas").select("status")
        if empresa_id: q = q.eq("empresa_id", empresa_id)
        if agent_id: q = q.eq("agent_id", agent_id)
        if campaign_id: q = q.eq("campaign_id", campaign_id)
        if start_date: q = q.gte("fecha", start_date)
        if end_date: q = q.lte("fecha", end_date)
        r = q.execute()
        if not r.data:
            return {}
        from collections import Counter
        statuses = [row.get("status") or "unknown" for row in r.data]
        return dict(Counter(statuses))

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
        except Exception as e:
            logger.warning(f"⚠️ [dashboard] check_question_based falló: {e}")
        return False

    try:
        loop = asyncio.get_event_loop()
        results = await asyncio.gather(
            loop.run_in_executor(executor, fetch_total),
            loop.run_in_executor(executor, fetch_completed),
            loop.run_in_executor(executor, fetch_pending),
            loop.run_in_executor(executor, fetch_scores),
            loop.run_in_executor(executor, fetch_status_breakdown),
            loop.run_in_executor(executor, check_question_based)
        )
        total_calls, completed_calls, pending_calls, scores_data, status_breakdown, is_question_based = results

        avg_comercial = 0.0; avg_instalador = 0.0; avg_rapidez = 0.0; avg_overall = 0.0
        if scores_data:
            vals_com = [r['puntuacion_comercial'] for r in scores_data if r.get('puntuacion_comercial') is not None]
            vals_ins = [r['puntuacion_instalador'] for r in scores_data if r.get('puntuacion_instalador') is not None]
            vals_rap = [r['puntuacion_rapidez'] for r in scores_data if r.get('puntuacion_rapidez') is not None]
            if vals_com: avg_comercial = sum(vals_com) / len(vals_com)
            if vals_ins: avg_instalador = sum(vals_ins) / len(vals_ins)
            if vals_rap: avg_rapidez = sum(vals_rap) / len(vals_rap)
            all_vals = vals_com + vals_ins + vals_rap
            if all_vals:
                avg_overall = sum(all_vals) / len(all_vals)

        return {
            "total_calls": total_calls, "completed_calls": completed_calls, "pending_calls": pending_calls,
            "is_question_based": is_question_based,
            "status_breakdown": status_breakdown or {},
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
async def get_recent_calls(
    empresa_id: Optional[int] = None, 
    agent_id: Optional[int] = None, 
    campaign_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    empresa_id = _resolve_empresa(current_user, empresa_id)
    if not supabase: return []
    try:
        def _fetch_recent():
            cols = "id, telefono, campaign_name, campaign_id, nombre_cliente, fecha, status, llm_model, empresa_id, agent_id"
            query = supabase.table("encuestas").select(cols)
            if empresa_id: query = query.eq("empresa_id", empresa_id)
            if agent_id: query = query.eq("agent_id", agent_id)
            if campaign_id: query = query.eq("campaign_id", campaign_id)
            if start_date: query = query.gte("fecha", start_date)
            if end_date: query = query.lte("fecha", end_date)
            return query.order("fecha", desc=True).limit(50).execute()

        response = await sb_query(_fetch_recent)

        empresas_map = {}
        agent_types_map = {}
        try:
            emp_res = await sb_query(lambda: _apply_tenant_filter(supabase.table("empresas").select("id, nombre"), current_user).execute())
            empresas_map = {e["id"]: e.get("nombre", "—") for e in (emp_res.data or [])}
        except Exception as e:
            logger.warning(f"⚠️ [dashboard] No se pudo cargar mapa de empresas: {e}")
        try:
            agents_res = await sb_query(lambda: _apply_tenant_filter(supabase.table("agent_config").select("id, tipo_resultados, name"), current_user).execute())
            agent_types_map = {str(a["id"]): {"tipo": a.get("tipo_resultados"), "name": a.get("name")} for a in (agents_res.data or [])}
        except Exception as e:
            logger.warning(f"⚠️ [dashboard] No se pudo cargar mapa de agentes: {e}")

        mapped = []
        for r in (response.data or []):
            aid = str(r.get("agent_id") or "")
            camp_id = r.get("campaign_id")
            emp_id = r.get("empresa_id")
            is_test = not camp_id or camp_id == 0
            agent_info = agent_types_map.get(aid, {})

            mapped.append({
                "id": r.get("id"),
                "phone": r.get("telefono", ""),
                "campaign": r.get("campaign_name", r.get("nombre_cliente", "—")),
                "campaign_id": camp_id,
                "date": r.get("fecha", ""),
                "status": r.get("status", "pending"),
                "llm_model": r.get("llm_model"),
                "empresa_id": emp_id,
                "empresa_name": empresas_map.get(emp_id, "—") if emp_id else "—",
                "tipo_resultados": agent_info.get("tipo"),
                "agent_name": agent_info.get("name"),
                "is_test": is_test,
            })

        return mapped
    except Exception as e:
        logger.error(f"Error recent calls: {e}")
        return []

@router.get("/dashboard/top-performers")
async def get_top_performers(
    empresa_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Devuelve la campaña y agente más exitosos por tasa de completadas."""
    if not supabase:
        return {"top_campaign": None, "top_agent": None}
    try:
        cols = "campaign_id, campaign_name, agent_id, status"
        q = supabase.table("encuestas").select(cols)
        empresa_id = _resolve_empresa(current_user, empresa_id)
        if empresa_id:
            q = q.eq("empresa_id", empresa_id)
        if start_date:
            q = q.gte("fecha", start_date)
        if end_date:
            q = q.lte("fecha", end_date)
        q = q.not_.is_("campaign_id", "null")
        res = q.execute()
        rows = res.data or []

        if not rows:
            return {"top_campaign": None, "top_agent": None}


        campaign_stats: dict[str, Any] = defaultdict(lambda: {"total": 0, "completed": 0, "name": ""})
        agent_stats: dict[str, Any] = defaultdict(lambda: {"total": 0, "completed": 0})

        for r in rows:
            cid = r.get("campaign_id")
            aid = r.get("agent_id")
            st = (r.get("status") or "").lower()
            is_completed = 1 if st in ("completada", "completed") else 0

            if cid:
                campaign_stats[cid]["total"] += 1
                campaign_stats[cid]["completed"] += is_completed
                campaign_stats[cid]["name"] = r.get("campaign_name") or ""
            if aid:
                agent_stats[aid]["total"] += 1
                agent_stats[aid]["completed"] += is_completed

        top_campaign = None
        best_rate = -1
        for cid, s in campaign_stats.items():
            if s["total"] >= 2:
                rate = s["completed"] / s["total"]
                if rate > best_rate:
                    best_rate = rate
                    top_campaign = {"id": cid, "name": s["name"], "completed": s["completed"], "total": s["total"], "rate": round(rate * 100, 1)}

        top_agent = None
        best_agent_rate = -1
        agent_names = {}
        try:
            ag_res = _apply_tenant_filter(supabase.table("agent_config").select("id, name"), current_user).execute()
            agent_names = {a["id"]: a.get("name", "") for a in (ag_res.data or [])}
        except:
            pass

        for aid, s in agent_stats.items():
            if s["total"] >= 2:
                rate = s["completed"] / s["total"]
                if rate > best_agent_rate:
                    best_agent_rate = rate
                    top_agent = {"id": aid, "name": agent_names.get(aid, f"Agente #{aid}"), "completed": s["completed"], "total": s["total"], "rate": round(rate * 100, 1)}

        return {"top_campaign": top_campaign, "top_agent": top_agent}
    except Exception as e:
        logger.error(f"Error top performers: {e}")
        return {"top_campaign": None, "top_agent": None}

@router.get("/results")
async def get_all_results(
    empresa_id: Optional[int] = None, 
    agent_id: Optional[int] = None, 
    campaign_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase: return []
    try:
        cols = "id, telefono, fecha, completada, puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez, comentarios, campaign_id, campaign_name, agent_id, agent_type, agent_results, status, llm_model, seconds_used, empresa_id, datos_extra"
        empresa_id = _resolve_empresa(current_user, empresa_id)
        query = supabase.table("encuestas").select(cols)
        if empresa_id: query = query.eq("empresa_id", empresa_id)
        if agent_id: query = query.eq("agent_id", agent_id)
        if campaign_id: query = query.eq("campaign_id", campaign_id)
        if start_date: query = query.gte("fecha", start_date)
        if end_date: query = query.lte("fecha", end_date)
        response = query.order("fecha", desc=True).execute()
        results = response.data        
        try:
            agents_res = _apply_tenant_filter(supabase.table("agent_config").select("id, instructions, critical_rules, survey_type, tipo_resultados"), current_user).execute()
            qs_agents = set()
            agent_types = {}
            agent_critical_rules = {}
            for a in (agents_res.data or []):
                aid = str(a["id"])
                t_res = a.get("tipo_resultados")
                
                if t_res:
                    agent_types[aid] = t_res
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
                    
            emp_res = _apply_tenant_filter(supabase.table("empresas").select("id, nombre"), current_user).execute()
            empresas_map = { e["id"]: e.get("nombre", f"Empresa #{e['id']}") for e in (emp_res.data or []) }
                    
            for res in results:
                aid_res = str(res.get("agent_id"))
                res["is_question_based"] = aid_res in qs_agents
                res["tipo_resultados"] = agent_types.get(aid_res)
                res["agent_critical_rules"] = agent_critical_rules.get(aid_res)
                res["empresa_name"] = empresas_map.get(res.get("empresa_id"))
        except Exception as e_agent:
            logger.error(f"Error enriching query based question agents: {e_agent}")
        return results
    except Exception as e:
        logger.error(f"Error getting results: {e}")
        return []

@router.get("/users")
async def get_users_list(current_user: CurrentUser = Depends(require_admin)):
    if current_user.role == "superadmin":
        cached = await get_ui_cache("users_list")
        if cached: return cached
    if not supabase: return []
    try:
        def _fetch_users():
            q = supabase.table("user_profiles").select("*, empresas(*)")
            if current_user.role != "superadmin":
                q = q.eq("empresa_id", current_user.empresa_id)
            return q.order("created_at", desc=True).execute()
        res = await sb_query(_fetch_users)
        return res.data
    except Exception as e:
        logger.error(f"Error users list: {e}")
        return []

@router.get("/empresas")
async def get_empresas_list(current_user: CurrentUser = Depends(require_admin)):
    if current_user.role == "superadmin":
        cached = await get_ui_cache("empresas_list")
        if cached: return cached
    if not supabase: return []
    try:
        def _fetch_empresas():
            q = supabase.table("empresas").select("*")
            if current_user.role != "superadmin":
                q = q.eq("id", current_user.empresa_id)
            return q.order("nombre").execute()
        res = await sb_query(_fetch_empresas)
        return res.data
    except Exception as e:
        logger.error(f"Error empresas list: {e}")
        return []

@router.get("/dashboard/insights")
async def get_recent_insights(
    empresa_id: Optional[int] = None,
    agent_id: Optional[int] = None,
    campaign_id: Optional[int] = None,
    limit: int = 5,
    current_user: CurrentUser = Depends(get_current_user),
):
    """Últimas llamadas con datos_extra no vacío — para la tarjeta de Insights."""
    if not supabase:
        return []
    try:
        cols = "id, telefono, fecha, status, datos_extra, campaign_name, tipo_resultados"
        empresa_id = _resolve_empresa(current_user, empresa_id)
        query = supabase.table("encuestas").select(cols).neq("datos_extra", None)
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        if agent_id:
            query = query.eq("agent_id", agent_id)
        if campaign_id:
            query = query.eq("campaign_id", campaign_id)
        response = query.order("fecha", desc=True).limit(limit).execute()

        insights = []
        for r in (response.data or []):
            extra = r.get("datos_extra")
            if not extra or (isinstance(extra, dict) and len(extra) == 0):
                continue
            keys_preview = list(extra.keys())[:4] if isinstance(extra, dict) else [] # type: ignore
            insights.append({
                "id": r.get("id"),
                "telefono": r.get("telefono"),
                "fecha": r.get("fecha"),
                "status": r.get("status"),
                "campaign_name": r.get("campaign_name"),
                "keys": keys_preview,
                "datos_extra": extra,
            })
        return insights[:limit]
    except Exception as e:
        logger.error(f"Error insights: {e}")
        return []

@router.get("/alerts")
async def get_alerts(empresa_id: Optional[int] = None, current_user: CurrentUser = Depends(get_current_user)):
    if not supabase: return []
    try:
        empresa_id = _resolve_empresa(current_user, empresa_id)
        query = supabase.table("encuestas").select("*").in_("status", ["fallida", "failed"])
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


@router.post("/alerts/{alert_id}/resolve")
async def resolve_alert(alert_id: str, current_user: CurrentUser = Depends(get_current_user)):
    """
    Marca una alerta como vista en el panel.
    Las alertas se generan desde encuestas fallidas; el frontend también las oculta en cliente.
    """
    encuesta_id: Optional[int] = None
    if alert_id.startswith("alert_"):
        try:
            encuesta_id = int(alert_id.replace("alert_", "", 1))
        except ValueError:
            pass
    logger.info("Alerta resuelta en UI: %s (encuesta=%s)", alert_id, encuesta_id)
    return {"status": "ok", "alert_id": alert_id, "encuesta_id": encuesta_id}


@router.get("/dashboard/integrations")
async def get_integrations(current_user: CurrentUser = Depends(get_current_user)):
    integrations = [
        {"name": "LLM Engine", "provider": "Groq", "active": bool(os.getenv("GROQ_API_KEY")), "model": "Llama 3.3 70B"},
        {"name": "LLM Backup", "provider": "OpenAI", "active": bool(os.getenv("OPENAI_API_KEY")), "model": "GPT-4o"},
        {"name": "LLM Google", "provider": "Google", "active": bool(os.getenv("GOOGLE_API_KEY")), "model": "Gemini 1.5 Pro"},
        {"name": "TTS Engine", "provider": "Cartesia", "active": bool(os.getenv("CARTESIA_API_KEY")), "model": "Sonic Multilingual"},
        {"name": "STT Engine", "provider": "Deepgram", "active": bool(os.getenv("DEEPGRAM_API_KEY")), "model": "Nova-2"},
        {"name": "Real-time", "provider": "LiveKit", "active": bool(os.getenv("LIVEKIT_API_KEY")), "url": os.getenv("LIVEKIT_URL")}
    ]
    return integrations

@router.get("/dashboard/usage-stats")
async def get_usage_stats(
    empresa_id: Optional[int] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase: return {"total_tokens": 0, "total_minutes": 0, "per_model_stats": []}
    try:
        empresa_id = _resolve_empresa(current_user, empresa_id)
        query = supabase.table("encuestas").select("llm_model, seconds_used, status")
        if empresa_id: query = query.eq("empresa_id", empresa_id)
        if start_date: query = query.gte("fecha", start_date)
        if end_date: query = query.lte("fecha", end_date)
        
        loop = asyncio.get_event_loop()
        res = await loop.run_in_executor(executor, query.execute)
        
        total_seconds = sum(r.get('seconds_used') or 0 for r in res.data)
        model_stats: dict[str, dict[str, Any]] = {}
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
async def get_ai_limits(current_user: CurrentUser = Depends(get_current_user)):
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

@router.get("/dashboard/live-sessions")
async def get_live_sessions(current_user: CurrentUser = Depends(get_current_user)):
    """List active LiveKit rooms for supervision with enriched metadata."""
    if not lkapi:
        return []
    try:
        from livekit import api
        import re
        rooms_res = await lkapi.room.list_rooms(api.ListRoomsRequest())
        sessions = []
        now_ts = int(time.time())
        for r in rooms_res.rooms:
            # Extraer metadata del nombre de sala
            name = r.name or ""
            encuesta_match = re.search(r"encuesta_(\d+)", name)
            empresa_match = re.search(r"empresa_(\d+)", name)
            campana_match = re.search(r"campana_(\d+)", name)

            duration_secs = max(0, now_ts - r.creation_time) if r.creation_time else 0

            session_data = {
                "sid": r.sid,
                "name": name,
                "num_participants": r.num_participants,
                "created_at": r.creation_time,
                "duration_seconds": duration_secs,
                "metadata": {
                    "encuesta_id": int(encuesta_match.group(1)) if encuesta_match else None,
                    "empresa_id": int(empresa_match.group(1)) if empresa_match else None,
                    "campaign_id": int(campana_match.group(1)) if campana_match else None,
                },
            }
            if current_user.role != "superadmin" and session_data["metadata"]["empresa_id"] != current_user.empresa_id:
                continue

            # Intentar obtener info de participantes
            participants = []
            for p in (r.metadata or "").split(","):
                if p.strip():
                    participants.append(p.strip())
            if participants:
                session_data["metadata"]["participants"] = participants

            sessions.append(session_data)
        return sessions
    except Exception as e:
        logger.error(f"Error listing LiveKit sessions: {e}")
        return []

@router.get("/dashboard/token")
async def get_monitoring_token(
    room_name: str,
    identity: str = "supervisor",
    current_user: CurrentUser = Depends(get_current_user),
):
    """Generate a LiveKit token for monitoring (supervisor)."""
    if not lkapi:
        raise HTTPException(status_code=500, detail="LiveKit not configured")
    try:
        await _assert_room_allowed(room_name, current_user)
        from livekit import api
        # Create token
        token = (
            api.AccessToken(os.getenv("LIVEKIT_API_KEY"), os.getenv("LIVEKIT_API_SECRET"))
            .with_identity(f"{identity}_{int(time.time())}")
            .with_name("Supervisor")
            .with_grants(api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=False, # Supervisor doesn't speak
                can_subscribe=True,
                can_publish_data=True
            ))
        )
        return {"token": token.to_jwt()}
    except Exception as e:
        logger.error(f"Error generating monitoring token: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@router.get("/dashboard/api-status")
async def get_api_status(current_user: CurrentUser = Depends(get_current_user)):
    """
    Check the connectivity and basic status of external APIs like OpenAI and LiveKit.
    Returns 'active' or 'inactive' to display in the UI Dashboard.
    """
    status = {
        "openai": "inactive",
        "livekit": "inactive",
        "supabase": "active" if supabase else "inactive",
    }

    # Simple OpenAI Key check
    if os.getenv("OPENAI_API_KEY"):
        # Without making a real billing call, we assume active if key exists. 
        # Optionally, one could ping https://api.openai.com/v1/models.
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://api.openai.com/v1/models",
                    headers={"Authorization": f"Bearer {os.getenv('OPENAI_API_KEY')}"},
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as resp:
                    if resp.status == 200:
                        status["openai"] = "active"
                    else:
                        logger.warning(f"OpenAI API check failed with status: {resp.status}")
        except Exception as e:
            logger.warning(f"OpenAI API check error: {e}")

    # Simple LiveKit check
    if os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_URL"):
        # Since LiveKit URL is often a WebSocket, checking it directly might be complex,
        # but if lkapi is initialized, we can consider it active.
        if lkapi:
            status["livekit"] = "active"

    return status
