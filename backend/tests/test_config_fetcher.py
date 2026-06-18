"""Tests unitarios para agents.config_fetcher."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents import config_fetcher


class _FakeHttpResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status = status
        self._body = body or {}

    async def json(self) -> dict[str, Any]:
        return self._body

    async def __aenter__(self) -> "_FakeHttpResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


class _FakeHttpSession:
    def __init__(self, responses: list[_FakeHttpResponse]) -> None:
        self._responses = responses
        self.call_count = 0

    def get(self, *_args: object, **_kwargs: object) -> _FakeHttpResponse:
        idx = min(self.call_count, len(self._responses) - 1)
        self.call_count += 1
        return self._responses[idx]

    async def __aenter__(self) -> "_FakeHttpSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None


def _patch_client_session(responses: list[_FakeHttpResponse]) -> MagicMock:
    fake_session = _FakeHttpSession(responses)
    mock_cls = MagicMock(return_value=fake_session)
    return mock_cls


@pytest.mark.asyncio
async def test_fetch_with_retries_success_first_attempt(monkeypatch):
    mock_cls = _patch_client_session([_FakeHttpResponse(200, {"name": "Bot"})])
    monkeypatch.setattr(config_fetcher.aiohttp, "ClientSession", mock_cls)

    result = await config_fetcher._fetch_with_retries("http://example/config")

    assert result == {"name": "Bot"}
    assert mock_cls.return_value.call_count == 1


@pytest.mark.asyncio
async def test_fetch_with_retries_retries_then_succeeds(monkeypatch):
    mock_cls = _patch_client_session([
        _FakeHttpResponse(503),
        _FakeHttpResponse(503),
        _FakeHttpResponse(200, {"name": "Bot"}),
    ])
    monkeypatch.setattr(config_fetcher.aiohttp, "ClientSession", mock_cls)
    sleep_mock = AsyncMock()
    monkeypatch.setattr(config_fetcher.asyncio, "sleep", sleep_mock)

    result = await config_fetcher._fetch_with_retries("http://example/config")

    assert result == {"name": "Bot"}
    assert mock_cls.return_value.call_count == 3
    assert sleep_mock.await_count == 2
    sleep_mock.assert_any_await(0.25)
    sleep_mock.assert_any_await(0.5)


@pytest.mark.asyncio
async def test_fetch_with_retries_returns_none_after_max_attempts(monkeypatch):
    mock_cls = _patch_client_session([_FakeHttpResponse(500)] * 3)
    monkeypatch.setattr(config_fetcher.aiohttp, "ClientSession", mock_cls)
    monkeypatch.setattr(config_fetcher.asyncio, "sleep", AsyncMock())

    result = await config_fetcher._fetch_with_retries("http://example/config")

    assert result is None
    assert mock_cls.return_value.call_count == 3


@pytest.mark.asyncio
async def test_fetch_with_retries_reraises_security_violation(monkeypatch):
    class _ExplodingSession:
        def get(self, *_args: object, **_kwargs: object) -> None:
            raise RuntimeError("Violación de seguridad Multi-Tenant")

        async def __aenter__(self) -> "_ExplodingSession":
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    monkeypatch.setattr(config_fetcher.aiohttp, "ClientSession", lambda: _ExplodingSession())

    with pytest.raises(RuntimeError, match="Violación de seguridad"):
        await config_fetcher._fetch_with_retries("http://example/config")


@pytest.mark.asyncio
async def test_fetch_agent_config_returns_cached_config(monkeypatch):
    cached = {"name": "Cached", "empresa_id": "1"}
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=json.dumps(cached))
    monkeypatch.setattr(config_fetcher, "get_redis", AsyncMock(return_value=redis_mock))

    result = await config_fetcher.fetch_agent_config("42", expected_empresa_id="1")

    assert result == cached
    redis_mock.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_agent_config_http_fallback_and_cache(monkeypatch):
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    redis_mock.set = AsyncMock()
    monkeypatch.setattr(config_fetcher, "get_redis", AsyncMock(return_value=redis_mock))

    http_config = {"name": "HTTP Bot", "empresa_id": "2", "llm_model": "gpt-4o-mini"}
    fetch_mock = AsyncMock(return_value=http_config)
    monkeypatch.setattr(config_fetcher, "_fetch_with_retries", fetch_mock)
    cache_mock = AsyncMock()
    monkeypatch.setattr(config_fetcher, "_cache_agent_config", cache_mock)

    result = await config_fetcher.fetch_agent_config("99", expected_empresa_id="2")

    assert result == http_config
    fetch_mock.assert_awaited_once()
    cache_mock.assert_awaited_once()


@pytest.mark.asyncio
async def test_fetch_agent_config_returns_empty_dict_when_http_fails(monkeypatch):
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(side_effect=RuntimeError("redis down"))
    monkeypatch.setattr(config_fetcher, "get_redis", AsyncMock(return_value=redis_mock))
    monkeypatch.setattr(config_fetcher, "_fetch_with_retries", AsyncMock(return_value=None))

    result = await config_fetcher.fetch_agent_config("99")

    assert result == {}


@pytest.mark.asyncio
async def test_fetch_agent_config_by_agent_id_raises_after_retries(monkeypatch):
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    monkeypatch.setattr(config_fetcher, "get_redis", AsyncMock(return_value=redis_mock))
    monkeypatch.setattr(config_fetcher, "_fetch_with_retries", AsyncMock(return_value=None))

    with pytest.raises(RuntimeError, match="agent_id=7"):
        await config_fetcher.fetch_agent_config_by_agent_id("7", expected_empresa_id="1")


@pytest.mark.asyncio
async def test_fetch_agent_config_by_agent_id_caches_http_result(monkeypatch):
    redis_mock = AsyncMock()
    redis_mock.get = AsyncMock(return_value=None)
    monkeypatch.setattr(config_fetcher, "get_redis", AsyncMock(return_value=redis_mock))

    http_config = {"name": "Inbound", "empresa_id": "3", "id": 5}
    monkeypatch.setattr(config_fetcher, "_fetch_with_retries", AsyncMock(return_value=http_config))
    cache_mock = AsyncMock()
    monkeypatch.setattr(config_fetcher, "_cache_agent_config", cache_mock)

    result = await config_fetcher.fetch_agent_config_by_agent_id("5", expected_empresa_id="3")

    assert result == http_config
    cache_mock.assert_awaited_once()
