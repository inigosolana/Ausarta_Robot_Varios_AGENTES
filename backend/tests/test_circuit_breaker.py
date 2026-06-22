"""Tests del Circuit Breaker distribuido."""

from __future__ import annotations

import asyncio

import pytest

from utils.circuit_breaker import (
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitState,
)


@pytest.fixture(autouse=True)
def _reset_breakers():
    CircuitBreaker.reset_memory_store()
    yield
    CircuitBreaker.reset_memory_store()


@pytest.fixture
def memory_breaker() -> CircuitBreaker:
    config = CircuitBreakerConfig(
        failure_threshold=3,
        open_seconds=300,
        extreme_timeout_seconds=1.0,
        use_redis=False,
    )
    return CircuitBreaker("test:provider", config=config)


@pytest.mark.asyncio
async def test_circuit_opens_after_three_failures(memory_breaker: CircuitBreaker):
    for _ in range(3):
        await memory_breaker.record_failure(RuntimeError("boom"))

    assert await memory_breaker.is_open() is True
    status = await memory_breaker.status()
    assert status.state == CircuitState.OPEN
    assert status.failures >= 3


@pytest.mark.asyncio
async def test_circuit_opens_immediately_on_extreme_timeout(memory_breaker: CircuitBreaker):
    await memory_breaker.record_failure(asyncio.TimeoutError(), extreme=True)

    assert await memory_breaker.is_open() is True


@pytest.mark.asyncio
async def test_record_success_closes_circuit(memory_breaker: CircuitBreaker):
    await memory_breaker.record_failure(RuntimeError("x"))
    await memory_breaker.record_failure(RuntimeError("y"))
    await memory_breaker.record_success()

    status = await memory_breaker.status()
    assert status.state == CircuitState.CLOSED
    assert status.failures == 0
    assert await memory_breaker.is_open() is False


@pytest.mark.asyncio
async def test_execute_with_fallback_uses_primary_when_closed(memory_breaker: CircuitBreaker):
    calls: list[str] = []

    async def primary():
        calls.append("primary")
        return "ok"

    async def fallback():
        calls.append("fallback")
        return "fb"

    result = await memory_breaker.execute_with_fallback(primary, fallback, timeout=2.0)

    assert result == "ok"
    assert calls == ["primary"]


@pytest.mark.asyncio
async def test_execute_with_fallback_skips_primary_when_open(memory_breaker: CircuitBreaker):
    for _ in range(3):
        await memory_breaker.record_failure(RuntimeError("fail"))

    calls: list[str] = []

    async def primary():
        calls.append("primary")
        return "ok"

    async def fallback():
        calls.append("fallback")
        return "fb"

    result = await memory_breaker.execute_with_fallback(primary, fallback)

    assert result == "fb"
    assert calls == ["fallback"]


@pytest.mark.asyncio
async def test_execute_with_fallback_opens_on_timeout(memory_breaker: CircuitBreaker):
    async def slow_primary():
        await asyncio.sleep(2.0)
        return "late"

    async def fallback():
        return "fb"

    result = await memory_breaker.execute_with_fallback(
        slow_primary,
        fallback,
        timeout=0.05,
    )

    assert result == "fb"
    assert await memory_breaker.is_open() is True


@pytest.mark.asyncio
async def test_half_open_after_open_duration():
    config = CircuitBreakerConfig(
        failure_threshold=3,
        open_seconds=0,
        extreme_timeout_seconds=1.0,
        use_redis=False,
    )
    breaker = CircuitBreaker("test:half-open", config=config)

    for _ in range(3):
        await breaker.record_failure(RuntimeError("fail"))

    assert await breaker.is_open() is False
    status = await breaker.status()
    assert status.state == CircuitState.HALF_OPEN


@pytest.mark.asyncio
async def test_half_open_failure_reopens_circuit():
    config = CircuitBreakerConfig(
        failure_threshold=3,
        open_seconds=0,
        extreme_timeout_seconds=1.0,
        use_redis=False,
    )
    breaker = CircuitBreaker("test:half-open-reopen", config=config)

    for _ in range(3):
        await breaker.record_failure(RuntimeError("fail"))
    await breaker.is_open()  # → half_open

    await breaker.record_failure(RuntimeError("probe failed"))

    status = await breaker.status()
    assert status.state == CircuitState.OPEN
