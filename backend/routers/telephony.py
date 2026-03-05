from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse
from models.schemas import CallEndRequest, EncuestaData
from services.supabase_service import supabase
from services.livekit_service import lkapi
from livekit import api
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta, timezone
import time
import random
import logging

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])

@router.post("/colgar")
async def finalizar_llamada(req: CallEndRequest):
    """Corta la llamada en LiveKit"""
    try:
        print(f"✂️ Solicitud de colgar sala: {req.nombre_sala}")
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=req.nombre_sala))
        return {"status": "ok", "message": f"Sala {req.nombre_sala} cerrada"}
    except Exception as e:
        print(f"⚠️ Error al cerrar sala {req.nombre_sala}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@router.post("/guardar-encuesta")
async def guardar_encuesta(datos: EncuestaData, background_tasks: BackgroundTasks):
    if not supabase: return {"status": "error", "message": "No DB connection"}
    
    print(f"📥 [API] Recibiendo datos encuesta {datos.id_encuesta}: {datos.dict(exclude_none=True)}")
    
    # Normalizar estados (aceptar legacy ES + EN) a un set canónico EN para campañas/UI
    status_map = {
        # EN (canonical)
        "completed": "completed",
        "failed": "failed",
        "incomplete": "incomplete",
        "unreached": "unreached",
        "rejected_opt_out": "rejected_opt_out",
        "rejected": "rejected_opt_out",
        "calling": "calling",
        "pending": "pending",
        "called": "called",
        # ES (legacy)
        "completada": "completed",
        "fallida": "failed",
        "parcial": "incomplete",
        "no_contesta": "unreached",
        "rechazada": "rejected_opt_out",
    }

    update_data = {}
    
    if datos.nota_comercial is not None: update_data["puntuacion_comercial"] = datos.nota_comercial
    if datos.nota_instalador is not None: update_data["puntuacion_instalador"] = datos.nota_instalador
    if datos.nota_rapidez is not None: update_data["puntuacion_rapidez"] = datos.nota_rapidez
    if datos.comentarios is not None: update_data["comentarios"] = datos.comentarios
    if datos.transcription is not None: update_data["transcription"] = datos.transcription
    if datos.seconds_used is not None: update_data["seconds_used"] = datos.seconds_used
    if datos.llm_model is not None: update_data["llm_model"] = datos.llm_model
    if datos.datos_extra is not None: update_data["datos_extra"] = datos.datos_extra
    
    normalized_status = status_map.get((datos.status or "").strip().lower()) if datos.status else None
    es_completada = False
    
    if normalized_status:
        update_data["status"] = normalized_status
        if normalized_status == 'completed':
            es_completada = True
            update_data["completada"] = 1
            
    curr = supabase.table("encuestas").select("status, empresa_id, telefono").eq("id", datos.id_encuesta).execute()
    curr_data = curr.data[0] if curr.data else {}

    if not update_data and not normalized_status:
        return {"status": "ignored", "message": "No data to update"}
        
    if not normalized_status and curr_data:
         if (curr_data.get('status') or '') not in ('completed', 'rejected_opt_out'):
             update_data["status"] = 'incomplete'

    logger.info(f"📝 [API] Intentando actualizar encuesta {datos.id_encuesta} con: {update_data}")
    try:
        supabase.table("encuestas").update(update_data).eq("id", datos.id_encuesta).execute()
        logger.info(f"✅ [API] Supabase actualizado para encuesta {datos.id_encuesta}")
        
        if normalized_status in ('completed', 'rejected_opt_out', 'incomplete', 'failed', 'unreached'):
             lead_update = {"status": normalized_status}
             
             # Rechazada: marcar como no reintentar para excluir de campañas futuras
             if normalized_status == 'rejected_opt_out':
                 lead_update["no_reintentar"] = True
             
             # Parcial, Fallida, No Contesta: programar reintento
             if normalized_status in ('incomplete', 'failed', 'unreached'):
                 retry_seconds = 3600
                 max_retries = 3
                 current_retries = 0
                 try:
                     # Obtener info del lead y campaña
                     lead_res = supabase.table("campaign_leads").select("campaign_id, retries_attempted").eq("call_id", datos.id_encuesta).limit(1).execute()
                     if lead_res.data:
                         current_retries = lead_res.data[0].get('retries_attempted', 0)
                         camp_id = lead_res.data[0]['campaign_id']
                         camp_res = supabase.table("campaigns").select("retry_interval, retries_count").eq("id", camp_id).limit(1).execute()
                         if camp_res.data:
                             camp_retry = camp_res.data[0].get('retry_interval')
                             max_retries = camp_res.data[0].get('retries_count', 3)
                             if camp_retry and camp_retry > 0:
                                 retry_seconds = camp_retry
                 except Exception as ex_interval:
                     print(f"⚠️ Error fetching campaign data for retry: {ex_interval}")

                 new_retries = current_retries + 1
                 lead_update["retries_attempted"] = new_retries
                 
                 # Si aún quedan reintentos, volver a ponerlo en pending y programar
                 if new_retries < max_retries:
                     lead_update["status"] = "pending"
                     next_retry = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
                     lead_update["next_retry_at"] = next_retry
                     print(f"🔄 [API] Reintento programado ({new_retries}/{max_retries}) para lead de encuesta {datos.id_encuesta} a las {next_retry}")
                 else:
                     print(f"🚫 [API] Máximo de reintentos alcanzado ({new_retries}/{max_retries}) para lead de encuesta {datos.id_encuesta}")
                     # El status se queda como lo que vino (failed/unreached/incomplete)
             
             lead_result = supabase.table("campaign_leads").update(lead_update).eq("call_id", datos.id_encuesta).execute()
             rows_updated = len(lead_result.data) if lead_result.data else 0
             logger.info(f"📊 [API] Lead update por call_id={datos.id_encuesta}: {rows_updated} filas afectadas, lead_update={lead_update}")
             
             # Fallback: si no se encontró el lead por call_id, buscar por campaign_id + teléfono
             if rows_updated == 0 and curr_data.get('telefono'):
                 logger.warning(f"⚠️ [API] No se encontró lead con call_id={datos.id_encuesta}. Intentando fallback por teléfono...")
                 try:
                     enc_data = supabase.table("encuestas").select("campaign_id, telefono").eq("id", datos.id_encuesta).execute()
                     if enc_data.data and enc_data.data[0].get('campaign_id'):
                         camp_id = enc_data.data[0]['campaign_id']
                         tel = enc_data.data[0].get('telefono', '')
                         lead_update_fb = {**lead_update, "call_id": datos.id_encuesta}
                         fb_result = supabase.table("campaign_leads").update(lead_update_fb).eq("campaign_id", camp_id).eq("phone_number", tel).execute()
                         fb_rows = len(fb_result.data) if fb_result.data else 0
                         logger.info(f"🔄 [API] Fallback lead update: campaign_id={camp_id}, tel={tel} → {fb_rows} filas")
                 except Exception as fb_err:
                     logger.error(f"❌ [API] Error en fallback de lead update: {fb_err}")

             if normalized_status in ('completed', 'failed', 'rejected_opt_out') and curr_data.get('empresa_id'):
                 result_data = {
                     "nota_comercial": datos.nota_comercial,
                     "nota_instalador": datos.nota_instalador,
                     "nota_rapidez": datos.nota_rapidez,
                     "comentarios": datos.comentarios,
                     "transcription": datos.transcription,
                     "seconds_used": datos.seconds_used,
                     "llm_model": datos.llm_model
                 }
                 background_tasks.add_task(trigger_crm_webhook, datos.id_encuesta, normalized_status, result_data, curr_data['empresa_id'], curr_data.get('telefono', ''))

        return {"status": "ok", "updated": update_data}
    except Exception as e:
        logger.error(f"❌ [API] Error DB al guardar encuesta {datos.id_encuesta}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

async def trigger_crm_webhook(encuesta_id: int, status: str, result_data: dict, empresa_id: int, telefono: str):
    try:
        emp_res = supabase.table("empresas").select("crm_webhook_url, crm_type").eq("id", empresa_id).execute()
        if not emp_res.data or not emp_res.data[0].get("crm_webhook_url"): return
        
        cfg = emp_res.data[0]
        url = cfg["crm_webhook_url"]
        
        payload = {
            "event": "call_completed" if status == "completed" else ("call_rejected" if status == "rejected_opt_out" else "call_failed"),
            "encuesta_id": encuesta_id,
            "status": status,
            "lead": {
                "phone": telefono
            },
            "results": result_data,
            "crm_type": cfg.get("crm_type", "custom")
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=10) as resp:
                print(f"📡 CRM Webhook [{status}] sent to {url} -> {resp.status}")
    except Exception as e:
        print(f"⚠️ CRM Webhook Error: {e}")

# Lock para evitar doble despacho accidental
processing_rooms = set()

@router.post("/api/calls/outbound")
async def make_outbound_call(request: dict):
    """Endpoint para llamadas de prueba o llamadas disparadas por Webhook de n8n"""
    phone = request.get("phoneNumber")
    agent_id = request.get("agentId", "1")
    lead_id = request.get("leadId")
    campaign_id = request.get("campaignId")
    
    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number is required"})

    # Usamos un ID único para la encuesta para evitar duplicaciones en la base de datos
    # si se llama dos veces muy rápido.
    encuesta_id = None
    
    try:
        if supabase:
            # (Logic for creating the survey record)
            emp_id = request.get("empresa_id")
            if not emp_id and agent_id:
                try:
                    agent_res = supabase.table("agent_config").select("empresa_id").eq("id", agent_id).execute()
                    if agent_res.data:
                        emp_id = agent_res.data[0].get("empresa_id")
                except: pass

            campaign_name = request.get("campaignName")
            if campaign_id and not campaign_name:
                try:
                    camp_res = supabase.table("campaigns").select("name").eq("id", campaign_id).execute()
                    if camp_res.data:
                        campaign_name = camp_res.data[0].get("name")
                except: pass

            encuesta_data = {
                "telefono": phone,
                "nombre_cliente": request.get("customerName", "Prueba Dashboard"),
                "fecha": datetime.now(timezone.utc).isoformat(),
                "status": "initiated",
                "completada": 0,
                "agent_id": agent_id,
                "empresa_id": emp_id,
                "campaign_id": campaign_id,
                "campaign_name": campaign_name
            }
            res_enc = supabase.table("encuestas").insert(encuesta_data).execute()
            encuesta_id = res_enc.data[0]['id']
            
            if lead_id:
                supabase.table("campaign_leads").update({
                    "call_id": encuesta_id,
                    "status": "calling",
                    "last_call_at": datetime.now(timezone.utc).isoformat()
                }).eq("id", lead_id).execute()
        else:
            encuesta_id = random.randint(1000, 9999)

        # Prefijamos la sala con el nombre del despachador para aislar entornos
        agent_name_dispatch = os.getenv("AGENT_NAME_DISPATCH", "default_agent")
        room_name = f"{agent_name_dispatch}_encuesta_{encuesta_id}"
        sip_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")

        # --- PREVENCIÓN DE DOBLE DESPACHO ---
        if room_name in processing_rooms:
            logger.warning(f"⚠️ [API] Despacho ya en curso para sala {room_name}. Ignorando duplicado.")
            return {"status": "ok", "message": "Call already initiated", "roomName": room_name}
        
        processing_rooms.add(room_name)

        print(f"📡 [API] Creando sala: {room_name}")
        try:
            await lkapi.room.create_room(api.CreateRoomRequest(name=room_name))
        except Exception as e:
            print(f"⚠️ [API] Aviso al crear sala: {e}")

        logger.info(f"☎️ [API] Marcando vía SIP a {phone} en sala {room_name}...")
        try:
            await lkapi.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"user_{phone}_{encuesta_id}",
                participant_name="Cliente"
            ))
        except Exception as sip_err:
            processing_rooms.discard(room_name)
            raise sip_err

        # Despachamos el agente específico para este entorno
        # Explicit dispatching via lkapi is failing due to attribute missing in current SDK version.
        # LiveKit auto-dispatching is working as fallback.
        # await lkapi.agent.create_agent_dispatch(api.CreateAgentDispatchRequest(
        #     room=room_name,
        #     agent_name=agent_name_dispatch
        # ))
        logger.info(f"✅ [API] Sala {room_name} creada y agente {agent_name_dispatch} solicitado.")
        # The try-except block around the dispatch is also removed/commented out.
        # The original `logger.info(f"🚀 [API] Solicitando despacho...")` is also removed.
        # The `except Exception as dispatch_err:` block is also removed.

        # Limpiamos el lock después de un tiempo prudencial
        async def clear_room_lock(rname):
            await asyncio.sleep(10)
            processing_rooms.discard(rname)
        
        asyncio.create_task(clear_room_lock(room_name))

        return {"status": "ok", "roomName": room_name, "callId": encuesta_id}
        
    except Exception as e:
        if 'room_name' in locals(): processing_rooms.discard(room_name)
        print(f"❌ [API] Error fatal en outbound call: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})
