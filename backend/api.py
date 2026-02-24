import os
import aiohttp
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Optional, Union, List
from dotenv import load_dotenv
from livekit import api
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from supabase import create_client, Client
import logging
import sys

# --- CONFIGURACIÓN DE LOGS ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("api.log", mode='a', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger("api-backend")

load_dotenv()

# --- CONFIGURACIÓN SUPABASE ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ ERROR CRÍTICO: Faltan variables SUPABASE_URL o SUPABASE_KEY en .env")
    # No detenemos la ejecución para que al menos arranque la API, pero fallará al usar BD
    supabase: Client = None
else:
    try:
        supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
        print(f"✅ Conectado a Supabase: {SUPABASE_URL}")
    except Exception as e:
        logger.error(f"❌ Error al conectar a Supabase: {e}")
        supabase = None

app = FastAPI(title="Ausarta Voice Agent API", version="1.0.0")

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- LOGS SIP ---
@app.get("/api/logs/sip")
async def get_sip_logs(lines: int = 100):
    try:
        log_path = "api.log"
        if os.path.exists(log_path):
            with open(log_path, "r", encoding="utf-8") as f:
                content = f.readlines()
                return {"logs": [l.strip() for l in content[-lines:]]}
        return {"logs": ["No hay logs acumulados en api.log."]}
    except Exception as e:
        return {"error": str(e)}

# --- MODELOS PYDANTIC ---
class VoiceAgentCreate(BaseModel):
    name: str

class VoiceAgentUpdate(BaseModel):
    instructions: Optional[str] = None
    greeting: Optional[str] = None
    agent_config: Optional[dict] = None # Para guardar configuraciones completas si se necesita

class CampaignCreate(BaseModel):
    name: str
    agent_id: int
    scheduled_time: Optional[datetime] = None
    leads_csv: Optional[str] = None # Contenido CSV en base64 o raw string
    retries_count: int = 3
    retry_interval: int = 60 # Minutos - Default 1 hora

class CampaignLeadModel(BaseModel):
    phone_number: str
    customer_name: str
    id: Optional[int] = None # ID opcional si viene de fuera

class CampaignModel(BaseModel):
    name: str
    agent_id: int
    empresa_id: Optional[int] = None
    status: str = "pending"
    scheduled_time: Optional[datetime] = None
    retries_count: int = 3
    retry_interval: int = 180

class LlmConfig(BaseModel):
    llm_provider: str
    llm_model: str
    stt_provider: str
    stt_model: str
    tts_provider: str
    tts_model: str
    tts_voice: str
    language: str

class EncuestaData(BaseModel):
    id_encuesta: int
    status: Optional[str] = None
    nota_comercial: Optional[int] = None
    nota_instalador: Optional[int] = None
    nota_rapidez: Optional[int] = None
    comentarios: Optional[str] = None
    transcription: Optional[str] = None
    seconds_used: Optional[int] = None
    llm_model: Optional[str] = None

class CallEndRequest(BaseModel):
    nombre_sala: str

class AIPromptRequest(BaseModel):
    user_request: str
    empresa_id: Optional[int] = None
    current_name: Optional[str] = None
    current_use_case: Optional[str] = None
    current_greeting: Optional[str] = None
    current_description: Optional[str] = None
    current_instructions: Optional[str] = None
    current_critical_rules: Optional[str] = None

# --- LIVEKIT SETUP ---
LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')
lkapi = api.LiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)

# --- ENDPOINTS ---

@app.get("/")
async def root():
    return {"status": "ok", "service": "Ausarta Backend", "database": "Supabase"}

@app.post("/api/ai/generate-prompt")
async def generate_ai_prompt(req: AIPromptRequest):
    try:
        from openai import AsyncOpenAI
        import json
        client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))
        
        empresa_name = "la empresa"
        if req.empresa_id and supabase:
            try:
                emp_res = supabase.table("empresas").select("nombre").eq("id", req.empresa_id).execute()
                if emp_res.data:
                    empresa_name = emp_res.data[0]["nombre"]
            except Exception as e_emp:
                logger.warning(f"No se pudo cargar nombre de empresa: {e_emp}")

        system_prompt = f"""
Eres un experto en diseñar e implementar Agentes Telefónicos de IA.
El usuario te dará un propósito general o unas preguntas que quiere hacer en su campaña. O tal vez te pida editar un agente existente.
Tu tarea es devolver la configuración del agente EN FORMATO JSON ESTRICTO, con las siguientes claves y nada más:
- "name": Un nombre creativo y común (ej: Dakota, Carlos, Laura) para el agente.
- "use_case": Frase muy breve de qué va (ej: Encuesta de satisfacción).
- "greeting": El saludo inicial. Como regla general, debe decir que es el asistente virtual de "{empresa_name}". Ejemplo: "Hola, soy [name], el asistente virtual de {empresa_name}. ¿Tiene un momento?".
- "description": Breve descripción interna del propósito.
- "instructions": Todo el texto del prompt, en español, con las reglas de cómo debe comportarse. Si es una encuesta, incluye explícitamente "Pregunta 1:", "Pregunta 2:", etc. como instrucciones de paso a paso.
- "critical_rules": Una lista de 3 a 5 reglas críticas e innegociables que el agente debe seguir pase lo que pase (ej: "No inventar datos", "Siempre despedirse", "No saltar a la siguiente pregunta sin confirmar").

SOLO DEBES DEVOLVER EL TEXTO EN FORMATO JSON, QUE SEA PUEDE CARGAR MEDIANTE JSON.LOADS(). SIN ACENTOS EN LAS CLAVES DEL JSON (sólo usa las indicadas en inglés). SI USAS MARKDOWN PARA EL JSON (```json), EL SISTEMA FALLARÁ. DEVUELVE DIRECTAMENTE `{{"name": ...}}`.
"""
        
        if any([req.current_name, req.current_instructions, req.current_greeting]):
            system_prompt += f"""
CONFIGURACIÓN ACTUAL DEL AGENTE:
- Nombre: {req.current_name or ''}
- Caso de uso: {req.current_use_case or ''}
- Saludo: {req.current_greeting or ''}
- Descripción: {req.current_description or ''}
- Instrucciones: {req.current_instructions or ''}
- Reglas críticas: {req.current_critical_rules or ''}

IMPORTANTE: El usuario quiere ACTUALIZAR este agente con el nuevo request. Modifica solo lo que pida el usuario y mantén el resto de la configuración si sigue teniendo sentido.
"""
        response = await client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.user_request}
            ],
            temperature=0.7,
            max_tokens=1500
        )
        
        raw_content = response.choices[0].message.content.strip()
        if raw_content.startswith("```json"):
            raw_content = raw_content[7:-3].strip()
        elif raw_content.startswith("```"):
            raw_content = raw_content[3:-3].strip()
            
        data = json.loads(raw_content)
        return {"success": True, "data": data}
    except Exception as e:
        logger.error(f"Error AI Prompt Generator: {e}")
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})

