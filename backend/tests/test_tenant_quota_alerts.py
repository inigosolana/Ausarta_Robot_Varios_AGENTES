"""Tests de alertas de cuota tenant."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from services.tenant_quota_alerts import (
    maybe_alert_call_quota_threshold,
    maybe_alert_spend_quota_threshold,
)


class _FakeRedis:
    def __init__(self) -> None:
        self.keys: set[str] = set()

    async def set(self, key: str, value: str, *, nx: bool = False, ex: int | None = None) -> bool:
        if nx and key in self.keys:
            return False
        self.keys.add(key)
        return True


@pytest.mark.asyncio
async def test_call_quota_80_alert_once_per_month():
    redis = _FakeRedis()
    enqueue = AsyncMock()
    with patch("services.queue_service.enqueue_telegram_alert", enqueue):
        await maybe_alert_call_quota_threshold(7, consumed=85, max_calls=100, redis=redis)
        await maybe_alert_call_quota_threshold(7, consumed=86, max_calls=100, redis=redis)
    enqueue.assert_awaited_once()
    assert "80%" in enqueue.await_args.args[0]


@pytest.mark.asyncio
async def test_call_quota_100_alert():
    redis = _FakeRedis()
    enqueue = AsyncMock()
    with patch("services.queue_service.enqueue_telegram_alert", enqueue):
        await maybe_alert_call_quota_threshold(3, consumed=100, max_calls=100, redis=redis)
    assert "100%" in enqueue.await_args.args[0]


@pytest.mark.asyncio
async def test_spend_quota_skips_below_threshold():
    redis = _FakeRedis()
    enqueue = AsyncMock()
    with patch("services.queue_service.enqueue_telegram_alert", enqueue):
        await maybe_alert_spend_quota_threshold(1, spent_eur=10.0, limit_eur=100.0, redis=redis)
    enqueue.assert_not_awaited()


@pytest.mark.asyncio
async def test_spend_quota_80_alert():
    redis = _FakeRedis()
    enqueue = AsyncMock()
    with patch("services.queue_service.enqueue_telegram_alert", enqueue):
        await maybe_alert_spend_quota_threshold(1, spent_eur=85.0, limit_eur=100.0, redis=redis)
    assert "80%" in enqueue.await_args.args[0]
