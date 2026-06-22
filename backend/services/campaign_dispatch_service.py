"""Helpers async para dispatch de campaña con A/B testing."""

from __future__ import annotations

from typing import Any

from services.agent_router import resolve_outbound_agent
from services.campaign_ab_service import AbAssignment, assign_ab_variant


async def resolve_campaign_dispatch_agent(
    campaign: dict[str, Any],
    lead_id: int,
) -> dict[str, Any]:
    """
    Combina asignación A/B con resolve_outbound_agent.
    Retorna agent_id, agent_type, agent_name, voice_id, ab_variant, ab_test_enabled.
    """
    assignment: AbAssignment = assign_ab_variant(campaign, lead_id)
    resolved = await resolve_outbound_agent(
        empresa_id=int(campaign.get("empresa_id") or 0) or None,
        campaign_agent_id=assignment.agent_id,
        agent_type=campaign.get("agent_type"),
        call_purpose=campaign.get("call_purpose"),
    )
    return {
        **resolved,
        "ab_variant": assignment.variant,
        "ab_test_enabled": assignment.ab_test_enabled,
    }
