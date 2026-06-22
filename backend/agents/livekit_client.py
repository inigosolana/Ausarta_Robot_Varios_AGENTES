"""Cliente LiveKit reutilizable en el worker de agentes (evita leaks por instancia)."""
from __future__ import annotations

import logging
import os

from livekit import api as lk_api

logger = logging.getLogger("agent-dynamic")

_client: lk_api.LiveKitAPI | None = None


async def get_livekit_admin_api() -> lk_api.LiveKitAPI:
    global _client
    if _client is None:
        url = (os.getenv("LIVEKIT_URL") or "").strip()
        api_key = (os.getenv("LIVEKIT_API_KEY") or "").strip()
        api_secret = (os.getenv("LIVEKIT_API_SECRET") or "").strip()
        if not url or not api_key or not api_secret:
            raise RuntimeError("Credenciales LiveKit no configuradas en el worker")
        _client = lk_api.LiveKitAPI(url, api_key, api_secret)
    return _client


async def close_livekit_admin_api() -> None:
    global _client
    if _client is None:
        return
    try:
        await _client.aclose()
    except Exception as exc:
        logger.debug("[LiveKit] Error cerrando cliente admin del worker: %s", exc)
    finally:
        _client = None


async def remove_room_participant(room_name: str, identity: str) -> None:
    lk = await get_livekit_admin_api()
    await lk.room.remove_participant(
        lk_api.RoomParticipantIdentity(room=room_name, identity=identity)
    )
