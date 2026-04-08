"""
telephony.py — Gestión de llamadas y webhooks entrantes.

Responsabilidades:
  - /colgar: cierra una sala de LiveKit.
  - /guardar-encuesta: persiste datos de una encuesta y propaga estado a campaign_leads.
  - /api/calls/outbound: inicia una llamada SIP individual (test o desde campaña).
  - /api/livekit/webhook: recibe eventos de LiveKit (room_finished, participant_left)
    para actualizar el estado de los leads sin polling.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Request
from fastapi.responses import JSONResponse
from models.schemas import CallEndRequest, EncuestaData
from services.supabase_service import supabase
from services.livekit_service import lkapi, create_isolated_room, dispatch_agent_explicit
from livekit import api
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta, timezone
import random
import logging
from services.auth import require_api_key as _outbound_api_key

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])

# ──────────────────────────────────────────────
# Colgar sala
# ──────────────────────────────────────────────

@router.post("/colgar")
async def finalizar_llamada(req: CallEndRequest):
    """Cierra una sala de LiveKit."""
    try:
        logger.info(f"✂️ Cerrando sala: {req.nombre_sala}")
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=req.nombre_sala))
        return {"status": "ok", "message": f"Sala {req.nombre_sala} cerrada"}
    except Exception as e:
        err_msg = str(e).lower()
        # Sala ya cerrada (cliente colgó primero, room_finished, etc.) → tratar como éxito
        if "not_found" in err_msg or "does not exist" in err_msg or "404" in err_msg:
            logger.info(f"✓ Sala {req.nombre_sala} ya cerrada (no existe). OK.")
            return {"status": "ok", "message": "Sala ya cerrada"}
        logger.error(f"⚠️ Error al cerrar sala {req.nombre_sala}: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# Guardar encuesta y propagar a campaign_leads
# ──────────────────────────────────────────────

# Mapa canónico de estados (ES legacy + EN)
_STATUS_MAP = {
    "completed": "completed", "failed": "failed", "incomplete": "incomplete",
    "unreached": "unreached", "rejected_opt_out": "rejected_opt_out",
    "rejected": "rejected_opt_out", "calling": "calling", "pending": "pending",
    "called": "called",
    # Legacy ES
    "completada": "completed", "fallida": "failed", "parcial": "incomplete",
    "no_contesta": "failed", "rechazada": "rejected_opt_out",
    # Señales típicas SIP/telefonía que deben computar como fallida reintentable
    "busy": "failed", "ocupado": "failed",
    "voicemail": "failed", "buzon": "failed", "buzón": "failed",
}

# Estados que deben disparar la propagación a campaign_leads
_PROPAGABLE_STATUSES = {"completed", "rejected_opt_out", "incomplete", "failed", "unreached"}

# Estados terminales que no deben ser sobrescritos por el webhook de LiveKit
_TERMINAL_STATUSES = {"completed", "failed", "unreached", "incomplete", "rejected_opt_out"}


@router.post("/guardar-encuesta")
async def guardar_encuesta(datos: EncuestaData, background_tasks: BackgroundTasks):
    if not supabase:
        return {"status": "error", "message": "No DB connection"}

    logger.info(f"📥 [guardar-encuesta] encuesta={datos.id_encuesta}: {datos.dict(exclude_none=True)}")

    # --- Construir payload de actualización ---
    from typing import Any
    update_data: dict[str, Any] = {}
    if datos.nota_comercial is not None:  update_data["puntuacion_comercial"] = datos.nota_comercial
    if datos.nota_instalador is not None: update_data["puntuacion_instalador"] = datos.nota_instalador
    if datos.nota_rapidez is not None:    update_data["puntuacion_rapidez"] = datos.nota_rapidez
    if datos.comentarios is not None:     update_data["comentarios"] = datos.comentarios
    if datos.transcription is not None:   update_data["transcription"] = datos.transcription
    if datos.seconds_used is not None:    update_data["seconds_used"] = datos.seconds_used
    if datos.llm_model is not None:       update_data["llm_model"] = datos.llm_model
    if datos.datos_extra is not None:     update_data["datos_extra"] = datos.datos_extra

    normalized_status = _STATUS_MAP.get((datos.status or "").strip().lower()) if datos.status else None

    if not update_data and not normalized_status:
        return {"status": "ignored", "message": "No data to update"}

    # Leer el estado actual de la encuesta en BD
    curr = supabase.table("encuestas").select("status, empresa_id, telefono").eq("id", datos.id_encuesta).execute()
    curr_data = curr.data[0] if curr.data else {}
    current_db_status = (curr_data.get("status") or "")

    # Si llegaron datos pero sin status explícito:
    # Mantenemos el que haya calculado, si no se queda sin tocar.
    if normalized_status:
        update_data["status"] = normalized_status
        if normalized_status == "completed":
            update_data["completada"] = 1

    # --- Persistir en encuestas ---
    logger.info(f"📝 [guardar-encuesta] UPDATE encuesta {datos.id_encuesta}: {update_data}")
    try:
        supabase.table("encuestas").update(update_data).eq("id", datos.id_encuesta).execute()
        logger.info(f"✅ [guardar-encuesta] Encuesta {datos.id_encuesta} actualizada")
    except Exception as e:
        logger.error(f"❌ [guardar-encuesta] Error DB: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

    # --- Propagar estado a campaign_leads ---
    if normalized_status in _PROPAGABLE_STATUSES:
        background_tasks.add_task(
            _propagate_to_lead, datos.id_encuesta, normalized_status, curr_data
        )

    # --- Notificar a n8n si el estado es terminal relevante ---
    if normalized_status in ("completed", "rejected_opt_out", "failed") and curr_data.get("empresa_id"):
        result_data = {
            "nota_comercial": datos.nota_comercial,
            "nota_instalador": datos.nota_instalador,
            "nota_rapidez": datos.nota_rapidez,
            "comentarios": datos.comentarios,
            "transcription": datos.transcription,
            "seconds_used": datos.seconds_used,
            "llm_model": datos.llm_model,
            "datos_extra": datos.datos_extra,
        }
        background_tasks.add_task(
            _notify_n8n_post_call,
            datos.id_encuesta,
            normalized_status,
            result_data,
            curr_data["empresa_id"],
            curr_data.get("telefono", ""),
        )

    return {"status": "ok", "updated": update_data}


async def _propagate_to_lead(encuesta_id: int, final_status: str, enc_curr_data: dict):
    """
    Actualiza el campaign_lead asociado a esta encuesta.
    Calcula reintentos según la configuración de la campaña.
    """
    lead_update: dict = {"status": final_status}

    if final_status == "rejected_opt_out":
        lead_update["no_reintentar"] = True

    elif final_status in ("incomplete", "failed", "unreached"):
        retry_seconds = 3600
        max_retries = 3
        current_retries = 0
        try:
            lead_res = supabase.table("campaign_leads").select("campaign_id, retries_attempted").eq("call_id", encuesta_id).limit(1).execute()
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
            logger.error(f"Error leyendo config de reintentos para encuesta {encuesta_id}: {e}")

        new_retries = current_retries + 1
        lead_update["retries_attempted"] = new_retries

        if new_retries < max_retries:
            lead_update["status"] = "pending"
            next_retry = (datetime.utcnow() + timedelta(seconds=retry_seconds)).isoformat()
            lead_update["next_retry_at"] = next_retry
            logger.info(f"🔄 Reintento {new_retries}/{max_retries} programado para encuesta {encuesta_id} → {next_retry}")
        else:
            logger.info(f"🚫 Máx. reintentos alcanzado ({new_retries}/{max_retries}) para encuesta {encuesta_id}")

    try:
        result = supabase.table("campaign_leads").update(lead_update).eq("call_id", encuesta_id).execute()
        rows = len(result.data) if result.data else 0
        logger.info(f"📊 Lead actualizado (call_id={encuesta_id}): {rows} filas | {lead_update}")

        # Fallback: buscar por campaign_id + teléfono si no se encontró por call_id
        if rows == 0 and enc_curr_data.get("telefono"):
            logger.warning(f"⚠️ Fallback por teléfono para encuesta {encuesta_id}")
            enc_full = supabase.table("encuestas").select("campaign_id, telefono").eq("id", encuesta_id).execute()
            if enc_full.data and enc_full.data[0].get("campaign_id"):
                camp_id = enc_full.data[0]["campaign_id"]
                tel = enc_full.data[0].get("telefono", "")
                supabase.table("campaign_leads").update({**lead_update, "call_id": encuesta_id}).eq("campaign_id", camp_id).eq("phone_number", tel).execute()
    except Exception as e:
        logger.error(f"❌ Error propagando lead para encuesta {encuesta_id}: {e}")


async def _notify_n8n_post_call(encuesta_id: int, status: str, result_data: dict, empresa_id: int, telefono: str):
    """
    Envía los datos post-llamada a n8n para integración CRM.
    n8n ya NO orquesta el goteo; solo recibe los resultados finales.
    """
    # Primero intentamos el webhook específico de CRM (si la empresa lo tiene configurado)
    try:
        emp_res = supabase.table("empresas").select("crm_webhook_url, crm_type").eq("id", empresa_id).execute()
        if emp_res.data and emp_res.data[0].get("crm_webhook_url"):
            cfg = emp_res.data[0]
            crm_payload = {
                "event": "call_completed" if status == "completed" else ("call_rejected" if status == "rejected_opt_out" else "call_failed"),
                "encuesta_id": encuesta_id,
                "empresa_id": empresa_id,
                "status": status,
                "lead": {"phone": telefono},
                "results": result_data,
                "crm_type": cfg.get("crm_type", "custom"),
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(cfg["crm_webhook_url"], json=crm_payload, timeout=10) as resp:
                    logger.info(f"📡 CRM Webhook [{status}] → {cfg['crm_webhook_url']} ({resp.status})")
    except Exception as e:
        logger.warning(f"⚠️ Error en CRM Webhook: {e}")

    # También notificar al webhook global de n8n si está configurado
    n8n_results_url = os.getenv("N8N_WEBHOOK_URL_RESULTS")
    if not n8n_results_url:
        return
    try:
        n8n_payload = {
            "encuesta_id": encuesta_id,
            "empresa_id": empresa_id,
            "telefono": telefono,
            "status": status,
            "resultados": result_data,
            "transcription": result_data.get("transcription"),
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(n8n_results_url, json=n8n_payload, timeout=10) as resp:
                logger.info(f"📡 n8n results webhook [{status}] → {resp.status}")
    except Exception as e:
        logger.warning(f"⚠️ Error en n8n results webhook: {e}")


# ──────────────────────────────────────────────
# Llamada saliente (individual o desde campaña)
# ──────────────────────────────────────────────

# Lock para evitar doble despacho accidental
# Fallback en memoria si Redis no está disponible
_processing_rooms_fallback: set[str] = set()


async def _acquire_room_lock(room_name: str) -> bool:
    """Intenta adquirir lock distribuido para un room. Fallback a set local."""
    try:
        from services.redis_service import acquire_lock
        return await acquire_lock(f"room:{room_name}", ttl_seconds=30)
    except Exception:
        # Redis no disponible: fallback a set en memoria
        if room_name in _processing_rooms_fallback:
            return False
        _processing_rooms_fallback.add(room_name)
        return True


async def _release_room_lock(room_name: str) -> None:
    """Libera lock distribuido para un room."""
    try:
        from services.redis_service import release_lock
        await release_lock(f"room:{room_name}")
    except Exception:
        pass
    _processing_rooms_fallback.discard(room_name)


@router.post("/api/calls/outbound")
async def make_outbound_call(request: dict, _api_key: str = Depends(_outbound_api_key)):
    """Inicia una llamada SIP individual. Usado para pruebas desde el dashboard."""
    phone = request.get("phoneNumber")
    agent_id = request.get("agentId", "1")
    lead_id = request.get("leadId")
    campaign_id = request.get("campaignId")

    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number is required"})

    encuesta_id = None

    try:
        if supabase:
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

            res_enc = supabase.table("encuestas").insert({
                "telefono": phone,
                "nombre_cliente": request.get("customerName", "Prueba Dashboard"),
                "fecha": datetime.now(timezone.utc).isoformat(),
                "status": "initiated",
                "completada": 0,
                "agent_id": agent_id,
                "empresa_id": emp_id,
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
            }).execute()
            encuesta_id = res_enc.data[0]["id"]

            if lead_id:
                supabase.table("campaign_leads").update({
                    "call_id": encuesta_id,
                    "status": "calling",
                    "last_call_at": datetime.now(timezone.utc).isoformat(),
                }).eq("id", lead_id).execute()
        else:
            encuesta_id = random.randint(1000, 9999)

        agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
        # Formato aislado estricto con prefijo de dominio propio:
        # llamada_ausarta_empresa_{id}_campana_{id}_contacto_{id}_encuesta_{id}
        contacto_id = int(lead_id) if lead_id else 0
        camp_id_str = str(campaign_id) if campaign_id else "0"
        room_name = f"llamada_ausarta_empresa_{emp_id or 0}_campana_{camp_id_str}_contacto_{contacto_id}_encuesta_{encuesta_id}"
        sip_trunk_id = os.getenv("SIP_OUTBOUND_TRUNK_ID")

        # Prevención de doble despacho (lock distribuido vía Redis)
        if not await _acquire_room_lock(room_name):
            logger.warning(f"⚠️ Despacho ya en curso para {room_name}. Ignorando.")
            return {"status": "ok", "message": "Call already initiated", "roomName": room_name}

        room_metadata = {
            "empresa_id": int(emp_id or 0),
            "campaign_id": int(campaign_id or 0),
            "campana_id": int(campaign_id or 0),
            "contacto_id": contacto_id,
            "client_id": contacto_id,
            "lead_id": contacto_id,
            "survey_id": int(encuesta_id),
        }

        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as e:
            logger.warning(f"⚠️ Aviso al crear sala {room_name}: {e}")

        # Despachar agente ANTES del SIP para que esté listo cuando el cliente conteste
        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            logger.info(f"✅ Agente {agent_name_dispatch} despachado a sala {room_name}")
            await asyncio.sleep(float(os.getenv("DRIP_AGENT_JOIN_DELAY_SECONDS", "3")))
        except Exception as dispatch_err:
            logger.warning(f"⚠️ Dispatch explícito fallido (auto-dispatch como fallback): {dispatch_err}")

        try:
            await lkapi.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=sip_trunk_id,
                sip_call_to=phone,
                room_name=room_name,
                participant_identity=f"user_{phone}_{encuesta_id}",
                participant_name="Cliente",
            ))
        except Exception as sip_err:
            await _release_room_lock(room_name)
            raise sip_err
        except Exception as dispatch_err:
            logger.warning(f"⚠️ Dispatch explícito fallido (auto-dispatch como fallback): {dispatch_err}")

        async def clear_lock(rname: str) -> None:
            await asyncio.sleep(10)
            await _release_room_lock(rname)

        asyncio.create_task(clear_lock(room_name))

        # Grabación de audio (solo si ENABLE_RECORDING=true y credenciales configuradas)
        asyncio.create_task(_safe_start_recording(room_name, encuesta_id))

        return {"status": "ok", "roomName": room_name, "callId": encuesta_id}

    except Exception as e:
        if "room_name" in locals():
            await _release_room_lock(room_name)
        logger.error(f"❌ Error fatal en outbound call: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# ──────────────────────────────────────────────
# Webhook de LiveKit — sustituye al polling
# ──────────────────────────────────────────────

@router.post("/api/livekit/webhook")
async def livekit_webhook(request: Request):
    """
    Recibe eventos de LiveKit y actualiza los estados de leads y encuestas.

    Eventos relevantes:
      - room_finished: la sala se cerró (todos los participantes se fueron).
      - participant_left: un participante salió (para detectar cliente que cuelga).

    Nota: LiveKit envía estos eventos firmados con el API Secret.
    Para producción, valida la firma con livekit.api.WebhookReceiver.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON"})

    event = body.get("event", "")
    room_info = body.get("room", {})
    room_name = room_info.get("name", "")
    room_metadata_raw = room_info.get("metadata")

    logger.info(f"🔔 [LK Webhook] Evento: {event} | Sala: {room_name}")

    if not room_name:
        return {"status": "ignored", "reason": "No room name"}

    # Extraer encuesta_id del nombre de sala (formato: {agent_prefix}_encuesta_{id})
    room_metadata = {}
    if isinstance(room_metadata_raw, str) and room_metadata_raw.strip():
        try:
            import json
            room_metadata = json.loads(room_metadata_raw)
        except Exception:
            logger.warning(f"[LK Webhook] metadata no parseable en sala {room_name}: {room_metadata_raw}")

    encuesta_id = _extract_encuesta_id_from_room(room_name)
    if not encuesta_id:
        try:
            encuesta_id = int(room_metadata.get("survey_id") or 0)
        except Exception:
            encuesta_id = 0

    if not encuesta_id:
        logger.info(f"[LK Webhook] No se pudo extraer encuesta_id de sala {room_name} ni metadata")
        return {"status": "ignored", "reason": "No encuesta_id in room name/metadata"}

    if event == "room_finished":
        await _handle_room_finished(encuesta_id, room_name, room_metadata)

    elif event == "participant_left":
        participant = body.get("participant", {})
        participant_identity = participant.get("identity", "")
        # Solo nos interesa cuando el cliente (no el agente) se va
        if not participant_identity.startswith("agent-"):
            await _handle_participant_left(encuesta_id, room_name, participant_identity, room_metadata)

    return {"status": "ok", "event": event}