# --- DASHBOARD METRICS ---
@app.get("/api/dashboard/stats")
async def get_dashboard_stats(empresa_id: Optional[int] = None, agent_id: Optional[int] = None, campaign_id: Optional[int] = None):
    if not supabase: return {"error": "Database not connected"}
    
    try:
        # Total llamadas
        query_total = supabase.table("encuestas").select("count", count="exact")
        if empresa_id:
            query_total = query_total.eq("empresa_id", empresa_id)
        if agent_id:
            query_total = query_total.eq("agent_id", agent_id)
        if campaign_id:
            query_total = query_total.eq("campaign_id", campaign_id)
        res_total = query_total.execute()
        total_calls = res_total.count if res_total.count is not None else 0
        
        # Completadas
        query_comp = supabase.table("encuestas").select("count", count="exact").eq("completada", 1)
        if empresa_id:
            query_comp = query_comp.eq("empresa_id", empresa_id)
        if agent_id:
            query_comp = query_comp.eq("agent_id", agent_id)
        if campaign_id:
            query_comp = query_comp.eq("campaign_id", campaign_id)
        res_completed = query_comp.execute()
        completed_calls = res_completed.count if res_completed.count is not None else 0
        
        # Pendientes (Campaign Leads)
        # Para leads pendientes, buscamos los que pertenecen a campañas de esta empresa
        if empresa_id:
            # Primero obtenemos IDs de campañas de la empresa
            camps_res = supabase.table("campaigns").select("id").eq("empresa_id", empresa_id).execute()
            camp_ids = [c['id'] for c in camps_res.data]
            if camp_ids:
                res_pending = supabase.table("campaign_leads").select("count", count="exact").eq("status", "pending").in_("campaign_id", camp_ids).execute()
                pending_calls = res_pending.count if res_pending.count is not None else 0
            else:
                pending_calls = 0
        else:
            res_pending = supabase.table("campaign_leads").select("count", count="exact").eq("status", "pending").execute()
            pending_calls = res_pending.count if res_pending.count is not None else 0
        
        # Promedios
        query_scores = supabase.table("encuestas").select("puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez").not_.is_("puntuacion_comercial", "null")
        if empresa_id:
            query_scores = query_scores.eq("empresa_id", empresa_id)
        if agent_id:
            query_scores = query_scores.eq("agent_id", agent_id)
        if campaign_id:
            query_scores = query_scores.eq("campaign_id", campaign_id)
        res_scores = query_scores.execute()
        
        avg_comercial = 0
        avg_instalador = 0
        avg_rapidez = 0
        avg_overall = 0
        count = len(res_scores.data)
        
        if count > 0:
            sum_com = sum(r['puntuacion_comercial'] or 0 for r in res_scores.data)
            sum_ins = sum(r['puntuacion_instalador'] or 0 for r in res_scores.data)
            sum_rap = sum(r['puntuacion_rapidez'] or 0 for r in res_scores.data)
            
            avg_comercial = sum_com / count
            avg_instalador = sum_ins / count
            avg_rapidez = sum_rap / count
            avg_overall = (avg_comercial + avg_instalador + avg_rapidez) / 3

        # Determinar si es basado en preguntas
        is_question_based = False
        try:
            if agent_id:
                agent_res = supabase.table("agent_config").select("instructions").eq("id", agent_id).maybeSingle().execute()
                if agent_res.data:
                    inst = agent_res.data.get("instructions", "").lower()
                    if "pregunta 1" in inst or "pregunta 2" in inst or "pregunta:" in inst:
                        is_question_based = True
            elif campaign_id:
                camp_res = supabase.table("campaigns").select("agent_id").eq("id", campaign_id).maybeSingle().execute()
                if camp_res.data and camp_res.data.get("agent_id"):
                    agent_res = supabase.table("agent_config").select("instructions").eq("id", camp_res.data["agent_id"]).maybeSingle().execute()
                    if agent_res.data:
                        inst = agent_res.data.get("instructions", "").lower()
                        if "pregunta 1" in inst or "pregunta 2" in inst or "pregunta:" in inst:
                            is_question_based = True
        except Exception as e_qb:
            print(f"Error checking question based: {e_qb}")

        return {
            "total_calls": total_calls,
            "completed_calls": completed_calls,
            "pending_calls": pending_calls,
            "is_question_based": is_question_based,
            "avg_scores": {
                "comercial": round(float(avg_comercial), 1),
                "instalador": round(float(avg_instalador), 1),
                "rapidez": round(float(avg_rapidez), 1),
                "overall": round(float(avg_overall), 1)
            }
        }
    except Exception as e:
        print(f"Error stats: {e}")
        return {"total_calls": 0, "completed_calls": 0, "pending_calls": 0, "avg_scores": {}}

