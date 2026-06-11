"""
Clasificación post-llamada (disposición + datos_extra) vía API Groq.
También actualiza la ficha de contacto tras cada llamada (Fase 2).
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone

import aiohttp

logger = logging.getLogger(__name__)


def _contacto_llamada_entry(
    disposicion: str | None,
    resumen: str | None,
    datos_llamada: dict | None,
) -> dict:
    return {
        **(datos_llamada or {}),
        "disposicion": disposicion,
        "resumen": resumen,
    }


async def _fetch_contacto_row(empresa_id: int, telefono: str) -> tuple[dict | None, bool]:
    """Devuelve (fila, tiene_columna_historial). Tolera esquemas sin historial_llamadas."""
    from services.supabase_service import supabase, sb_query

    if not supabase:
        return None, False

    for fields, with_hist in (
        ("id, total_llamadas, score, nombre, historial_llamadas, datos_extra", True),
        ("id, total_llamadas, score, nombre, datos_extra", False),
        ("id, total_llamadas, score, nombre", False),
    ):
        try:
            res = await sb_query(
                lambda f=fields, eid=empresa_id, tel=telefono: supabase.table("contactos")
                .select(f)
                .eq("empresa_id", eid)
                .eq("telefono", tel)
                .limit(1)
                .execute()
            )
            if res.data:
                return res.data[0], with_hist and "historial_llamadas" in res.data[0]
        except Exception:
            continue
    return None, False


async def upsert_contacto_post_call(
    empresa_id: int,
    telefono: str,
    nombre_detectado: str | None,
    disposicion: str | None,
    resumen: str | None,
    datos_llamada: dict | None = None,
) -> None:
    """
    Crea o actualiza la ficha de contacto tras una llamada.
    Compatible con esquemas antiguos (sin historial_llamadas).
    Nunca propaga excepciones; si falla, solo loguea.
    """
    if not telefono or not empresa_id:
        return

    try:
        from services.supabase_service import supabase, sb_query
        if not supabase:
            return

        now_iso = datetime.now(timezone.utc).isoformat()

        score_delta = 0
        if disposicion in ("completada",):
            score_delta = 10
        elif disposicion in ("rechazada",):
            score_delta = -5

        existing, has_historial_col = await _fetch_contacto_row(empresa_id, telefono)
        llamada_entry = _contacto_llamada_entry(disposicion, resumen, datos_llamada)

        if existing:
            contact_id = existing["id"]
            new_total = (existing.get("total_llamadas") or 0) + 1
            new_score = max(0, (existing.get("score") or 0) + score_delta)

            update_data: dict = {
                "ultima_llamada": now_iso,
                "total_llamadas": new_total,
                "ultima_disposicion": disposicion,
                "score": new_score,
            }
            if nombre_detectado and not existing.get("nombre"):
                update_data["nombre"] = nombre_detectado

            if has_historial_col:
                historial = existing.get("historial_llamadas") or []
                if not isinstance(historial, list):
                    historial = []
                historial.append(llamada_entry)
                update_data["historial_llamadas"] = historial[-50:]
            elif datos_llamada:
                datos_extra = existing.get("datos_extra") if isinstance(existing.get("datos_extra"), dict) else {}
                hist = datos_extra.get("llamadas") if isinstance(datos_extra.get("llamadas"), list) else []
                hist.append(llamada_entry)
                datos_extra["llamadas"] = hist[-50:]
                update_data["datos_extra"] = datos_extra

            await sb_query(
                lambda cid=contact_id, d=update_data: supabase.table("contactos")
                .update(d)
                .eq("id", cid)
                .execute()
            )
            logger.info(
                "[contacto] Actualizado id=%s empresa=%d total=%d disp=%s",
                contact_id, empresa_id, new_total, disposicion,
            )
        else:
            insert_data: dict = {
                "empresa_id": empresa_id,
                "telefono": telefono,
                "nombre": nombre_detectado or None,
                "ultima_llamada": now_iso,
                "total_llamadas": 1,
                "ultima_disposicion": disposicion,
                "score": max(0, 50 + score_delta),
            }
            if datos_llamada:
                insert_data["historial_llamadas"] = [llamada_entry]
                insert_data["datos_extra"] = {"llamadas": [llamada_entry]}

            try:
                await sb_query(
                    lambda d=insert_data: supabase.table("contactos").insert(d).execute()
                )
            except Exception:
                insert_data.pop("historial_llamadas", None)
                await sb_query(
                    lambda d=insert_data: supabase.table("contactos").insert(d).execute()
                )
            logger.info(
                "[contacto] Creado nuevo contacto empresa=%d telefono=%s disp=%s",
                empresa_id, telefono[:6] + "…", disposicion,
            )

    except Exception as exc:
        logger.warning("[contacto] upsert_contacto_post_call falló (no bloqueante): %s", exc)


async def analyze_call_disposition(
    transcript: str,
    agent_type: str,
    data_saved: bool,
    language: str,
    call_direction: str = "outbound",
) -> tuple[str | None, dict | None]:
    """
    Clasifica la disposición de la llamada y devuelve datos_extra enriquecidos.
    Retorna (None, None) si no hay API key, falla HTTP o hay error de parseo.
    """
    groq_api_key = os.getenv("GROQ_API_KEY")
    if not groq_api_key:
        return None, None

    # SYSTEM_PROMPT con JSON Schema explícito para guiar al LLM con precisión.
    # Se añade 'resumen_narrativo' (Fase 1 SaaS): 3-4 frases que describen qué quería
    # el cliente, cómo se desarrolló la interacción y en qué quedó la situación.
    # Esto permite presentar un resumen legible en dashboards y fichas de contacto
    # sin necesidad de leer la transcripción completa.
    disposition_prompt = (
        "Eres un analista experto en llamadas telefónicas comerciales. "
        "Analiza la transcripción y responde ÚNICAMENTE con JSON válido (sin markdown, sin explicaciones) "
        "que cumpla exactamente este schema:\n\n"
        "{\n"
        '  "disposicion": <string: "completada" | "parcial" | "rechazada" | "no_contesta">,\n'
        '  "sentimiento_cliente": <string: "Positivo" | "Neutral" | "Negativo">,\n'
        '  "resumen_narrativo": <string: 3-4 frases en español que expliquen (1) qué quería o '
        "necesitaba el cliente, (2) cómo transcurrió la interacción con el agente, "
        "y (3) en qué estado quedó la situación al finalizar la llamada. "
        'Sé concreto y útil para un equipo de ventas o soporte.>\n'
        "}\n\n"
        "Definiciones de 'disposicion':\n"
        "  - 'completada': El cliente respondió a todas o casi todas las preguntas/objetivos.\n"
        "  - 'parcial': Contestó la llamada y respondió a ALGUNAS preguntas, pero se interrumpió antes de terminar.\n"
        "  - 'rechazada': Contestó pero rechazó participar explícitamente.\n"
        "  - 'no_contesta': Buzón de voz, contestador automático o sin interacción humana real.\n\n"
    )

    is_inbound = str(call_direction or "").lower() == "inbound"
    if is_inbound:
        disposition_prompt += (
            "CONTEXTO LLAMADA ENTRANTE:\n"
            "- El cliente llamó a la empresa (no es campaña saliente).\n"
            "- Si hay diálogo real con el cliente (preguntas, respuestas, consultas), "
            "NUNCA uses 'no_contesta'. Usa 'completada', 'parcial' o 'rechazada'.\n"
            "- 'no_contesta' solo si no hubo interacción humana (cuelgue inmediato, buzón, silencio total).\n\n"
        )

    if agent_type == "SOPORTE_CLIENTE":
        disposition_prompt += (
            "Añade también estos campos al JSON:\n"
            "- 'motivo_llamada' (string): Motivo principal de la llamada del cliente.\n"
            "- 'resolucion' (string): Qué se resolvió o qué quedó pendiente.\n"
            "- 'puntos_clave' (array de strings): Los 3 puntos más importantes.\n"
        )
    elif agent_type == "CUALIFICACION_LEAD":
        disposition_prompt += (
            "Añade también estos campos al JSON:\n"
            "- 'lead_cualificado' (booleano): ¿El lead cumple los criterios de cualificación?\n"
            "- 'interes' (string: 'alto', 'medio', 'bajo'): Nivel de interés detectado.\n"
            "- 'motivo_rechazo' (string o null): Razón por la que no cualifica o rechaza.\n"
        )
    elif agent_type == "AGENDAMIENTO_CITA":
        disposition_prompt += (
            "Añade también estos campos al JSON:\n"
            "- 'cita_agendada' (booleano): ¿Se agendó una cita?\n"
            "- 'fecha_cita' (string formato libre o null): Fecha/hora acordada.\n"
            "- 'disponibilidad' (string o null): Resumen de cuándo está disponible.\n"
        )
    elif agent_type != "ENCUESTA_NUMERICA":
        disposition_prompt += (
            "Añade también este campo al JSON:\n"
            "- 'puntos_clave' (array de strings): Los 3 puntos más importantes de la conversación.\n"
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

                # Extraer resumen_narrativo si el LLM lo generó (Fase 1 SaaS).
                # Se guarda en datos_extra para que el worker lo persista en
                # encuestas.resumen_llamada vía guardar-encuesta.
                resumen_narrativo: str | None = parsed.pop("resumen_narrativo", None)
                if resumen_narrativo and not isinstance(resumen_narrativo, str):
                    resumen_narrativo = str(resumen_narrativo)

                datos_extra: dict | None = None
                if parsed:
                    datos_extra = parsed

                if datos_extra is None:
                    datos_extra = {}
                datos_extra["sentimiento_cliente"] = sentimiento
                datos_extra["idioma"] = language
                if resumen_narrativo:
                    datos_extra["resumen_narrativo"] = resumen_narrativo

                if is_inbound:
                    from utils.inbound_call import normalize_inbound_disposition

                    call_disposition = normalize_inbound_disposition(
                        call_disposition,
                        transcript,
                        data_saved,
                        agent_type,
                    )

                logger.info(
                    "✅ Disposición: %s | Sentimiento: %s | Idioma: %s | "
                    "Resumen: %s | datos_extra_keys: %s",
                    call_disposition,
                    sentimiento,
                    datos_extra["idioma"],
                    "sí" if resumen_narrativo else "no",
                    list(datos_extra.keys()),
                )
                return call_disposition, datos_extra

    except Exception as e:
        logger.error(f"Error clasificando disposición con LLM: {e}")
        return None, None
