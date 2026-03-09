from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import os
import asyncio
from datetime import datetime, timedelta
from typing import Optional, Union
from dotenv import load_dotenv
from livekit import api
from supabase import create_client, Client

load_dotenv()
app = FastAPI()

# --- CORS ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONEXIÓN SUPABASE ---
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")

supabase: Client = None
if SUPABASE_URL and SUPABASE_KEY:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Conectado a Supabase correctamente.")
    except Exception as e:
        print(f"❌ Error conectando a Supabase: {e}")

# --- MODELOS ---
class InicioEncuesta(BaseModel):
    telefono: str

class FinEncuesta(BaseModel):
    id_encuesta: Union[int, str, None] = None
    nota_comercial: Union[int, str, None] = None
    nota_instalador: Union[int, str, None] = None
    nota_rapidez: Union[int, str, None] = None
    comentarios: Optional[str] = None 
    status: Optional[str] = None
    transcription: Optional[str] = None
    datos_extra: Optional[dict] = None

class ColgarLlamada(BaseModel):
    nombre_sala: str 

@app.exception_handler(Exception)
async def validation_exception_handler(request: Request, exc: Exception):
    return JSONResponse(status_code=422, content={"detail": str(exc)})

# --- UTILS DASHBOARD (SUPABASE) ---
def get_dashboard_stats_supabase():
    if not supabase: return {}
    try:
        # 1. Total Calls
        res_total = supabase.table("encuestas").select("count", count="exact").execute()
        total = res_total.count if res_total.count is not None else 0
        
        # 2. Completed Calls
        res_completed = supabase.table("encuestas").select("count", count="exact").eq("completada", 1).execute()
        completed = res_completed.count if res_completed.count is not None else 0
        
        # 3. Pending
        # Consideramos pending si status es initiated/pending
        res_pending = supabase.table("encuestas").select("count", count="exact").eq("completada", 0).execute()
        pending = res_pending.count if res_pending.count is not None else 0
        
        # 4. Averages
        # Supabase doesn't do aggregations easily in one query without RPC.
        # Fetching all non-null scores to calculate average in python (fine for <10k records)
        res_scr = supabase.table("encuestas").select("puntuacion_comercial, puntuacion_instalador, puntuacion_rapidez").execute()
        data = res_scr.data
        
        avg_com, avg_ins, avg_rap = 0, 0, 0
        count_com, count_ins, count_rap = 0, 0, 0
        
        for r in data:
            if r['puntuacion_comercial'] is not None:
                avg_com += r['puntuacion_comercial']
                count_com += 1
            if r['puntuacion_instalador'] is not None:
                avg_ins += r['puntuacion_instalador']
                count_ins += 1
            if r['puntuacion_rapidez'] is not None:
                avg_rap += r['puntuacion_rapidez']
                count_rap += 1
                
        avg_com = round(avg_com / count_com, 1) if count_com else 0
        avg_ins = round(avg_ins / count_ins, 1) if count_ins else 0
        avg_rap = round(avg_rap / count_rap, 1) if count_rap else 0
        overall = round((avg_com + avg_ins + avg_rap) / 3, 1)

        return {
            "total_calls": total,
            "completed_calls": completed,
            "pending_calls": pending,
            "avg_scores": {
                "comercial": avg_com,
                "instalador": avg_ins,
                "rapidez": avg_rap,
                "overall": overall
            }
        }
    except Exception as e:
        print(f"Error stats: {e}")
        return {"total_calls": 0, "completed_calls": 0, "pending_calls": 0, "avg_scores": {}}

def get_calls_supabase(limit=50):
    if not supabase: return []
    try:
        res = supabase.table("encuestas").select("*").order("fecha", desc=True).limit(limit).execute()
        calls = res.data
        mapped = []
        # Obtener tipos de agentes para marcar if is_question_based
        qs_agents = set()
        agent_types = {}
        try:
            agents_res = supabase.table("agent_config").select("id, instructions, survey_type, tipo_resultados").execute()
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
                        inst_lower = (a.get("instructions") or "").lower()
                        has_preguntas = "pregunta 1" in inst_lower or "pregunta 2" in inst_lower or "pregunta:" in inst_lower
                        is_numeric = any(kw in inst_lower for kw in ["1 al 10", "0 al 10", "del uno al diez", "uno al 10", "uno al diez", "numérica", "puntuación"])
                        if has_preguntas and not is_numeric:
                            qs_agents.add(aid)
        except: pass

        for c in calls:
            # Map status nicely
            raw_status = c.get('status', 'initiated')
            if c.get('completada'): raw_status = 'completada'
            
            res_agent_id = str(c.get('agent_id')) if c.get('agent_id') else ""
            
            mapped.append({
                "id": c['id'],
                "telefono": c.get('telefono'),
                "phone": c.get('telefono'),
                "campaign": c.get('campaign_name', "Ausarta"), 
                "campaign_name": c.get('campaign_name', "Ausarta"),
                "fecha": c.get('fecha'),
                "date": c.get('fecha'),
                "completada": c.get('completada'),
                "status": raw_status,
                "is_question_based": res_agent_id in qs_agents,
                "tipo_resultados": agent_types.get(res_agent_id),
                "scores": {
                    "comercial": c.get('puntuacion_comercial'),
                    "instalador": c.get('puntuacion_instalador'),
                    "rapidez": c.get('puntuacion_rapidez')
                },
                "puntuacion_comercial": c.get('puntuacion_comercial'),
                "puntuacion_instalador": c.get('puntuacion_instalador'),
                "puntuacion_rapidez": c.get('puntuacion_rapidez'),
                
                "llm_model": c.get('llm_model', "Unknown"),
                "comentarios": c.get('comentarios'),
                "transcription": c.get('transcription'),
                "datos_extra": c.get('datos_extra')
            })
        return mapped
    except Exception as e:
        print(f"Error recent calls: {e}")
        return []

