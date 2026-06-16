"""Listado de voces Cartesia con caché Redis y fallback curado."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import aiohttp

from config import settings

logger = logging.getLogger("api-backend")

CARTESIA_VOICES_URL = "https://api.cartesia.ai/voices"
CARTESIA_API_VERSION = "2024-06-10"
CACHE_KEY = "ausarta:cartesia:voices"
CACHE_TTL_SECONDS = 3600

# Voces curadas de la plataforma (fallback si Cartesia no responde)
CURATED_VOICES: list[dict[str, Any]] = [
    {
        "id": "b5aa8098-49ef-475d-89b0-c9262ecf33fd",
        "name": "Inés",
        "label": "Inés (España - Natural)",
        "language": "es",
        "group": "Español",
        "gender": "feminine",
    },
    {
        "id": "cefcb124-080b-4655-b31f-932f3ee743de",
        "name": "Raquel",
        "label": "Raquel (España - Suave)",
        "language": "es",
        "group": "Español",
        "gender": "feminine",
    },
    {
        "id": "a2f12ebd-80df-4de7-83f3-809599135b1d",
        "name": "Marta",
        "label": "Marta (España - Corporativa)",
        "language": "es",
        "group": "Español",
        "gender": "feminine",
    },
    {
        "id": "50074b01-9420-4bf5-905e-3a992665e717",
        "name": "Alba",
        "label": "Alba (España - Narrativa)",
        "language": "es",
        "group": "Español",
        "gender": "feminine",
    },
    {
        "id": "692cd5ac-7140-49e5-950c-35cd0ebebc12",
        "name": "Javier",
        "label": "Javier (España - Hombre)",
        "language": "es",
        "group": "Español",
        "gender": "masculine",
    },
    {
        "id": "79a125e3-4d2a-4645-83e3-a618400030f0",
        "name": "Carlos",
        "label": "Carlos (España - Hombre serio)",
        "language": "es",
        "group": "Español",
        "gender": "masculine",
    },
    {
        "id": "d4db5fb9-f44b-4bd1-85fa-192e0f0d75f9",
        "name": "VOZ BUENA",
        "label": "VOZ BUENA",
        "language": "es",
        "group": "Español",
        "gender": "feminine",
        "recommended_tts_model": "sonic-3",
        "recommended_speaking_speed": 1.15,
    },
    {
        "id": "99543693-cf6e-4e1d-9259-2e5cc9a0f76b",
        "name": "Ane",
        "label": "Ane (Chica Euskera)",
        "language": "eu",
        "group": "Euskera",
        "gender": "feminine",
    },
    {
        "id": "a62209c3-9f0a-4474-9b51-84b191593f49",
        "name": "Ion",
        "label": "Ion (Chico Euskera)",
        "language": "eu",
        "group": "Euskera",
        "gender": "masculine",
    },
    {
        "id": "96eade6e-d863-4f9a-8b08-5d7b74d1643b",
        "name": "Sabela",
        "label": "Sabela (Chica Gallega)",
        "language": "gl",
        "group": "Gallego",
        "gender": "feminine",
    },
    {
        "id": "4679c1e3-1fd5-45c0-a3a6-7f6e21ef82e2",
        "name": "Brais",
        "label": "Brais (Chico Gallego)",
        "language": "gl",
        "group": "Gallego",
        "gender": "masculine",
    },
    {
        "id": "62ae83ad-4f6a-430b-af41-a9bede9286ca",
        "name": "Sarah",
        "label": "Sarah (Chica Inglés)",
        "language": "en",
        "group": "Inglés",
        "gender": "feminine",
    },
    {
        "id": "0ad65e7f-006c-47cf-bd31-52279d487913",
        "name": "Mark",
        "label": "Mark (Chico Inglés)",
        "language": "en",
        "group": "Inglés",
        "gender": "masculine",
    },
]

_LANGUAGE_GROUPS = {
    "es": "Español",
    "en": "Inglés",
    "eu": "Euskera",
    "gl": "Gallego",
    "fr": "Francés",
    "de": "Alemán",
    "pt": "Portugués",
}

_CURATED_BY_ID = {v["id"]: dict(v) for v in CURATED_VOICES}


def _language_group(language: str | None) -> str:
    code = (language or "es").strip().lower().split("-")[0]
    return _LANGUAGE_GROUPS.get(code, code.upper() or "Otros")


def normalize_cartesia_voice(raw: dict[str, Any]) -> dict[str, Any]:
    voice_id = str(raw.get("id") or raw.get("voice_id") or "").strip()
    if not voice_id:
        return {}

    curated = _CURATED_BY_ID.get(voice_id, {})
    name = str(raw.get("name") or curated.get("name") or voice_id[:8]).strip()
    language = str(
        raw.get("language")
        or curated.get("language")
        or (raw.get("locale") or "")[:2]
        or "es"
    ).lower().split("-")[0]

    label = curated.get("label") or name
    if not curated and raw.get("description"):
        label = f"{name} ({raw['description']})"

    voice = {
        "id": voice_id,
        "name": name,
        "label": label,
        "language": language,
        "group": curated.get("group") or _language_group(language),
        "gender": raw.get("gender") or curated.get("gender"),
        "source": "curated" if voice_id in _CURATED_BY_ID else "cartesia",
    }
    if curated.get("recommended_tts_model"):
        voice["recommended_tts_model"] = curated["recommended_tts_model"]
    if curated.get("recommended_speaking_speed") is not None:
        voice["recommended_speaking_speed"] = curated["recommended_speaking_speed"]
    return voice


def merge_voices(api_voices: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Prioriza voces curadas y añade el resto desde la API."""
    merged: dict[str, dict[str, Any]] = {}

    for raw in api_voices:
        voice = normalize_cartesia_voice(raw)
        if voice:
            merged[voice["id"]] = voice

    for curated in CURATED_VOICES:
        entry = dict(curated)
        entry["source"] = "curated"
        api_entry = merged.get(entry["id"])
        if api_entry:
            entry["name"] = api_entry.get("name") or entry["name"]
            if api_entry.get("gender"):
                entry["gender"] = api_entry["gender"]
        merged[entry["id"]] = entry

    voices = list(merged.values())
    voices.sort(key=lambda v: (v.get("group", ""), v.get("label", "")))
    return voices