@app.get("/api/dashboard/recent-calls")
async def get_recent_calls(empresa_id: Optional[int] = None, agent_id: Optional[int] = None, campaign_id: Optional[int] = None):
    if not supabase: return []
    try:
        query = supabase.table("encuestas").select("*")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        if agent_id:
            query = query.eq("agent_id", agent_id)
        if campaign_id:
            query = query.eq("campaign_id", campaign_id)
        response = query.order("fecha", desc=True).limit(50).execute()
        # Mapeamos los campos de la BD al formato que espera el frontend
        mapped = []
        for r in response.data:
            mapped.append({
                "id": r.get("id"),
                "phone": r.get("telefono", ""),
                "campaign": r.get("campaign_name", r.get("nombre_cliente", "—")),
                "date": r.get("fecha", ""),
                "status": r.get("status", "pending"),
                "llm_model": r.get("llm_model"),
                "scores": {
                    "comercial": r.get("puntuacion_comercial"),
                    "instalador": r.get("puntuacion_instalador"),
                    "rapidez": r.get("puntuacion_rapidez")
                }
            })
        return mapped
    except Exception as e:
        print(f"Error recent calls: {e}")
        return []

@app.get("/api/results")
async def get_all_results(empresa_id: Optional[int] = None, agent_id: Optional[int] = None, campaign_id: Optional[int] = None):
    if not supabase: return []
    try:
        # Traemos todos los resultados de encuestas
        query = supabase.table("encuestas").select("*")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        if agent_id:
            query = query.eq("agent_id", agent_id)
        if campaign_id:
            query = query.eq("campaign_id", campaign_id)
        response = query.order("fecha", desc=True).execute()
        
        results = response.data
        
        # Enriquecer con is_question_based
        try:
            agents_res = supabase.table("agent_config").select("id, instructions, critical_rules").execute()
            qs_agents = set()
            agent_critical_rules = {}
            for a in (agents_res.data or []):
                inst_lower = a.get("instructions", "").lower()
                if "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower:
                    qs_agents.add(str(a["id"]))
                if a.get("critical_rules"):
                    agent_critical_rules[str(a["id"])] = a["critical_rules"]
            
            for res in results:
                res["is_question_based"] = str(res.get("agent_id")) in qs_agents
                res["agent_critical_rules"] = agent_critical_rules.get(str(res.get("agent_id")))
        except Exception as e_agent:
            print(f"Error enriching query based question agents: {e_agent}")
            
        return results
    except Exception as e:
        print(f"Error getting results: {e}")
        return []


# --- ALERTAS ---
@app.get("/api/alerts")
async def get_alerts(empresa_id: Optional[int] = None):
    # En un sistema real, esto vendría de una tabla 'alerts'
    # Por ahora devolvemos una alerta de ejemplo si hay fallos recientes
    if not supabase: return []
    try:
        query = supabase.table("encuestas").select("*").eq("status", "failed")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
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
    except:
        return []

@app.get("/api/dashboard/integrations")
async def get_integrations():
    """Estado de las APIs configuradas"""
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

@app.get("/api/dashboard/usage-stats")
async def get_usage_stats(empresa_id: Optional[int] = None):
    if not supabase: return {"total_tokens": 0, "total_minutes": 0, "per_model_stats": []}
    
    try:
        query = supabase.table("encuestas").select("llm_model, seconds_used, status")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        res = query.execute()
        
        total_seconds = sum(r.get('seconds_used') or 0 for r in res.data)
        
        # Agrupar por modelo
        model_stats = {}
        for r in res.data:
            model = r.get('llm_model') or "Standard"
            if model not in model_stats:
                model_stats[model] = {"llm_model": model, "calls": 0, "tokens": 0, "seconds": 0}
            
            model_stats[model]["calls"] += 1
            model_stats[model]["seconds"] += r.get('seconds_used') or 0
            # Estimación de tokens (aprox 15 tokens por segundo de conversación)
            model_stats[model]["tokens"] += (r.get('seconds_used') or 0) * 15
            
        total_tokens = sum(s["tokens"] for s in model_stats.values())
        
        return {
            "total_tokens": total_tokens,
            "total_minutes": round(total_seconds / 60, 1),
            "per_model_stats": list(model_stats.values())
        }
    except Exception as e:
        print(f"Error usage stats: {e}")
        return {"total_tokens": 0, "total_minutes": 0, "per_model_stats": []}

@app.get("/api/ai/limits")
async def get_ai_limits():
    """Mock de límites para el frontend"""
    return {
        "groq_models": {
            "llama-3.3-70b-versatile": {"tokens_remaining": 60000, "tokens_limit": 100000, "requests_remaining": 950, "requests_limit": 1000},
            "llama-3.1-8b-instant": {"tokens_remaining": 25000, "tokens_limit": 30000, "requests_remaining": 480, "requests_limit": 500}
        },
        "openai": {"active": True, "tokens_remaining": 850000, "tokens_limit": 1000000, "requests_remaining": 4500, "requests_limit": 5000, "info": "Tier 1 Account"},
        "deepgram": {"balances": [{"amount": "12.45", "units": "USD"}]},
        "cartesia": {"active": True, "info": "Enterprise Plan - Unlimited Credits", "dashboard_url": "https://play.cartesia.ai/"},
        "google": {"active": True}
    }

# --- CALL CONTROL ---

@app.post("/colgar")
async def finalizar_llamada(req: CallEndRequest):
    """Corta la llamada en LiveKit"""
    try:
        print(f"✂️ Solicitud de colgar sala: {req.nombre_sala}")
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=req.nombre_sala))
        return {"status": "ok", "message": f"Sala {req.nombre_sala} cerrada"}
    except Exception as e:
        print(f"⚠️ Error al cerrar sala {req.nombre_sala}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/guardar-encuesta")
