from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from services.supabase_service import supabase, get_ui_cache, clear_ui_cache
from services.audit import log_audit_event
from services.auth import CurrentUser, require_admin
from fastapi import Depends
from models.schemas import VoiceAgentCreate, VoiceAgentUpdate
from datetime import datetime
import logging

logger = logging.getLogger("api-backend")
DEFAULT_AUSARTA_VOICE_ID = "b5aa8098-49ef-475d-89b0-c9262ecf33fd"  # Chica castellano Cartesia
DEFAULT_HUMAN_INSTRUCTIONS = (
    "Habla como una persona real en llamada: tono cercano, frases cortas y naturales. "
    "Si te interrumpen, párate y retoma con amabilidad. "
    "Usa el contexto de empresa para responder sin inventar."
)
ALLOWED_AGENT_TYPES = {
    "ENCUESTA_NUMERICA",
    "ENCUESTA_MIXTA",
    "PREGUNTAS_ABIERTAS",
    "CUALIFICACION_LEAD",
    "AGENDAMIENTO_CITA",
    "SOPORTE_CLIENTE",
}


def _normalize_agent_type(raw_type: Optional[str], raw_survey_type: Optional[str] = None) -> str:
    t = (raw_type or "").strip().upper()
    if t in ALLOWED_AGENT_TYPES:
        return t

    survey = (raw_survey_type or "").strip().lower()
    if survey == "mixed":
        return "ENCUESTA_MIXTA"
    if survey in ("open_questions", "open"):
        return "PREGUNTAS_ABIERTAS"
    return "ENCUESTA_NUMERICA"


def _to_legacy_survey_type(agent_type: str) -> str:
    if agent_type == "ENCUESTA_MIXTA":
        return "mixed"
    if agent_type in {"PREGUNTAS_ABIERTAS", "CUALIFICACION_LEAD", "AGENDAMIENTO_CITA", "SOPORTE_CLIENTE"}:
        return "open_questions"
    return "numeric"

router = APIRouter(prefix="/api", tags=["agents"])

@router.get("/agents")
async def get_agents(empresa_id: Optional[int] = None):
    """Endpoint con cache para lista de agentes"""
    if not empresa_id:
        cached = await get_ui_cache("agents_list")
        if cached: return cached

    if not supabase: return [{"name": "Dakota", "instructions": "Default"}]
    try:
        query = supabase.table("agent_config").select("*")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        
        res = query.execute()
        agents = []
        for agent in (res.data or []):
            prev_tipo = agent.get("tipo_resultados")
            prev_agent_type = agent.get("agent_type")
            prev_survey_type = agent.get("survey_type")
            effective_type = _normalize_agent_type(prev_tipo or prev_agent_type, prev_survey_type)
            agent["tipo_resultados"] = effective_type
            agent["agent_type"] = effective_type
            if (
                prev_tipo != effective_type
                or prev_agent_type != effective_type
                or not prev_survey_type
            ):
                try:
                    supabase.table("agent_config").update({
                        "tipo_resultados": effective_type,
                        "agent_type": effective_type,
                        "survey_type": _to_legacy_survey_type(effective_type),
                        "updated_at": datetime.utcnow().isoformat(),
                    }).eq("id", int(agent["id"])).execute()
                except Exception as sync_err:
                    logger.warning(f"No se pudo sincronizar tipo de agente {agent.get('id')}: {sync_err}")
            agent['id'] = str(agent['id'])
            agents.append(agent)
        return agents
    except Exception as e:
        logger.error(f"Error getting agents: {e}")
        return []

@router.get("/prompts")
async def get_prompts_alias():
    """Alias para que el frontend pueda cargar las instrucciones si usa este endpoint"""
    return await get_agents()

