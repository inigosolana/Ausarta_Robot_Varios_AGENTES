import os
import json
import logging
from dotenv import load_dotenv
from livekit import api

load_dotenv()

LIVEKIT_URL = os.getenv('LIVEKIT_URL')
LIVEKIT_API_KEY = os.getenv('LIVEKIT_API_KEY')
LIVEKIT_API_SECRET = os.getenv('LIVEKIT_API_SECRET')
DEFAULT_AGENT_NAME = (os.getenv("AGENT_NAME_DISPATCH") or "default_agent").strip() or "default_agent"

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


async def create_outbound_call(
    number_to_dial: str,
    trunk_id: str,
    room_name: str,
    empresa_id: str,
    survey_id: str,
):
    """
    Inicia una llamada SIP saliente: crea un participante SIP en la sala indicada.
    """
    req = api.CreateSIPParticipantRequest(
        sip_trunk_id=trunk_id,
        sip_call_to=number_to_dial,
        room_name=room_name,
        participant_identity=f"user_{number_to_dial}_{survey_id}",
        participant_name="Cliente",
    )
    logger.info(
        "☎️ Outbound SIP: %s → room=%s (empresa=%s, survey=%s)",
        number_to_dial,
        room_name,
        empresa_id,
        survey_id,
    )
    return await lkapi.sip.create_sip_participant(req)


async def wait_for_agent_ready(room_name: str, timeout: float = 15.0) -> bool:
    """
    FIX 1 — Race condition agente vs participante SIP.

    Problema: un sleep fijo de 3 s no garantiza que el agente esté en sala cuando
    Silero VAD o un cold start de CPU retrasan el worker más de ese tiempo.

    Solución: polling real sobre list_participants cada 500 ms hasta detectar al
    menos 1 participante no-SIP (el agente), o hasta agotar el timeout.
    Retorna True si el agente está listo, False si se agotó el tiempo.
    """
    import asyncio as _asyncio
    loop = _asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        try:
            res = await lkapi.room.list_participants(
                api.ListParticipantsRequest(room=room_name)
            )
            participants = getattr(res, "participants", []) or []
            # Participantes no-SIP = el agente (SIP tiene identity user_* o sip_*)
            non_sip = [
                p for p in participants
                if not (getattr(p, "identity", "") or "").startswith(("sip_", "user_"))
            ]
            if non_sip:
                logger.info(
                    "✅ wait_for_agent_ready: agente listo en sala %s (%d participante(s))",
                    room_name, len(non_sip),
                )
                return True
        except Exception as poll_err:
            logger.debug("wait_for_agent_ready poll error room=%s: %s", room_name, poll_err)
        await _asyncio.sleep(0.5)
    logger.error(
        "⏰ wait_for_agent_ready: timeout (%.0fs) alcanzado sin detectar agente en sala %s",
        timeout, room_name,
    )
    return False
