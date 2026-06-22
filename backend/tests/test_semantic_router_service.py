"""Tests del router semántico (Tier 0 regex + Tier 1 Groq mock)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from agents.semantic_routes import resolve_semantic_routing_config
from config import clear_settings_cache
from services.semantic_router_service import SemanticRouterService, _match_tier0


@pytest.fixture(autouse=True)
def _reset_settings_cache():
    clear_settings_cache()
    yield
    clear_settings_cache()


def test_tier0_matches_explicit_transfer_phrases():
    assert _match_tier0("Hola, quiero hablar con un humano por favor")
    assert _match_tier0("Pásame con un agente real")
    assert _match_tier0("I need to talk to a human please")


def test_tier0_rejects_negative_cues():
    assert not _match_tier0("No quiero hablar con un humano, sigue tú")
    assert not _match_tier0("No me pases con nadie")


def test_tier0_custom_phrase():
    assert _match_tier0("necesito el departamento comercial", extra_phrases=("departamento comercial",))


@pytest.mark.asyncio
async def test_classify_tier0_without_groq():
    router = SemanticRouterService(tier0_only=True)
    result = await router.classify("Quiero hablar con una persona")
    assert result.intent == "transfer_human"
    assert result.tier == "tier0"
    assert result.confidence == 1.0
    assert router.is_actionable(result)


@pytest.mark.asyncio
async def test_classify_continue_on_empty():
    router = SemanticRouterService(tier0_only=True)
    result = await router.classify("   ")
    assert result.intent == "continue"
    assert result.tier == "fallback"


@pytest.mark.asyncio
async def test_classify_tier1_groq_transfer():
    async def _fake_groq(_text: str):
        from services.semantic_router_service import SemanticRouteResult

        return SemanticRouteResult(
            intent="transfer_human",
            confidence=0.95,
            tier="tier1",
            latency_ms=0.0,
        )

    with patch("services.semantic_router_service.os.getenv", return_value="test-key"):
        router = SemanticRouterService(tier0_only=False)
        with patch.object(router, "_classify_with_groq", side_effect=_fake_groq):
            result = await router.classify("me gustaría que me atienda alguien del equipo")

    assert result.intent == "transfer_human"
    assert result.tier == "tier1"
    assert router.is_actionable(result)


@pytest.mark.asyncio
async def test_classify_tier1_timeout_falls_back_to_continue():
    router = SemanticRouterService(tier0_only=False, timeout_ms=50)

    with patch("services.semantic_router_service.os.getenv", return_value="test-key"), patch(
        "services.semantic_router_service.aiohttp.ClientSession",
        side_effect=TimeoutError("timeout"),
    ):
        result = await router.classify("texto ambiguo sin match regex")

    assert result.intent == "continue"
    assert result.tier == "fallback"


def test_resolve_semantic_routing_config_from_datos_extra():
    enabled, phrases = resolve_semantic_routing_config(
        {
            "datos_extra": {
                "semantic_routing_enabled": False,
                "human_transfer_phrases": ["soporte nivel 2"],
            }
        }
    )
    assert enabled is False
    assert phrases == ("soporte nivel 2",)
