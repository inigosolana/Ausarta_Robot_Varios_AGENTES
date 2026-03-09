import os
import json
import logging
from dotenv import load_dotenv
from livekit import api

load_dotenv()

LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')
DEFAULT_AGENT_NAME = os.getenv("AGENT_NAME_DISPATCH", "ausarta_agent")

logger = logging.getLogger("api-backend")

class LazyLiveKitAPI:
    def __init__(self, url, api_key, api_secret):
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            if self._url and self._api_key and self._api_secret:
                import asyncio
                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                self._instance = api.LiveKitAPI(self._url, self._api_key, self._api_secret)
            else:
                print("⚠️ WARNING: LiveKit credentials missing.")
                self._instance = None
        return self._instance

    def __getattr__(self, item):
        inst = self._get_instance()
        if inst is None:
            raise AttributeError(f"LiveKitAPI not initialized (missing config), cannot get '{item}'")
        return getattr(inst, item)

lkapi = LazyLiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)


async def create_isolated_room(room_name: str, metadata: dict | None = None):
    """
    Crea sala LiveKit con aislamiento estricto:
    - max_participants=2 (SIP + 1 agente)
    - metadata JSON serializada para trazabilidad de campaña/contacto
    """
    meta_str = json.dumps(metadata or {}, ensure_ascii=True)
    req = api.CreateRoomRequest(
        name=room_name,
        max_participants=2,
        metadata=meta_str,
    )
    return await lkapi.room.create_room(req)


async def dispatch_agent_explicit(room_name: str, metadata: dict | None = None, agent_name: str | None = None):
    """
    Dispatch explícito del agente. Evita colisiones con workers no deseados.
    """
    meta_str = json.dumps(metadata or {}, ensure_ascii=True)
    req = api.CreateAgentDispatchRequest(
        room=room_name,
        agent_name=agent_name or DEFAULT_AGENT_NAME,
        metadata=meta_str,
    )
    return await lkapi.agent_dispatch.create_dispatch(req)