async def _fetch_cartesia_api_voices() -> list[dict[str, Any]]:
    api_key = (os.getenv("CARTESIA_API_KEY") or "").strip()
    if not api_key:
        return []

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                CARTESIA_VOICES_URL,
                headers={
                    "X-API-Key": api_key,
                    "Cartesia-Version": CARTESIA_API_VERSION,
                },
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    logger.warning("🎙️ [voices] Cartesia HTTP %s", resp.status)
                    return []
                payload = await resp.json()
    except Exception as exc:
        logger.warning("🎙️ [voices] Error Cartesia API: %s", exc)
        return []

    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        data = payload.get("data") or payload.get("voices") or []
        return data if isinstance(data, list) else []
    return []


async def _read_cache() -> tuple[list[dict[str, Any]], str] | None:
    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        raw = await redis.get(CACHE_KEY)
        if not raw:
            return None
        voices = json.loads(raw)
        if isinstance(voices, list) and voices:
            return voices, "cache"
    except Exception as exc:
        logger.debug("🎙️ [voices] Sin caché Redis: %s", exc)
    return None


async def _write_cache(voices: list[dict[str, Any]]) -> None:
    try:
        from services.redis_service import get_redis

        redis = await get_redis()
        await redis.setex(CACHE_KEY, CACHE_TTL_SECONDS, json.dumps(voices))
    except Exception as exc:
        logger.debug("🎙️ [voices] No se pudo escribir caché: %s", exc)


def _fallback_voices() -> list[dict[str, Any]]:
    return [dict(v, source="curated") for v in CURATED_VOICES]


def filter_voices_by_language(
    voices: list[dict[str, Any]],
    language: str | None,
) -> list[dict[str, Any]]:
    if not language:
        return voices
    code = language.strip().lower().split("-")[0]
    return [v for v in voices if str(v.get("language", "")).lower().startswith(code)]


async def list_voices(language: str | None = None) -> dict[str, Any]:
    """Devuelve voces Cartesia con caché, API o fallback curado."""
    source = "fallback"
    voices: list[dict[str, Any]] = []

    cached = await _read_cache()
    if cached:
        voices, source = cached
    else:
        api_raw = await asyncio.wait_for(_fetch_cartesia_api_voices(), timeout=5)
        if api_raw:
            voices = merge_voices(api_raw)
            source = "api"
            await _write_cache(voices)
        else:
            voices = _fallback_voices()
            source = "fallback"

    filtered = filter_voices_by_language(voices, language)
    return {
        "voices": filtered or voices,
        "source": source,
        "default_voice_id": settings.default_cartesia_voice_id,
        "count": len(filtered or voices),
    }
