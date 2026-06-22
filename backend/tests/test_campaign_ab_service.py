"""Tests A/B testing de campañas."""

from __future__ import annotations

import pytest

from services.campaign_ab_service import (
    assign_ab_variant,
    is_ab_test_active,
    pick_ab_variant,
    validate_ab_campaign_payload,
)


def test_pick_ab_variant_is_deterministic():
    v1 = pick_ab_variant(lead_id=42, campaign_id=7, split_ratio=0.5)
    v2 = pick_ab_variant(lead_id=42, campaign_id=7, split_ratio=0.5)
    assert v1 == v2


def test_pick_ab_variant_respects_split_ratio():
    total = 1000
    a_count = sum(
        1
        for lead_id in range(total)
        if pick_ab_variant(lead_id=lead_id, campaign_id=99, split_ratio=0.5) == "A"
    )
    assert 400 <= a_count <= 600


def test_is_ab_test_active_requires_two_distinct_agents():
    assert not is_ab_test_active({"ab_test_enabled": True, "agent_id": 1})
    assert not is_ab_test_active({"ab_test_enabled": True, "agent_id": 1, "agent_id_b": 1})
    assert is_ab_test_active({"ab_test_enabled": True, "agent_id": 1, "agent_id_b": 2})


def test_assign_ab_variant_disabled_uses_agent_a():
    assignment = assign_ab_variant({"id": 1, "agent_id": 10, "ab_test_enabled": False}, lead_id=5)
    assert assignment.variant == "A"
    assert assignment.agent_id == 10
    assert assignment.ab_test_enabled is False


def test_assign_ab_variant_enabled_maps_b_to_agent_b():
    campaign = {
        "id": 3,
        "agent_id": 10,
        "agent_id_b": 20,
        "ab_test_enabled": True,
        "ab_split_ratio": 0.0,
    }
    assignment = assign_ab_variant(campaign, lead_id=1)
    assert assignment.variant == "B"
    assert assignment.agent_id == 20
    assert assignment.ab_test_enabled is True


def test_validate_ab_campaign_payload():
    assert validate_ab_campaign_payload({"ab_test_enabled": False}) is None
    assert validate_ab_campaign_payload({"ab_test_enabled": True}) is not None
    assert (
        validate_ab_campaign_payload(
            {"ab_test_enabled": True, "agent_id": 1, "agent_id_b": 2}
        )
        is None
    )


@pytest.mark.asyncio
async def test_resolve_campaign_dispatch_agent(monkeypatch):
    from services import campaign_dispatch_service

    async def _fake_resolve(**_kwargs):
        return {
            "agent_id": _kwargs.get("campaign_agent_id", 1),
            "agent_type": "ENCUESTA_NUMERICA",
            "agent_name": "Bot",
            "voice_id": None,
        }

    monkeypatch.setattr(campaign_dispatch_service, "resolve_outbound_agent", _fake_resolve)

    campaign = {
        "id": 1,
        "empresa_id": 5,
        "agent_id": 10,
        "agent_id_b": 20,
        "ab_test_enabled": True,
        "ab_split_ratio": 0.0,
    }
    result = await campaign_dispatch_service.resolve_campaign_dispatch_agent(campaign, lead_id=99)
    assert result["ab_variant"] == "B"
    assert result["agent_id"] == 20
