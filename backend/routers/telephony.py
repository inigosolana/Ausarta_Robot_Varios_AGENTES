"""
telephony.py — Gestión de llamadas, webhooks entrantes e integración Yeastar PBX.

Responsabilidades:
  - /colgar: cierra una sala de LiveKit.
  - /guardar-encuesta: persiste datos de una encuesta y propaga estado a campaign_leads.
  - /api/calls/outbound: inicia una llamada SIP individual (test o desde campaña).
  - /api/livekit/webhook: recibe eventos de LiveKit (room_finished, participant_left)
    para actualizar el estado de los leads sin polling.
  - /api/telephony/yeastar: CRUD de la configuración Yeastar PBX por empresa.
  - /api/telephony/yeastar/test: prueba la conexión en tiempo real sin persistir.
  - /api/calls/transfer: transferencia multi-tenant a agente humano (Yeastar).
  - /api/telephony/transfer: alias legacy del endpoint de transferencia.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, Request, HTTPException
from fastapi.responses import JSONResponse
from models.schemas import (
    CallEndRequest,
    CallTransferRequest,
    EncuestaData,
    TelephonyTransferRequest,
    TestOutboundCallRequest,
    YeastarPSeriesConfigCreate,
    YeastarPSeriesConfigResponse,
    YeastarPSeriesConfigTest,
)
from services.supabase_service import supabase, sb_query
from services.platform_access import has_global_access
from services.livekit_service import (
    lkapi,
    create_isolated_room,
    create_outbound_call,
    dispatch_agent_explicit,
)
from services.yeastar_service import YeastarPSeriesClient
from services.auth import get_current_user, CurrentUser, require_admin, require_outbound_auth
from services.crypto_service import encrypt_data, decrypt_data
from services.rate_limiter import limiter
from livekit import api
from livekit.api import WebhookReceiver
import aiohttp
import asyncio
import os
from datetime import datetime, timedelta, timezone
import random
import logging

# Credenciales LiveKit para validar firmas de webhooks entrantes
_LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
_LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])


# ──────────────────────────────────────────────────────────────────────────────
# Yeastar PBX — configuración multi-tenant (P-Series)
# ──────────────────────────────────────────────────────────────────────────────

@router.get("/api/telephony/yeastar", response_model=YeastarPSeriesConfigResponse | None)
async def get_yeastar_config(
    empresa_id: int | None = None,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Devuelve la configuración Yeastar de la empresa.
    Si empresa_id no se especifica, usa la del usuario autenticado.
    El Client Secret se enmascara si existe.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    target_empresa_id = empresa_id if empresa_id else current_user.empresa_id
    if target_empresa_id != current_user.empresa_id and not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos para ver esta configuración")

    if not target_empresa_id:
        raise HTTPException(status_code=403, detail="Usuario sin empresa asignada")

    res = await sb_query(
        lambda: supabase.table("empresas")
        .select("id, yeastar_pbx_url, yeastar_client_id, yeastar_client_secret")
        .eq("id", target_empresa_id)
        .limit(1)
        .execute()
    )

    if not res.data:
        return JSONResponse(status_code=204, content=None)

    row = res.data[0]
    
    # Check if we have Yeastar configured at all
    if not row.get("yeastar_pbx_url") or not row.get("yeastar_client_id"):
        return JSONResponse(status_code=204, content=None)

    # Mask the secret
    secret = row.get("yeastar_client_secret")
    masked_secret = "********" if secret else ""

    return {
        "empresa_id": row["id"],
        "yeastar_pbx_url": row["yeastar_pbx_url"],
        "yeastar_client_id": row["yeastar_client_id"],
        "yeastar_client_secret": masked_secret,
    }


@router.post("/api/telephony/yeastar", response_model=YeastarPSeriesConfigResponse)
async def save_yeastar_config(
    payload: YeastarPSeriesConfigCreate,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Guarda la configuración Yeastar de la empresa en la tabla empresas.
    Solo accesible para roles admin y superadmin.
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    target_empresa_id = payload.empresa_id if payload.empresa_id else current_user.empresa_id
    if target_empresa_id != current_user.empresa_id and not has_global_access(current_user):
        raise HTTPException(status_code=403, detail="No tienes permisos para editar esta configuración")

    if not target_empresa_id:
        raise HTTPException(status_code=403, detail="Usuario sin empresa asignada")

    update_data = {
        "yeastar_pbx_url": payload.yeastar_pbx_url.strip(),
        "yeastar_client_id": payload.yeastar_client_id.strip(),
    }
    
    # Only update secret if it's not the masked string
    if payload.yeastar_client_secret and payload.yeastar_client_secret != "********":
        # Hardening: Encrypt secret before saving
        update_data["yeastar_client_secret"] = encrypt_data(payload.yeastar_client_secret.strip())

    res = await sb_query(
        lambda: supabase.table("empresas")
        .update(update_data)
        .eq("id", target_empresa_id)
        .execute()
    )

    if not res.data:
        raise HTTPException(status_code=500, detail="Error al guardar la configuración Yeastar")

    row = res.data[0]
    
    return {
        "empresa_id": row["id"],
        "yeastar_pbx_url": row["yeastar_pbx_url"],
        "yeastar_client_id": row["yeastar_client_id"],
        "yeastar_client_secret": "********" if row.get("yeastar_client_secret") else "",
    }


@router.post("/api/telephony/yeastar/test")
async def test_yeastar_connection(
    payload: YeastarPSeriesConfigTest,
    current_user: CurrentUser = Depends(require_admin),
):
    """
    Prueba la conexión con la centralita Yeastar usando las credenciales
    proporcionadas en tiempo real.
    """
    client_secret = payload.yeastar_client_secret
    target_empresa_id = payload.empresa_id if payload.empresa_id else current_user.empresa_id

    # If masked, we need to fetch the real secret from DB
    if client_secret == "********":
        res = await sb_query(
            lambda: supabase.table("empresas")
            .select("yeastar_client_secret")
            .eq("id", target_empresa_id)
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("yeastar_client_secret"):
            # Hardening: Decrypt secret from DB for testing
            client_secret = decrypt_data(res.data[0]["yeastar_client_secret"])
        else:
            return {"ok": False, "message": "No se encontró el secreto original en la base de datos."}
    else:
        # If it's a new secret being tested, use it as is (will be encrypted on save)
        pass

    client = YeastarPSeriesClient(
        pbx_url=payload.yeastar_pbx_url,
        client_id=payload.yeastar_client_id,
        client_secret=client_secret,
        tenant_id=target_empresa_id,
    )

    ok, message = await client.test_connection()
    await client.close()
    return {"ok": ok, "message": message}


def _parse_datos_extra(raw: object) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            import json as _json
            parsed = _json.loads(raw)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


async def _resolve_survey_id(room_name: str, survey_id: int | None) -> int:
    """Obtiene survey_id del body o extrayéndolo del nombre de sala LiveKit."""
    if survey_id:
        return survey_id
    extracted = _extract_encuesta_id_from_room(room_name.strip())
    if extracted:
        return extracted
    raise HTTPException(
        status_code=400,
        detail="No se pudo determinar survey_id. Envíe survey_id o un room_name válido (ej. ..._encuesta_123).",
    )


async def _load_yeastar_tenant_config(empresa_id: int) -> dict:
    """
    Credenciales Yeastar del tenant (tabla empresas).
    target_extension: variable de entorno global o datos_extra de la encuesta.
    """
    emp_res = await sb_query(
        lambda: supabase.table("empresas")
        .select("id, yeastar_pbx_url, yeastar_client_id, yeastar_client_secret")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    emp = emp_res.data[0]
    if not emp.get("yeastar_pbx_url") or not emp.get("yeastar_client_id"):
        raise HTTPException(
            status_code=400,
            detail="Centralita Yeastar no configurada para esta empresa",
        )
    if not emp.get("yeastar_client_secret"):
        raise HTTPException(status_code=400, detail="Credenciales Yeastar incompletas")

    return emp


def _resolve_target_extension(
    datos_extra: dict,
    explicit: str | None = None,
) -> str:
    ext = (
        (explicit or "").strip()
        or (os.getenv("YEASTAR_HUMAN_TRANSFER_EXTENSION") or "").strip()
        or str(datos_extra.get("target_extension") or "").strip()
        or str(datos_extra.get("human_transfer_extension") or "").strip()
    )
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Extensión de transferencia no configurada (YEASTAR_HUMAN_TRANSFER_EXTENSION).",
        )
    return ext


async def _execute_yeastar_transfer(
    *,
    room_name: str,
    survey_id: int,
    motivo: str | None = None,
    call_id: str | None = None,
    target_extension: str | None = None,
    yeastar_call_id: str | None = None,
) -> dict:
    """Lógica compartida de transferencia multi-tenant vía Yeastar P-Series."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    room_name = room_name.strip()

    enc_res = await sb_query(
        lambda sid=survey_id: supabase.table("encuestas")
        .select("id, empresa_id, telefono, datos_extra, status")
        .eq("id", sid)
        .limit(1)
        .execute()
    )
    if not enc_res.data:
        raise HTTPException(status_code=404, detail=f"Encuesta {survey_id} no encontrada")

    enc = enc_res.data[0]
    empresa_id = enc.get("empresa_id")
    if not empresa_id:
        logger.error(f"[transfer] Encuesta {survey_id} sin empresa_id (room={room_name})")
        raise HTTPException(status_code=400, detail="Encuesta sin empresa asociada")

    emp = await _load_yeastar_tenant_config(empresa_id)
    datos_extra = _parse_datos_extra(enc.get("datos_extra"))

    resolved_call_id = (
        call_id
        or yeastar_call_id
        or datos_extra.get("yeastar_callid")
        or datos_extra.get("yeastar_call_id")
        or room_name
    )
    resolved_extension = _resolve_target_extension(datos_extra, target_extension)

    client_secret = decrypt_data(emp["yeastar_client_secret"])
    client = YeastarPSeriesClient(
        pbx_url=emp["yeastar_pbx_url"],
        client_id=emp["yeastar_client_id"],
        client_secret=client_secret,
        tenant_id=empresa_id,
    )

    try:
        await client.transfer_call(str(resolved_call_id), resolved_extension)
    except Exception as exc:
        logger.error(
            f"[transfer] Fallo Yeastar empresa={empresa_id} survey={survey_id} "
            f"room={room_name} call_id={resolved_call_id}: {exc}"
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await client.close()

    motivo_text = (motivo or "Transferencia a agente humano").strip()
    merged_extra = {
        **datos_extra,
        "transfer_room": room_name,
        "transfer_extension": resolved_extension,
        "yeastar_callid": str(resolved_call_id),
    }
    await sb_query(
        lambda sid=survey_id, extra=merged_extra, m=motivo_text, ext=resolved_extension: supabase.table("encuestas")
        .update({
            "status": "transferred",
            "comentarios": f"Transferido a ext {ext}: {m}",
            "datos_extra": extra,
        })
        .eq("id", sid)
        .execute()
    )

    logger.info(
        f"✅ [transfer] empresa={empresa_id} survey={survey_id} "
        f"call_id={resolved_call_id} → ext {resolved_extension} room={room_name}"
    )
    return {
        "status": "ok",
        "message": "Transferencia iniciada en la centralita",
        "empresa_id": empresa_id,
        "survey_id": survey_id,
        "room_name": room_name,
        "call_id": str(resolved_call_id),
        "target_extension": resolved_extension,
    }


@router.post("/api/calls/transfer")
async def transfer_call_to_human(payload: CallTransferRequest):
    """
    Transfiere una llamada a extensión humana tras comprobar que está Idle en Yeastar.

    Body: ``room_name``, ``empresa_id``, ``call_id``, ``extension`` (default 1000).
    """
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    room_name = payload.room_name.strip()
    if not room_name:
        raise HTTPException(status_code=400, detail="room_name es obligatorio")

    if not payload.empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es obligatorio")

    call_id = (payload.call_id or "").strip()
    if not call_id:
        raise HTTPException(status_code=400, detail="call_id es obligatorio")

    extension = (payload.extension or "1000").strip()
    empresa_id = int(payload.empresa_id)

    emp_res = await sb_query(
        lambda eid=empresa_id: supabase.table("empresas")
        .select("id, yeastar_pbx_url, yeastar_client_id, yeastar_client_secret")
        .eq("id", eid)
        .limit(1)
        .execute()
    )
    if not emp_res.data:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")

    emp = emp_res.data[0]
    pbx_url = emp.get("yeastar_pbx_url") or emp.get("yeastar_url")
    client_id = emp.get("yeastar_client_id")
    client_secret_enc = emp.get("yeastar_client_secret") or emp.get("yeastar_secret")

    if not pbx_url or not client_id or not client_secret_enc:
        logger.warning(f"[transfer] Yeastar no configurado para empresa_id={empresa_id}")
        raise HTTPException(
            status_code=404,
            detail="Centralita Yeastar no configurada para esta empresa",
        )

    client_secret = decrypt_data(client_secret_enc)
    yeastar_client = YeastarPSeriesClient(
        pbx_url=pbx_url,
        client_id=client_id,
        client_secret=client_secret,
        tenant_id=empresa_id,
    )

    try:
        ext_status = await yeastar_client.get_extension_status(extension)
        if ext_status != "Idle":
            logger.info(
                f"[transfer] Extensión {extension} no disponible (status={ext_status}) "
                f"empresa={empresa_id} room={room_name}"
            )
            return JSONResponse(
                status_code=409,
                content={
                    "message": f"Extensión ocupada ({ext_status})",
                    "status": ext_status,
                },
            )

        await yeastar_client.transfer_call(call_id, extension)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            f"[transfer] Error Yeastar empresa={empresa_id} call_id={call_id}: {exc}"
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    finally:
        await yeastar_client.close()

    survey_id = payload.survey_id
    if survey_id is None:
        survey_id = _extract_encuesta_id_from_room(room_name)

    if survey_id:
        motivo_text = (payload.motivo or "Transferencia a agente humano").strip()
        try:
            enc_res = await sb_query(
                lambda sid=survey_id: supabase.table("encuestas")
                .select("datos_extra")
                .eq("id", sid)
                .limit(1)
                .execute()
            )
            datos_extra = _parse_datos_extra(
                enc_res.data[0].get("datos_extra") if enc_res.data else {}
            )
            merged_extra = {
                **datos_extra,
                "transfer_room": room_name,
                "transfer_extension": extension,
                "yeastar_callid": call_id,
            }
            await sb_query(
                lambda sid=survey_id, extra=merged_extra, m=motivo_text, ext=extension: supabase.table("encuestas")
                .update({
                    "status": "transferred",
                    "comentarios": f"Transferido a ext {ext}: {m}",
                    "datos_extra": extra,
                })
                .eq("id", sid)
                .execute()
            )
        except Exception as db_err:
            logger.warning(f"[transfer] No se pudo actualizar encuesta {survey_id}: {db_err}")

    logger.info(
        f"✅ [transfer] empresa={empresa_id} call_id={call_id} → ext {extension} room={room_name}"
    )
    return {
        "status": "ok",
        "message": "Transferencia iniciada en la centralita",
        "empresa_id": empresa_id,
        "room_name": room_name,
        "call_id": call_id,
        "extension": extension,
        "extension_status": ext_status,
    }


@router.post("/api/telephony/transfer")
async def transfer_call_to_human_legacy(payload: TelephonyTransferRequest):
    """Alias legacy; prefiere call_id de Yeastar si está en BD."""
    return await _execute_yeastar_transfer(
        room_name=payload.room_name.strip(),
        survey_id=payload.survey_id,
        motivo=payload.motivo,
        call_id=None,
        target_extension=payload.target_extension,
        yeastar_call_id=payload.yeastar_call_id,
    )

# Hardening: IP Whitelist for Yeastar Webhooks (example placeholder)
YEASTAR_IP_WHITELIST = os.getenv("YEASTAR_IP_WHITELIST", "").split(",")

async def validate_yeastar_ip(request: Request):
    """Optional: Validates that the request comes from a trusted Yeastar PBX IP."""
    if not YEASTAR_IP_WHITELIST or YEASTAR_IP_WHITELIST == [""]:
        return # Whitelist not configured, skip validation
    
    client_ip = request.client.host
    if client_ip not in YEASTAR_IP_WHITELIST:
        logger.warning(f"🛡️ [Security] Blocked unauthorized webhook attempt from IP: {client_ip}")
        raise HTTPException(status_code=403, detail="Unauthorized IP")

@limiter.exempt
@router.post("/webhooks/yeastar")
async def yeastar_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    _=Depends(validate_yeastar_ip),  # Bloquea IPs no autorizadas si YEASTAR_IP_WHITELIST está configurado
):
    """
    Recibe eventos de la centralita Yeastar (CallAnswered, CallHangup, etc.).
    Optimización: Procesa en segundo plano para evitar timeouts de la PBX.
    """
    try:
        payload = await request.json()

        # Rendimiento: Responder inmediatamente y procesar en segundo plano
        background_tasks.add_task(_process_yeastar_event, payload)

        return {"status": "ok", "message": "Event queued"}
    except Exception as e:
        logger.error(f"❌ Error recibiendo webhook de Yeastar: {e}")
        return JSONResponse(status_code=400, content={"error": "Invalid payload"})

