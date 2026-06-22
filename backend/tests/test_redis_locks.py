"""Tests de locks Redis con token de propiedad."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services import redis_service as rs


@pytest.fixture(autouse=True)
def _reset_scripts():
    yield


@pytest.mark.asyncio
async def test_acquire_returns_token_and_release_requires_owner():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=True)
    mock_redis.eval = AsyncMock(return_value=1)

    with patch.object(rs, "get_redis", new=AsyncMock(return_value=mock_redis)):
        token = await rs.acquire_lock("empresa:1", ttl_seconds=60)

    assert token is not None
    mock_redis.set.assert_awaited_once()
    args, kwargs = mock_redis.set.await_args
    assert args[0] == "ausarta:lock:empresa:1"
    assert kwargs["nx"] is True
    assert kwargs["ex"] == 60

    with patch.object(rs, "get_redis", new=AsyncMock(return_value=mock_redis)):
        released = await rs.release_lock("empresa:1", token)

    assert released is True
    mock_redis.eval.assert_awaited()


@pytest.mark.asyncio
async def test_release_with_wrong_token_does_not_delete():
    mock_redis = AsyncMock()
    mock_redis.eval = AsyncMock(return_value=0)

    with patch.object(rs, "get_redis", new=AsyncMock(return_value=mock_redis)):
        released = await rs.release_lock("empresa:1", "wrong-token")

    assert released is False


@pytest.mark.asyncio
async def test_acquire_returns_none_when_busy():
    mock_redis = AsyncMock()
    mock_redis.set = AsyncMock(return_value=None)

    with patch.object(rs, "get_redis", new=AsyncMock(return_value=mock_redis)):
        token = await rs.acquire_lock("campaign:process:9")

    assert token is None


def test_is_orchestrated_campaign_filter():
    from tasks.campaign_orchestrator import _is_orchestrated_campaign

    assert _is_orchestrated_campaign({"type": "orchestrated"}) is True
    assert _is_orchestrated_campaign({"use_orchestrator": True}) is True
    assert _is_orchestrated_campaign({"type": "drip", "use_orchestrator": False}) is False
