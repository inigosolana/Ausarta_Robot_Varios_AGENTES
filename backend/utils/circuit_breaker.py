"""
Circuit Breaker distribuido (Redis) con fallback en memoria por proceso.

Estados:
  - closed: tráfico normal al proveedor primario
  - open: fallos consecutivos o timeout extremo → solo fallback durante open_seconds
  - half_open: tras open_seconds, una petición de prueba al primario

Uso:
  breaker = get_circuit_breaker("provider:cartesia:tts")
  result = await breaker.execute_with_fallback(primary_fn, fallback_fn, timeout=8.0)
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Awaitable, Callable, TypeVar

logger = logging.getLogger("circuit-breaker")

T = TypeVar("T")

CIRCUIT_PREFIX = "ausarta:circuit"


class CircuitState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class CircuitBreakerConfig:
    failure_threshold: int = 3
    open_seconds: int = 300
    extreme_timeout_seconds: float = 15.0
    use_redis: bool = True

    @classmethod
    def from_env(cls) -> "CircuitBreakerConfig":
        return cls(
            failure_threshold=int(os.getenv("CIRCUIT_BREAKER_FAILURE_THRESHOLD", "3")),
            open_seconds=int(os.getenv("CIRCUIT_BREAKER_OPEN_SECONDS", "300")),
            extreme_timeout_seconds=float(
                os.getenv("CIRCUIT_BREAKER_EXTREME_TIMEOUT_SECONDS", "15")
            ),
            use_redis=os.getenv("CIRCUIT_BREAKER_USE_REDIS", "true").strip().lower()
            in ("1", "true", "yes"),
        )


@dataclass
class _CircuitSnapshot:
    state: CircuitState = CircuitState.CLOSED
    failures: int = 0
    opened_at: float = 0.0


@dataclass
class CircuitStatus:
    name: str
    state: CircuitState
    failures: int
    opened_at: float
    is_open: bool
    backend: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.failures,
            "opened_at": self.opened_at,
            "is_open": self.is_open,
            "backend": self.backend,
        }


class CircuitBreaker:
    """Circuit breaker async con persistencia Redis y fallback en memoria."""

    _memory_store: dict[str, _CircuitSnapshot] = {}
    _memory_lock = asyncio.Lock()

    def __init__(self, name: str, config: CircuitBreakerConfig | None = None) -> None:
        self.name = name.strip()
        if not self.name:
            raise ValueError("circuit breaker name is required")
        self._config = config or CircuitBreakerConfig.from_env()
        self._redis_key = f"{CIRCUIT_PREFIX}:{self.name}"

    async def is_open(self) -> bool:
        """True si el circuito bloquea el proveedor primario."""
        snap = await self._load_snapshot()
        now = time.time()

        if snap.state == CircuitState.CLOSED:
            return False

        if snap.state == CircuitState.HALF_OPEN:
            return False

        if snap.state == CircuitState.OPEN:
            if snap.opened_at > 0 and (now - snap.opened_at) >= self._config.open_seconds:
                await self._set_state(
                    CircuitState.HALF_OPEN,
                    failures=snap.failures,
                    opened_at=snap.opened_at,
                )
                logger.info("Circuit %s → half_open (probe permitido)", self.name)
                return False
            return True

        return False

    async def status(self) -> CircuitStatus:
        snap = await self._load_snapshot()
        backend = "redis" if self._config.use_redis else "memory"
        try:
            if self._config.use_redis:
                from services.redis_service import get_redis

                await get_redis()
                backend = "redis"
        except Exception:
            backend = "memory"
        return CircuitStatus(
            name=self.name,
            state=snap.state,
            failures=snap.failures,
            opened_at=snap.opened_at,
            is_open=await self.is_open(),
            backend=backend,
        )

    async def record_success(self) -> None:
        await self._set_state(CircuitState.CLOSED, failures=0, opened_at=0.0)

    async def record_failure(self, exc: BaseException | None = None, *, extreme: bool = False) -> None:
        snap = await self._load_snapshot()

        if extreme:
            await self._open_circuit(failures=max(snap.failures, self._config.failure_threshold))
            logger.warning(
                "Circuit %s OPEN (timeout extremo): %s",
                self.name,
                exc,
            )
            return

        if snap.state == CircuitState.HALF_OPEN:
            await self._open_circuit(failures=snap.failures + 1)
            logger.warning("Circuit %s OPEN (fallo en half_open): %s", self.name, exc)
            return

        failures = snap.failures + 1
        if failures >= self._config.failure_threshold:
            await self._open_circuit(failures=failures)
            logger.warning(
                "Circuit %s OPEN (%s fallos consecutivos): %s",
                self.name,
                failures,
                exc,
            )
            return

        await self._set_state(CircuitState.CLOSED, failures=failures, opened_at=snap.opened_at)

    async def execute_with_fallback(
        self,
        primary: Callable[[], Awaitable[T]],
        fallback: Callable[[], Awaitable[T]],
        *,
        timeout: float | None = None,
    ) -> T:
        """
        Ejecuta primary si el circuito lo permite; en fallo o circuito abierto → fallback.
        """
        if await self.is_open():
            logger.info("Circuit %s abierto → fallback inmediato", self.name)
            return await fallback()

        effective_timeout = timeout if timeout is not None else self._config.extreme_timeout_seconds
        try:
            if effective_timeout and effective_timeout > 0:
                result = await asyncio.wait_for(primary(), timeout=effective_timeout)
            else:
                result = await primary()
            await self.record_success()
            return result
        except asyncio.TimeoutError as exc:
            await self.record_failure(exc, extreme=True)
            return await fallback()
        except Exception as exc:
            await self.record_failure(exc)
            return await fallback()

    async def _open_circuit(self, *, failures: int) -> None:
        await self._set_state(
            CircuitState.OPEN,
            failures=failures,
            opened_at=time.time(),
        )

    async def _set_state(
        self,
        state: CircuitState,
        *,
        failures: int,
        opened_at: float,
    ) -> None:
        snap = _CircuitSnapshot(state=state, failures=failures, opened_at=opened_at)
        if self._config.use_redis:
            try:
                await self._write_redis(snap)
                return
            except Exception as exc:
                logger.debug("Circuit %s Redis write failed, memory fallback: %s", self.name, exc)
        await self._write_memory(snap)

    async def _load_snapshot(self) -> _CircuitSnapshot:
        if self._config.use_redis:
            try:
                return await self._read_redis()
            except Exception as exc:
                logger.debug("Circuit %s Redis read failed, memory fallback: %s", self.name, exc)
        return await self._read_memory()

    async def _read_redis(self) -> _CircuitSnapshot:
        from services.redis_service import get_redis

        redis = await get_redis()
        raw = await redis.hgetall(self._redis_key)
        if not raw:
            return _CircuitSnapshot()
        state_raw = raw.get("state", CircuitState.CLOSED.value)
        try:
            state = CircuitState(state_raw)
        except ValueError:
            state = CircuitState.CLOSED
        return _CircuitSnapshot(
            state=state,
            failures=int(raw.get("failures", 0) or 0),
            opened_at=float(raw.get("opened_at", 0) or 0),
        )

    async def _write_redis(self, snap: _CircuitSnapshot) -> None:
        from services.redis_service import get_redis

        redis = await get_redis()
        ttl = max(self._config.open_seconds + 3600, 3600)
        pipe = redis.pipeline()
        pipe.hset(
            self._redis_key,
            mapping={
                "state": snap.state.value,
                "failures": str(snap.failures),
                "opened_at": str(snap.opened_at),
            },
        )
        pipe.expire(self._redis_key, ttl)
        await pipe.execute()

    async def _read_memory(self) -> _CircuitSnapshot:
        async with self._memory_lock:
            stored = self._memory_store.get(self.name)
            if stored is None:
                return _CircuitSnapshot()
            return _CircuitSnapshot(
                state=stored.state,
                failures=stored.failures,
                opened_at=stored.opened_at,
            )

    async def _write_memory(self, snap: _CircuitSnapshot) -> None:
        async with self._memory_lock:
            self._memory_store[self.name] = snap

    @classmethod
    def reset_memory_store(cls) -> None:
        """Solo para tests."""
        cls._memory_store.clear()


_registry: dict[str, CircuitBreaker] = {}
_registry_lock = asyncio.Lock()


async def get_circuit_breaker(
    name: str,
    *,
    config: CircuitBreakerConfig | None = None,
) -> CircuitBreaker:
    if name in _registry:
        return _registry[name]
    async with _registry_lock:
        if name not in _registry:
            _registry[name] = CircuitBreaker(name, config=config)
        return _registry[name]


def get_circuit_breaker_sync(name: str) -> CircuitBreaker:
    """Acceso sync al registry (crea si no existe)."""
    if name not in _registry:
        _registry[name] = CircuitBreaker(name)
    return _registry[name]
