"""
monitoring.py — SSE endpoint /api/monitoring/stream

FIX H: Sustituye el polling HTTP cada 8-15s del frontend por un Server-Sent Events
(SSE) que emite un evento cada 2s con métricas de llamadas activas y Redis.
Esto reduce la latencia perceptible de 8-15s a 2s sin aumentar carga en el servidor
(1 conexión persistente vs peticiones repetidas).

Protegido con Bearer JWT (require_admin).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import StreamingResponse

from services.auth import CurrentUser, require_admin, _get_user_from_supabase_jwt
from services.profile_cache import get_user_profile_cached

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])

# Intervalo de emisión SSE (segundos)
_SSE_INTERVAL = float(os.getenv("MONITORING_SSE_INTERVAL", "2"))
# Timeout máximo de la conexión SSE antes de que el cliente reconecte (segundos)
_SSE_KEEPALIVE_INTERVAL = 30.0


async def _build_metrics_payload() -> dict:
    """
    Construye el payload de métricas para un evento SSE.
    Consulta LiveKit y Redis en paralelo; si falla alguno devuelve valores parciales.
    """
    from services.livekit_service import lkapi
    from services.redis_service import get_redis

    rooms_data: list[dict] = []
    total_rooms = 0
    redis_info: dict = {}

    # ── LiveKit rooms ───────────────────────────────────────────────
    try:
        if lkapi:
            from livekit import api as lk_api
            rooms_res = await lkapi.room.list_rooms(lk_api.ListRoomsRequest())
            import re
            now_ts = int(time.time())
            for r in rooms_res.rooms:
                name = r.name or ""
                enc_m = re.search(r"encuesta_(\d+)", name)
                emp_m = re.search(r"empresa_(\d+)", name)
                cam_m = re.search(r"campana_(\d+)", name)
                rooms_data.append({
                    "sid": r.sid,
                    "name": name,
                    "num_participants": r.num_participants,
                    "created_at": r.creation_time,
                    "duration_seconds": max(0, now_ts - r.creation_time) if r.creation_time else 0,
                    "metadata": {
                        "encuesta_id": int(enc_m.group(1)) if enc_m else None,
                        "empresa_id": int(emp_m.group(1)) if emp_m else None,
                        "campaign_id": int(cam_m.group(1)) if cam_m else None,
                    },
                })
            total_rooms = len(rooms_data)
    except Exception as lk_err:
        logger.debug("[SSE] LiveKit rooms error: %s", lk_err)

    # ── Redis info ──────────────────────────────────────────────────
    try:
        r = await get_redis()
        info = await r.info("all")

        def _fmt_bytes(n: int) -> str:
            for unit in ("B", "KB", "MB", "GB"):
                if n < 1024:
                    return f"{n:.1f} {unit}"
                n //= 1024
            return f"{n} TB"

        redis_info = {
            "memory_used": _fmt_bytes(info.get("used_memory", 0)),
            "memory_peak": _fmt_bytes(info.get("used_memory_peak", 0)),
            "connected_clients": info.get("connected_clients", 0),
            "ops_per_second": info.get("instantaneous_ops_per_sec", 0),
            "uptime_days": info.get("uptime_in_days", 0),
        }
    except Exception as redis_err:
        logger.debug("[SSE] Redis info error: %s", redis_err)

    return {
        "ts": int(time.time() * 1000),
        "live_calls": {
            "total": total_rooms,
            "rooms": rooms_data,
        },
        "redis": redis_info,
    }


async def _event_generator(user: CurrentUser) -> AsyncGenerator[str, None]:
    """
    Generador async que emite eventos SSE mientras el cliente esté conectado.
    Emite cada _SSE_INTERVAL segundos.
    Emite keepalive comment (": keep-alive\n\n") para mantener la conexión.
    """
    last_keepalive = time.monotonic()
    while True:
        try:
            payload = await _build_metrics_payload()
            data = json.dumps(payload, ensure_ascii=False)
            yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            logger.debug("[SSE] Cliente desconectado (%s)", user.user_id)
            return
        except Exception as err:
            logger.warning("[SSE] Error construyendo payload: %s", err)
            yield f"data: {json.dumps({'error': str(err)})}\n\n"

        now = time.monotonic()
        if now - last_keepalive >= _SSE_KEEPALIVE_INTERVAL:
            yield ": keep-alive\n\n"
            last_keepalive = now

        try:
            await asyncio.sleep(_SSE_INTERVAL)
        except asyncio.CancelledError:
            return


async def _resolve_sse_user(token: str) -> CurrentUser:
    """
    Valida un JWT enviado como query param ?token=<jwt> para SSE.
    EventSource nativo del navegador no permite enviar headers Authorization,
    por lo que usamos query param como alternativa estándar para SSE autenticado.
    """
    try:
        auth_user = _get_user_from_supabase_jwt(token)
        user_id = auth_user.get("id")
        if not user_id:
            raise HTTPException(status_code=401, detail="Token inválido")
        profile = await get_user_profile_cached(user_id)
        role = profile.get("role", "")
        if role not in ("superadmin", "admin"):
            raise HTTPException(status_code=403, detail="Admin required")
        return CurrentUser(
            user_id=user_id,
            email=profile.get("email"),
            role=role,
            empresa_id=profile.get("empresa_id"),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


_CALL_SSE_INTERVAL = 1.5


async def _build_call_payload(room_name: str) -> dict:
    """
    Construye el payload SSE para una llamada individual.
    Extrae transcript, contacto y extensiones desde Supabase + LiveKit.
    """
    from services.supabase_service import supabase, sb_query
    import re as _re

    status = "active"
    duration_seconds = 0
    transcript: list[dict] = []
    contact: dict = {"nombre": None, "telefono": "", "datos_extra": {}}
    transfer_briefing: str | None = None
    extensions_available: list[dict] = []
    empresa_id: int | None = None

    # ── Duración y status de la sala (LiveKit) ──────────────────────────────
    try:
        from services.livekit_service import lkapi
        if lkapi:
            from livekit import api as lk_api
            rooms_res = await lkapi.room.list_rooms(lk_api.ListRoomsRequest(names=[room_name]))
            if rooms_res.rooms:
                r = rooms_res.rooms[0]
                now_ts = int(time.time())
                duration_seconds = max(0, now_ts - r.creation_time) if r.creation_time else 0
    except Exception:
        pass

    # ── Datos de encuesta (Supabase) ─────────────────────────────────────────
    if supabase:
        try:
            enc_m = _re.search(r"encuesta_(\d+)", room_name)
            enc_id = int(enc_m.group(1)) if enc_m else None

            if enc_id:
                enc_res = await sb_query(
                    lambda eid=enc_id: supabase.table("encuestas")
                    .select("status, datos_extra, empresa_id")
                    .eq("id", eid)
                    .limit(1)
                    .execute()
                )
                if enc_res.data:
                    enc = enc_res.data[0]
                    enc_status = enc.get("status") or "active"
                    empresa_id = enc.get("empresa_id")

                    if enc_status in ("transferred",):
                        status = "transferred"
                    elif enc_status in ("completed", "failed", "no_contesta"):
                        status = "ended"

                    datos_extra_raw = enc.get("datos_extra") or {}
                    if isinstance(datos_extra_raw, str):
                        try:
                            import json as _json
                            datos_extra_raw = _json.loads(datos_extra_raw)
                        except Exception:
                            datos_extra_raw = {}

                    transfer_briefing = datos_extra_raw.get("transfer_briefing") or None

                    # Transcript desde datos_extra o transcripcion
                    raw_transcript = datos_extra_raw.get("raw") or []
                    if raw_transcript and isinstance(raw_transcript, list):
                        for entry in raw_transcript[-50:]:
                            role = entry.get("role", "assistant")
                            speaker = "agent" if role == "assistant" else "user"
                            transcript.append({
                                "speaker": speaker,
                                "text": entry.get("content", ""),
                                "ts": "",
                            })

            # ── Contacto ─────────────────────────────────────────────────────
            if empresa_id:
                emp_m = _re.search(r"empresa_(\d+)", room_name)
                eid_room = int(emp_m.group(1)) if emp_m else empresa_id

                phone_patterns = _re.findall(r"\+?[\d]{9,15}", room_name)
                if not phone_patterns:
                    contact_res = await sb_query(
                        lambda eid=eid_room: supabase.table("contactos")
                        .select("nombre, telefono, datos_extra")
                        .eq("empresa_id", eid)
                        .limit(1)
                        .execute()
                    )
                else:
                    phone = phone_patterns[0]
                    contact_res = await sb_query(
                        lambda eid=eid_room, p=phone: supabase.table("contactos")
                        .select("nombre, telefono, datos_extra")
                        .eq("empresa_id", eid)
                        .eq("telefono", p)
                        .limit(1)
                        .execute()
                    )
                if contact_res.data:
                    c = contact_res.data[0]
                    contact = {
                        "nombre": c.get("nombre"),
                        "telefono": c.get("telefono", ""),
                        "datos_extra": c.get("datos_extra") or {},
                    }

                # ── Extensiones disponibles ──────────────────────────────────
                ext_res = await sb_query(
                    lambda eid=eid_room: supabase.table("yeastar_extensions")
                    .select("id, extension_number, extension_name, departamento")
                    .eq("empresa_id", eid)
                    .order("extension_number")
                    .execute()
                )
                extensions_available = ext_res.data or []

        except Exception as db_err:
            logger.debug("[SSE call] Error obteniendo datos encuesta/contacto: %s", db_err)

    return {
        "room_name": room_name,
        "status": status,
        "duration_seconds": duration_seconds,
        "transcript": transcript,
        "contact": contact,
        "transfer_briefing": transfer_briefing,
        "extensions_available": extensions_available,
    }


async def _call_event_generator(room_name: str, user: CurrentUser) -> AsyncGenerator[str, None]:
    """Generador SSE para una llamada individual. Emite cada 1.5 s."""
    last_keepalive = time.monotonic()
    while True:
        try:
            payload = await _build_call_payload(room_name)
            data = json.dumps(payload, ensure_ascii=False)
            yield f"data: {data}\n\n"
        except asyncio.CancelledError:
            return
        except Exception as err:
            logger.warning("[SSE call] Error construyendo payload: %s", err)
            yield f"data: {json.dumps({'error': str(err)})}\n\n"

        now = time.monotonic()
        if now - last_keepalive >= _SSE_KEEPALIVE_INTERVAL:
            yield ": keep-alive\n\n"
            last_keepalive = now

        try:
            await asyncio.sleep(_CALL_SSE_INTERVAL)
        except asyncio.CancelledError:
            return


@router.get("/call/{room_name}/stream")
async def call_stream(
    room_name: str,
    token: str = Query(..., description="Bearer JWT"),
) -> StreamingResponse:
    """
    SSE endpoint de llamada individual en tiempo real.
    Emite cada 1.5 s con: status, duration, transcript, contact, transfer_briefing, extensions.
    Autenticación: pasa el JWT como ?token=<jwt>.
    """
    user = await _resolve_sse_user(token)
    return StreamingResponse(
        _call_event_generator(room_name, user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/stream")
async def monitoring_stream(
    token: str = Query(..., description="Bearer JWT (EventSource no soporta Authorization header)"),
) -> StreamingResponse:
    """
    SSE endpoint de métricas de monitorización en tiempo real.

    Emite eventos 'message' cada 2s con:
      - live_calls.total, live_calls.rooms
      - redis

    Autenticación: pasa el JWT como ?token=<jwt> (necesario porque EventSource
    nativo del navegador no admite cabeceras Authorization personalizadas).
    Solo accesible para rol admin o superadmin.
    """
    user = await _resolve_sse_user(token)
    return StreamingResponse(
        _event_generator(user),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Nginx: desactivar buffer para SSE
        },
    )
