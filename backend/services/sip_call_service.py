"""Reintentos SIP, marcado de fallos y alertas operativas."""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("api-backend")

DEFAULT_SIP_RETRY_MAX = 3
DEFAULT_SIP_RETRY_BASE_DELAY = 2.0


def sip_retry_max_attempts() -> int:
    try:
        return max(1, int(os.getenv("SIP_RETRY_MAX_ATTEMPTS", str(DEFAULT_SIP_RETRY_MAX))))
    except ValueError:
        return DEFAULT_SIP_RETRY_MAX


def sip_retry_base_delay() -> float:
    try:
        return max(0.5, float(os.getenv("SIP_RETRY_BASE_DELAY_SECONDS", str(DEFAULT_SIP_RETRY_BASE_DELAY))))
    except ValueError:
        return DEFAULT_SIP_RETRY_BASE_DELAY


async def create_sip_participant_with_retry(
    request: Any,
    *,
    max_attempts: int | None = None,
    base_delay: float | None = None,
) -> Any:
    """Invoca LiveKit create_sip_participant con reintentos y backoff exponencial."""
    from services.livekit_service import lkapi

    attempts = max_attempts or sip_retry_max_attempts()
    delay = base_delay if base_delay is not None else sip_retry_base_delay()
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            return await asyncio.wait_for(
                lkapi.sip.create_sip_participant(request),
                timeout=10,
            )
        except Exception as exc:
            last_error = exc
            logger.warning(
                "📞 [SIP] Intento %s/%s fallido: %s",
                attempt,
                attempts,
                exc,
            )
            if attempt < attempts:
                await asyncio.sleep(delay * (2 ** (attempt - 1)))

    assert last_error is not None
    raise last_error


async def _merge_encuesta_failure_extra(
    encuesta_id: int,
    failure: dict[str, Any],
) -> None:
    from services.supabase_service import sb_query, supabase

    if not supabase:
        return

    res = await sb_query(
        lambda: supabase.table("encuestas")
        .select("datos_extra")
        .eq("id", encuesta_id)
        .limit(1)
        .execute()
    )
    current = {}
    if res.data and isinstance(res.data[0].get("datos_extra"), dict):
        current = dict(res.data[0]["datos_extra"])

    sip_meta = current.get("sip_failures")
    if not isinstance(sip_meta, list):
        sip_meta = []
    sip_meta.append(failure)
    current["sip_failures"] = sip_meta[-10:]
    current["last_failure"] = failure

    await sb_query(
        lambda payload=current: supabase.table("encuestas")
        .update({"datos_extra": payload, "status": "failed"})
        .eq("id", encuesta_id)
        .execute()
    )


async def notify_call_failure(
    *,
    encuesta_id: int,
    reason: str,
    empresa_id: int | None = None,
    phone: str | None = None,
    error_code: str = "sip_error",
) -> None:
    if not (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip():
        return
    try:
        from services.queue_service import enqueue_telegram_alert

        empresa_part = f" empresa={empresa_id}" if empresa_id else ""
        phone_part = f" tel={phone}" if phone else ""
        message = (
            f"❌ [AUSARTA] Llamada fallida encuesta={encuesta_id}"
            f"{empresa_part}{phone_part} código={error_code}: {reason[:240]}"
        )
        await enqueue_telegram_alert(message)
    except Exception as exc:
        logger.warning("⚠️ [SIP] No se pudo encolar alerta Telegram: %s", exc)


async def mark_call_failed(
    encuesta_id: int,
    reason: str,
    *,
    error_code: str = "sip_error",
    source: str = "outbound",
    notify: bool = True,
    empresa_id: int | None = None,
    phone: str | None = None,
    room_name: str | None = None,
    sip_attempts: int | None = None,
) -> None:
    """
    Marca encuesta como failed, persiste motivo en datos_extra y propaga a campaign_leads.
    """
    if encuesta_id <= 0:
        return

    failure = {
        "reason": reason[:500],
        "error_code": error_code,
        "source": source,
        "room_name": room_name,
        "sip_attempts": sip_attempts,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        await _merge_encuesta_failure_extra(encuesta_id, failure)
    except Exception as exc:
        logger.error("❌ [SIP] Error persistiendo fallo encuesta %s: %s", encuesta_id, exc)

    enc_curr: dict[str, Any] = {"empresa_id": empresa_id, "telefono": phone}
    try:
        from services.supabase_service import sb_query, supabase

        if supabase:
            res = await sb_query(
                lambda: supabase.table("encuestas")
                .select("empresa_id, telefono, datos_extra")
                .eq("id", encuesta_id)
                .limit(1)
                .execute()
            )
            if res.data:
                enc_curr = res.data[0]
                empresa_id = empresa_id or enc_curr.get("empresa_id")
                phone = phone or enc_curr.get("telefono")
    except Exception:
        pass

    try:
        from routers.telephony import _propagate_to_lead

        await _propagate_to_lead(encuesta_id, "failed", enc_curr)
    except Exception as exc:
        logger.warning("⚠️ [SIP] propagate lead falló encuesta %s: %s", encuesta_id, exc)

    if notify:
        await notify_call_failure(
            encuesta_id=encuesta_id,
            reason=reason,
            empresa_id=int(empresa_id) if empresa_id else None,
            phone=str(phone) if phone else None,
            error_code=error_code,
        )

    logger.info(
        "📵 [SIP] Encuesta %s marcada failed (%s): %s",
        encuesta_id,
        error_code,
        reason[:120],
    )