async def _process_yeastar_event(payload: dict):
    """Lógica pesada de procesamiento de eventos en segundo plano."""
    try:
        event_action = payload.get("action")
        call_id = payload.get("callid")
        logger.info(f"📞 [Yeastar Background] Procesando {event_action} para callid {call_id}")

        if not call_id or not supabase:
            return

        # Vincular callid de Yeastar con encuesta activa por teléfono (normalizado)
        caller = (
            payload.get("caller")
            or payload.get("from")
            or payload.get("src")
            or payload.get("callernumber")
            or ""
        )
        callee = (
            payload.get("callee")
            or payload.get("to")
            or payload.get("dst")
            or payload.get("calleenumber")
            or ""
        )
        phone_candidates = [p for p in (caller, callee) if p]

        for raw_phone in phone_candidates:
            digits = "".join(c for c in str(raw_phone) if c.isdigit())
            if len(digits) < 6:
                continue
            tail = digits[-9:] if len(digits) >= 9 else digits
            enc_res = await sb_query(
                lambda t=tail: supabase.table("encuestas")
                .select("id, datos_extra")
                .in_("status", ["initiated", "calling", "in_progress"])
                .ilike("telefono", f"%{t}%")
                .order("id", desc=True)
                .limit(1)
                .execute()
            )
            if not enc_res.data:
                continue

            row = enc_res.data[0]
            extra = row.get("datos_extra") or {}
            if isinstance(extra, str):
                try:
                    import json as _json
                    extra = _json.loads(extra)
                except Exception:
                    extra = {}
            extra["yeastar_callid"] = str(call_id)
            await sb_query(
                lambda eid=row["id"], ex=extra: supabase.table("encuestas")
                .update({"datos_extra": ex})
                .eq("id", eid)
                .execute()
            )
            logger.info(
                f"📞 [Yeastar] callid {call_id} vinculado a encuesta {row['id']} (tel ~{tail})"
            )
            break

    except Exception as e:
        logger.error(f"❌ Error en BackgroundTask de Yeastar: {e}")

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
    curr = await sb_query(
        lambda: supabase.table("encuestas").select("status, empresa_id, telefono").eq("id", datos.id_encuesta).execute()
    )
    curr_data = curr.data[0] if curr.data else {}
    (curr_data.get("status") or "")

    # Si llegaron datos pero sin status explícito:
    # Mantenemos el que haya calculado, si no se queda sin tocar.
    if normalized_status:
        update_data["status"] = normalized_status
        if normalized_status == "completed":
            update_data["completada"] = 1

    # --- Persistir en encuestas ---
    logger.info(f"📝 [guardar-encuesta] UPDATE encuesta {datos.id_encuesta}: {update_data}")
    try:
        await sb_query(
            lambda: supabase.table("encuestas").update(update_data).eq("id", datos.id_encuesta).execute()
        )
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
            lead_res = await sb_query(
                lambda: supabase.table("campaign_leads").select("campaign_id, retries_attempted").eq("call_id", encuesta_id).limit(1).execute()
            )
            if lead_res.data:
                current_retries = lead_res.data[0].get("retries_attempted", 0) or 0
                camp_id = lead_res.data[0]["campaign_id"]
                camp_res = await sb_query(
                    lambda: supabase.table("campaigns").select("retry_interval, retries_count").eq("id", camp_id).limit(1).execute()
                )
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
        result = await sb_query(
            lambda: supabase.table("campaign_leads").update(lead_update).eq("call_id", encuesta_id).execute()
        )
        rows = len(result.data) if result.data else 0
        logger.info(f"📊 Lead actualizado (call_id={encuesta_id}): {rows} filas | {lead_update}")

        # Fallback: buscar por campaign_id + teléfono si no se encontró por call_id
        if rows == 0 and enc_curr_data.get("telefono"):
            logger.warning(f"⚠️ Fallback por teléfono para encuesta {encuesta_id}")
            enc_full = await sb_query(
                lambda: supabase.table("encuestas").select("campaign_id, telefono").eq("id", encuesta_id).execute()
            )
            if enc_full.data and enc_full.data[0].get("campaign_id"):
                camp_id = enc_full.data[0]["campaign_id"]
                tel = enc_full.data[0].get("telefono", "")
                await sb_query(
                    lambda: supabase.table("campaign_leads").update({**lead_update, "call_id": encuesta_id}).eq("campaign_id", camp_id).eq("phone_number", tel).execute()
                )
    except Exception as e:
        logger.error(f"❌ Error propagando lead para encuesta {encuesta_id}: {e}")


