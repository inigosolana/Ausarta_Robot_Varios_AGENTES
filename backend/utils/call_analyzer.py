"""
Clasificación post-llamada (disposición + datos_extra) vía API Groq.
"""

from __future__ import annotations

import json
import logging
import os
import re

import aiohttp

logger = logging.getLogger(__name__)


async def analyze_call_disposition(
    transcript: str,
    agent_type: str,
    data_saved: bool,
    language: str,
) -> tuple[str | None, dict | None]:
    """
    Clasifica la disposición de la llamada y devuelve datos_extra enriquecidos.
    Retorna (None, None) si no hay API key, falla HTTP o hay error de parseo.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return None, None

    disposition_prompt = (
        "Eres un analista experto en llamadas telefónicas comerciales. "
        "Analiza la transcripción y responde ÚNICAMENTE con JSON válido con estos campos:\n\n"
        "1. 'disposicion': OBLIGATORIO. Clasifica la llamada en exactamente UNO de estos valores:\n"
        "   - 'completada': El cliente respondió a todas o casi todas las preguntas/objetivos de la llamada.\n"
        "   - 'parcial': El cliente contestó la llamada y respondió a ALGUNAS preguntas, pero colgó o se interrumpió antes de terminar.\n"
        "   - 'rechazada': El cliente contestó pero rechazó participar (dijo 'no me interesa', 'no tengo tiempo', 'quitadme de la lista', etc.).\n"
        "   - 'no_contesta': La llamada fue contestada por un buzón de voz, contestador automático, o no hubo interacción humana real.\n\n"
    )

    if agent_type == "CUALIFICACION_LEAD":
        disposition_prompt += (
            "2. 'lead_cualificado' (booleano): ¿El lead cumple los criterios de cualificación?\n"
            "3. 'interes' (string: 'alto', 'medio', 'bajo'): Nivel de interés detectado.\n"
            "4. 'motivo_rechazo' (string o null): Razón por la que no cualifica o rechaza.\n"
        )
    elif agent_type == "AGENDAMIENTO_CITA":
        disposition_prompt += (
            "2. 'cita_agendada' (booleano): ¿Se agendó una cita?\n"
            "3. 'fecha_cita' (string formato libre o null): Fecha/hora acordada.\n"
            "4. 'disponibilidad' (string o null): Resumen de cuándo está disponible.\n"
        )
    elif agent_type != "ENCUESTA_NUMERICA":
        disposition_prompt += (
            "2. 'puntos_clave' (array de strings): Los 3 puntos más importantes de la conversación.\n"
        )
    else:
        disposition_prompt += ""

    disposition_prompt += (
        "\nAdemás, SIEMPRE incluye este campo obligatorio:\n"
        "- 'sentimiento_cliente': Clasifica estrictamente como 'Positivo', 'Neutral' o 'Negativo' "
        "basándote en el tono general del cliente durante la llamada.\n"
    )

    try:
        async with aiohttp.ClientSession() as llm_sess:
            headers = {
                "Authorization": f"Bearer {groq_api_key}",
                "Content-Type": "application/json",
            }
            payload_llm = {
                "model": "llama-3.3-70b-versatile",
                "messages": [
                    {"role": "system", "content": disposition_prompt},
                    {"role": "user", "content": f"Transcripción:\n{transcript}"},
                ],
                "response_format": {"type": "json_object"},
                "temperature": 0.1,
            }
            async with llm_sess.post(
                "https://api.groq.com/openai/v1/chat/completions",
                json=payload_llm,
                headers=headers,
                timeout=20,
            ) as llm_resp:
                if llm_resp.status != 200:
                    logger.error(f"Error HTTP del LLM al clasificar: {llm_resp.status}")
                    return None, None

                llm_data = await llm_resp.json()
                json_str = llm_data["choices"][0]["message"]["content"]
                json_str = re.sub(
                    r"^```(?:json)?\s*|\s*```$",
                    "",
                    json_str.strip(),
                    flags=re.IGNORECASE,
                )
                parsed = json.loads(json_str)

                call_disposition = parsed.pop("disposicion", None)
                valid_dispositions = ("completada", "parcial", "rechazada", "no_contesta")
                if call_disposition not in valid_dispositions:
                    call_disposition = "completada" if data_saved else "parcial"

                sentimiento = parsed.pop("sentimiento_cliente", None)
                valid_sentimientos = ("Positivo", "Neutral", "Negativo")
                if sentimiento not in valid_sentimientos:
                    sentimiento = "Neutral"

                datos_extra: dict | None = None
                if parsed:
                    datos_extra = parsed

                if datos_extra is None:
                    datos_extra = {}
                datos_extra["sentimiento_cliente"] = sentimiento
                datos_extra["idioma"] = language

                logger.info(
                    f"✅ Disposición: {call_disposition} | Sentimiento: {sentimiento} | Idioma: {datos_extra['idioma']} | datos_extra_keys: {list(datos_extra.keys())}"
                )
                return call_disposition, datos_extra

    except Exception as e:
        logger.error(f"Error clasificando disposición con LLM: {e}")
        return None, None