def _extract_encuesta_id_from_room(room_name: str) -> int | None:
    """
    Extrae el encuesta_id del nombre de sala. Soporta dos formatos:
      - Nuevo:   llamada_ausarta_empresa_{id}_campana_{id}_contacto_{id}_encuesta_{encuesta_id}
      - Intermedio: empresa_{id}_camp_{id}_call_{encuesta_id}
      - Legacy:  {prefix}_encuesta_{encuesta_id}  o  encuesta_{encuesta_id}
    Retorna None si no se puede extraer.
    """
    try:
        # Formato nuevo estricto: ..._encuesta_{id}
        if "encuesta_" in room_name:
            after_enc = room_name.split("encuesta_")[-1]
            candidate = after_enc.split("_")[0]
            if candidate.isdigit():
                return int(candidate)

        # Formato intermedio: empresa_N_camp_N_call_N
        if "call_" in room_name:
            after_call = room_name.split("call_")[-1]
            candidate = after_call.split("_")[0]
            if candidate.isdigit():
                return int(candidate)

        # Fallback: el último segmento numérico
        parts = room_name.split("_")
        for segment in reversed(parts):
            if segment.isdigit():
                return int(segment)

        return None
    except Exception:
        return None



async def _safe_start_recording(room_name: str, encuesta_id: int) -> None:
    """Inicia la grabación de audio sin bloquear el flujo principal."""
    try:
        from services.recording_service import start_recording
        await start_recording(room_name, encuesta_id)
    except Exception as exc:
        logger.debug(f"[Recording] start_recording ignorado: {exc}")


