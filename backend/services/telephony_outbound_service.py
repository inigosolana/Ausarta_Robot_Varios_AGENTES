"""Lógica de llamadas salientes LiveKit SIP."""
from __future__ import annotations

import asyncio
import logging
import os
import random
from datetime import datetime, timezone

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from livekit import api

from middleware.tenant_context import assert_tenant_within_spending_limit
from models.schemas import TestOutboundCallRequest
from services.agent_router import build_outbound_room_metadata, resolve_outbound_agent
from services.livekit_service import (
    create_isolated_room,
    create_outbound_call,
    dispatch_agent_explicit,
    wait_for_agent_ready,
)
from services.sip_call_service import (
    SipOutboundRejected,
    create_sip_participant_with_retry,
    mark_call_failed,
    sip_retry_max_attempts,
)
from services.supabase_service import sb_query, supabase
from services.telephony_livekit_webhook_service import safe_start_recording
from services.tenant_context import get_current_empresa_id
from services.trunk_service import resolve_outbound_trunk_id

logger = logging.getLogger("api-backend")

_processing_rooms_fallback: set[str] = set()


def normalize_test_outbound_phone(raw: str) -> str:
    """Convierte números españoles sin prefijo a E.164 (+34…)."""
    s = (raw or "").strip()
    if not s:
        return ""
    if s.startswith("+"):
        return s
    digits = "".join(c for c in s if c.isdigit())
    if len(digits) == 9 and digits[0] in "6789":
        return f"+34{digits}"
    if len(digits) == 11 and digits.startswith("34"):
        return f"+{digits}"
    return s


async def resolve_test_outbound_context(payload: TestOutboundCallRequest) -> tuple[str, str, int]:
    """Resuelve empresa + encuesta + campaign_id para test-outbound."""
    if not supabase:
        raise HTTPException(status_code=503, detail="Supabase no disponible")

    from_name = (payload.from_empresa_nombre or "").strip()
    empresa_hint = (payload.empresa_id or "").strip()

    empresa_id_int: int | None = None
    if empresa_hint.isdigit():
        empresa_id_int = int(empresa_hint)

    if from_name:
        emp_res = await sb_query(lambda: supabase.table("empresas").select("id,nombre").execute())
        want = from_name.casefold()
        candidates = emp_res.data or []
        exact = next(
            (r for r in candidates if str(r.get("nombre") or "").strip().casefold() == want),
            None,
        )
        partial = next(
            (r for r in candidates if want in str(r.get("nombre") or "").strip().casefold()),
            None,
        )
        picked = exact or partial
        if not picked:
            raise HTTPException(status_code=404, detail=f"Empresa no encontrada por nombre: {from_name}")
        resolved = int(picked["id"])
        if empresa_id_int is not None and empresa_id_int != resolved:
            logger.warning(
                "[test-outbound] empresa_id (%s) no coincide con from_empresa_nombre='%s' (id=%s); "
                "se usa la empresa resuelta por nombre.",
                empresa_id_int,
                from_name,
                resolved,
            )
        empresa_id_int = resolved

    if empresa_id_int is None:
        raise HTTPException(status_code=400, detail="empresa_id o from_empresa_nombre es obligatorio")

    survey_hint = (payload.survey_id or "").strip()
    survey_id_int: int | None = None
    campaign_id_int = 0

    if survey_hint.isdigit() and int(survey_hint) > 0:
        survey_id_int = int(survey_hint)
        chk = await sb_query(
            lambda sid=survey_id_int: supabase.table("encuestas")
            .select("id, empresa_id, campaign_id, agent_id")
            .eq("id", sid)
            .limit(1)
            .execute()
        )
        row = chk.data[0] if chk.data else None
        if not row:
            raise HTTPException(status_code=404, detail=f"Encuesta id={survey_id_int} no encontrada")
        if row.get("empresa_id") != empresa_id_int:
            raise HTTPException(status_code=400, detail="survey_id no pertenece a la empresa indicada")
        if row.get("agent_id") is None:
            raise HTTPException(
                status_code=400,
                detail="Esa encuesta no tiene agent_id; elige otra o deja survey_id vacío para autoselección",
            )
        campaign_id_int = int(row["campaign_id"] or 0)
    else:
        enc_res = await sb_query(
            lambda eid=empresa_id_int: supabase.table("encuestas")
            .select("id,campaign_id")
            .eq("empresa_id", eid)
            .not_.is_("agent_id", "null")
            .order("id", desc=True)
            .limit(1)
            .execute()
        )
        rows = enc_res.data or []
        if not rows:
            raise HTTPException(
                status_code=400,
                detail="No hay encuestas con agente asignado para esa empresa — indica survey_id explícito",
            )
        survey_id_int = int(rows[0]["id"])
        campaign_id_int = int(rows[0].get("campaign_id") or 0)

    empresa_str = str(empresa_id_int)
    survey_str = str(survey_id_int)
    logger.info(
        "[test-outbound] Contexto resuelto: empresa_id=%s encuesta_id=%s campaign_id=%s",
        empresa_str,
        survey_str,
        campaign_id_int,
    )
    return empresa_str, survey_str, campaign_id_int


