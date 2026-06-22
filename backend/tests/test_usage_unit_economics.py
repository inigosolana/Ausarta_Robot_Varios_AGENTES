"""Tests de pricing y endpoint unit economics."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.billing_pricing import BillingRates, calculate_usage_cost_breakdown
from services.billing_service import TenantUsageSnapshot


def test_calculate_usage_cost_breakdown():
    usage = TenantUsageSnapshot(
        tenant_id=1,
        period="2026-06",
        llm_prompt_tokens=1_000_000,
        llm_completion_tokens=500_000,
        tts_characters=10_000,
        telephony_seconds=1200,
        llm_by_model={
            "llama-3.3-70b": {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
        },
        tts_by_provider={"cartesia": 10_000},
    )
    rates = BillingRates(
        llm_input_eur_per_1m=1.0,
        llm_output_eur_per_1m=2.0,
        tts_eur_per_1k_chars=0.1,
        stt_eur_per_minute=0.5,
        telephony_eur_per_minute=0.2,
    )

    result = calculate_usage_cost_breakdown(usage, rates=rates)

    assert result["llm_eur"] == 2.0  # 1M*1 + 0.5M*2
    assert result["voice_tts_eur"] == 1.0  # 10k chars * 0.1/1k
    assert result["voice_stt_eur"] == 10.0  # 20 min * 0.5
    assert result["voice_eur"] == 11.0
    assert result["telephony_eur"] == 4.0  # 20 min * 0.2
    assert result["total_eur"] == 17.0
    assert len(result["breakdown"]) == 3
    assert result["breakdown"][0]["category"] == "llm"


@pytest.mark.asyncio
async def test_build_unit_economics_response():
    from routers.usage import _build_unit_economics_response

    usage = TenantUsageSnapshot(
        tenant_id=5,
        period="2026-06",
        llm_prompt_tokens=100,
        llm_completion_tokens=50,
        tts_characters=200,
        telephony_seconds=60,
    )
    billing = AsyncMock()
    billing.get_tenant_usage_summary = AsyncMock(return_value=usage)

    with (
        patch("routers.usage.get_billing_service", return_value=billing),
        patch(
            "routers.usage._fetch_call_stats",
            new=AsyncMock(
                return_value={
                    "total_calls": 3,
                    "completed_calls": 2,
                    "total_seconds": 60,
                    "per_model_stats": [],
                }
            ),
        ),
    ):
        payload = await _build_unit_economics_response(5, "2026-06", "2026-06-01", "2026-07-01")

    assert payload["empresa_id"] == 5
    assert payload["usage"]["llm_total_tokens"] == 150
    assert payload["costs_eur"]["total"] >= 0
    assert payload["costs_breakdown"][0]["category"] == "llm"
    assert payload["total_calls"] == 3
    assert payload["estimated_cost_eur"] == payload["costs_eur"]["total"]
