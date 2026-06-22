"""Tests de extracción y registro de métricas de uso para billing."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.call_results_service import (
    CallUsageMetrics,
    extract_call_usage_metrics,
    record_call_usage_billing,
)


def test_extract_call_usage_metrics_from_livekit_summary():
    summary = SimpleNamespace(
        llm_prompt_tokens=150,
        llm_completion_tokens=75,
        tts_characters_count=420,
        stt_audio_duration=33.5,
    )
    metrics = extract_call_usage_metrics(
        summary,
        agent_config={
            "llm_model": "llama-3.3-70b-versatile",
            "tts_provider": "cartesia",
        },
        telephony_seconds=120,
    )

    assert metrics.llm_prompt_tokens == 150
    assert metrics.llm_completion_tokens == 75
    assert metrics.llm_total_tokens == 225
    assert metrics.tts_characters == 420
    assert metrics.tts_provider == "cartesia"
    assert metrics.telephony_seconds == 120
    assert metrics.stt_audio_seconds == 33.5


@pytest.mark.asyncio
async def test_record_call_usage_billing_invokes_billing_service():
    metrics = CallUsageMetrics(
        llm_prompt_tokens=100,
        llm_completion_tokens=50,
        llm_model="llama-3.3-70b-versatile",
        tts_characters=200,
        tts_provider="cartesia",
        telephony_seconds=90,
    )
    billing = MagicMock()
    billing.log_llm_tokens = AsyncMock()
    billing.log_tts_characters = AsyncMock()
    billing.log_telephony_seconds = AsyncMock()

    with (
        patch("services.call_results_service._claim_billing_slot", new=AsyncMock(return_value=True)),
        patch("services.billing_service.get_billing_service", return_value=billing),
    ):
        ok = await record_call_usage_billing(7, metrics, encuesta_id=55)

    assert ok is True
    billing.log_llm_tokens.assert_awaited_once_with(7, 100, 50, "llama-3.3-70b-versatile")
    billing.log_tts_characters.assert_awaited_once_with(7, 200, "cartesia")
    billing.log_telephony_seconds.assert_awaited_once_with(7, 90)


@pytest.mark.asyncio
async def test_record_call_usage_billing_skips_duplicate_encuesta():
    metrics = CallUsageMetrics(
        llm_prompt_tokens=0,
        llm_completion_tokens=0,
        llm_model="model",
        tts_characters=0,
        tts_provider="cartesia",
        telephony_seconds=30,
    )

    with patch(
        "services.call_results_service._claim_billing_slot",
        new=AsyncMock(return_value=False),
    ):
        ok = await record_call_usage_billing(7, metrics, encuesta_id=99)

    assert ok is False


@pytest.mark.asyncio
async def test_record_call_usage_billing_skips_zero_tenant():
    metrics = CallUsageMetrics(
        llm_prompt_tokens=10,
        llm_completion_tokens=5,
        llm_model="model",
        tts_characters=1,
        tts_provider="cartesia",
        telephony_seconds=1,
    )
    ok = await record_call_usage_billing(0, metrics, encuesta_id=1)
    assert ok is False