async def acquire_room_lock(room_name: str) -> str | None:
    try:
        from services.redis_service import acquire_lock

        return await acquire_lock(f"room:{room_name}", ttl_seconds=30)
    except Exception:
        if room_name in _processing_rooms_fallback:
            return None
        _processing_rooms_fallback.add(room_name)
        return f"local-fallback:{room_name}"


async def release_room_lock(room_name: str, token: str | None = None) -> None:
    try:
        from services.redis_service import release_lock

        if token and not str(token).startswith("local-fallback:"):
            await release_lock(f"room:{room_name}", token)
        elif token is None:
            await release_lock(f"room:{room_name}")
    except Exception:
        pass
    _processing_rooms_fallback.discard(room_name)


async def check_and_increment_call_limit(empresa_id: int) -> None:
    if not supabase:
        return

    try:
        emp_res = await sb_query(
            lambda: supabase.table("empresas")
            .select("plan, max_llamadas_mes, llamadas_consumidas_mes, nombre")
            .eq("id", empresa_id)
            .limit(1)
            .execute()
        )
        if not emp_res.data:
            return

        emp = emp_res.data[0]
        max_calls = int(emp.get("max_llamadas_mes") or 100)
        used_calls = int(emp.get("llamadas_consumidas_mes") or 0)

        if used_calls >= max_calls:
            plan = emp.get("plan", "basico")
            raise HTTPException(
                status_code=403,
                detail=(
                    f"Límite de llamadas mensual alcanzado para tu plan ({plan}). "
                    f"Consumidas: {used_calls}/{max_calls}. "
                    "Contacta con Ausarta para ampliar tu plan."
                ),
            )

        await sb_query(
            lambda: supabase.rpc(
                "increment_llamadas_consumidas",
                {"p_empresa_id": empresa_id},
            ).execute()
        )

        try:
            from services.redis_service import get_redis
            from services.tenant_quota_alerts import maybe_alert_call_quota_threshold

            redis = await get_redis()
            await maybe_alert_call_quota_threshold(
                empresa_id,
                consumed=used_calls + 1,
                max_calls=max_calls,
                empresa_nombre=emp.get("nombre"),
                redis=redis,
            )
        except Exception as alert_exc:
            logger.debug("[limits] Alerta cuota llamadas omitida: %s", alert_exc)

    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("[limits] No se pudo verificar límite de empresa %s: %s", empresa_id, exc)


async def enforce_call_placement_limits(empresa_id: int) -> None:
    await check_and_increment_call_limit(empresa_id)
    await assert_tenant_within_spending_limit(empresa_id)


async def test_outbound_call(payload: TestOutboundCallRequest) -> dict:
    empresa_id, survey_id, campaign_id = await resolve_test_outbound_context(payload)

    trunk_id = await resolve_outbound_trunk_id(int(empresa_id) if str(empresa_id).isdigit() else None)
    if not trunk_id:
        raise HTTPException(
            status_code=500,
            detail="SIP_OUTBOUND_TRUNK_ID no está configurado. Define el trunk de salida en .env.",
        )

    phone = normalize_test_outbound_phone(payload.phone_number)
    if not phone:
        raise HTTPException(status_code=400, detail="phone_number es obligatorio")

    if empresa_id:
        await enforce_call_placement_limits(int(empresa_id))

    room_name = f"llamada_ausarta_{empresa_id}_{survey_id}"
    test_contact_id = 0
    room_metadata = {
        "empresa_id": int(empresa_id),
        "survey_id": int(survey_id),
        "campaign_id": int(campaign_id),
        "campana_id": int(campaign_id),
        "contacto_id": test_contact_id,
        "client_id": test_contact_id,
        "lead_id": test_contact_id,
    }

    try:
        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as room_err:
            logger.warning("⚠️ [test-outbound] Aviso al crear sala %s: %s", room_name, room_err)

        agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            agent_ready = await wait_for_agent_ready(room_name)
            if not agent_ready:
                raise HTTPException(
                    status_code=503,
                    detail=(
                        "Agente no disponible (timeout de arranque). Revisa logs del worker LiveKit "
                        f"({agent_name_dispatch}) y que ROOM_PREFIX coincida."
                    ),
                )
        except HTTPException:
            raise
        except Exception as dispatch_err:
            logger.warning("⚠️ [test-outbound] Dispatch fallido: %s", dispatch_err)

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
            "empresa_id": int(empresa_id),
            "survey_id": int(survey_id),
            "campaign_id": int(campaign_id),
            "participant_id": participant_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("❌ [test-outbound] Error: %s", exc)
        raise HTTPException(status_code=500, detail="Error en llamada de prueba") from exc


