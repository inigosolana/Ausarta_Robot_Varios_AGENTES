"""Post-procesamiento al finalizar una llamada (transcripción, disposición, persistencia)."""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING, Any

from agents.agent_common import (
    _build_inbound_datos_extra,
    _extract_transcript_from_session,
    _is_inbound_agent_config,
)
from services.queue_service import enqueue_guardar_encuesta
from services.call_results_service import (
    extract_call_usage_metrics,
    prepare_transcription_for_storage,
    record_call_usage_billing,
)
from utils.call_analyzer import analyze_call_disposition

if TYPE_CHECKING:
    from agents.dynamic_agent import CallSession

logger = logging.getLogger("agent-dynamic")


async def _record_session_billing_usage(
    call_session: "CallSession",
    seconds_used: int,
    encuesta_id: int,
) -> None:
    """Extrae métricas LiveKit y las persiste vía billing_service."""
    empresa_id = int(call_session.agent_config.get("empresa_id") or 0)
    if empresa_id <= 0:
        return

    usage_collector = getattr(call_session, "usage_collector", None)
    if usage_collector is None:
        logger.debug("[%s] Sin usage_collector; billing omitido", call_session.job_id)
        return

    usage_summary = usage_collector.get_summary()
    metrics = extract_call_usage_metrics(
        usage_summary,
        agent_config=call_session.agent_config,
        telephony_seconds=seconds_used,
    )

    if (
        metrics.llm_total_tokens == 0
        and metrics.tts_characters == 0
        and metrics.telephony_seconds == 0
    ):
        return

    recorded = await record_call_usage_billing(
        empresa_id,
        metrics,
        encuesta_id=encuesta_id or None,
    )
    if recorded:
        logger.info(
            "[%s] Billing registrado empresa=%s encuesta=%s "
            "llm_tokens=%s tts_chars=%s telephony_s=%s model=%s",
            call_session.job_id,
            empresa_id,
            encuesta_id,
            metrics.llm_total_tokens,
            metrics.tts_characters,
            metrics.telephony_seconds,
            metrics.llm_model,
        )


