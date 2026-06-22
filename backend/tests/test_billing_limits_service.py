"""Tests del cortafuego financiero (límite de gasto mensual)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

from services.billing_limits_service import (
    TenantSpendStatus,
    enforce_tenant_spending_limit,
    evaluate_tenant_spending,
)
from services.billing_service import TenantUsageSnapshot


@pytest.mark.asyncio
async def test_evaluate_tenant_spending_unlimited_when_no_limit_configured():
    usage = TenantUsageSnapshot(
        tenant_id=3,
        period="2026-06",
        llm_prompt_tokens=1000,
        llm_completion_tokens=500,
        telephony_seconds=60,
    )

    with (
        patch(
            "services.billing_limits_service._load_monthly_spend_limit",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "services.billing_limits_service.get_billing_service",
        ) as mock_get_billing,
    ):
        mock_get_billing.return_value.get_tenant_usage_summary = AsyncMock(return_value=usage)
        status = await evaluate_tenant_spending(3, period="2026-06")

    assert status.limit_exceeded is False
    assert status.limit_eur is None
    assert status.spent_eur >= 0


@pytest.mark.asyncio
async def test_enforce_tenant_spending_limit_raises_402():
    usage = TenantUsageSnapshot(
        tenant_id=5,
        period="2026-06",
        llm_prompt_tokens=10_000_000,
        llm_completion_tokens=5_000_000,
        telephony_seconds=3600,
    )

    with (
        patch(
            "services.billing_limits_service._load_monthly_spend_limit",
            new=AsyncMock(return_value=10.0),
        ),
        patch(
            "services.billing_limits_service.get_billing_service",
        ) as mock_get_billing,
        patch("services.billing_limits_service._SPEND_LIMITS_ENABLED", True),
    ):
        mock_get_billing.return_value.get_tenant_usage_summary = AsyncMock(return_value=usage)

        with pytest.raises(HTTPException) as exc_info:
            await enforce_tenant_spending_limit(5, period="2026-06", raise_http=True)

    assert exc_info.value.status_code == 402
    detail = exc_info.value.detail
    assert detail["limit_exceeded"] is True
    assert detail["limit_eur"] == 10.0


@pytest.mark.asyncio
async def test_enforce_tenant_spending_limit_allows_under_cap():
    usage = TenantUsageSnapshot(tenant_id=2, period="2026-06", telephony_seconds=30)

    with (
        patch(
            "services.billing_limits_service._load_monthly_spend_limit",
            new=AsyncMock(return_value=100.0),
        ),
        patch(
            "services.billing_limits_service.get_billing_service",
        ) as mock_get_billing,
        patch("services.billing_limits_service._SPEND_LIMITS_ENABLED", True),
    ):
        mock_get_billing.return_value.get_tenant_usage_summary = AsyncMock(return_value=usage)
        status = await enforce_tenant_spending_limit(2, period="2026-06", raise_http=True)

    assert isinstance(status, TenantSpendStatus)
    assert status.limit_exceeded is False