async def guardar_encuesta(datos: EncuestaData):
    if not supabase: return {"status": "error", "message": "No DB connection"}
    
    print(f"📥 [API] Recibiendo datos encuesta {datos.id_encuesta}: {datos.model_dump(exclude_none=True)}")
    
    update_data = {}
    
    if datos.nota_comercial is not None: update_data["puntuacion_comercial"] = datos.nota_comercial
    if datos.nota_instalador is not None: update_data["puntuacion_instalador"] = datos.nota_instalador
    if datos.nota_rapidez is not None: update_data["puntuacion_rapidez"] = datos.nota_rapidez
    if datos.comentarios is not None: update_data["comentarios"] = datos.comentarios
    if datos.transcription is not None: update_data["transcription"] = datos.transcription
    if datos.seconds_used is not None: update_data["seconds_used"] = datos.seconds_used
    if datos.llm_model is not None: update_data["llm_model"] = datos.llm_model
    
    # Lógica de estados
    status_final = datos.status
    es_completada = False
    
    # Si viene status explícito (ej: 'rejected_opt_out' o 'completed'), lo respetamos
    if datos.status:
        update_data["status"] = datos.status
        if datos.status == 'completed':
            es_completada = True
            update_data["completada"] = 1 # TINYINT 1
    
    # Si NO viene status, deducimos 'incomplete' si hay datos parciales y no estaba ya terminada
    elif update_data: # Si hay algo que actualizar
         # Primero verificamos estado actual para no sobrescribir 'completed'
         curr = supabase.table("encuestas").select("status").eq("id", datos.id_encuesta).execute()
         if curr.data and curr.data[0]['status'] not in ('completed', 'rejected_opt_out'):
             update_data["status"] = 'incomplete'

    if not update_data:
        return {"status": "ignored", "message": "No data to update"}

    # update_data["updated_at"] = datetime.utcnow().isoformat()

    try:
        supabase.table("encuestas").update(update_data).eq("id", datos.id_encuesta).execute()
        
        # Si la encuesta se completó o rechazó, actualizamos el LEAD asociado también
        # Buscamos el lead por call_id (que es el id_encuesta)
        if datos.status in ('completed', 'rejected_opt_out', 'incomplete', 'failed'):
             lead_update = {"status": datos.status}
             
             # Si es fallo o incompleta, programamos reintento automático
             if datos.status in ('incomplete', 'failed'):
                 # Intentar obtener el intervalo de reintento de la campaña
                 retry_seconds = 3600 # Default 1 hora
                 try:
                     # Obtener campaign_id del lead
                     lead_res = supabase.table("campaign_leads").select("campaign_id").eq("call_id", datos.id_encuesta).limit(1).execute()
                     if lead_res.data:
                         camp_id = lead_res.data[0]['campaign_id']
                         # Obtener retry_interval de la campaña
                         camp_res = supabase.table("campaigns").select("retry_interval").eq("id", camp_id).limit(1).execute()
                         if camp_res.data:
                             camp_retry = camp_res.data[0]['retry_interval']
                             # Asegurarse que sea un valor razonable
                             if camp_retry and camp_retry > 0:
                                 retry_seconds = camp_retry
                 except Exception as ex_interval:
                     print(f"⚠️ Error fetching campaign retry interval: {ex_interval}")

                 next_retry = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
                 lead_update["next_retry_at"] = next_retry
             
             supabase.table("campaign_leads").update(lead_update).eq("call_id", datos.id_encuesta).execute()

        return {"status": "ok", "updated": update_data}
    except Exception as e:
        print(f"❌ Error DB al guardar: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# --- CONFIGURACIÓN DEL AGENTE ---

import time
import random

@app.post("/api/calls/outbound")
async def make_outbound_call(request: dict):
    """Endpoint para llamadas de prueba desde el Dashboard"""
    phone = request.get("phoneNumber")
    agent_id = request.get("agentId", "1")
    
    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number is required"})

    print(f"📞 [API] Iniciando solicitud de llamada a {phone} (Agent ID: {agent_id})...")
    
    try:
        # 1. Crear registro en BD
        if supabase:
            # Obtener empresa_id del agente si no viene en el request
            emp_id = request.get("empresa_id")
            if not emp_id and agent_id:
                try:
                    agent_res = supabase.table("agent_config").select("empresa_id").eq("id", agent_id).execute()
                    if agent_res.data:
                        emp_id = agent_res.data[0].get("empresa_id")
                except: pass

            encuesta_data = {
                "telefono": phone,
                "nombre_cliente": "Prueba Dashboard",
                "fecha": datetime.now(timezone.utc).isoformat(),
                "status": "initiated",
                "completada": 0,
                "agent_id": agent_id,
                "empresa_id": emp_id
            }
            res_enc = supabase.table("encuestas").insert(encuesta_data).execute()
            encuesta_id = res_enc.data[0]['id']
        else:
            encuesta_id = random.randint(1000, 9999)
            
        # 2. Configurar LiveKit con nombre de sala ÚNICO
        sip_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
        room_name = f"encuesta_{encuesta_id}_{int(time.time())}"

        print(f"📡 [API] Creando sala: {room_name}")
        try:
            await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))
        except Exception as e:
            print(f"⚠️ [API] Aviso al crear sala (puede que ya exista): {e}")

        # 3. Dial Out
        logger.info(f"☎️ [API] Marcando vía SIP a {phone} en sala {room_name}...")
        print(f"☎️ [API] Marcando vía SIP a {phone} en sala {room_name}...", flush=True)
        try:
            sip_res = await lkapi.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"user_{phone}_{int(time.time())}",
                participant_name="Test User"
            ))
            logger.info(f"✅ [API] Respuesta SIP: {sip_res}")
            print(f"✅ [API] Respuesta SIP: {sip_res}", flush=True)
        except Exception as sip_err:
            logger.error(f"❌ [API] Error creando participante SIP: {sip_err}")
            print(f"❌ [API] Error creando participante SIP: {sip_err}", flush=True)
            raise sip_err

        # 4. FORZAR UNIÓNN DEL AGENTE (Job Dispatch)
        # Esto asegura que LiveKit mande al agente Dakota-1ef9 a la sala inmediatamente
        print(f"🚀 [API] Solicitando despacho de agente genérico a sala {room_name}...")
        try:
            await lkapi.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                agent_name="",
                room=room_name
            ))
        except Exception as e:
            print(f"⚠️ [API] No se pudo forzar despacho (puede que ya exista regla): {e}")

        return {"status": "ok", "roomName": room_name, "callId": encuesta_id}
        
    except Exception as e:
        print(f"❌ [API] Error fatal en outbound call: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/agents")
