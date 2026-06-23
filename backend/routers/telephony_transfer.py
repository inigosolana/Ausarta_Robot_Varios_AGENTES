"""Endpoints de transferencia de llamadas a agentes humanos."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse

from models.schemas import CallTransferRequest, TelephonyTransferRequest
from services.auth import CurrentUser, get_current_user
from services.platform_access import has_global_access
from services.supabase_service import sb_query, supabase
from services.telephony_room_utils import extract_encuesta_id_from_room, parse_datos_extra
from services.telephony_transfer_service import (
    execute_yeastar_transfer,
    is_internal_extension,
    normalize_external_number,
)
from services.telephony_yeastar_config_service import (
    load_yeastar_tenant_config,
    yeastar_client_from_config,
)

logger = logging.getLogger("api-backend")

router = APIRouter(tags=["telephony"])


@router.post("/api/calls/transfer")
async def transfer_call_to_human(payload: CallTransferRequest):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    room_name = payload.room_name.strip()
    if not room_name:
        raise HTTPException(status_code=400, detail="room_name es obligatorio")
    if not payload.empresa_id:
        raise HTTPException(status_code=400, detail="empresa_id es obligatorio")

    call_id = (payload.call_id or "").strip()
    survey_id = payload.survey_id or extract_encuesta_id_from_room(room_name)
    datos_extra: dict = {}
    if survey_id:
        enc_res = await sb_query(
            lambda sid=survey_id: supabase.table("encuestas")
            .select("datos_extra")
            .eq("id", sid)
            .limit(1)
            .execute()
        )
        datos_extra = parse_datos_extra(enc_res.data[0].get("datos_extra") if enc_res.data else {})
        call_id = str(
            datos_extra.get("yeastar_callid") or datos_extra.get("yeastar_call_id") or call_id
        ).strip()

    channel_id = str(datos_extra.get("yeastar_channel_id") or "").strip()
    if not call_id:
        raise HTTPException(status_code=400, detail="call_id es obligatorio")
    if call_id == room_name:
        raise HTTPException(
            status_code=409,
            detail=(
                "La llamada no tiene call_id de Yeastar. La llamada debe haber pasado "
                "por Yeastar y haberse recibido el webhook 30011 para poder transferir."
            ),
        )
    if not channel_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "La llamada no tiene channel_id de Yeastar. Comprueba que el webhook "
                "30011 Call State Changed está activo antes de intentar transferir."
            ),
        )

    target = (payload.extension or "1000").strip()
    empresa_id = int(payload.empresa_id)
    outbound_prefix = payload.outbound_prefix

    is_internal = await is_internal_extension(empresa_id, target)
    transfer_type = "internal" if is_internal else "external"

    if not is_internal:
        normalized = normalize_external_number(target)
        if normalized is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Número externo '{target}' inválido. "
                    "Usa formato nacional (ej. '612345678') o E.164 (ej. '+34612345678'). "
                    "Mínimo 6 dígitos."
                ),
            )
        target = normalized

    logger.info(
        "[transfer] empresa=%s room=%s destino='%s' tipo=%s",
        empresa_id,
        room_name,
        target,
        transfer_type,
    )

    config = await load_yeastar_tenant_config(empresa_id)
    effective_prefix = outbound_prefix if outbound_prefix is not None else ""
    if not is_internal and not effective_prefix:
        effective_prefix = str(config.get("outbound_prefix") or "").strip()

    ext_status: str = "N/A"
    try:
        async with yeastar_client_from_config(config) as yeastar_client:
            if is_internal:
                ext_status = await yeastar_client.get_extension_status(target)
                if str(ext_status).strip().lower() not in {"idle", "available"}:
                    return JSONResponse(
                        status_code=409,
                        content={
                            "message": f"Extensión ocupada ({ext_status})",
                            "status": ext_status,
                            "transfer_type": "internal",
                        },
                    )
            await yeastar_client.transfer_call(channel_id, target, outbound_prefix=effective_prefix)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[transfer] Error Yeastar empresa=%s call_id=%s destino=%s (%s): %s",
            empresa_id,
            call_id,
            target,
            transfer_type,
            exc,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if survey_id:
        motivo_text = (payload.motivo or "Transferencia a agente humano").strip()
        dest_label = f"ext {target}" if is_internal else f"número externo {target}"
        try:
            merged_extra = {
                **datos_extra,
                "transfer_room": room_name,
                "transfer_extension": target,
                "transfer_type": transfer_type,
                "yeastar_callid": call_id,
            }
            await sb_query(
                lambda sid=survey_id, extra=merged_extra, m=motivo_text, dl=dest_label: supabase.table("encuestas")
                .update({
                    "status": "transferred",
                    "comentarios": f"Transferido a {dl}: {m}",
                    "datos_extra": extra,
                })
                .eq("id", sid)
                .execute()
            )
        except Exception as db_err:
            logger.warning("[transfer] No se pudo actualizar encuesta %s: %s", survey_id, db_err)

    return {
        "status": "ok",
        "message": "Transferencia iniciada en la centralita",
        "empresa_id": empresa_id,
        "room_name": room_name,
        "call_id": call_id,
        "target_extension": target,
        "transfer_type": transfer_type,
        "extension_status": ext_status if is_internal else "skipped_external",
    }


@router.get("/api/calls/{encuesta_id}/briefing")
async def get_call_transfer_briefing(
    encuesta_id: int,
    current_user: CurrentUser = Depends(get_current_user),
):
    if not supabase:
        raise HTTPException(status_code=503, detail="Sin conexión con la base de datos")

    res = await sb_query(
        lambda sid=encuesta_id: supabase.table("encuestas")
        .select("id, empresa_id, transfer_briefing, datos_extra")
        .eq("id", sid)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status_code=404, detail="Encuesta no encontrada")

    row = res.data[0]
    empresa_id = int(row.get("empresa_id") or 0)
    if not has_global_access(current_user) and int(current_user.empresa_id or 0) != empresa_id:
        raise HTTPException(status_code=403, detail="Acceso denegado")

    datos_extra = parse_datos_extra(row.get("datos_extra") or {})
    briefing = row.get("transfer_briefing") or datos_extra.get("transfer_briefing") or ""
    return {"encuesta_id": encuesta_id, "transfer_briefing": briefing}


@router.post("/api/telephony/transfer")
async def transfer_call_to_human_legacy(payload: TelephonyTransferRequest):
    return await execute_yeastar_transfer(
        room_name=payload.room_name.strip(),
        survey_id=payload.survey_id,
        motivo=payload.motivo,
        call_id=None,
        target_extension=payload.target_extension,
        yeastar_call_id=payload.yeastar_call_id,
        outbound_prefix=payload.outbound_prefix,
    )
