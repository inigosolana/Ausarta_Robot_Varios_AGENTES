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


def _livekit_safe_name(value: str) -> str:
    """Normaliza nombres visibles para recursos SIP de LiveKit."""
    import re

    cleaned = re.sub(r"[^A-Za-z0-9]+", "_", str(value or "").strip()).strip("_")
    return cleaned.upper()[:40] or "EMPRESA"

class LazyLiveKitAPI:
    def __init__(self, url, api_key, api_secret):
        self._url = url
        self._api_key = api_key
        self._api_secret = api_secret
        self._instance = None

    def _get_instance(self):
        if self._instance is None:
            if self._url and self._api_key and self._api_secret:
                self._instance = api.LiveKitAPI(self._url, self._api_key, self._api_secret)
            else:
                print("⚠️ WARNING: LiveKit credentials missing.")
                self._instance = None
        return self._instance

    async def aclose(self) -> None:
        inst = self._instance
        if inst is None:
            return
        closer = getattr(inst, "aclose", None)
        if callable(closer):
            try:
                await closer()
            except Exception as exc:
                logger.debug("LiveKitAPI aclose: %s", exc)
        self._instance = None

    def __getattr__(self, item):
        inst = self._get_instance()
        if inst is None:
            raise AttributeError(f"LiveKitAPI not initialized (missing config), cannot get '{item}'")
        return getattr(inst, item)


lkapi = LazyLiveKitAPI(LIVEKIT_URL, LIVEKIT_API_KEY, LIVEKIT_API_SECRET)


async def close_livekit_api() -> None:
    """Cierra el cliente HTTP singleton del backend API."""
    await lkapi.aclose()


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
    from services.sip_call_service import create_sip_participant_with_retry

    emp_int: int | None = None
    try:
        emp_int = int(empresa_id)
    except (TypeError, ValueError):
        emp_int = None

    return await create_sip_participant_with_retry(
        req,
        empresa_id=emp_int,
        phone=number_to_dial,
        source="livekit_service",
    )


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


def _livekit_sip_trunk_to_dict(trunk, direction: str) -> dict:
    """Normaliza una troncal SIP de LiveKit para consumo del frontend."""
    return {
        "provider": "livekit",
        "direction": direction,
        "id": getattr(trunk, "sip_trunk_id", ""),
        "name": getattr(trunk, "name", "") or getattr(trunk, "sip_trunk_id", ""),
        "phone_numbers": list(getattr(trunk, "numbers", []) or []),
        "status": "available",
        "address": getattr(trunk, "address", None),
        "allowed_addresses": list(getattr(trunk, "allowed_addresses", []) or []),
        "allowed_numbers": list(getattr(trunk, "allowed_numbers", []) or []),
        "metadata": getattr(trunk, "metadata", "") or "",
    }


async def list_sip_trunks() -> list[dict]:
    """
    Lista las troncales SIP inbound/outbound configuradas en LiveKit.
    """
    inbound_response = await lkapi.sip.list_sip_inbound_trunk(
        api.ListSIPInboundTrunkRequest()
    )
    outbound_response = await lkapi.sip.list_sip_outbound_trunk(
        api.ListSIPOutboundTrunkRequest()
    )

    inbound = [
        _livekit_sip_trunk_to_dict(item, "inbound")
        for item in (getattr(inbound_response, "items", []) or [])
    ]
    outbound = [
        _livekit_sip_trunk_to_dict(item, "outbound")
        for item in (getattr(outbound_response, "items", []) or [])
    ]
    return inbound + outbound