async def get_agents(empresa_id: Optional[int] = None):
    """Endpoint compatible con frontend que espera lista de agentes"""
    if not supabase: return [{"name": "Dakota", "instructions": "Default"}]
    try:
        query = supabase.table("agent_config").select("*")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
        
        res = query.execute()
        
        if res.data:
            # Frontend espera 'instructions' en el objeto principal
            # Y 'id' como string si es posible
            agents = []
            for agent in res.data:
                agent['id'] = str(agent['id'])
                agents.append(agent)
            return agents # Devolvemos lista
        else:
            return []
    except Exception as e:
        print(f"Error getting agents: {e}")
        return []

@app.get("/api/prompts")
async def get_prompts_alias():
    """Alias para que el frontend pueda cargar las instrucciones si usa este endpoint"""
    return await get_agents()

@app.put("/api/agents/{agent_id}")
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
        
        # Update the specific agent by its ID
        supabase.table("agent_config").update(db_config).eq("id", int(agent_id)).execute()
            
        return {"status": "ok", "message": f"Agente {agent_id} actualizado"}
    except Exception as e:
        print(f"Error updating agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/agents")
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
        new_agent['id'] = str(new_agent.get('id', ''))
        
        return {"status": "ok", "agent": new_agent}
    except Exception as e:
        print(f"Error creating agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/agents/{agent_id}")