@router.put("/agents/{agent_id}")
async def update_agent(agent_id: str, config: dict, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return {"error": "No DB"}
    try:
        # Agent Config
        db_config = {}
        if "name" in config: db_config["name"] = config["name"]
        if "instructions" in config: db_config["instructions"] = config["instructions"]
        if "critical_rules" in config: db_config["critical_rules"] = config["critical_rules"]
        if "greeting" in config: db_config["greeting"] = config["greeting"]
        if "description" in config: db_config["description"] = config["description"]
        if "useCase" in config or "use_case" in config: 
            db_config["use_case"] = config.get("useCase") or config.get("use_case")
        if "company_context" in config: db_config["company_context"] = config["company_context"]
        if "enthusiasm_level" in config: db_config["enthusiasm_level"] = config["enthusiasm_level"]
        if "voice_id" in config: db_config["voice_id"] = config["voice_id"]
        if "speaking_speed" in config: db_config["speaking_speed"] = config["speaking_speed"]
        if "empresa_id" in config: db_config["empresa_id"] = config["empresa_id"]
        if "tipo_resultados" in config or "agent_type" in config or "survey_type" in config:
            effective_type = _normalize_agent_type(
                config.get("tipo_resultados") or config.get("agent_type"),
                config.get("survey_type"),
            )
            db_config["tipo_resultados"] = effective_type
            db_config["agent_type"] = effective_type
            db_config["survey_type"] = _to_legacy_survey_type(effective_type)
        
        db_config["updated_at"] = datetime.utcnow().isoformat()
        supabase.table("agent_config").update(db_config).eq("id", int(agent_id)).execute()

        # AI Config associated
        ai_config = {}
        if "llm_provider" in config: ai_config["llm_provider"] = config["llm_provider"]
        if "llm_model" in config: ai_config["llm_model"] = config["llm_model"]
        if "tts_provider" in config: ai_config["tts_provider"] = config["tts_provider"]
        if "tts_model" in config: ai_config["tts_model"] = config["tts_model"]
        if "voice_id" in config or "tts_voice" in config: 
            ai_config["tts_voice"] = config.get("voice_id") or config.get("tts_voice")
        if "stt_provider" in config: ai_config["stt_provider"] = config["stt_provider"]
        if "stt_model" in config: ai_config["stt_model"] = config["stt_model"]
        if "language" in config: ai_config["language"] = config["language"]

        if ai_config:
            # Upsert logic
            ai_config["agent_id"] = int(agent_id)
            ai_config["updated_at"] = datetime.utcnow().isoformat()
            
            # Check if exists
            existing = supabase.table("ai_config").select("id").eq("agent_id", int(agent_id)).execute()
            if existing.data:
                supabase.table("ai_config").update(ai_config).eq("agent_id", int(agent_id)).execute()
            else:
                supabase.table("ai_config").insert(ai_config).execute()
        
        # Classification Hook
        if "instructions" in config:
            async def call_webhook():
                try:
                    import aiohttp
                    import os
                    n8n_base = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
                    url = f"{n8n_base}/classify-agent"
                    payload = {"agent_id": agent_id, "instructions": config["instructions"]}
                    async with aiohttp.ClientSession() as sess:
                        await sess.post(url, json=payload)
                except: pass
            import asyncio
            asyncio.create_task(call_webhook())
        
        await clear_ui_cache("agents_list")
        await log_audit_event(
            user_id=current_user.user_id,
            action="update_agent",
            target_type="agent",
            target_id=str(agent_id),
            metadata={"empresa_id": db_config.get("empresa_id"), "fields": list(db_config.keys())},
        )
        return {"status": "ok", "message": f"Agente {agent_id} actualizado"}
    except Exception as e:
        logger.error(f"Error updating agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/agents")
async def create_agent(config: dict, current_user: CurrentUser = Depends(require_admin)):
    if not supabase: return JSONResponse(status_code=500, content={"error": "No DB"})
    try:
        effective_type = _normalize_agent_type(
            config.get("tipo_resultados") or config.get("agent_type"),
            config.get("survey_type"),
        )
        db_config = {
            "name": config.get("name", "Nuevo Agente"),
            "instructions": config.get("instructions", DEFAULT_HUMAN_INSTRUCTIONS),
            "critical_rules": config.get("critical_rules", ""),
            "greeting": config.get("greeting", "Buenas, ¿tiene un momento?"),
            "description": config.get("description", ""),
            "use_case": config.get("useCase") or config.get("use_case", ""),
            "company_context": config.get("company_context", ""),
            "enthusiasm_level": config.get("enthusiasm_level", "Normal"),
            "voice_id": config.get("voice_id") or config.get("tts_voice", DEFAULT_AUSARTA_VOICE_ID),
            "speaking_speed": config.get("speaking_speed", 1.0),
            "empresa_id": config.get("empresa_id"),
            "tipo_resultados": effective_type,
            "agent_type": effective_type,
            "survey_type": _to_legacy_survey_type(effective_type),
        }
        
        res = supabase.table("agent_config").insert(db_config).execute()
        new_agent = res.data[0] if res.data else {}
        new_id = int(new_agent.get('id', 0))
        
        # Create AI Config
        ai_config = {
            "agent_id": new_id,
            "llm_provider": config.get("llm_provider", "groq"),
            "llm_model": config.get("llm_model", "llama-3.3-70b-versatile"),
            "tts_provider": config.get("tts_provider", "cartesia"),
            "tts_model": config.get("tts_model", "sonic-multilingual"),
            "tts_voice": config.get("voice_id") or config.get("tts_voice", DEFAULT_AUSARTA_VOICE_ID),
            "stt_provider": config.get("stt_provider", "deepgram"),
            "stt_model": config.get("stt_model", "nova-2"),
            "language": config.get("language", "es")
        }
        supabase.table("ai_config").insert(ai_config).execute()

        # Classification Hook
        async def call_webhook():
            try:
                import aiohttp
                import os
                n8n_base = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
                url = f"{n8n_base}/classify-agent"
                payload = {"agent_id": str(new_id), "instructions": db_config["instructions"]}
                async with aiohttp.ClientSession() as sess:
                    await sess.post(url, json=payload)
            except: pass
        import asyncio
        asyncio.create_task(call_webhook())

        await clear_ui_cache("agents_list")
        await log_audit_event(
            user_id=current_user.user_id,
            action="create_agent",
            target_type="agent",
            target_id=str(new_id),
            metadata={"empresa_id": db_config.get("empresa_id"), "name": db_config.get("name")},
        )
        return {"status": "ok", "agent": new_agent}
    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, current_user: CurrentUser = Depends(require_admin)):
    """Elimina un agente y ABSOLUTAMENTE TODO lo relacionado (Campañas, leads, encuestas, config)"""
    if not supabase: return JSONResponse(status_code=500, content={"error": "No DB connection"})
    
    aid = int(agent_id)
    try:
        # 1. Buscar campañas del agente para borrar sus leads primero
        camps_res = supabase.table("campaigns").select("id").eq("agent_id", aid).execute()
        camp_ids = [c['id'] for c in (camps_res.data or [])]
        
        if camp_ids:
            # Borrar leads de esas campañas
            supabase.table("campaign_leads").delete().in_("campaign_id", camp_ids).execute()
            # Borrar las campañas
            supabase.table("campaigns").delete().in_("id", camp_ids).execute()
        
        # 2. Borrar encuestas (registros de llamadas)
        supabase.table("encuestas").delete().eq("agent_id", aid).execute()
        
        # 3. Borrar configuración de IA
        supabase.table("ai_config").delete().eq("agent_id", aid).execute()
        
        # 4. Borrar el agente
        supabase.table("agent_config").delete().eq("id", aid).execute()
        
        # 5. Limpiar cache
        await clear_ui_cache("agents_list")
        
        logger.info(f"🗑️ Agente {aid} y todos sus datos eliminados por solicitud del usuario.")
        await log_audit_event(
            user_id=current_user.user_id,
            action="delete_agent",
            target_type="agent",
            target_id=str(aid),
            metadata={"cascade": ["campaigns", "campaign_leads", "encuestas", "ai_config"]},
        )
        return {"status": "ok", "message": f"Agente {aid} y todos sus datos relacionados (campañas, leads, encuestas) han sido eliminados."}
        
    except Exception as e:
        logger.error(f"Error en borrado completo del agente {aid}: {e}")
        return JSONResponse(status_code=500, content={"error": f"Error al realizar el borrado completo: {str(e)}"})