# 1. INICIO
@app.post("/iniciar-encuesta")
async def iniciar_encuesta(datos: InicioEncuesta):
    print(f"📝 1. Creando ficha (Supabase) para: {datos.telefono}")
    if not supabase: return {"error": "No DB"}
    try:
        data = {
            "telefono": datos.telefono,
            "fecha": datetime.now().isoformat(),
            "completada": 0,
            "status": "initiated"
        }
        res = supabase.table("encuestas").insert(data).execute()
        if res.data:
            nuevo_id = res.data[0]['id']
            print(f"✅ Ficha creada con ID: {nuevo_id}")
            return {"id": nuevo_id}
        else:
            return {"error": "No ID returned"}
    except Exception as e:
        print(f"Error DB: {e}")
        return {"error": str(e)}

# 2. GUARDAR
@app.post("/guardar-encuesta")
async def guardar_encuesta(datos: FinEncuesta):
    print(f"📥 Recibiendo datos parciales/finales para ID: {datos.id_encuesta}")
    if not supabase: return {"error": "No DB"}
    
    def clean_nota(val):
        try:
            num = int(val)
            if 1 <= num <= 10: return num
            return None 
        except: return None
    
    val_comercial = clean_nota(datos.nota_comercial) if datos.nota_comercial is not None else None
    val_instalador = clean_nota(datos.nota_instalador) if datos.nota_instalador is not None else None
    val_rapidez = clean_nota(datos.nota_rapidez) if datos.nota_rapidez is not None else None
    val_comentarios = datos.comentarios

    # Extract ID logic
    id_final = None
    try:
        # Try as int direct
        if isinstance(datos.id_encuesta, int):
            id_final = datos.id_encuesta
        # Try parsing string
        elif datos.id_encuesta:
             import re
             nums = re.findall(r'\d+', str(datos.id_encuesta))
             if nums and int(nums[0]) > 0: id_final = int(nums[0])
    except: pass

    if not id_final:
        # Fallback: get last id
        try:
            res = supabase.table("encuestas").select("id").order("id", desc=True).limit(1).execute()
            if res.data: id_final = res.data[0]['id']
        except: pass
    
    if not id_final: return {"status": "error", "msg": "No ID found"}

    updates = {}
    if val_comercial is not None: updates["puntuacion_comercial"] = val_comercial
    if val_instalador is not None: updates["puntuacion_instalador"] = val_instalador
    if val_rapidez is not None: updates["puntuacion_rapidez"] = val_rapidez
    if val_comentarios is not None:
        updates["comentarios"] = val_comentarios
    if datos.transcription is not None:
        updates["transcription"] = datos.transcription
    if datos.datos_extra is not None:
        updates["datos_extra"] = datos.datos_extra
    
    # Lógica de estados
    if datos.status:
        print(f"🔄 Actualizando status a: {datos.status}")
        raw_status = (datos.status or "").strip().lower()
        _STATUS_MAP_PRE = {
            "completed": "completed", "failed": "failed", "incomplete": "incomplete",
            "unreached": "unreached", "rejected_opt_out": "rejected_opt_out",
            "rejected": "rejected_opt_out", "completada": "completed", "fallida": "failed",
            "parcial": "incomplete", "no_contesta": "unreached", "rechazada": "rejected_opt_out",
        }
        normalized_status = _STATUS_MAP_PRE.get(raw_status) or datos.status
        updates["status"] = normalized_status
        if normalized_status == "completed":
            updates["completada"] = 1
    elif val_comentarios is not None:
         pass

    if not updates:
        print("⚠️ Llamada a guardar sin datos nuevos.")
        return {"status": "no_changes"}

    # Propagación a campaign_leads
    _PROPAGABLE = {"completed", "rejected_opt_out", "incomplete", "failed", "unreached"}
    normalized_status = updates.get("status")

    try:
        supabase.table("encuestas").update(updates).eq("id", id_final).execute()
        print(f"💾 Guardado incremental en ficha {id_final}: {updates}")

        # Propagar a campaign_leads (misma lógica que telephony)
        if normalized_status and normalized_status in _PROPAGABLE:
            try:
                enc = supabase.table("encuestas").select("status, empresa_id, telefono").eq("id", id_final).limit(1).execute()
                curr_data = enc.data[0] if enc.data else {}
                lead_update = {"status": normalized_status}
                if normalized_status == "rejected_opt_out":
                    lead_update["no_reintentar"] = True
                elif normalized_status in ("incomplete", "failed", "unreached"):
                    retry_seconds, max_retries, current_retries = 3600, 3, 0
                    try:
                        lead_res = supabase.table("campaign_leads").select("campaign_id, retries_attempted").eq("call_id", id_final).limit(1).execute()
                        if lead_res.data:
                            current_retries = lead_res.data[0].get("retries_attempted", 0) or 0
                            camp_id = lead_res.data[0]["campaign_id"]
                            camp_res = supabase.table("campaigns").select("retry_interval, retries_count").eq("id", camp_id).limit(1).execute()
                            if camp_res.data:
                                ri = camp_res.data[0].get("retry_interval")
                                max_retries = camp_res.data[0].get("retries_count", 3) or 3
                                if ri and ri > 0:
                                    retry_seconds = ri
                    except Exception as e:
                        print(f"Error leyendo config reintentos: {e}")
                    new_retries = current_retries + 1
                    lead_update["retries_attempted"] = new_retries
                    if new_retries < max_retries:
                        lead_update["status"] = "pending"
                        lead_update["next_retry_at"] = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
                        print(f"🔄 Reintento {new_retries}/{max_retries} programado → {lead_update['next_retry_at']}")
                    else:
                        print(f"🚫 Máx reintentos alcanzado ({new_retries}/{max_retries})")
                r = supabase.table("campaign_leads").update(lead_update).eq("call_id", id_final).execute()
                if (not r.data or len(r.data) == 0) and curr_data.get("telefono"):
                    enc_full = supabase.table("encuestas").select("campaign_id").eq("id", id_final).execute()
                    if enc_full.data and enc_full.data[0].get("campaign_id"):
                        supabase.table("campaign_leads").update({**lead_update, "call_id": id_final}).eq("campaign_id", enc_full.data[0]["campaign_id"]).eq("phone_number", curr_data["telefono"]).execute()
                print(f"📊 Lead propagado: {lead_update}")
            except Exception as prop_err:
                print(f"⚠️ Error propagando a campaign_leads: {prop_err}")

        return {"status": "success"}
    except Exception as e:
        print(f"Error updating Supabase: {e}")
        return {"error": str(e)}

