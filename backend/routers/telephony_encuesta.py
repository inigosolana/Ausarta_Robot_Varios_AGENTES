"""Endpoints de persistencia de encuestas y registro inbound."""
from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import JSONResponse

from models.schemas import EncuestaData, InboundCallRegisterRequest
from services.supabase_service import supabase
from services.telephony_encuesta_service import guardar_encuesta
from utils.inbound_call import create_inbound_encuesta_record, find_recent_inbound_encuesta

router = APIRouter(tags=["telephony"])


@router.post("/inbound-call/register")
async def register_inbound_call(body: InboundCallRegisterRequest):
    """Registra la llamada entrante al conectar el agente (id numérico antes de colgar)."""
    if not supabase:
        return JSONResponse(status_code=503, content={"error": "No DB connection"})

    telefono = (body.telefono or "desconocido").strip() or "desconocido"
    room_name = (body.room_name or "").strip()

    existing = await find_recent_inbound_encuesta(body.empresa_id, room_name, telefono)
    if existing:
        return {"status": "ok", "encuesta_id": existing, "reused": True}

    encuesta_id = await create_inbound_encuesta_record(
        empresa_id=body.empresa_id,
        agent_id=body.agent_id,
        telefono=telefono,
        room_name=room_name,
        agent_type=body.agent_type,
        status="calling",
    )
    if not encuesta_id:
        return JSONResponse(status_code=500, content={"error": "No se pudo registrar la llamada"})
    return {"status": "ok", "encuesta_id": encuesta_id, "reused": False}


@router.post("/guardar-encuesta")
async def guardar_encuesta_endpoint(datos: EncuestaData, background_tasks: BackgroundTasks):
    return await guardar_encuesta(datos, background_tasks)