async def _safe_stop_recording(encuesta_id: int) -> None:
    """Para la grabación y guarda la URL en la encuesta si existe."""
    try:
        from services.recording_service import stop_recording
        recording_url = await stop_recording(encuesta_id)
        if recording_url and supabase:
            await asyncio.to_thread(
                supabase.table("encuestas")
                    .update({"recording_url": recording_url})
                    .eq("id", encuesta_id)
                    .execute
            )
            logger.info(f"🎵 [Recording] URL guardada para encuesta {encuesta_id}: {recording_url}")
    except Exception as exc:
        logger.debug(f"[Recording] stop_recording ignorado: {exc}")


async def _handle_room_finished(encuesta_id: int, room_name: str, room_metadata: dict | None = None):
    """
    La sala se cerró. Si el estado en BD todavía no es terminal,
    significa que la llamada no se completó normalmente → marcamos 'failed'.
    """
    if not supabase:
        return

    # Parar grabación (si estaba activa) antes de cualquier otra cosa
    asyncio.create_task(_safe_stop_recording(encuesta_id))

    try:
        res = await asyncio.to_thread(
            supabase.table("encuestas")
                .select("status, empresa_id, telefono")
                .eq("id", encuesta_id)
                .limit(1)
                .execute
        )
        if not res.data:
            return

        enc = res.data[0]
        current_status = enc.get("status") or ""

        if current_status not in _TERMINAL_STATUSES:
            # La sala cerró pero el agente no guardó un status final → fallida reintentable
            logger.warning(f"📵 [LK Webhook] Sala {room_name} cerrada sin status terminal. Forzando 'failed'. metadata={room_metadata or {}}")
            await asyncio.to_thread(
                supabase.table("encuestas").update({"status": "failed"}).eq("id", encuesta_id).execute
            )
            # Propagar a campaign_leads
            await _propagate_to_lead(encuesta_id, "failed", enc)
        else:
            logger.info(f"[LK Webhook] Sala {room_name} cerrada con status terminal: {current_status}. Sin acción.")
    except Exception as e:
        logger.error(f"❌ [LK Webhook] Error en room_finished para encuesta {encuesta_id}: {e}")


async def _handle_participant_left(encuesta_id: int, room_name: str, identity: str, room_metadata: dict | None = None):
    """
    Un participante (cliente) salió de la sala.
    No hacemos nada terminante aquí: esperamos el evento room_finished.
    Solo registramos el evento para auditoría.
    """
    logger.info(f"👤 [LK Webhook] Participante '{identity}' salió de sala {room_name} (encuesta {encuesta_id}, metadata={room_metadata or {}}). Esperando room_finished.")
