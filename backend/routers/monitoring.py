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

from services.auth import CurrentUser, require_admin, _get_user_from_supabase_jwt, get_user_profile_cached

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
