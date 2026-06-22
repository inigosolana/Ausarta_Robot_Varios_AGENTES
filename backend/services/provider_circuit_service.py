"""Circuit breakers nombrados para proveedores externos de voz/LLM."""

from __future__ import annotations

from utils.circuit_breaker import CircuitBreaker, get_circuit_breaker

# Claves estándar (compartidas entre API backend y worker LiveKit)
CIRCUIT_CARTESIA = "provider:cartesia"
CIRCUIT_CARTESIA_TTS = "provider:cartesia:tts"
CIRCUIT_DEEPGRAM_STT = "provider:deepgram:stt"
CIRCUIT_GROQ_LLM = "provider:groq:llm"


async def cartesia_breaker() -> CircuitBreaker:
    return await get_circuit_breaker(CIRCUIT_CARTESIA)


async def cartesia_tts_breaker() -> CircuitBreaker:
    return await get_circuit_breaker(CIRCUIT_CARTESIA_TTS)


async def deepgram_stt_breaker() -> CircuitBreaker:
    return await get_circuit_breaker(CIRCUIT_DEEPGRAM_STT)


async def groq_llm_breaker() -> CircuitBreaker:
    return await get_circuit_breaker(CIRCUIT_GROQ_LLM)