async def _notify_n8n_post_call(encuesta_id: int, status: str, result_data: dict, empresa_id: int, telefono: str):
    """
    Envía los datos post-llamada a:
      1. webhook_url  (Zapier / Make — payload limpio y aplanado)
      2. crm_webhook_url  (CRM específico — HubSpot / Salesforce / n8n)
      3. N8N_WEBHOOK_URL_RESULTS  (webhook global de plataforma, si existe)
    """
    try:
        emp_res = await sb_query(
            lambda: supabase.table("empresas").select("crm_webhook_url, crm_type, webhook_url").eq("id", empresa_id).execute()
        )
        emp_cfg = emp_res.data[0] if (emp_res.data) else {}
    except Exception as e:
        logger.warning(f"⚠️ No se pudo leer config de empresa {empresa_id}: {e}")
        emp_cfg = {}

    datos_extra: dict = result_data.get("datos_extra") or {}

    # ── 1. Automation webhook (Zapier / Make) ──────────────────────────────────
    automation_url = emp_cfg.get("webhook_url")
    if automation_url:
        try:
            # Payload plano: los campos de datos_extra se elevan al nivel raíz
            # para que Zapier/Make los detecte como variables individuales.
            automation_payload = {
                "event": "call.completed" if status == "completed" else (
                    "call.rejected" if status == "rejected_opt_out" else "call.failed"
                ),
                "call_id": encuesta_id,
                "phone": telefono,
                "status": status,
                "date": datetime.now(timezone.utc).isoformat(),
                "campaign_name": result_data.get("campaign_name"),
                "transcription": result_data.get("transcription"),
                "seconds_used": result_data.get("seconds_used"),
                "datos_extra": datos_extra,
                **{k: v for k, v in datos_extra.items()},  # flatten for Zapier
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(automation_url, json=automation_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.info(f"📡 Automation Webhook [{status}] → {automation_url} ({resp.status})")
        except Exception as e:
            logger.warning(f"⚠️ Error en Automation Webhook: {e}")

    # ── 2. CRM webhook (HubSpot / Salesforce / n8n) ────────────────────────────
    if emp_cfg.get("crm_webhook_url"):
        try:
            crm_payload = {
                "event": "call_completed" if status == "completed" else ("call_rejected" if status == "rejected_opt_out" else "call_failed"),
                "encuesta_id": encuesta_id,
                "empresa_id": empresa_id,
                "status": status,
                "lead": {"phone": telefono},
                "results": result_data,
                "crm_type": emp_cfg.get("crm_type", "custom"),
            }
            async with aiohttp.ClientSession() as session:
                async with session.post(emp_cfg["crm_webhook_url"], json=crm_payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    logger.info(f"📡 CRM Webhook [{status}] → {emp_cfg['crm_webhook_url']} ({resp.status})")
        except Exception as e:
            logger.warning(f"⚠️ Error en CRM Webhook: {e}")


# ──────────────────────────────────────────────
# Llamada saliente (individual o desde campaña)
# ──────────────────────────────────────────────


@router.post("/api/telephony/test-outbound")
async def test_outbound_call(payload: TestOutboundCallRequest):
    """
    Endpoint de prueba: dispara una llamada saliente LiveKit SIP al número indicado.
    Crea sala, despacha agente y luego inicia el participante SIP.
    """
    trunk_id = (os.getenv("LIVEKIT_OUTBOUND_TRUNK_ID") or "").strip()
    if not trunk_id:
        raise HTTPException(
            status_code=500,
            detail="LIVEKIT_OUTBOUND_TRUNK_ID no está configurado. Configure el trunk de salida en LiveKit.",
        )

    phone = payload.phone_number.strip()
    if not phone:
        raise HTTPException(status_code=400, detail="phone_number es obligatorio")

    empresa_id = str(payload.empresa_id).strip()
    survey_id = str(payload.survey_id).strip()
    room_name = f"llamada_ausarta_{empresa_id}_{survey_id}"

    room_metadata = {
        "empresa_id": int(empresa_id) if empresa_id.isdigit() else 0,
        "survey_id": int(survey_id) if survey_id.isdigit() else 0,
    }

    try:
        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as room_err:
            logger.warning(f"⚠️ [test-outbound] Aviso al crear sala {room_name}: {room_err}")

        agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            await asyncio.sleep(float(os.getenv("DRIP_AGENT_JOIN_DELAY_SECONDS", "3")))
        except Exception as dispatch_err:
            logger.warning(f"⚠️ [test-outbound] Dispatch fallido: {dispatch_err}")

        sip_response = await create_outbound_call(
            number_to_dial=phone,
            trunk_id=trunk_id,
            room_name=room_name,
            empresa_id=empresa_id,
            survey_id=survey_id,
        )

        participant_id = getattr(sip_response, "participant_id", None) or getattr(
            sip_response, "participant_identity", None
        )

        return {
            "status": "ok",
            "message": "Llamada saliente iniciada",
            "room_name": room_name,
            "phone_number": phone,
            "participant_id": participant_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ [test-outbound] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e)) from e


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
async def make_outbound_call(request: dict, _auth: str = Depends(require_outbound_auth)):
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
                    agent_res = await sb_query(
                        lambda: supabase.table("agent_config").select("empresa_id").eq("id", agent_id).execute()
                    )
                    if agent_res.data:
                        emp_id = agent_res.data[0].get("empresa_id")
                except Exception as e:
                    logger.warning(f"⚠️ [telephony] No se pudo resolver empresa desde agente {agent_id}: {e}")

            campaign_name = request.get("campaignName")
            if campaign_id and not campaign_name:
                try:
                    camp_res = await sb_query(
                        lambda: supabase.table("campaigns").select("name").eq("id", campaign_id).execute()
                    )
                    if camp_res.data:
                        campaign_name = camp_res.data[0].get("name")
                except Exception as e:
                    logger.warning(f"⚠️ [telephony] No se pudo resolver nombre de campaña {campaign_id}: {e}")

            res_enc = await sb_query(lambda: supabase.table("encuestas").insert({
                "telefono": phone,
                "nombre_cliente": request.get("customerName", "Prueba Dashboard"),
                "fecha": datetime.now(timezone.utc).isoformat(),
                "status": "initiated",
                "completada": 0,
                "agent_id": agent_id,
                "empresa_id": emp_id,
                "campaign_id": campaign_id,
                "campaign_name": campaign_name,
            }).execute())
            encuesta_id = res_enc.data[0]["id"]

            if lead_id:
                await sb_query(
                    lambda: supabase.table("campaign_leads").update({
                        "call_id": encuesta_id,
                        "status": "calling",
                        "last_call_at": datetime.now(timezone.utc).isoformat(),
                    }).eq("id", lead_id).execute()
                )
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

@limiter.exempt
@router.post("/api/livekit/webhook")
async def livekit_webhook(request: Request):
    """
    Recibe eventos de LiveKit y actualiza los estados de leads y encuestas.

    Eventos relevantes:
      - room_finished: la sala se cerró (todos los participantes se fueron).
      - participant_left: un participante salió (para detectar cliente que cuelga).

    Seguridad: Valida la firma HMAC del webhook usando WebhookReceiver antes
    de procesar cualquier dato. Requests sin firma válida reciben un 401.
    """
    body_bytes = await request.body()
    auth_token = request.headers.get("Authorization", "")

    # Validar firma criptográfica antes de procesar el payload
    try:
        receiver = WebhookReceiver(_LIVEKIT_API_KEY, _LIVEKIT_API_SECRET)
        webhook_event = receiver.receive(body_bytes.decode("utf-8"), auth_token)
    except Exception as e:
        logger.warning(f"🛡️ [LK Webhook] Firma inválida o payload malformado: {e}")
        return JSONResponse(status_code=401, content={"error": "Invalid signature"})

    # Extraer campos del proto validado
    event = webhook_event.event
    room_name = webhook_event.room.name if webhook_event.HasField("room") else ""
    room_metadata_raw = webhook_event.room.metadata if webhook_event.HasField("room") else ""

    logger.info(f"🔔 [LK Webhook] Evento: {event} | Sala: {room_name}")

    if not room_name:
        return {"status": "ignored", "reason": "No room name"}

    # Parsear metadata de sala (JSON string embebido en el proto)
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
        participant_identity = webhook_event.participant.identity if webhook_event.HasField("participant") else ""
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

    Si la encuesta tiene transcripción, encola el análisis con LLM vía ARQ
    (process_transcription_ai) en lugar de llamar a n8n.
    """
    if not supabase:
        return

    # Parar grabación (si estaba activa) antes de cualquier otra cosa
    asyncio.create_task(_safe_stop_recording(encuesta_id))

    try:
        res = await asyncio.to_thread(
            supabase.table("encuestas")
                .select("status, empresa_id, telefono, transcription")
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

        # Encolar análisis de transcripción vía ARQ (reemplaza llamada HTTP a n8n)
        transcription = enc.get("transcription") or ""
        empresa_id = enc.get("empresa_id")
        if transcription.strip() and empresa_id:
            try:
                from services.queue_service import get_arq_pool
                arq_pool = await get_arq_pool()
                job = await arq_pool.enqueue_job(
                    "process_transcription_ai",
                    encuesta_id,
                    transcription,
                    empresa_id,
                )
                logger.info(
                    f"📬 [LK Webhook] Tarea process_transcription_ai encolada para "
                    f"encuesta {encuesta_id} (job_id={getattr(job, 'job_id', 'n/a')})."
                )
            except Exception as eq:
                # No bloquear el flujo principal si la cola falla
                logger.warning(f"⚠️ [LK Webhook] No se pudo encolar transcripción para encuesta {encuesta_id}: {eq}")
        else:
            logger.info(f"[LK Webhook] Encuesta {encuesta_id} sin transcripción o empresa_id. Skipping análisis AI.")

    except Exception as e:
        logger.error(f"❌ [LK Webhook] Error en room_finished para encuesta {encuesta_id}: {e}")


async def _handle_participant_left(encuesta_id: int, room_name: str, identity: str, room_metadata: dict | None = None):
    """
    Un participante (cliente) salió de la sala.
    No hacemos nada terminante aquí: esperamos el evento room_finished.
    Solo registramos el evento para auditoría.
    """
    logger.info(f"👤 [LK Webhook] Participante '{identity}' salió de sala {room_name} (encuesta {encuesta_id}, metadata={room_metadata or {}}). Esperando room_finished.")
