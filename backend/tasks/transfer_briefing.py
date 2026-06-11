"""
transfer_briefing.py — Generación de briefing LLM al transferir a agente humano.

Extraído de worker.py para mantener WorkerSettings limpio.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

logger = logging.getLogger("arq-worker")


async def generate_transfer_briefing_task(
    ctx: dict[str, Any],
    payload_or_encuesta_id: dict[str, Any] | int,
    transcript: str | None = None,
    empresa_id: int | None = None,
    extension: str | None = None,
    room_name: str | None = None,
) -> None:
    """
    Tarea ARQ: genera un briefing estructurado con LLM y lo persiste en
    encuestas.datos_extra.transfer_briefing + encuestas.transfer_briefing.
    Opcionalmente lanza un webhook n8n con el resumen.
    """
    import openai
    from services.supabase_service import supabase, sb_query

    if isinstance(payload_or_encuesta_id, dict):
        encuesta_id = int(payload_or_encuesta_id.get("encuesta_id") or 0)
        transcript = str(payload_or_encuesta_id.get("transcript") or "")
        empresa_id = int(payload_or_encuesta_id.get("empresa_id") or 0)
        extension = str(payload_or_encuesta_id.get("extension") or "")
        room_name = str(payload_or_encuesta_id.get("room_name") or "")
    else:
        encuesta_id = int(payload_or_encuesta_id or 0)
        transcript = str(transcript or "")
        empresa_id = int(empresa_id or 0)
        extension = str(extension or "")
        room_name = str(room_name or "")

    if not supabase or not transcript.strip():
        return

    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        logger.warning("⚠️ [worker] OPENAI_API_KEY no configurada para briefing.")
        return

    client = openai.AsyncOpenAI(api_key=openai_api_key)
    system_prompt = (
        "Genera un briefing con formato fijo para un agente humano. "
        "Debes devolver exactamente estas secciones: SISTEMA, CLIENTE, MOTIVO, DATOS CLAVE, RESUMEN y TRANSCRIPCION COMPLETA."
    )
    user_prompt = (
        "Usa este formato exacto:\n"
        "SISTEMA: Transferencia de llamada IA -> Agente Humano\n"
        "CLIENTE: {nombre_detectado o No identificado}\n"
        "MOTIVO: {motivo de la llamada en 1 frase}\n"
        "DATOS CLAVE: {maximo 3 datos relevantes}\n"
        "RESUMEN: {2-3 frases}\n"
        "TRANSCRIPCION COMPLETA:\n"
        "{transcript completo}\n\n"
        f"TRANSCRIPCION:\n{transcript[:7000]}"
    )

    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=os.getenv("TRANSCRIPTION_LLM_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.2,
                max_tokens=500,
            ),
            timeout=30,
        )
        briefing = (response.choices[0].message.content or "").strip()
        if not briefing:
            return

        current = await sb_query(
            lambda: supabase.table("encuestas")
            .select("datos_extra")
            .eq("id", encuesta_id)
            .limit(1)
            .execute()
        )
        datos_extra: dict = {}
        if current.data:
            raw = current.data[0].get("datos_extra")
            if isinstance(raw, dict):
                datos_extra = raw

        datos_extra["transfer_briefing"] = briefing
        await sb_query(
            lambda: supabase.table("encuestas")
            .update({"datos_extra": datos_extra, "transfer_briefing": briefing})
            .eq("id", encuesta_id)
            .execute()
        )

        webhook_base = (os.getenv("N8N_WEBHOOK_BASE_URL") or "").strip().rstrip("/")
        if webhook_base:
            from tasks.notifications import process_n8n_webhook

            await process_n8n_webhook(
                ctx,
                {
                    "url": f"{webhook_base}/transfer-briefing",
                    "body": {
                        "encuesta_id": encuesta_id,
                        "empresa_id": empresa_id,
                        "extension": extension,
                        "room_name": room_name,
                        "transcript": transcript,
                        "resumen": briefing,
                    },
                },
            )

        logger.info("✅ [worker] Briefing guardado para encuesta=%s empresa=%s", encuesta_id, empresa_id)
    except Exception as exc:
        logger.warning("⚠️ [worker] Error generando briefing para encuesta=%s: %s", encuesta_id, exc)
