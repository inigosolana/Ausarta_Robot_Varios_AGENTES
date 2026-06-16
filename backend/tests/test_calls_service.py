import pytest

from services.calls_service import _parse_room_name, _call_direction_from_extra


def test_parse_room_name():
    meta = _parse_room_name(
        "llamada_ausarta_empresa_7_campana_12_contacto_99_encuesta_1842"
    )
    assert meta["empresa_id"] == 7
    assert meta["campaign_id"] == 12
    assert meta["encuesta_id"] == 1842


def test_call_direction_from_extra():
    assert _call_direction_from_extra({"call_direction": "inbound"}) == "inbound"
    assert _call_direction_from_extra({}) is None
