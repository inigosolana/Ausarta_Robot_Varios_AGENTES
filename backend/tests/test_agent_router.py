import pytest

from services.agent_router import (
    build_outbound_room_metadata,
    normalize_call_purpose,
    resolve_outbound_agent_sync,
)


def test_normalize_call_purpose_aliases():
    assert normalize_call_purpose("venta") == "CUALIFICACION_LEAD"
    assert normalize_call_purpose("ENCUESTA_MIXTA") == "ENCUESTA_MIXTA"
    assert normalize_call_purpose("unknown_xyz") is None


def test_build_outbound_room_metadata_includes_agent_fields():
    meta = build_outbound_room_metadata(
        empresa_id=7,
        survey_id=42,
        agent_id=3,
        agent_type="CUALIFICACION_LEAD",
        campaign_id=9,
        contacto_id=11,
    )
    assert meta["call_direction"] == "outbound"
    assert meta["agent_id"] == 3
    assert meta["agent_type"] == "CUALIFICACION_LEAD"
    assert meta["survey_id"] == 42
    assert meta["contacto_id"] == 11


def test_resolve_outbound_agent_sync_without_db():
    resolved = resolve_outbound_agent_sync(
        empresa_id=None,
        agent_id="5",
        call_purpose="soporte",
    )
    assert resolved["agent_id"] == 5
    assert resolved["agent_type"] == "SOPORTE_CLIENTE"


@pytest.mark.asyncio
async def test_resolve_outbound_agent_async_timeout_safe(monkeypatch):
    import asyncio
    from services import agent_router

    async def slow_thread(*_args, **_kwargs):
        await asyncio.sleep(10)
        return {}

    monkeypatch.setattr(asyncio, "to_thread", slow_thread)

    resolved = await agent_router.resolve_outbound_agent(empresa_id=1, agent_id=2)
    assert resolved["agent_id"] == 2
    assert resolved["agent_type"] == "ENCUESTA_NUMERICA"
