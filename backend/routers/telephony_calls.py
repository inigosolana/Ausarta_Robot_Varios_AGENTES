"""Endpoints para colgar salas LiveKit."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from livekit import api

from models.schemas import CallEndRequest
from services.auth import CurrentUser, require_admin
from services.livekit_service import lkapi
from services.queue_service import get_arq_pool
from fastapi.responses import JSONResponse

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])


@router.post("/colgar")
async def finalizar_llamada(req: CallEndRequest):
    """Cierra una sala de LiveKit."""
    try:
        logger.info("✂️ Cerrando sala: %s", req.nombre_sala)
        await lkapi.room.delete_room(api.DeleteRoomRequest(room=req.nombre_sala))
        return {"status": "ok", "message": f"Sala {req.nombre_sala} cerrada"}
    except Exception as exc:
        err_msg = str(exc).lower()
        if "not_found" in err_msg or "does not exist" in err_msg or "404" in err_msg:
            logger.info("✓ Sala %s ya cerrada (no existe). OK.", req.nombre_sala)
            return {"status": "ok", "message": "Sala ya cerrada"}
        logger.error("⚠️ Error al cerrar sala %s: %s", req.nombre_sala, exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})


@router.post("/api/calls/hang_up")
async def hang_up_call(
    payload: dict,
    current_user: CurrentUser = Depends(require_admin),
):
    """Cierra/cuelga una sala LiveKit activa. Body: { \"room_name\": str }"""
    _ = current_user
    room_name = (payload.get("room_name") or "").strip()
    if not room_name:
        raise HTTPException(status_code=400, detail="room_name es obligatorio")

    try:
        arq_pool = await get_arq_pool()
        job = await arq_pool.enqueue_job("colgar_sala", room_name)
        logger.info(
            "📬 [hang_up] Colgar sala %s encolado (job=%s)",
            room_name,
            getattr(job, "job_id", "n/a"),
        )
    except Exception as q_err:
        logger.warning("⚠️ [hang_up] No se pudo encolar colgar sala %s: %s", room_name, q_err)
        if lkapi:
            try:
                await lkapi.room.delete_room(api.DeleteRoomRequest(room=room_name))
                logger.info("✅ [hang_up] Sala %s cerrada directamente via LiveKit API", room_name)
            except Exception as lk_err:
                raise HTTPException(status_code=502, detail=f"Error cerrando sala: {lk_err}") from lk_err

    return {"status": "ok", "room_name": room_name, "message": "Sala cerrada"}
