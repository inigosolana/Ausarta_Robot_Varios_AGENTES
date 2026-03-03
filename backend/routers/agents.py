from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Optional
from services.supabase_service import supabase, get_ui_cache
from models.schemas import VoiceAgentCreate, VoiceAgentUpdate
from datetime import datetime
import logging

logger = logging.getLogger("api-backend")

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
async def update_agent(agent_id: str, config: dict):
    if not supabase: return {"error": "No DB"}
    try:
        db_config = {}
        if "name" in config: db_config["name"] = config["name"]
        if "instructions" in config: db_config["instructions"] = config["instructions"]
        if "critical_rules" in config: db_config["critical_rules"] = config["critical_rules"]
        if "greeting" in config: db_config["greeting"] = config["greeting"]
        if "description" in config: db_config["description"] = config["description"]
        if "useCase" in config or "use_case" in config: 
            db_config["use_case"] = config.get("useCase") or config.get("use_case")
        if "voice_id" in config: db_config["voice_id"] = config["voice_id"]
        if "llm_model" in config: db_config["llm_model"] = config["llm_model"]
        if "empresa_id" in config: db_config["empresa_id"] = config["empresa_id"]
        
        db_config["updated_at"] = datetime.utcnow().isoformat()
        
        supabase.table("agent_config").update(db_config).eq("id", int(agent_id)).execute()
        
        # Clasificación automática vía n8n (Agent Classifier)
        if "instructions" in config:
            try:
                import aiohttp
                import os
                n8n_base = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
                url = f"{n8n_base}/classify-agent"
                payload = {"agent_id": agent_id, "instructions": config["instructions"]}
                async with aiohttp.ClientSession() as sess:
                    await sess.post(url, json=payload, timeout=2)
            except: pass
            
        return {"status": "ok", "message": f"Agente {agent_id} actualizado"}
    except Exception as e:
        logger.error(f"Error updating agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/agents")
async def create_agent(config: dict):
    """Crear un nuevo agente dinámico"""
    if not supabase: return JSONResponse(status_code=500, content={"error": "No DB"})
    try:
        db_config = {
            "name": config.get("name", "Nuevo Agente"),
            "instructions": config.get("instructions", "Eres un asistente virtual."),
            "critical_rules": config.get("critical_rules", ""),
            "greeting": config.get("greeting", "Buenas, ¿tiene un momento?"),
            "description": config.get("description", ""),
            "use_case": config.get("useCase") or config.get("use_case", ""),
            "voice_id": config.get("voice_id", "cefcb124-080b-4655-b31f-932f3ee743de"),
            "llm_model": config.get("llm_model", "llama-3.3-70b-versatile"),
            "empresa_id": config.get("empresa_id"),
        }
        
        res = supabase.table("agent_config").insert(db_config).execute()
        new_agent = res.data[0] if res.data else {}
        new_id = str(new_agent.get('id', ''))
        
        # Clasificación automática vía n8n (Agent Classifier)
        try:
            import aiohttp
            import os
            n8n_base = os.getenv("N8N_WEBHOOK_BASE_URL", "https://n8n.ausarta.net/webhook")
            url = f"{n8n_base}/classify-agent"
            payload = {"agent_id": new_id, "instructions": db_config["instructions"]}
            async with aiohttp.ClientSession() as sess:
                await sess.post(url, json=payload, timeout=2)
        except: pass

        new_agent['id'] = new_id
        return {"status": "ok", "agent": new_agent}
    except Exception as e:
        logger.error(f"Error creating agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Eliminar un agente"""
    if not supabase: return JSONResponse(status_code=500, content={"error": "No DB"})
    try:
        supabase.table("agent_config").delete().eq("id", int(agent_id)).execute()
        return {"status": "ok", "message": f"Agente {agent_id} eliminado"}
    except Exception as e:
        logger.error(f"Error deleting agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