async def ensure_yeastar_inbound_trunk(
    *,
    empresa_id: int,
    empresa_nombre: str,
    allowed_addresses: list[str],
    numbers: list[str],
    inbound_agent_id: int | None = None,
) -> dict:
    """Crea/reutiliza inbound LiveKit y su regla de despacho al agente."""
    clean_addresses = sorted({
        str(address).strip().split(":", 1)[0]
        for address in allowed_addresses
        if str(address).strip()
    })
    clean_numbers = sorted({str(number).strip() for number in numbers if str(number).strip()})
    expanded_numbers: set[str] = set(clean_numbers)
    for number in clean_numbers:
        if number.startswith("+") and len(number) > 1:
            expanded_numbers.add(number[1:])
        elif number.isdigit() and len(number) >= 9:
            expanded_numbers.add(f"+{number}")
    clean_numbers = sorted(expanded_numbers)
    if not clean_addresses:
        raise ValueError("La troncal Yeastar no proporciona una IP/host permitido")
    if not clean_numbers:
        raise ValueError("La troncal Yeastar no proporciona ningun DDI")

    empresa_slug = _livekit_safe_name(empresa_nombre)
    trunk_name = f"YEASTAR_INBOUND_{empresa_slug}_ID_{empresa_id}"
    legacy_trunk_name = f"YEASTAR_INBOUND_{empresa_id}"
    metadata = json.dumps(
        {
            "provider": "yeastar",
            "empresa_id": empresa_id,
            "empresa_nombre": empresa_nombre,
            "inbound_agent_id": inbound_agent_id,
        },
        ensure_ascii=True,
    )
    inbound_room_metadata = json.dumps(
        {
            "call_direction": "inbound",
            "empresa_id": empresa_id,
            "agent_id": inbound_agent_id,
            "campana_id": 0,
            "client_id": 0,
            "survey_id": f"inbound_{empresa_id}",
        },
        ensure_ascii=True,
    )

    response = await lkapi.sip.list_sip_inbound_trunk(api.ListSIPInboundTrunkRequest())
    existing = next(
        (
            item
            for item in (getattr(response, "items", []) or [])
            if getattr(item, "name", "") in {trunk_name, legacy_trunk_name}
        ),
        None,
    )
    if existing:
        # Merge existing IPs with new ones so manually-added SIP proxy IPs are preserved
        existing_addresses = sorted({
            str(a).strip().split(":", 1)[0]
            for a in (getattr(existing, "allowed_addresses", []) or [])
            if str(a).strip()
        })
        merged_addresses = sorted(set(clean_addresses) | set(existing_addresses))
        trunk = await lkapi.sip.update_sip_inbound_trunk(
            existing.sip_trunk_id,
            api.SIPInboundTrunkInfo(
                name=trunk_name,
                metadata=metadata,
                numbers=clean_numbers,
                allowed_addresses=merged_addresses,
            ),
        )
        created = False
    else:
        trunk = await lkapi.sip.create_sip_inbound_trunk(
            api.CreateSIPInboundTrunkRequest(
                trunk=api.SIPInboundTrunkInfo(
                    name=trunk_name,
                    metadata=metadata,
                    numbers=clean_numbers,
                    allowed_addresses=clean_addresses,
                )
            )
        )
        created = True

    trunk_id = getattr(trunk, "sip_trunk_id", "")
    rules = await lkapi.sip.list_sip_dispatch_rule(api.ListSIPDispatchRuleRequest())
    rule_name = f"YEASTAR_DISPATCH_{empresa_slug}_ID_{empresa_id}"
    legacy_rule_name = f"YEASTAR_DISPATCH_{empresa_id}"
    dispatch_rule = next(
        (
            item
            for item in (getattr(rules, "items", []) or [])
            if getattr(item, "name", "") in {rule_name, legacy_rule_name}
        ),
        None,
    )
    if dispatch_rule:
        await lkapi.sip.delete_sip_dispatch_rule(
            api.DeleteSIPDispatchRuleRequest(
                sip_dispatch_rule_id=dispatch_rule.sip_dispatch_rule_id
            )
        )
    dispatch_rule = await lkapi.sip.create_sip_dispatch_rule(
        api.CreateSIPDispatchRuleRequest(
            dispatch_rule=api.SIPDispatchRuleInfo(
                name=rule_name,
                metadata=metadata,
                trunk_ids=[trunk_id],
                attributes={
                    "call_direction": "inbound",
                    "empresa_id": str(empresa_id),
                    "agent_id": str(inbound_agent_id or ""),
                },
                rule=api.SIPDispatchRule(
                    dispatch_rule_individual=api.SIPDispatchRuleIndividual(
                        room_prefix=f"yeastar_{empresa_id}_"
                    )
                ),
                room_config=api.RoomConfiguration(
                    max_participants=3,
                    metadata=inbound_room_metadata,
                    agents=[
                        api.RoomAgentDispatch(
                            agent_name=DEFAULT_AGENT_NAME,
                            metadata=inbound_room_metadata,
                        )
                    ],
                ),
            )
        )
    )

    return {
        "id": trunk_id,
        "name": getattr(trunk, "name", trunk_name),
        "numbers": list(getattr(trunk, "numbers", []) or clean_numbers),
        "allowed_addresses": list(getattr(trunk, "allowed_addresses", []) or clean_addresses),
        "dispatch_rule_id": getattr(dispatch_rule, "sip_dispatch_rule_id", ""),
        "created": created,
    }


async def ensure_citelia_outbound_trunk(
    *,
    empresa_id: int,
    empresa_nombre: str,
    ddi: str,
) -> dict:
    """
    Crea o reutiliza una troncal saliente CITELIA_SBC para una empresa.

    Plantilla fija:
    - address: 212.63.112.35:38932
    - transport: UDP
    - from_host: 212.63.112.35
    - numbers: [ddi]
    """
    ddi_clean = str(ddi or "").strip()
    if not ddi_clean:
        raise ValueError("DDI obligatorio para crear troncal CITELIA")

    trunk_name = f"CITELIA_SBC_{empresa_id}_{ddi_clean}"
    trunk_address = "212.63.112.35:38932"
    from_host = "212.63.112.35"

    existing = await lkapi.sip.list_outbound_trunk(api.ListSIPOutboundTrunkRequest())
    items = getattr(existing, "items", []) or []
    for item in items:
        existing_name = getattr(item, "name", "") or ""
        existing_address = getattr(item, "address", "") or ""
        existing_numbers = list(getattr(item, "numbers", []) or [])
        if existing_name == trunk_name or (
            existing_address == trunk_address and ddi_clean in existing_numbers
        ):
            return {
                "provider": "livekit",
                "id": getattr(item, "sip_trunk_id", ""),
                "name": existing_name,
                "phone_numbers": existing_numbers,
                "status": "available",
                "address": existing_address,
                "metadata": getattr(item, "metadata", "") or "",
                "created": False,
            }

    metadata = json.dumps(
        {
            "provider_template": "citelia_sbc",
            "empresa_id": empresa_id,
            "empresa_nombre": empresa_nombre,
            "ddi": ddi_clean,
        },
        ensure_ascii=True,
    )

    trunk = api.SIPOutboundTrunkInfo(
        name=trunk_name,
        metadata=metadata,
        address=trunk_address,
        transport=api.SIP_TRANSPORT_UDP,
        numbers=[ddi_clean],
        from_host=from_host,
    )
    created = await lkapi.sip.create_outbound_trunk(
        api.CreateSIPOutboundTrunkRequest(trunk=trunk)
    )
    return {
        "provider": "livekit",
        "id": getattr(created, "sip_trunk_id", ""),
        "name": getattr(created, "name", trunk_name),
        "phone_numbers": list(getattr(created, "numbers", []) or [ddi_clean]),
        "status": "available",
        "address": getattr(created, "address", trunk_address),
        "metadata": getattr(created, "metadata", metadata),
        "created": True,
    }
