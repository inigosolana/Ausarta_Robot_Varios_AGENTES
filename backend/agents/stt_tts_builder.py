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
    Construye el plugin STT (sync, sin circuit breaker).
    Preferir build_resilient_stt_plugin() en el agente LiveKit.
    """
    if language in ("eu", "gl") or stt_provider == "openai":
        logger.info("🎙️ Usando STT: OpenAI Whisper")
        return openai.STT(language=language), False

    plugin = _build_deepgram_stt_plugin(stt_model, language)
    logger.info(f"🎙️ Usando STT: Deepgram {stt_model} (vad_events=True)")
    return plugin, True

def _build_cartesia_tts_plugin(
    voice_id: str, language: str, speaking_speed: float, tts_model: str
):
    """Plugin Cartesia TTS (primario)."""
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
        logger.warning(
            "⚠️ cartesia.TTS con modelo %s no soporta 'speed' en esta versión. Usando fallback sin speed.",
            safe_model,
        )
        return cartesia.TTS(
            model=safe_model,
            voice=safe_voice,
            language=language,
        )


def _build_openai_tts_fallback(language: str) -> Any:
    """Fallback TTS cuando Cartesia está caído (OpenAI tts-1)."""
    voice = "alloy"
    if language.startswith("es"):
        voice = "nova"
    logger.info("🎙️ Fallback TTS: OpenAI tts-1 voice=%s lang=%s", voice, language)
    return openai.TTS(model="tts-1", voice=voice)


def _build_deepgram_stt_plugin(stt_model: str, language: str) -> Any:
    import inspect

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
        return deepgram.STT(**dg_kwargs)
    except TypeError:
        dg_kwargs.pop("flush_signal", None)
        return deepgram.STT(**dg_kwargs)


def _build_openai_stt_fallback(language: str) -> Any:
    logger.info("🎙️ Fallback STT: OpenAI Whisper lang=%s", language)
    return openai.STT(language=language)


async def build_resilient_tts_plugin(
    voice_id: str,
    language: str,
    speaking_speed: float,
    tts_model: str = settings.default_tts_model,
):
    """
    TTS con Circuit Breaker (Cartesia) + FallbackAdapter (OpenAI tts-1).
    Si el circuito Cartesia está OPEN, usa solo OpenAI durante open_seconds.
    """
    from livekit.agents.tts.fallback_adapter import FallbackAdapter

    from services.provider_circuit_service import cartesia_tts_breaker

    breaker = await cartesia_tts_breaker()
    openai_tts = _build_openai_tts_fallback(language)

    if await breaker.is_open():
        logger.warning("🔴 Circuit OPEN %s → TTS solo OpenAI", breaker.name)
        return openai_tts

    cartesia_tts = _build_cartesia_tts_plugin(voice_id, language, speaking_speed, tts_model)
    adapter = FallbackAdapter(
        [cartesia_tts, openai_tts],
        max_retry_per_tts=1,
    )
    adapter._ausarta_circuit_breaker = breaker  # type: ignore[attr-defined]  # noqa: SLF001
    logger.info("🎙️ TTS resiliente: Cartesia primario + OpenAI fallback (circuit=%s)", breaker.name)
    return adapter


async def build_resilient_stt_plugin(
    stt_provider: str,
    stt_model: str,
    language: str,
) -> tuple[Any, bool]:
    """
    STT con Circuit Breaker (Deepgram) + fallback OpenAI Whisper.
    """
    from livekit.agents.stt.fallback_adapter import FallbackAdapter as STTFallbackAdapter

    from services.provider_circuit_service import deepgram_stt_breaker

    if language in ("eu", "gl") or stt_provider == "openai":
        logger.info("🎙️ Usando STT: OpenAI Whisper")
        return openai.STT(language=language), False

    breaker = await deepgram_stt_breaker()
    openai_stt = _build_openai_stt_fallback(language)

    if await breaker.is_open():
        logger.warning("🔴 Circuit OPEN %s → STT solo OpenAI Whisper", breaker.name)
        return openai_stt, False

    deepgram_stt = _build_deepgram_stt_plugin(stt_model, language)
    adapter = STTFallbackAdapter(
        [deepgram_stt, openai_stt],
        attempt_timeout=float(os.getenv("CIRCUIT_BREAKER_STT_ATTEMPT_TIMEOUT", "10")),
        max_retry_per_stt=1,
    )
    adapter._ausarta_circuit_breaker = breaker  # type: ignore[attr-defined]  # noqa: SLF001
    logger.info(
        "🎙️ STT resiliente: Deepgram %s + OpenAI fallback (circuit=%s)",
        stt_model,
        breaker.name,
    )
    return adapter, True


def _build_tts_plugin(voice_id: str, language: str, speaking_speed: float, tts_model: str = settings.default_tts_model):
    """
    Crea el plugin TTS Cartesia (sync, sin circuit breaker).
    Preferir build_resilient_tts_plugin() en el agente LiveKit.
    """
    return _build_cartesia_tts_plugin(voice_id, language, speaking_speed, tts_model)