async def make_outbound_call(request: dict, auth: str):
    phone = request.get("phoneNumber")
    agent_id = request.get("agentId", "1")
    lead_id = request.get("leadId")
    campaign_id = request.get("campaignId")

    if not phone:
        return JSONResponse(status_code=400, content={"error": "Phone number is required"})

    encuesta_id = None
    resolved_agent_type = "ENCUESTA_NUMERICA"

    try:
        if supabase:
            emp_id = request.get("empresa_id")
            api_tenant = get_current_empresa_id()
            if auth == "api-key" and api_tenant:
                if emp_id and int(emp_id) != int(api_tenant):
                    return JSONResponse(
                        status_code=403,
                        content={"error": "API key no autorizada para esta empresa"},
                    )
                emp_id = api_tenant

            if not emp_id and agent_id:
                try:
                    agent_res = await sb_query(
                        lambda: supabase.table("agent_config")
                        .select("empresa_id")
                        .eq("id", agent_id)
                        .execute()
                    )
                    if agent_res.data:
                        emp_id = agent_res.data[0].get("empresa_id")
                except Exception as exc:
                    logger.warning("⚠️ [telephony] No se pudo resolver empresa desde agente %s: %s", agent_id, exc)

            if emp_id:
                await enforce_call_placement_limits(int(emp_id))

            resolved = await resolve_outbound_agent(
                empresa_id=int(emp_id) if emp_id else None,
                agent_id=agent_id,
                agent_type=request.get("agentType"),
                call_purpose=request.get("callPurpose"),
            )
            agent_id = resolved["agent_id"]
            resolved_agent_type = resolved["agent_type"]
            logger.info(
                "🤖 [outbound] Agente resuelto id=%s tipo=%s empresa=%s",
                agent_id,
                resolved_agent_type,
                emp_id,
            )

            campaign_name = request.get("campaignName")
            if campaign_id and not campaign_name:
                try:
                    camp_res = await sb_query(
                        lambda: supabase.table("campaigns").select("name").eq("id", campaign_id).execute()
                    )
                    if camp_res.data:
                        campaign_name = camp_res.data[0].get("name")
                except Exception as exc:
                    logger.warning("⚠️ [telephony] No se pudo resolver nombre de campaña %s: %s", campaign_id, exc)

            res_enc = await sb_query(
                lambda: supabase.table("encuestas")
                .insert({
                    "telefono": phone,
                    "nombre_cliente": request.get("customerName", "Prueba Dashboard"),
                    "fecha": datetime.now(timezone.utc).isoformat(),
                    "status": "initiated",
                    "completada": 0,
                    "agent_id": agent_id,
                    "agent_type": resolved_agent_type,
                    "empresa_id": emp_id,
                    "campaign_id": campaign_id,
                    "campaign_name": campaign_name,
                })
                .execute()
            )
            encuesta_id = res_enc.data[0]["id"]

            if lead_id:
                await sb_query(
                    lambda: supabase.table("campaign_leads")
                    .update({
                        "call_id": encuesta_id,
                        "status": "calling",
                        "last_call_at": datetime.now(timezone.utc).isoformat(),
                    })
                    .eq("id", lead_id)
                    .execute()
                )
        else:
            encuesta_id = random.randint(1000, 9999)

        agent_name_dispatch = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip()
        contacto_id = int(lead_id) if lead_id else 0
        camp_id_str = str(campaign_id) if campaign_id else "0"
        room_name = (
            f"llamada_ausarta_empresa_{emp_id or 0}_campana_{camp_id_str}"
            f"_contacto_{contacto_id}_encuesta_{encuesta_id}"
        )
        sip_trunk_id = await resolve_outbound_trunk_id(int(emp_id) if str(emp_id).isdigit() else None)

        room_lock_token = await acquire_room_lock(room_name)
        if not room_lock_token:
            logger.warning("⚠️ Despacho ya en curso para %s. Ignorando.", room_name)
            return {"status": "ok", "message": "Call already initiated", "roomName": room_name}

        room_metadata = build_outbound_room_metadata(
            empresa_id=int(emp_id or 0),
            survey_id=int(encuesta_id),
            agent_id=int(agent_id),
            agent_type=resolved_agent_type,
            campaign_id=int(campaign_id or 0),
            contacto_id=contacto_id,
        )

        try:
            await create_isolated_room(room_name, metadata=room_metadata)
        except Exception as exc:
            logger.warning("⚠️ Aviso al crear sala %s: %s", room_name, exc)

        try:
            await dispatch_agent_explicit(
                room_name=room_name,
                agent_name=agent_name_dispatch,
                metadata=room_metadata,
            )
            logger.info(
                "✅ Agente %s (tipo=%s) despachado a sala %s",
                agent_name_dispatch,
                resolved_agent_type,
                room_name,
            )
            agent_ready = await wait_for_agent_ready(room_name)
            if not agent_ready:
                logger.error(
                    "⚠️ [outbound] Agente no listo en sala %s tras timeout. Marcando encuesta como failed.",
                    room_name,
                )
                if supabase and encuesta_id:
                    await mark_call_failed(
                        int(encuesta_id),
                        "Agente no disponible antes del SIP",
                        error_code="agent_not_ready",
                        source="outbound",
                        empresa_id=int(emp_id) if emp_id else None,
                        phone=str(phone),
                        room_name=room_name,
                    )
                await release_room_lock(room_name, room_lock_token)
                return JSONResponse(
                    status_code=503,
                    content={"error": "Agente no disponible — llamada abortada para evitar audio mudo"},
                )
        except Exception as dispatch_err:
            logger.warning("⚠️ Dispatch explícito fallido (auto-dispatch como fallback): %s", dispatch_err)

        try:
            await create_sip_participant_with_retry(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=sip_trunk_id,
                    sip_call_to=phone,
                    room_name=room_name,
                    participant_identity=f"user_{phone}_{encuesta_id}",
                    participant_name="Cliente",
                ),
                empresa_id=int(emp_id) if emp_id else None,
                phone=str(phone),
                source="telephony_outbound",
            )
        except SipOutboundRejected as guard_err:
            await release_room_lock(room_name, room_lock_token)
            if supabase and encuesta_id:
                await mark_call_failed(
                    int(encuesta_id),
                    guard_err.message,
                    error_code=guard_err.code,
                    source="outbound",
                    empresa_id=int(emp_id) if emp_id else None,
                    phone=str(phone),
                    room_name=room_name,
                )
            status = 429 if guard_err.code.endswith("rate_limit") else 400
            return JSONResponse(status_code=status, content={"error": guard_err.message})
        except Exception as sip_err:
            await release_room_lock(room_name, room_lock_token)
            if supabase and encuesta_id:
                await mark_call_failed(
                    int(encuesta_id),
                    str(sip_err),
                    error_code="sip_dispatch_failed",
                    source="outbound",
                    empresa_id=int(emp_id) if emp_id else None,
                    phone=str(phone),
                    room_name=room_name,
                    sip_attempts=sip_retry_max_attempts(),
                )
            return JSONResponse(
                status_code=502,
                content={"error": f"Error SIP tras reintentos: {sip_err}"},
            )

        async def clear_lock(rname: str, token: str | None) -> None:
            await asyncio.sleep(10)
            await release_room_lock(rname, token)

        asyncio.create_task(clear_lock(room_name, room_lock_token))
        asyncio.create_task(safe_start_recording(room_name, encuesta_id))

        return {"status": "ok", "roomName": room_name, "callId": encuesta_id}

    except Exception as exc:
        if "room_name" in locals() and locals().get("room_lock_token"):
            await release_room_lock(room_name, room_lock_token)
        if supabase and encuesta_id:
            try:
                await mark_call_failed(
                    int(encuesta_id),
                    str(exc),
                    error_code="outbound_fatal",
                    source="outbound",
                    empresa_id=int(emp_id) if "emp_id" in locals() and emp_id else None,
                    phone=str(phone) if phone else None,
                    room_name=room_name if "room_name" in locals() else None,
                )
            except Exception:
                pass
        logger.error("❌ Error fatal en outbound call: %s", exc)
        return JSONResponse(status_code=500, content={"error": str(exc)})
