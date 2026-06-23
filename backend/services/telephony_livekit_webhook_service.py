"""Procesamiento de eventos webhook de LiveKit (room_finished, participant_left)."""

from __future__ import annotations

import asyncio
import json
import logging
import os

from livekit.api import WebhookReceiver

from services.supabase_service import supabase
from services.telephony_lead_propagation import propagate_to_lead
from services.telephony_room_utils import extract_encuesta_id_from_room

logger = logging.getLogger("api-backend")

TERMINAL_STATUSES = {"completed", "failed", "unreached", "incomplete", "rejected_opt_out"}

_LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
_LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")


def parse_livekit_webhook(body_bytes: bytes, auth_token: str):
    receiver = WebhookReceiver(_LIVEKIT_API_KEY, _LIVEKIT_API_SECRET)
    return receiver.receive(body_bytes.decode("utf-8"), auth_token)


async def safe_start_recording(room_name: str, encuesta_id: int) -> None:
    try:
        from services.recording_service import start_recording

        await start_recording(room_name, encuesta_id)
    except Exception as exc:
        logger.debug("[Recording] start_recording ignorado: %s", exc)


async def safe_stop_recording(encuesta_id: int) -> None:
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
            logger.info("🎵 [Recording] URL guardada para encuesta %s: %s", encuesta_id, recording_url)
    except Exception as exc:
        logger.debug("[Recording] stop_recording ignorado: %s", exc)


async def handle_room_finished(encuesta_id: int, room_name: str, room_metadata: dict | None = None) -> None:
    if not supabase:
        return

    asyncio.create_task(safe_stop_recording(encuesta_id))

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

        if current_status not in TERMINAL_STATUSES:
            logger.warning(
                "📵 [LK Webhook] Sala %s cerrada sin status terminal. Forzando 'failed'. metadata=%s",
                room_name,
                room_metadata or {},
            )
            await asyncio.to_thread(
                supabase.table("encuestas").update({"status": "failed"}).eq("id", encuesta_id).execute
            )
            await propagate_to_lead(encuesta_id, "failed", enc)
        else:
            logger.info(
                "[LK Webhook] Sala %s cerrada con status terminal: %s. Sin acción.",
                room_name,
                current_status,
            )

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
                    "📬 [LK Webhook] Tarea process_transcription_ai encolada para encuesta %s (job_id=%s).",
                    encuesta_id,
                    getattr(job, "job_id", "n/a"),
                )
            except Exception as exc:
                logger.warning(
                    "⚠️ [LK Webhook] No se pudo encolar transcripción para encuesta %s: %s",
                    encuesta_id,
                    exc,
                )
        else:
            logger.info(
                "[LK Webhook] Encuesta %s sin transcripción o empresa_id. Skipping análisis AI.",
                encuesta_id,
            )
    except Exception as exc:
        logger.error("❌ [LK Webhook] Error en room_finished para encuesta %s: %s", encuesta_id, exc)


async def handle_participant_left(
    encuesta_id: int,
    room_name: str,
    identity: str,
    room_metadata: dict | None = None,
) -> None:
    logger.info(
        "👤 [LK Webhook] Participante '%s' salió de sala %s (encuesta %s, metadata=%s). Esperando room_finished.",
        identity,
        room_name,
        encuesta_id,
        room_metadata or {},
    )


async def process_livekit_webhook_event(body_bytes: bytes, auth_token: str) -> dict:
    webhook_event = parse_livekit_webhook(body_bytes, auth_token)
    event = webhook_event.event
    room_name = webhook_event.room.name if webhook_event.HasField("room") else ""
    room_metadata_raw = webhook_event.room.metadata if webhook_event.HasField("room") else ""

    logger.info("🔔 [LK Webhook] Evento: %s | Sala: %s", event, room_name)

    if not room_name:
        return {"status": "ignored", "reason": "No room name"}

    room_metadata: dict = {}
    if isinstance(room_metadata_raw, str) and room_metadata_raw.strip():
        try:
            room_metadata = json.loads(room_metadata_raw)
        except Exception:
            logger.warning(
                "[LK Webhook] metadata no parseable en sala %s: %s",
                room_name,
                room_metadata_raw,
            )

    encuesta_id = extract_encuesta_id_from_room(room_name)
    if not encuesta_id:
        try:
            encuesta_id = int(room_metadata.get("survey_id") or 0)
        except Exception:
            encuesta_id = 0

    if not encuesta_id:
        logger.info("[LK Webhook] No se pudo extraer encuesta_id de sala %s ni metadata", room_name)
        return {"status": "ignored", "reason": "No encuesta_id in room name/metadata"}

    if event == "room_finished":
        await handle_room_finished(encuesta_id, room_name, room_metadata)
    elif event == "participant_left":
        participant_identity = (
            webhook_event.participant.identity if webhook_event.HasField("participant") else ""
        )
        if not participant_identity.startswith("agent-"):
            await handle_participant_left(encuesta_id, room_name, participant_identity, room_metadata)

    return {"status": "ok", "event": event}