async def finalize_call_session(call_session: "CallSession") -> None:
    """
    Post-procesamiento tras el fin de la llamada: extrae transcripción,
    clasifica disposición con LLM y encola la persistencia de resultados.
    """
    try:
        raw_messages: list[dict[str, Any]] = []
        transcript = ""
        try:
            raw_messages, transcript = _extract_transcript_from_session(call_session.session)
            logger.info(
                f"📝 [{call_session.job_id}] Transcripción extraída en finally: {len(transcript)} chars"
            )
            if not transcript:
                raw_messages, transcript = call_session._build_transcript_from_event_buffer()
                if transcript:
                    logger.info(
                        f"📝 [{call_session.job_id}] Usando buffer de eventos: {len(transcript)} chars"
                    )
            if not transcript and call_session.transcript_snapshot.get("transcript"):
                transcript = call_session.transcript_snapshot["transcript"]
                raw_messages = call_session.transcript_snapshot.get("raw", [])
                logger.info(
                    f"📝 [{call_session.job_id}] Usando snapshot de transcripción: {len(transcript)} chars"
                )
        except Exception as ex:
            logger.error(f"Error procesando historia para transcripción local: {ex}")
            if not transcript:
                raw_messages, transcript = call_session._build_transcript_from_event_buffer()
            if not transcript and call_session.transcript_snapshot.get("transcript"):
                transcript = call_session.transcript_snapshot["transcript"]
                raw_messages = call_session.transcript_snapshot.get("raw", [])

        seconds_used = 0
        if call_session.call_start_time is not None:
            seconds_used = max(0, int(time.time() - call_session.call_start_time))

        agent_type = call_session.agent_config.get("agent_type", "ENCUESTA_NUMERICA")
        data_saved = getattr(call_session.agent_instance, "data_saved", False)
        datos_extra: dict[str, Any] | None = None
        call_disposition: str | None = None

        if transcript:
            logger.info(
                f"🧠 Clasificando disposición de llamada y extrayendo datos "
                f"para encuesta {call_session.survey_id} (Tipo: {agent_type})"
            )
            call_direction = (
                "inbound"
                if _is_inbound_agent_config(call_session.agent_config)
                else "outbound"
            )
            call_disposition, datos_extra = await analyze_call_disposition(
                transcript,
                agent_type,
                data_saved,
                call_session.lang_state.get("active_lang", call_session.language),
                call_direction=call_direction,
            )
            if _is_inbound_agent_config(call_session.agent_config):
                datos_extra = _build_inbound_datos_extra(
                    call_session.agent_config,
                    call_session.room_name,
                    datos_extra,
                )
        else:
            if _is_inbound_agent_config(call_session.agent_config):
                call_disposition = "no_contesta"
            else:
                call_disposition = "no_contesta"
            datos_extra = {
                "sentimiento_cliente": "Neutral",
                "idioma": call_session.lang_state.get("active_lang", call_session.language),
            }
            logger.info(
                f"📵 Sin transcripción para encuesta {call_session.survey_id} → "
                f"disposición: {call_disposition}"
            )

        if not call_disposition:
            call_disposition = "completada" if data_saved else "parcial"

        inbound_fb_comentarios = None
        if _is_inbound_agent_config(call_session.agent_config):
            from utils.inbound_call import (
                build_inbound_fallback_comentarios,
                normalize_inbound_disposition,
            )

            call_disposition = normalize_inbound_disposition(
                call_disposition,
                transcript,
                data_saved,
                agent_type,
            )
            datos_extra = _build_inbound_datos_extra(
                call_session.agent_config,
                call_session.room_name,
                datos_extra,
            )
            inbound_fb_comentarios = build_inbound_fallback_comentarios

        enc_id = int(call_session.survey_id) if str(call_session.survey_id).isdigit() else 0
        storage_transcript = prepare_transcription_for_storage(transcript) if transcript else transcript

        if data_saved:
            logger.info(
                f"📝 Guardando transcripción/disposición/datos_extra para encuesta "
                f"{call_session.survey_id} (datos numéricos ya guardados por tool)"
            )
            try:
                _enc_job = await enqueue_guardar_encuesta({
                    "id_encuesta": enc_id,
                    "transcription": storage_transcript,
                    "datos_extra": datos_extra,
                    "seconds_used": seconds_used,
                })
                logger.info(f"📬 Extras post-llamada encolados (job={_enc_job})")
            except Exception as save_err:
                logger.error(f"Error encolando extras: {save_err}")
        else:
            logger.warning(
                f"⚠️ La sesión terminó sin guardar datos explícitos por tool "
                f"(Survey ID: {call_session.survey_id}) → Disposición: {call_disposition}"
            )
            try:
                if inbound_fb_comentarios is not None:
                    comentarios_fb = inbound_fb_comentarios(
                        call_disposition,
                        datos_extra,
                        agent_type,
                    )
                else:
                    comentarios_fb = (
                        "Llamada finalizada sin interacción"
                        if call_disposition == "no_contesta"
                        else f"Llamada {call_disposition} via post-call"
                    )
                _enc_job = await enqueue_guardar_encuesta({
                    "id_encuesta": enc_id,
                    "transcription": storage_transcript,
                    "status": call_disposition,
                    "comentarios": comentarios_fb,
                    "datos_extra": datos_extra,
                    "seconds_used": seconds_used,
                })
                logger.info(
                    f"📬 Fallback post-llamada encolado "
                    f"(disposición: {call_disposition}, job={_enc_job})"
                )
            except Exception as save_err:
                logger.error(f"Error encolando fallback: {save_err}")

        # Fase 2 — Actualizar ficha de contacto post-llamada (no bloqueante)
        try:
            from utils.call_analyzer import upsert_contacto_post_call

            _telefono = (
                (datos_extra or {}).get("telefono")
                or call_session.agent_config.get("contacto_phone")
                or ""
            )
            _nombre = getattr(call_session.agent_instance, "_detected_customer_name", "") or None
            _empresa_id_int = int(call_session.agent_config.get("empresa_id") or 0)
            if _telefono and _empresa_id_int:
                resumen = (datos_extra or {}).get("resumen_narrativo")
                asyncio.create_task(
                    upsert_contacto_post_call(
                        empresa_id=_empresa_id_int,
                        telefono=str(_telefono),
                        nombre_detectado=_nombre,
                        disposicion=call_disposition,
                        resumen=resumen,
                        datos_llamada={
                            "encuesta_id": enc_id,
                            "duracion_segundos": seconds_used,
                            "agent_name": call_session.agent_config.get("name"),
                            "fecha": datetime.now().isoformat(),
                            "notas_agente": datos_extra or {},
                        },
                    )
                )
        except Exception as contact_err:
            logger.warning(
                "[%s] Error actualizando ficha de contacto: %s",
                call_session.job_id,
                contact_err,
            )

        # Unit economics — registrar consumo LLM/TTS/telefonía (no bloqueante)
        try:
            await _record_session_billing_usage(call_session, seconds_used, enc_id)
        except Exception as billing_err:
            logger.warning(
                "[%s] Error registrando billing de llamada: %s",
                call_session.job_id,
                billing_err,
            )

    except Exception as fatal_post:
        logger.error(
            f"🚨 [{call_session.job_id}] EXCEPCIÓN FATAL NO CAPTURADA en finalize: {fatal_post}"
        )
