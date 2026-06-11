from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

from config import settings
from livekit.plugins import cartesia, deepgram, openai, silero

from agents.agent_common import _is_uuid_like

logger = logging.getLogger("agent-dynamic")

DEFAULT_CARTESIA_VOICE = os.getenv("VOICE_ID_AUSARTA", settings.default_cartesia_voice)

_GLOBAL_VAD_MODEL = None
_VAD_LOCK = asyncio.Lock()

async def get_vad_model(min_silence_duration: float):
    global _GLOBAL_VAD_MODEL
    async with _VAD_LOCK:
        if _GLOBAL_VAD_MODEL is None:
            _GLOBAL_VAD_MODEL = await asyncio.to_thread(
                silero.VAD.load, min_silence_duration=min_silence_duration
            )
            logger.info("✅ VAD Silero cargado (singleton global)")
    return _GLOBAL_VAD_MODEL


def _build_stt_plugin(
    stt_provider: str, stt_model: str, language: str
) -> tuple[Any, bool]:
    """
    Construye el plugin STT. Si delegate_turn_to_stt es True, el turno se delega al STT
    (Deepgram vad_events) y AgentSession puede omitir Silero VAD.
    """
    import inspect

    if language in ("eu", "gl") or stt_provider == "openai":
        logger.info("🎙️ Usando STT: OpenAI Whisper")
        return openai.STT(language=language), False

    dg_kwargs: dict[str, Any] = {
        "model": stt_model,
        "language": language,
        "vad_events": True,
        "endpointing_ms": int(os.getenv("AGENT_DEEPGRAM_ENDPOINTING_MS", "300")),
        "no_delay": True,
        "interim_results": True,
    }
    try:
        sig = inspect.signature(deepgram.STT.__init__)
        if "flush_signal" in sig.parameters:
            dg_kwargs["flush_signal"] = True
            logger.info("🎙️ Deepgram STT: flush_signal=True")
    except Exception:
        pass

    try:
        plugin = deepgram.STT(**dg_kwargs)
    except TypeError:
        dg_kwargs.pop("flush_signal", None)
        plugin = deepgram.STT(**dg_kwargs)
        logger.warning("🎙️ Deepgram STT: flush_signal no soportado en esta versión del SDK")

    logger.info(f"🎙️ Usando STT: Deepgram {stt_model} (vad_events=True)")
    return plugin, True

def _build_tts_plugin(voice_id: str, language: str, speaking_speed: float, tts_model: str = settings.default_tts_model):
    """
    Crea el plugin TTS aplicando voz + velocidad + modelo.
    Si el SDK no soporta el parámetro speed en la versión actual, hace fallback seguro.
    """
    safe_speed = 1.0
    try:
        safe_speed = float(speaking_speed or 1.0)
    except Exception:
        safe_speed = 1.0

    safe_voice = (voice_id or "").strip()
    if not _is_uuid_like(safe_voice):
        logger.warning(
            f"⚠️ voice_id inválida para Cartesia ('{voice_id}'). Usando voz por defecto."
        )
        safe_voice = DEFAULT_CARTESIA_VOICE

    safe_model = (tts_model or settings.default_tts_model).strip()
    # Cartesia deprecó sonic-multilingual; migrar automáticamente al modelo activo.
    if safe_model in {"sonic-multilingual", "sonic-english", "sonic", "sonic-2-2025-03-07"}:
        logger.warning(
            "⚠️ Modelo TTS '%s' deprecado en Cartesia. Usando '%s'.",
            safe_model,
            settings.default_tts_model,
        )
        safe_model = settings.default_tts_model

    try:
        return cartesia.TTS(
            model=safe_model,
            voice=safe_voice,
            language=language,
            speed=safe_speed,
        )
    except TypeError:
        logger.warning(f"⚠️ cartesia.TTS con modelo {safe_model} no soporta 'speed' en esta versión. Usando fallback sin speed.")
        return cartesia.TTS(
            model=safe_model,
            voice=safe_voice,
            language=language,
        )
