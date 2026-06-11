"""
transcription_processor.py — Análisis de transcripciones con LLM.

Extraído de worker.py para mantener WorkerSettings limpio.
Incluye también los helpers de programación de reintentos de encuesta fallida.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from utils.call_schedule import is_call_allowed

logger = logging.getLogger("arq-worker")


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de retry
# ──────────────────────────────────────────────────────────────────────────────

def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _next_retry_base(attempt: int, reference: datetime) -> datetime:
    if attempt == 1:
        return reference + timedelta(hours=2)
    if attempt == 2:
        return reference + timedelta(hours=24)
    return reference + timedelta(hours=48)


def _align_retry_to_allowed_slot(
    target: datetime,
    timezone_str: str,
    allowed_hours: tuple[int, int],
    forbidden_weekdays: set[int],
) -> datetime:
    candidate = target
    for _ in range(24 * 14):
        allowed, _ = is_call_allowed(
            now=candidate,
            timezone_str=timezone_str,
            allowed_hours=allowed_hours,
            forbidden_weekdays=forbidden_weekdays,
        )
        if allowed:
            return candidate
        candidate += timedelta(hours=1)
        candidate = candidate.replace(minute=0, second=0, microsecond=0)
    return candidate


async def _schedule_failed_survey_retry(encuesta_row: dict[str, Any]) -> datetime | None:
    """Programa el siguiente reintento de una encuesta fallida respetando el horario de campaña."""
    from services.supabase_service import supabase, sb_query

    if not supabase:
        return None

    encuesta_id = int(encuesta_row.get("id") or 0)
    retry_count = int(encuesta_row.get("retry_count") or 0)
    if not encuesta_id or retry_count >= 3:
        return None

    reference = _parse_iso_datetime(encuesta_row.get("scheduled_at")) or datetime.now(timezone.utc)
    next_retry = _next_retry_base(retry_count + 1, reference)

    timezone_str = "Europe/Madrid"
    allowed_hours = (9, 21)
    forbidden_weekdays: set[int] = {6}

    campaign_id = encuesta_row.get("campaign_id")
    if campaign_id:
        try:
            campaign_res = await sb_query(
                lambda: supabase.table("campaigns")
                .select("call_start_hour, call_end_hour, call_timezone, forbidden_weekdays")
                .eq("id", campaign_id)
                .limit(1)
                .execute()
            )
            if campaign_res.data:
                campaign = campaign_res.data[0]
                timezone_str = campaign.get("call_timezone") or timezone_str
                allowed_hours = (
                    int(campaign.get("call_start_hour") or allowed_hours[0]),
                    int(campaign.get("call_end_hour") or allowed_hours[1]),
                )
                forbidden_weekdays = set(campaign.get("forbidden_weekdays") or list(forbidden_weekdays))
        except Exception as exc:
            logger.warning("⚠️ [worker] No se pudo cargar horario de campaña para retry: %s", exc)

    retry_at = _align_retry_to_allowed_slot(
        target=next_retry,
        timezone_str=timezone_str,
        allowed_hours=allowed_hours,
        forbidden_weekdays=forbidden_weekdays,
    )

    await sb_query(
        lambda: supabase.table("encuestas")
        .update({
            "status": "pending_retry",
            "retry_count": retry_count + 1,
            "scheduled_at": retry_at.isoformat(),
        })
        .eq("id", encuesta_id)
        .execute()
    )
    try:
        await sb_query(
            lambda: supabase.table("campaign_leads")
            .update({
                "status": "pending_retry",
                "next_retry_at": retry_at.isoformat(),
            })
            .eq("call_id", encuesta_id)
            .execute()
        )
    except Exception as exc:
        logger.warning("⚠️ [worker] No se pudo sincronizar pending_retry en campaign_leads: %s", exc)

    logger.info("✅ [worker] Retry programado encuesta=%s retry_count=%s", encuesta_id, retry_count + 1)
    return retry_at


# ──────────────────────────────────────────────────────────────────────────────
# Tarea ARQ
# ──────────────────────────────────────────────────────────────────────────────

async def process_transcription_ai(
    ctx: dict[str, Any],
    encuesta_id: int,
    transcription: str,
    empresa_id: int,
) -> None:
    """
    Tarea ARQ: analiza la transcripción de una llamada con un LLM y persiste
    los resultados estructurados (notas + comentario) en la tabla encuestas.

    Registrada con max_tries=3 en WorkerSettings para tolerar errores
    transitorios de la API de OpenAI (rate limits, timeouts de red).

    Flujo:
        1. Obtener prompt de sistema de la empresa (agent_config → system_prompt).
        2. Llamar a OpenAI con la transcripción.
        3. Parsear JSON de respuesta.
        4. UPDATE en encuestas con las notas y comentarios extraídos.
    """
    import openai
    from services.supabase_service import supabase, sb_query

    logger.info(
        "🤖 [TranscriptionAI] Iniciando análisis encuesta=%s empresa=%s chars=%s",
        encuesta_id, empresa_id, len(transcription),
    )

    if not supabase:
        logger.error("[TranscriptionAI] Supabase no disponible. Abortando.")
        return

    if not transcription or not transcription.strip():
        logger.warning("[TranscriptionAI] Transcripción vacía para encuesta %s. Skipping.", encuesta_id)
        return

    # ── Paso 1: Obtener el prompt de sistema de la empresa ──────────────────
    system_prompt_extra = ""
    try:
        agent_res = await sb_query(
            lambda: supabase.table("agent_config")
            .select("system_prompt")
            .eq("empresa_id", empresa_id)
            .limit(1)
            .execute()
        )
        if agent_res.data:
            system_prompt_extra = agent_res.data[0].get("system_prompt") or ""
    except Exception as e:
        logger.warning("[TranscriptionAI] No se pudo leer agent_config empresa %s: %s", empresa_id, e)

    analysis_system_prompt = (
        "Eres un analizador experto de llamadas comerciales en español. "
        "Recibirás la transcripción completa de una llamada entre un agente IA y un cliente. "
        "Tu tarea es extraer las valoraciones y el comentario clave.\n\n"
        "RESPONDE ÚNICAMENTE con un JSON válido (sin markdown, sin explicaciones) con esta estructura exacta:\n"
        "{\n"
        '  "nota_comercial": <número 1-10 o null>,\n'
        '  "nota_instalador": <número 1-10 o null>,\n'
        '  "nota_rapidez": <número 1-10 o null>,\n'
        '  "comentario_resumen": "<resumen en 1-3 frases del feedback del cliente>"\n'
        "}\n\n"
        "Si una nota no fue mencionada en la llamada, devuelve null para ese campo.\n"
        f"{('Contexto adicional del agente: ' + system_prompt_extra) if system_prompt_extra else ''}"
    )

    # ── Paso 2: Llamar al LLM ───────────────────────────────────────────────
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.error("[TranscriptionAI] OPENAI_API_KEY no configurada. Abortando.")
        return

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    try:
        logger.info("[TranscriptionAI] Enviando transcripción a OpenAI para encuesta %s…", encuesta_id)
        response = await client.chat.completions.create(
            model=os.getenv("TRANSCRIPTION_LLM_MODEL", "gpt-4o-mini"),
            messages=[
                {"role": "system", "content": analysis_system_prompt},
                {"role": "user", "content": f"TRANSCRIPCIÓN:\n{transcription}"},
            ],
            temperature=0.1,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
        raw_json = response.choices[0].message.content or "{}"
        logger.info("[TranscriptionAI] Respuesta LLM encuesta %s: %s", encuesta_id, raw_json[:200])
    except openai.RateLimitError as e:
        logger.warning("[TranscriptionAI] Rate limit OpenAI encuesta %s: %s", encuesta_id, e)
        raise  # ARQ reintentará (max_tries=3)
    except Exception as e:
        logger.error("[TranscriptionAI] Error llamando a OpenAI para encuesta %s: %s", encuesta_id, e)
        raise

    # ── Paso 3: Parsear JSON de respuesta ───────────────────────────────────
    try:
        extracted = json.loads(raw_json)
    except json.JSONDecodeError as e:
        logger.error("[TranscriptionAI] JSON inválido del LLM encuesta %s: %s | raw=%s", encuesta_id, e, raw_json)
        return  # No reintentamos un JSON malformado

    # ── Paso 4: Persistir resultados en Supabase ────────────────────────────
    update_payload: dict[str, Any] = {"ai_analysis_done": True}

    nota_comercial = extracted.get("nota_comercial")
    nota_instalador = extracted.get("nota_instalador")
    nota_rapidez = extracted.get("nota_rapidez")
    comentario = extracted.get("comentario_resumen")

    if isinstance(nota_comercial, (int, float)) and 1 <= nota_comercial <= 10:
        update_payload["puntuacion_comercial"] = nota_comercial
    if isinstance(nota_instalador, (int, float)) and 1 <= nota_instalador <= 10:
        update_payload["puntuacion_instalador"] = nota_instalador
    if isinstance(nota_rapidez, (int, float)) and 1 <= nota_rapidez <= 10:
        update_payload["puntuacion_rapidez"] = nota_rapidez
    if comentario:
        update_payload["comentarios_ai"] = str(comentario)[:1000]

    try:
        await sb_query(
            lambda: supabase.table("encuestas")
            .update(update_payload)
            .eq("id", encuesta_id)
            .execute()
        )
        logger.info(
            "✅ [TranscriptionAI] Encuesta %s actualizada: comercial=%s instalador=%s rapidez=%s",
            encuesta_id, nota_comercial, nota_instalador, nota_rapidez,
        )
    except Exception as e:
        logger.error("[TranscriptionAI] Error guardando en Supabase encuesta %s: %s", encuesta_id, e)
        raise


# ARQ lee este atributo para configurar los reintentos de esta tarea concreta.
process_transcription_ai.max_tries = 3  # type: ignore[attr-defined]