# 3. COLGAR
@app.post("/colgar")
async def colgar(datos: ColgarLlamada):
    print(f"✂️  Petición de colgar.")
    lkapi = api.LiveKitAPI(
        os.getenv("LIVEKIT_URL"),
        os.getenv("LIVEKIT_API_KEY"),
        os.getenv("LIVEKIT_API_SECRET"),
    )
    try:
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=datos.nombre_sala))
        return {"status": "success"}
    except:
        return {"status": "error"} 
    finally:
        await lkapi.aclose()


# --- FRONTEND ENDPOINTS ---

@app.get("/api/dashboard/stats")
async def dashboard_stats():
    return get_dashboard_stats_supabase()

@app.get("/dashboard/stats") 
async def dashboard_stats_alias():
    return get_dashboard_stats_supabase()

@app.get("/api/dashboard/recent-calls")
async def recent_calls():
    return get_calls_supabase(limit=50)

@app.get("/dashboard/recent-calls")
async def recent_calls_alias():
    return get_calls_supabase(limit=50)

@app.get("/api/results")
async def results():
    return get_calls_supabase(limit=1000)

@app.get("/api/results/{id}/transcription")
async def get_transcription(id: int):
    if not supabase: return {"transcription": ""}
    try:
        res = supabase.table("encuestas").select("transcription").eq("id", id).execute()
        if res.data:
            return {"transcription": res.data[0].get('transcription', '')}
        return {"transcription": ""}
    except Exception as e:
        print(f"Error fetching transcription {id}: {e}")
        return {"transcription": ""}

@app.get("/dashboard/integrations")
async def integrations_alias():
    return [
        {"name": "Database", "provider": "Supabase", "active": bool(supabase), "env_var": "SUPABASE_URL"},
        {"name": "LiveKit", "provider": "LiveKit Cloud", "active": bool(os.getenv("LIVEKIT_URL")), "env_var": "LIVEKIT_URL"},
        {"name": "Voice Agent", "provider": "Dakota", "active": True, "model": "Llama 3.3"},
        {"name": "TTS", "provider": "Cartesia", "active": bool(os.getenv("CARTESIA_API_KEY")), "env_var": "CARTESIA_API_KEY"}
    ]

@app.get("/")
async def root():
    return {"status": "ok", "message": "Ausarta Voice Agent Bridge Server Running (Supabase)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)