async def delete_agent(agent_id: str):
    """Eliminar un agente"""
    if not supabase: return JSONResponse(status_code=500, content={"error": "No DB"})
    try:
        supabase.table("agent_config").delete().eq("id", int(agent_id)).execute()
        return {"status": "ok", "message": f"Agente {agent_id} eliminado"}
    except Exception as e:
        print(f"Error deleting agent: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- CONFIGURACIÓN DE MODELOS (AI) ---

@app.get("/api/ai/config")
async def get_ai_config():
    if not supabase: return {"llm_provider": "groq"}
    try:
        res = supabase.table("ai_config").select("*").limit(1).execute()
        return res.data[0] if res.data else {}
    except Exception as e:
        print(f"Error AI config: {e}")
        return {}

@app.post("/api/ai/config")
async def update_ai_config(config: dict):
    if not supabase: return {"error": "No DB"}
    try:
        curr = supabase.table("ai_config").select("id").limit(1).execute()
        if not curr.data:
            supabase.table("ai_config").insert(config).execute()
        else:
            first_id = curr.data[0]['id']
            # Filtrar
            valid_fields = ["llm_provider", "llm_model", "tts_provider", "tts_model", "tts_voice", "stt_provider", "stt_model"]
            clean_config = {k: v for k, v in config.items() if k in valid_fields}
            clean_config["updated_at"] = datetime.utcnow().isoformat()
            
            supabase.table("ai_config").update(clean_config).eq("id", first_id).execute()
            
        return {"status": "ok", "message": "Modelos actualizados"}
    except Exception as e:
        print(f"Error updating AI config: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- ALIAS FOR FRONTEND COMPATIBILITY ---
@app.get("/api/settings")
async def get_settings_alias():
    return await get_ai_config()

@app.post("/api/settings")
async def update_settings_alias(config: dict):
    return await update_ai_config(config)

# --- CAMPAIGN MANAGEMENT ---

@app.delete("/api/campaigns/{campaign_id}")
async def delete_campaign(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        # Borrar leads primero (aunque Cascade delete en DB debería hacerlo, mejor asegurar)
        supabase.table("campaign_leads").delete().eq("campaign_id", campaign_id).execute()
        # Borrar campaña
        supabase.table("campaigns").delete().eq("id", campaign_id).execute()
        return {"status": "ok", "message": f"Campaña {campaign_id} eliminada"}
    except Exception as e:
        print(f"Error deleting campaign: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/admin/users")
async def create_auth_user(payload: dict):
    """Crea un usuario administrativamente saltando límites de correo"""
    email = payload.get("email")
    password = payload.get("password")
    full_name = payload.get("full_name")
    role = payload.get("role")
    empresa_id = payload.get("empresa_id")

    if not email or not password:
        return JSONResponse(status_code=400, content={"error": "Email y contraseña son obligatorios"})

    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")
    try:
        admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)
        
        # Crear en Auth con auto-confirmación
        res = admin_client.auth.admin.create_user({
            "email": email,
            "password": password,
            "user_metadata": {"full_name": full_name, "role": role},
            "email_confirm": True
        })
        
        user_id = res.user.id
        
        # Crear perfil y permisos
        supabase.table("user_profiles").upsert({
            "id": user_id,
            "email": email,
            "full_name": full_name,
            "role": role,
            "empresa_id": empresa_id
        }).execute()

        # Permisos por defecto
        modules = ["overview", "agents", "test_call", "campaigns", "ai_models", "telephony", "results", "usage", "users", "billing", "settings"]
        perms = [{"user_id": user_id, "module": m, "enabled": True} for m in modules]
        supabase.table("user_permissions").insert(perms).execute()

        return {"status": "ok", "user_id": user_id}
    except Exception as e:
        logger.error(f"❌ Error al crear usuario admin: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/admin/users/{user_id}")
async def delete_auth_user(user_id: str):
    """Elimina un usuario de Supabase Auth (requiere Service Role Key)"""
    if not supabase: 
        return JSONResponse(status_code=500, content={"error": "No hay conexión con la base de datos"})
    
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not service_role_key:
        # Fallback: intentar usar la key normal si por casualidad fuera la de servicio
        service_role_key = os.getenv("SUPABASE_KEY")

    try:
        # Creamos un cliente con privilegios de root para esta operación
        admin_client = create_client(os.getenv("SUPABASE_URL"), service_role_key)
        # Auth Admin API de Supabase
        admin_client.auth.admin.delete_user(user_id)
        
        # También borramos explícitamente el perfil y permisos por si no hay CASCADE
        supabase.table("user_permissions").delete().eq("user_id", user_id).execute()
        supabase.table("user_profiles").delete().eq("id", user_id).execute()
        
        logger.info(f"🗑️ Usuario {user_id} eliminado completamente del sistema")
        return {"status": "ok", "message": f"Usuario {user_id} eliminado correctamente"}
    except Exception as e:
        logger.error(f"❌ Error al borrar usuario admin: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/campaigns")
async def create_campaign(campaign: CampaignModel, leads: List[CampaignLeadModel]):
    if not supabase: return {"error": "No DB"}
    
    try:
        # Lógica de auto-activación
        status_final = campaign.status
        if not campaign.scheduled_time and status_final == 'pending':
            status_final = 'active'

        # 1. Crear Campaña
        camp_data = {
            "name": campaign.name,
            "agent_id": campaign.agent_id,
            "empresa_id": campaign.empresa_id,
            "status": status_final,
            "scheduled_time": campaign.scheduled_time.isoformat() if campaign.scheduled_time else None,
            "retries_count": campaign.retries_count,
            "retry_interval": campaign.retry_interval * 60, # Convertir minutos a segundos para consistencia interna
            "created_at": datetime.utcnow().isoformat()
        }
        res_camp = supabase.table("campaigns").insert(camp_data).execute()
        campaign_id = res_camp.data[0]['id']
        
        # 2. Insertar Leads
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
            
        # El worker ya está corriendo en background desde el startup y detectará la nueva campaña activa
        # No lanzamos otro process_campaigns() aquí para evitar concurrencia duplicada.
             
        return {"id": campaign_id, "message": f"Campaña creada con {len(leads_data)} leads"}
        
    except Exception as e:
        print(f"Error creando campaña: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/campaigns")
async def list_campaigns(empresa_id: Optional[int] = None):
    if not supabase: return []
    try:
        # Traer campañas ordenadas por fecha reciente
        query = supabase.table("campaigns").select("*")
        if empresa_id:
            query = query.eq("empresa_id", empresa_id)
            
        res = query.order("created_at", desc=True).limit(50).execute()
        return res.data
    except Exception as e:
        print(f"Error listing campaigns: {e}")
        return []

@app.get("/api/campaigns/{campaign_id}")
async def get_campaign_details(campaign_id: int):
    if not supabase: return {"error": "No DB"}
    try:
        # 1. Obtener datos de la campaña
        res_camp = supabase.table("campaigns").select("*").eq("id", campaign_id).execute()
        if not res_camp.data:
            return JSONResponse(status_code=404, content={"error": "Campaign not found"})
        
        campaign = res_camp.data[0]
        
        # Check if agent is question-based
        is_question_based = False
        try:
            agent_res = supabase.table("agent_config").select("instructions").eq("id", campaign["agent_id"]).execute()
            if agent_res.data:
                inst_lower = agent_res.data[0].get("instructions", "").lower()
                if "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower:
                    is_question_based = True
        except Exception as e:
            print(f"Error fetching agent for question detection: {e}")
            
        campaign["is_question_based"] = is_question_based
        
        # 2. Obtener leads asociados
        res_leads = supabase.table("campaign_leads").select("*").eq("campaign_id", campaign_id).execute()
        leads = res_leads.data
        
        # 3. Obtener encuestas asociadas para enriquecer datos
        call_ids = [l['call_id'] for l in leads if l.get('call_id')]
        surveys_map = {}
        if call_ids:
            try:
                # Traer encuestas en batch (puede requerir paginación si son muchas, pero para MVP vale)
                res_surveys = supabase.table("encuestas").select("*").in_("id", call_ids).execute()
                for s in res_surveys.data:
                    surveys_map[s['id']] = s
            except Exception as e:
                print(f"Error fetching surveys for campaign: {e}")

        # 4. Calcular estadísticas y enriquecer leads
        stats = {
            "total": len(leads),
            "pending": 0,
            "calling": 0,
            "called": 0,
            "completed": 0,
            "failed": 0,
            "incomplete": 0
        }
        
        # Métricas de calidad (Promedios)
        sum_com = 0; count_com = 0
        sum_ins = 0; count_ins = 0
        sum_rap = 0; count_rap = 0
        
        enriched_leads = []
        
        for l in leads:
            status = l['status']
            if status in stats:
                stats[status] += 1
            else:
                # Fallback para estados raros
                stats["pending"] += 1
            
            # Enriquecer con datos de encuesta
            call_id = l.get("call_id")
            survey = surveys_map.get(call_id)
            
            l["encuesta"] = survey # Mantener anidado por si acaso
            
            if survey:
                # Aplanar datos para el frontend (CampaignsView.tsx espera las keys en la raíz del objeto lead)
                l['puntuacion_comercial'] = survey.get('puntuacion_comercial')
                l['puntuacion_instalador'] = survey.get('puntuacion_instalador')
                l['puntuacion_rapidez'] = survey.get('puntuacion_rapidez')
                l['comentarios'] = survey.get('comentarios')
                l['transcription_preview'] = survey.get('transcription') # Ojo: Frontend puede usar 'transcription_preview'

                # Acumular para promedios si hay nota
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
        print(f"Error getting campaign details {campaign_id}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/agent_config_by_survey/{survey_id}")
async def get_agent_config_by_survey(survey_id: int):
    if not supabase: return JSONResponse(status_code=500, content={"error": "Supabase not connected"})
    try:
        # Get survey
        res_survey = supabase.table("encuestas").select("agent_id").eq("id", survey_id).execute()
        if not res_survey.data:
            return JSONResponse(status_code=404, content={"error": "Survey not found"})
            
        agent_id = res_survey.data[0].get("agent_id")
        
        # If no agent explicitly mapped, return default
        if not agent_id:
            # Fallback to Dakota id=1 or just returning default values
            return {"name": "Bot", "greeting": "Buenas, le llamo...", "instructions": "Eres un asistente...", "voice_id": "cefcb124-080b-4655-b31f-932f3ee743de", "llm_model": "llama-3.3-70b-versatile"}
            
        res_agent = supabase.table("agent_config").select("*").eq("id", agent_id).execute()
        if not res_agent.data:
            return JSONResponse(status_code=404, content={"error": "Agent not found"})
            
        agent_data = res_agent.data[0]
        
        # Get AI config
        res_ai = supabase.table("ai_config").select("*").eq("agent_id", agent_id).execute()
        ai_data = res_ai.data[0] if res_ai.data else {}

        # Return sensible defaults for missing fields
        return {
            "name": agent_data.get("name", "Bot"),
            "greeting": agent_data.get("greeting", "Buenas, ¿tiene un momento?"),
            "instructions": agent_data.get("instructions", "Eres un asistente"),
            "critical_rules": agent_data.get("critical_rules", ""),
            "voice_id": ai_data.get("tts_voice") or "cefcb124-080b-4655-b31f-932f3ee743de",
            "llm_model": ai_data.get("llm_model") or "llama-3.3-70b-versatile",
            "language": ai_data.get("language") or "es",
            "stt_provider": ai_data.get("stt_provider") or "deepgram"
        }
            
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# --- WORKER DE LLAMADAS (Background) ---

async def process_campaigns():
    """Bucle principal que busca leads pendientes y lanza llamadas DE UNA EN UNA (Secuencial)"""
    global supabase  # Necesario para poder recrear el cliente si se pierde la conexión
    print("🚀 Iniciando Worker de Campañas SECUENCIAL (Supabase)...")
    
    while True:
        try:
            # 1. Buscar campañas activas
            res_camps = supabase.table("campaigns").select("*").eq("status", "active").execute()
            active_campaigns = res_camps.data
            
            for camp in active_campaigns:
                campaign_id = camp['id']
                max_retries = camp['retries_count']
                retry_interval = camp['retry_interval'] or 3600 # Fallback

                # 2. Buscar 1 LEAD pendiente (Limit 1 para secuencialidad estricta)
                now_str = datetime.utcnow().isoformat()
                
                # Prioridad 1: Pending
                res_leads = supabase.table("campaign_leads").select("*") \
                    .eq("campaign_id", campaign_id) \
                    .eq("status", "pending") \
                    .limit(1).execute()
                
                leads_to_call = res_leads.data
                
                # Prioridad 2: Retries (si no hay pending)
                # NOTA: 'rejected' NO se reintenta (el usuario dijo que no quiere).
                # Solo se reintentan: failed (móvil apagado/buzón/ocupado), unreached (no contesta/cuelga antes), incomplete (encuesta a medias)
                if not leads_to_call:
                     res_retries = supabase.table("campaign_leads").select("*") \
                        .eq("campaign_id", campaign_id) \
                        .in_("status", ["failed", "unreached", "incomplete"]) \
                        .lt("retries_attempted", max_retries) \
                        .lt("next_retry_at", now_str) \
                        .limit(1).execute()
                     leads_to_call = res_retries.data

                if not leads_to_call:
                    continue # Siguiente campaña

                # Procesar EL lead (solo 1)
                lead = leads_to_call[0]
                lead_id = lead['id']
                phone = lead['phone_number']
                name = lead['customer_name']
                initial_status = lead['status']
                
                call_type = "REINTENTO" if initial_status in ['failed', 'unreached', 'incomplete'] else "LLAMADA NUEVA"
                
                print(f"🔄 [Worker] Procesando lead {phone} (Campaña {campaign_id}) | Tipo: {call_type}...")

                # Actualizar a 'calling'
                supabase.table("campaign_leads").update({
                    "status": "calling", 
                    "last_call_at": datetime.utcnow().isoformat(),
                    "retries_attempted": lead['retries_attempted'] + 1
                }).eq("id", lead_id).execute()
                
                # 1. Crear entrada en 'encuestas'
                encuesta_data = {
                    "telefono": phone,
                    "nombre_cliente": name,
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "status": "initiated",
                    "completada": 0,
                    "agent_id": lead.get("agent_id") or camp.get("agent_id"),
                    "empresa_id": camp.get("empresa_id")
                }
                res_enc = supabase.table("encuestas").insert(encuesta_data).execute()
                encuesta_id = res_enc.data[0]['id']
                
                # 2. Vincular lead
                supabase.table("campaign_leads").update({"call_id": encuesta_id}).eq("id", lead_id).execute()

                # 3. Lanzar Llamada y ESPERAR
                try:
                    logger.info(f"📞 [Worker] Llamando a {phone} (Encuesta ID: {encuesta_id})...")
                    print(f"📞 [Worker] Llamando a {phone} (Encuesta ID: {encuesta_id})...", flush=True)
                    
                    sip_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")
                    room_name = f"encuesta_{encuesta_id}"
                    
                    try:
                        await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))
                    except: pass 

                    try:
                        sip_res = await lkapi.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                            sip_trunk_id=sip_trunk_id,
                            sip_call_to=phone,
                            room_name=room_name,
                            participant_identity=f"user_{phone}",
                            participant_name=name or "Cliente"
                        ))
                        logger.info(f"✅ [Worker] SIP Marcado: {sip_res}")
                        print(f"✅ [Worker] SIP Marcado: {sip_res}", flush=True)
                    except Exception as sip_err:
                        logger.error(f"❌ [Worker] Error SIP Participant: {sip_err}")
                        print(f"❌ [Worker] Error SIP Participant: {sip_err}", flush=True)
                        raise sip_err

                    # 4. FORZAR UNIÓNN DEL AGENTE (Igual que en llamada de prueba)
                    # Esto asegura que LiveKit mande al agente a la sala inmediatamente
                    print(f"🚀 [Worker] Despachando agente genérico a sala {room_name}...")
                    try:
                        await lkapi.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(
                            agent_name="",
                            room=room_name
                        ))
                    except Exception as e:
                        print(f"⚠️ [Worker] No se pudo despachar agente (ya existe?): {e}")
                    
                    # --- WAIT LOOP (ESPERA ACTIVA) ---
                    print(f"⏳ [Worker] Esperando finalización de llamada {encuesta_id}...")
                    
                    max_wait_seconds = 600 # 10 minutos máximo de llamada
                    waited = 0
                    call_finished = False
                    room_gone_count = 0  # Contador de veces consecutivas que la sala no existe
                    
                    while waited < max_wait_seconds:
                        await asyncio.sleep(5) # Polling cada 5s
                        waited += 5
                        
                        try:
                            # --- CHECK 1: Verificar si la sala LiveKit aún existe ---
                            # Si la sala ya no existe, la llamada terminó (cuelgue temprano, no contesta, etc.)
                            try:
                                rooms = await lkapi.room.list_rooms(api.ListRoomsRequest(names=[room_name]))
                                room_exists = len(rooms.rooms) > 0 if rooms and rooms.rooms else False
                            except:
                                room_exists = False  # Error consultando = asumimos que no existe
                            
                            if not room_exists:
                                room_gone_count += 1
                                # Esperamos 2 checks consecutivos (10s) para confirmar que realmente se fue
                                if room_gone_count >= 2:
                                    print(f"🔍 [Worker] Sala {room_name} NO existe (confirmado). Verificando estado final...")
                                    # Dar 5s extra para que el fallback del agente grabe el status
                                    await asyncio.sleep(5)
                            else:
                                room_gone_count = 0  # Reset si la sala existe
                            
                            # --- CHECK 2: Consultar estado en Supabase ---
                            r_status = supabase.table("encuestas").select("status, completada").eq("id", encuesta_id).execute()
                            if r_status.data:
                                s = r_status.data[0]
                                st = s.get('status')
                                comp = s.get('completada')
                                
                                # Criterio de fin: status final O completada=1
                                if comp == 1 or st in ['completed', 'failed', 'rejected', 'rejected_opt_out', 'incomplete', 'unreached']:
                                    print(f"✅ [Worker] Llamada {encuesta_id} terminó con estado: {st}")
                                    call_finished = True
                                    
                                    # --- PROPAGACIÓN DE ESTADO ---
                                    lead_update_payload = {"status": st}
                                    
                                    # Solo reintentar: failed (apagado/buzón/ocupado), unreached (no contesta), incomplete (a medias)
                                    # NO reintentar: rejected (usuario dijo no), completed (encuesta terminada)
                                    if st in ['failed', 'unreached', 'incomplete']:
                                        next_retry_time = (datetime.utcnow() + timedelta(seconds=retry_interval)).isoformat()
                                        lead_update_payload["next_retry_at"] = next_retry_time
                                        print(f"🔄 [Worker] Programando reintento para {phone} en {retry_interval}s")
                                    
                                    supabase.table("campaign_leads").update(lead_update_payload).eq("id", lead_id).execute()
                                    break
                                
                                # Si la sala desapareció pero el status sigue en 'initiated', el agente no guardó nada
                                # Esto pasa cuando cuelgan antes de coger (USER_REJECTED)
                                if room_gone_count >= 2 and st == 'initiated':
                                    print(f"⚠️ [Worker] Sala desaparecida + status 'initiated' = No contesta/Colgó antes")
                                    # Marcar como unreached
                                    supabase.table("encuestas").update({
                                        "status": "unreached",
                                        "comentarios": "No contestó o colgó antes de responder"
                                    }).eq("id", encuesta_id).execute()
                                    
                                    lead_update_payload = {
                                        "status": "unreached",
                                        "next_retry_at": (datetime.utcnow() + timedelta(seconds=retry_interval)).isoformat()
                                    }
                                    supabase.table("campaign_leads").update(lead_update_payload).eq("id", lead_id).execute()
                                    print(f"🔄 [Worker] Programando reintento para {phone} en {retry_interval}s (unreached)")
                                    call_finished = True
                                    break
                        
                        except Exception as poll_error:
                            error_msg = str(poll_error)
                            if 'ConnectionTerminated' in error_msg or 'ConnectionReset' in error_msg:
                                print(f"⚠️ [Worker] Conexión Supabase perdida, reconectando...")
                                # Recrear cliente Supabase
                                try:
                                    from supabase import create_client
                                    supabase = create_client(
                                        os.getenv("SUPABASE_URL"),
                                        os.getenv("SUPABASE_SERVICE_ROLE_KEY")
                                    )
                                    print("✅ [Worker] Supabase reconectado")
                                except Exception as reconn_err:
                                    print(f"❌ [Worker] Error reconectando Supabase: {reconn_err}")
                            else:
                                print(f"⚠️ [Worker] Error en polling: {poll_error}")
                    
                    if not call_finished:
                        print(f"⚠️ [Worker] Timeout esperando llamada {encuesta_id} (force break)")
                        # Forzar status update
                        try:
                            supabase.table("encuestas").update({"status": "unreached"}).eq("id", encuesta_id).execute()
                            supabase.table("campaign_leads").update({
                                "status": "unreached",
                                "next_retry_at": (datetime.utcnow() + timedelta(seconds=retry_interval)).isoformat()
                            }).eq("id", lead_id).execute()
                        except Exception as timeout_err:
                            print(f"❌ [Worker] Error actualizando timeout: {timeout_err}")

                except Exception as e:
                    print(f"❌ [Worker] Error al llamar {phone}: {e}")
                    # Marcar retry
                    next_retry = (datetime.utcnow() + timedelta(seconds=retry_interval)).isoformat()
                    supabase.table("campaign_leads").update({
                        "status": "failed", 
                        "next_retry_at": next_retry
                    }).eq("id", lead_id).execute()

                # --- COOLDOWN ENTRE LLAMADAS ---
                # Esperamos 120s (2 min) para asegurar que Asterisk/LiveKit liberen totalmente los recursos
                # y para dar tiempo entre llamadas.
                print("⏳ [Worker] Cooldown de 120s (2 min) antes del siguiente lead...")
                await asyncio.sleep(120)

        except Exception as e:
            print(f"⚠️ [Worker Loop Error]: {e}")
            await asyncio.sleep(30)
            
        await asyncio.sleep(2) # Pequeña pausa entre iteraciones de campañas

@app.on_event("startup")
async def startup_event():
    print("🌅 Iniciando API (Supabase Integration)...")
    asyncio.create_task(process_campaigns())
