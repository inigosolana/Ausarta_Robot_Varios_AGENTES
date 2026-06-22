"""Entrypoint LiveKit y servidor del agente de voz."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from typing import Any, Optional

from config import settings
from livekit import rtc
from livekit.agents import (
    AgentServer,
    AgentSession,
    AutoSubscribe,
    JobContext,
    cli,
)
from livekit.plugins import openai
from livekit.agents.llm import FallbackAdapter

from agents.agent_common import (
    ALLOWED_ROOM_PREFIXES,
    DISPATCH_AGENT_NAME,
    _parse_inbound_caller_from_room,
    _room_name_allowed,
)
from agents.agent_logging import configure_agent_logging
from agents.call_session import CallSession
from agents.config_fetcher import (
    _register_inbound_call_record,
    fetch_agent_config,
    fetch_agent_config_by_agent_id,
)
from agents.dynamic_agent import DynamicAgent
from agents.stt_tts_builder import (
    build_resilient_stt_plugin,
    build_resilient_tts_plugin,
    get_vad_model,
)
from utils.tracing import extract_carrier_from_metadata, traced_span, voice_call_context

logger = configure_agent_logging("agent-dynamic")
# ============================================================================
# FUNCIÓN PARA ENVIAR ALERTAS AL SISTEMA (VÍA ARQ)
# ============================================================================
async def notify_system_alert(message: str, details: Optional[dict] = None):
    try:
        from services.queue_service import get_arq_pool
        redis = await get_arq_pool()
        await redis.enqueue_job("process_system_alert", message, details)
        logger.info(f"📡 Alerta del sistema encolada: {message}")
    except Exception as e:
        logger.error(f"❌ Error encolando alerta del sistema: {e}")

# ============================================================================
# SERVIDOR Y ENTRYPOINT DINÁMICO
# ============================================================================
server = AgentServer()

@server.rtc_session(agent_name=DISPATCH_AGENT_NAME)
async def entrypoint(ctx: JobContext):
    # Identificador único para esta instancia/trabajo
    job_id = ctx.job.id if hasattr(ctx, 'job') else "unknown"
    room_name = ctx.room.name
    
    logger.info(f"--- 🚀 INICIO DE SESIÓN AGENTE (Job: {job_id}, Room: {room_name}) ---")
    
    def handle_error(error):
        msg = str(error)
        if "429" in msg or "Rate Limit" in msg or "insufficient_quota" in msg: 
            logger.error(f"🚨🚨🚨 ALERTA (Job {job_id}): Límite de API Alcanzado")
            asyncio.create_task(notify_system_alert("Límite de API Alcanzado (Error 429)", {"job_id": job_id, "error": msg}))
        else:
            logger.error(f"⚠️ ERROR DEL AGENTE (Job {job_id}): {error}")
            asyncio.create_task(notify_system_alert("Error en Agente LiveKit", {"job_id": job_id, "error": msg}))

    async def _safe_reject(reason: str):
        logger.error(f"🚫 [{job_id}] Job rechazado: {reason}")
        # En esta versión de LiveKit no existe ctx.reject(); cerramos de forma segura.
        try:
            shutdown_fn = getattr(ctx, "shutdown", None)
            if callable(shutdown_fn):
                try:
                    maybe = shutdown_fn(reason=reason)
                except TypeError:
                    maybe = shutdown_fn()
                if asyncio.iscoroutine(maybe):
                    await maybe
                return
            logger.warning(f"[{job_id}] No hay método reject/shutdown disponible en JobContext.")
        except Exception as rej_err:
            logger.error(f"[{job_id}] Error cerrando job rechazado: {rej_err}")

    # --- PASO 1: Filtro estricto de sala + metadata ---
    if not _room_name_allowed(room_name):
        await _safe_reject(
            f"Sala fuera de prefijos permitidos {ALLOWED_ROOM_PREFIXES}: {room_name}"
        )
        return

    metadata_str = getattr(ctx.job, 'metadata', '')
    if not metadata_str:
        await _safe_reject("metadata vacía")
        return

    try:
        meta_data = json.loads(metadata_str)
    except Exception as e:
        await _safe_reject(f"metadata no JSON válido: {e}")
        return

    is_inbound_call = str(meta_data.get("call_direction") or "").lower() == "inbound"
    inbound_agent_id = str(meta_data.get("agent_id") or "").strip()
    if not is_inbound_call and "campana_id" not in meta_data and "client_id" not in meta_data:
        await _safe_reject("metadata sin campana_id/client_id")
        return
    if is_inbound_call and not inbound_agent_id:
        await _safe_reject("metadata inbound sin agent_id")
        return

    # --- PASO 2: Extraer survey_id y empresa_id (Sello Multi-Tenant) ---
    survey_id = "0"
    empresa_id = "0"
    try:
        survey_id = str(meta_data.get("survey_id", "0"))
        empresa_id = str(meta_data.get("empresa_id", "0"))
        logger.info(f"🔑 [{job_id}] Metadatos parseados: empresa={empresa_id}, survey={survey_id}, campana_id={meta_data.get('campana_id')}, client_id={meta_data.get('client_id')}")
    except Exception as e:
        logger.warning(f"⚠️ [{job_id}] Error extrayendo campos de metadata: {e}")
            
    # 2. Fallback: intentar extraer del room_name
    if survey_id == "0":
        try:
            parts = room_name.split('_')
            survey_id = parts[-1] if parts else "0"
            if empresa_id == "0" and len(parts) >= 2 and parts[0] == "empresa":
                empresa_id = parts[1]
            logger.info(f"🔑 [{job_id}] Metadatos extraídos de room_name: empresa={empresa_id}, survey={survey_id}")
        except Exception as e:
            logger.warning(f"⚠️ [{job_id}] Error extrayendo survey_id de room_name: {e}")

    # 3. Validación de Identidad Temprana Crítica
    # Permite survey_ids numéricos Y alfanuméricos (UUIDs, slugs, etc.)
    if (not survey_id or survey_id == "0") and is_inbound_call:
        survey_id = f"inbound_{empresa_id or '0'}"
    if not survey_id or survey_id == "0":
        await _safe_reject(f"Identidad inválida o corrupta: survey_id='{survey_id}'")
        return

    # --- PASO 1.5: Validar Sello Multi-Tenant ANTES de conectar ---
    try:
        # Obtenemos config y validamos que la sala es del mismo tenant que el config
        if is_inbound_call and inbound_agent_id:
            agent_config = await fetch_agent_config_by_agent_id(
                inbound_agent_id,
                expected_empresa_id=empresa_id,
            )
            agent_config["call_direction"] = "inbound"
        else:
            agent_config = await fetch_agent_config(survey_id, expected_empresa_id=empresa_id)
    except Exception as e:
        if "Violación de seguridad" in str(e):
            await _safe_reject(str(e))
            return
        else:
            logger.warning(f"⚠️ [{job_id}] Error cargando config previa: {e}")
            agent_config = {}

    # --- PASO 2: Conectar a la sala (trace voice.call) ---
    from utils.tracing import extract_carrier_from_metadata, traced_span, voice_call_context

    async with voice_call_context(
        job_id=str(job_id),
        room_name=str(room_name),
        empresa_id=empresa_id,
        survey_id=survey_id,
        carrier=extract_carrier_from_metadata(meta_data),
    ):
        call_start_time = time.time()
        is_duplicate = False
        cs: "CallSession | None" = None
        try:
            logger.info(f"⏱️ [{job_id}] Intentando conectar a sala {room_name}...")
            await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

            # --- CONTROL DE DUPLICIDAD ---
            agent_participants = [p for p in ctx.room.remote_participants.values() if getattr(p, 'kind', None) == rtc.ParticipantKind.PARTICIPANT_KIND_AGENT or getattr(p, 'identity', '').startswith("agent-")]
            if len(agent_participants) > 1: # Ya estamos nosotros (1), si hay más (1+) es que hay otro
                logger.warning(f"⚠️ [{job_id}] Ya un agente en la sala {room_name}. Cancelando duplicado.")
                is_duplicate = True
                return

            logger.info(f"✅ [{job_id}] Conectado a sala {room_name}. Participantes: {len(ctx.room.remote_participants)}")

            if is_inbound_call:
                caller_phone = _parse_inbound_caller_from_room(room_name)
                if caller_phone:
                    meta_data.setdefault("telefono", caller_phone)
                    meta_data.setdefault("contacto_phone", caller_phone)

            # --- PASO 4 (Fase 2): Cargar contextos KB y cliente ANTES de crear el agente ---
            from utils.call_loader import enrich_agent_config_with_context
            await enrich_agent_config_with_context(
                job_id=job_id,
                agent_config=agent_config,
                empresa_id_str=empresa_id,
                meta_data=meta_data,
            )

            if is_inbound_call:
                inbound_encuesta_id = await _register_inbound_call_record(
                    agent_config,
                    room_name,
                    empresa_id,
                )
                if inbound_encuesta_id:
                    survey_id = str(inbound_encuesta_id)
                    agent_config["inbound_encuesta_id"] = inbound_encuesta_id
                    logger.info(
                        f"📞 [{job_id}] Llamada inbound registrada como encuesta {inbound_encuesta_id}"
                    )

            # --- PASO 4: Crear el asistente ---
            agent_instance = DynamicAgent(room_name=room_name, agent_config=agent_config)

            llm_model = agent_config.get("llm_model", "llama-3.3-70b-versatile")
            voice_id = agent_config.get("voice_id", os.getenv("VOICE_ID_AUSARTA", settings.default_cartesia_voice))
            tts_model = agent_config.get("tts_model", settings.default_tts_model)
            language = agent_config.get("language", "es")
            stt_provider = agent_config.get("stt_provider", "deepgram")
            stt_model = agent_config.get("stt_model", settings.default_stt_model)
            speaking_speed = agent_config.get("speaking_speed", 1.0)
            has_strict_extraction = bool(
                agent_config.get("extraction_schema")
                and isinstance(agent_config.get("extraction_schema"), list)
            )

            logger.info(
                f"🤖 [{job_id}] Config: LLM='{llm_model}', Voice='{voice_id}', TTS='{tts_model}', "
                f"Lang='{language}', STT='{stt_provider}/{stt_model}', Speed='{speaking_speed}'"
            )

            async with traced_span(
                "voice.stt.init",
                {"voice.stt_provider": stt_provider, "voice.stt_model": stt_model},
            ):
                stt_plugin, delegate_turn_to_stt = await build_resilient_stt_plugin(
                    stt_provider, stt_model, language
                )

            # VAD Silero solo si el STT no gestiona el turno (p. ej. OpenAI Whisper)
            vad_model = None
            if delegate_turn_to_stt:
                logger.info(f"✅ [{job_id}] Turn detection delegado al STT (sin VAD Silero).")
            else:
                min_silence_duration = float(os.getenv("AGENT_MIN_SILENCE_SECONDS", "0.65"))
                min_silence_duration = max(0.55, min(min_silence_duration, 1.0))
                vad_model = await get_vad_model(min_silence_duration)
                logger.info(f"✅ [{job_id}] VAD Silero cargado (min_silence={min_silence_duration}s).")

            from livekit.agents.llm.fallback_adapter import FallbackAdapter  # type: ignore

            # LLM Principal: OpenAI (GPT/o1/o3) o Groq (Llama, Mixtral, etc.)
            _is_openai_model = any(k in llm_model for k in ("gpt", "o1", "o3"))
            llm_parallel_tools = False if has_strict_extraction else None

            async with traced_span(
                "voice.llm.init",
                {"voice.llm_model": llm_model, "voice.llm_provider": "openai" if _is_openai_model else "groq"},
            ):
                if _is_openai_model:
                    logger.info(f"🤖 [{job_id}] Modelo OpenAI detectado ('{llm_model}'). Usando endpoint OpenAI.")
                    main_llm = openai.LLM(
                        model=llm_model,
                        api_key=os.getenv("OPENAI_API_KEY"),
                        temperature=0.35,
                        parallel_tool_calls=llm_parallel_tools,
                    )
                else:
                    logger.info(f"🤖 [{job_id}] Modelo Groq detectado ('{llm_model}'). Usando endpoint Groq.")
                    main_llm = openai.LLM(
                        model=llm_model,
                        base_url="https://api.groq.com/openai/v1",
                        api_key=os.getenv("GROQ_API_KEY"),
                        temperature=0.35,
                        parallel_tool_calls=llm_parallel_tools,
                    )

                # LLM Secundario (OpenAI - gpt-4o-mini): fallback universal
                fallback_llm = openai.LLM(
                    model="gpt-4o-mini",
                    api_key=os.getenv("OPENAI_API_KEY"),
                    temperature=0.2,
                    parallel_tool_calls=llm_parallel_tools,
                )

                # Usar FallbackAdapter transparente al cliente
                final_llm = FallbackAdapter([main_llm, fallback_llm], attempt_timeout=10.0)

            # --- Crear sesión del agente (latencia objetivo <500ms) ---
            endpointing_min = float(os.getenv("AGENT_ENDPOINTING_MIN", "0.07"))
            endpointing_max = float(os.getenv("AGENT_ENDPOINTING_MAX", "0.5"))
            endpointing_min = max(0.05, min(endpointing_min, 0.3))
            endpointing_max = max(endpointing_min + 0.05, min(endpointing_max, 1.0))

            async with traced_span("voice.tts.init", {"voice.tts_model": tts_model}):
                tts_plugin = await build_resilient_tts_plugin(
                    voice_id=voice_id,
                    language=language,
                    speaking_speed=speaking_speed,
                    tts_model=tts_model,
                )

            session_kwargs: dict[str, Any] = {
                "stt": stt_plugin,
                "llm": final_llm,
                "tts": tts_plugin,
                "min_endpointing_delay": endpointing_min,
                "max_endpointing_delay": endpointing_max,
                "preemptive_generation": True,
                "use_tts_aligned_transcript": True,
            }
            if vad_model is not None:
                session_kwargs["vad"] = vad_model
            turn_mode = "vad"
            if delegate_turn_to_stt:
                session_kwargs["turn_detection"] = "stt"
                turn_mode = "stt"

            try:
                session = AgentSession(**session_kwargs)
            except TypeError as session_err:
                if delegate_turn_to_stt and "turn_detection" in str(session_err):
                    logger.warning(
                        f"⚠️ [{job_id}] turn_detection='stt' no soportado; fallback a VAD Silero: {session_err}"
                    )
                    session_kwargs.pop("turn_detection", None)
                    min_silence = float(os.getenv("AGENT_MIN_SILENCE_SECONDS", "0.65"))
                    session_kwargs["vad"] = await get_vad_model(max(0.55, min(min_silence, 1.0)))
                    turn_mode = "vad"
                    session = AgentSession(**session_kwargs)
                else:
                    raise

            logger.info(
                f"⚡ [{job_id}] AgentSession endpointing={endpointing_min}-{endpointing_max}s "
                f"turn_detection={turn_mode}"
            )

            # --- Iniciar CallSession: agrupa todos los bucles y post-procesamiento ---
            cs = CallSession(
                ctx=ctx,
                job_id=job_id,
                room_name=room_name,
                survey_id=survey_id,
                agent_config=agent_config,
                session=session,
                agent_instance=agent_instance,
                language=language,
                voice_id=voice_id,
                speaking_speed=float(speaking_speed or 1.0),
                tts_model=tts_model,
                call_start_time=call_start_time,
                call_metadata=meta_data,
            )
            cs.setup_events()
            await session.start(room=ctx.room, agent=agent_instance)
            await cs.start()

        except Exception as e:
            handle_error(e)

        finally:
            if cs is not None:
                try:
                    await cs.cleanup()
                except Exception as cleanup_err:
                    logger.warning(f"[{job_id}] Error en cleanup de sesión: {cleanup_err}")

            if not is_duplicate:
                logger.info(
                    f"--- 🏁 FIN DE SESIÓN AGENTE "
                    f"(Job: {job_id}, Room: {room_name}, Survey: {survey_id}) ---"
                )
                if cs is not None:
                    try:
                        await cs.finalize()
                    except Exception as fatal_post:
                        logger.error(
                            f"🚨 [{job_id}] EXCEPCIÓN FATAL NO CAPTURADA en finalize: {fatal_post}"
                        )
            else:
                logger.info(
                    f"--- 🏁 FIN DE SESIÓN DUPLICADA (Job: {job_id}) - Saliendo sin reportar datos ---"
                )


if __name__ == "__main__":
    from agents.agent_common import BRIDGE_SERVER_URL_INTERNAL

    logger.info(
        "🤖 Arrancando worker LiveKit | agent_name=%s | livekit_url=%s | bridge=%s",
        DISPATCH_AGENT_NAME,
        (os.getenv("LIVEKIT_URL") or "NO SET"),
        BRIDGE_SERVER_URL_INTERNAL,
    )
    cli.run_app(server)
