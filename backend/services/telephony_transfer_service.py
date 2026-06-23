"""Transferencia de llamadas a extensiones internas o números externos vía Yeastar."""

from __future__ import annotations

import logging
import os
import re

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from services.supabase_service import sb_query, supabase
from services.telephony_room_utils import parse_datos_extra
from services.telephony_yeastar_config_service import (
    load_yeastar_tenant_config,
    yeastar_client_from_config,
)

logger = logging.getLogger("api-backend")

_PHONE_DIGITS = re.compile(r"^\+?[0-9]{6,20}$")


def normalize_external_number(target: str) -> str | None:
    stripped = target.strip()
    has_plus = stripped.startswith("+")
    digits_only = re.sub(r"[^0-9]", "", stripped)
    normalized = ("+" if has_plus else "") + digits_only
    if _PHONE_DIGITS.match(normalized):
        return normalized
    return None


async def is_internal_extension(empresa_id: int, target: str) -> bool:
    target_clean = target.strip()
    digits_only = re.sub(r"[^0-9]", "", target_clean)
    if len(digits_only) > 5:
        return False

    if supabase:
        try:
            res = await sb_query(
                lambda eid=empresa_id, t=target_clean: supabase.table("yeastar_extensions")
                .select("id")
                .eq("empresa_id", eid)
                .eq("extension_number", t)
                .limit(1)
                .execute()
            )
            if res and res.data:
                return True
            count_res = await sb_query(
                lambda eid=empresa_id: supabase.table("yeastar_extensions")
                .select("id", count="exact")
                .eq("empresa_id", eid)
                .limit(1)
                .execute()
            )
            if count_res and (count_res.count or 0) > 0:
                return False
        except Exception as exc:
            logger.debug("[transfer] is_internal_extension lookup error: %s", exc)

    return not target_clean.startswith("+") and len(digits_only) <= 5


def resolve_target_extension(datos_extra: dict, explicit: str | None = None) -> str:
    ext = (
        (explicit or "").strip()
        or (os.getenv("YEASTAR_HUMAN_TRANSFER_EXTENSION") or "").strip()
        or str(datos_extra.get("target_extension") or "").strip()
        or str(datos_extra.get("human_transfer_extension") or "").strip()
    )
    if not ext:
        raise HTTPException(
            status_code=400,
            detail="Extensión/número de transferencia no configurado (YEASTAR_HUMAN_TRANSFER_EXTENSION).",
        )
    return ext


async def execute_yeastar_transfer(
    *,
    room_name: str,
    survey_id: int,
    motivo: str | None = None,
    call_id: str | None = None,
    target_extension: str | None = None,
    yeastar_call_id: str | None = None,
    outbound_prefix: str | None = None,
) -> dict:
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
        logger.error("[transfer] Encuesta %s sin empresa_id (room=%s)", survey_id, room_name)
        raise HTTPException(status_code=400, detail="Encuesta sin empresa asociada")

    emp = await load_yeastar_tenant_config(empresa_id)
    datos_extra = parse_datos_extra(enc.get("datos_extra"))

    resolved_call_id = (
        call_id
        or yeastar_call_id
        or datos_extra.get("yeastar_callid")
        or datos_extra.get("yeastar_call_id")
        or room_name
    )
    resolved_channel_id = str(datos_extra.get("yeastar_channel_id") or "").strip()
    if not resolved_channel_id:
        raise HTTPException(
            status_code=409,
            detail="Falta yeastar_channel_id del webhook 30011 para transferir la llamada.",
        )
    resolved_extension = resolve_target_extension(datos_extra, target_extension)

    is_internal = await is_internal_extension(empresa_id, resolved_extension)
    transfer_type = "internal" if is_internal else "external"
    logger.info(
        "[transfer] empresa=%s survey=%s destino='%s' tipo=%s",
        empresa_id,
        survey_id,
        resolved_extension,
        transfer_type,
    )

    if not is_internal:
        normalized = normalize_external_number(resolved_extension)
        if normalized is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Número externo '{resolved_extension}' inválido. "
                    "Usa formato nacional (ej. '612345678') o E.164 (ej. '+34612345678'). "
                    "Mínimo 6 dígitos."
                ),
            )
        resolved_extension = normalized

    effective_prefix = outbound_prefix if outbound_prefix is not None else ""
    if not is_internal and not effective_prefix:
        effective_prefix = str(emp.get("outbound_prefix") or "").strip()

    try:
        async with yeastar_client_from_config(emp) as client:
            if is_internal:
                ext_status = await client.get_extension_status(resolved_extension)
                if str(ext_status).strip().lower() not in {"idle", "available"}:
                    logger.info(
                        "[transfer] Extensión interna %s no disponible (status=%s) empresa=%s",
                        resolved_extension,
                        ext_status,
                        empresa_id,
                    )
                    return JSONResponse(
                        status_code=409,
                        content={
                            "message": f"Extensión ocupada ({ext_status})",
                            "status": ext_status,
                            "transfer_type": "internal",
                        },
                    )
            await client.transfer_call(
                resolved_channel_id,
                resolved_extension,
                outbound_prefix=effective_prefix,
            )
    except Exception as exc:
        logger.error(
            "[transfer] Fallo Yeastar empresa=%s survey=%s room=%s call_id=%s: %s",
            empresa_id,
            survey_id,
            room_name,
            resolved_call_id,
            exc,
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    motivo_text = (motivo or "Transferencia a agente humano").strip()
    merged_extra = {
        **datos_extra,
        "transfer_room": room_name,
        "transfer_extension": resolved_extension,
        "transfer_type": transfer_type,
        "yeastar_callid": str(resolved_call_id),
    }
    dest_label = f"ext {resolved_extension}" if is_internal else f"número externo {resolved_extension}"
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

    logger.info(
        "✅ [transfer] empresa=%s survey=%s call_id=%s → %s (%s) room=%s",
        empresa_id,
        survey_id,
        resolved_call_id,
        resolved_extension,
        transfer_type,
        room_name,
    )
    return {
        "status": "ok",
        "message": "Transferencia iniciada en la centralita",
        "empresa_id": empresa_id,
        "survey_id": survey_id,
        "room_name": room_name,
        "call_id": str(resolved_call_id),
        "target_extension": resolved_extension,
        "transfer_type": transfer_type,
    }
