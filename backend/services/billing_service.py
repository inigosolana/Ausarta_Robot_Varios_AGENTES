"""
billing_service.py — Unit Economics: seguimiento de consumo por tenant (empresa_id).

Diseño:
  - Redis HASH + HINCRBY (script Lua) para acumulación atómica en tiempo real (~1 RTT).
  - Supabase (eventos + agregados mensuales) en segundo plano para no penalizar latencia.
  - Claves Redis con TTL largo (100 días) para cubrir el mes en curso + cierre contable.

Uso típico al finalizar turnos/llamadas:
  await billing.log_llm_tokens(empresa_id, prompt_tokens, completion_tokens, model_name)
  await billing.log_tts_characters(empresa_id, chars, "cartesia")
  await billing.log_telephony_seconds(empresa_id, seconds)
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Final, Literal, Optional

from services.redis_service import get_redis
from services.supabase_service import sb_query, supabase

logger = logging.getLogger("billing")

UsageEventType = Literal["llm_tokens", "tts_characters", "telephony_seconds"]
MonthlyCategory = Literal[
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "tts_characters",
    "telephony_seconds",
]

BILLING_PREFIX: Final[str] = "ausarta:billing"
BILLING_TTL_SECONDS: Final[int] = 100 * 24 * 3600  # ~100 días

FIELD_LLM_PROMPT: Final[str] = "llm:prompt_tokens"
FIELD_LLM_COMPLETION: Final[str] = "llm:completion_tokens"
FIELD_TTS_CHARACTERS: Final[str] = "tts:characters"
FIELD_TELEPHONY_SECONDS: Final[str] = "telephony:seconds"

_INCR_HASH_SCRIPT: Final[str] = """
local key = KEYS[1]
local ttl = tonumber(ARGV[1])
local argc = #ARGV
for i = 2, argc, 2 do
    local field = ARGV[i]
    local delta = tonumber(ARGV[i + 1])
    if field and delta and delta ~= 0 then
        redis.call('HINCRBY', key, field, delta)
    end
end
if redis.call('TTL', key) < 0 then
    redis.call('EXPIRE', key, ttl)
end
return 1
"""


def _utc_period(dt: datetime | None = None) -> str:
    moment = dt or datetime.now(timezone.utc)
    return moment.strftime("%Y-%m")


def _sanitize_sub_key(value: str) -> str:
    cleaned = re.sub(r"[^\w\-.]+", "_", (value or "").strip().lower())
    return (cleaned[:64] or "unknown")


def _redis_summary_key(tenant_id: int, period: str) -> str:
    return f"{BILLING_PREFIX}:tenant:{tenant_id}:{period}"


def _redis_llm_model_key(tenant_id: int, period: str, model_name: str) -> str:
    model = _sanitize_sub_key(model_name)
    return f"{BILLING_PREFIX}:tenant:{tenant_id}:{period}:llm:{model}"


def _redis_tts_provider_key(tenant_id: int, period: str, provider: str) -> str:
    prov = _sanitize_sub_key(provider)
    return f"{BILLING_PREFIX}:tenant:{tenant_id}:{period}:tts:{prov}"


def _validate_tenant_id(tenant_id: int) -> int:
    try:
        tid = int(tenant_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("tenant_id debe ser un entero positivo") from exc
    if tid <= 0:
        raise ValueError("tenant_id debe ser un entero positivo")
    return tid


def _validate_non_negative_int(name: str, value: int) -> int:
    try:
        qty = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} debe ser un entero >= 0") from exc
    if qty < 0:
        raise ValueError(f"{name} debe ser un entero >= 0")
    return qty


@dataclass(frozen=True)
class UsageLogResult:
    tenant_id: int
    period: str
    event_type: UsageEventType
    quantity: int
    redis_key: str
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TenantUsageSnapshot:
    tenant_id: int
    period: str
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    tts_characters: int = 0
    telephony_seconds: int = 0
    llm_by_model: dict[str, dict[str, int]] = field(default_factory=dict)
    tts_by_provider: dict[str, int] = field(default_factory=dict)

    @property
    def llm_total_tokens(self) -> int:
        return self.llm_prompt_tokens + self.llm_completion_tokens


class BillingService:
    """Registro de consumo por tenant con Redis (tiempo real) y Supabase (histórico)."""

    def __init__(self, *, defer_persistence: bool = True) -> None:
        self._defer_persistence = defer_persistence
        self._pending_tasks: set[asyncio.Task[None]] = set()

    async def log_llm_tokens(
        self,
        tenant_id: int,
        prompt_tokens: int,
        completion_tokens: int,
        model_name: str,
        *,
        period: str | None = None,
    ) -> UsageLogResult:
        tid = _validate_tenant_id(tenant_id)
        prompt = _validate_non_negative_int("prompt_tokens", prompt_tokens)
        completion = _validate_non_negative_int("completion_tokens", completion_tokens)
        model = (model_name or "unknown").strip() or "unknown"
        current_period = period or _utc_period()

        if prompt == 0 and completion == 0:
            return UsageLogResult(
                tenant_id=tid,
                period=current_period,
                event_type="llm_tokens",
                quantity=0,
                redis_key=_redis_summary_key(tid, current_period),
                metadata={"model_name": model, "prompt_tokens": 0, "completion_tokens": 0},
            )

        summary_key = _redis_summary_key(tid, current_period)
        model_key = _redis_llm_model_key(tid, current_period, model)

        await self._incr_redis(
            summary_key,
            {
                FIELD_LLM_PROMPT: prompt,
                FIELD_LLM_COMPLETION: completion,
            },
        )
        await self._incr_redis(
            model_key,
            {
                FIELD_LLM_PROMPT: prompt,
                FIELD_LLM_COMPLETION: completion,
            },
        )

        metadata = {
            "model_name": model,
            "prompt_tokens": prompt,
            "completion_tokens": completion,
        }
        await self._schedule_persistence(
            tenant_id=tid,
            period=current_period,
            event_type="llm_tokens",
            quantity=prompt + completion,
            unit="tokens",
            metadata=metadata,
            monthly_updates=[
                ("llm_prompt_tokens", model, prompt),
                ("llm_completion_tokens", model, completion),
            ],
        )

        return UsageLogResult(
            tenant_id=tid,
            period=current_period,
            event_type="llm_tokens",
            quantity=prompt + completion,
            redis_key=summary_key,
            metadata=metadata,
        )

    async def log_tts_characters(
        self,
        tenant_id: int,
        chars_count: int,
        provider: str,
        *,
        period: str | None = None,
    ) -> UsageLogResult:
        tid = _validate_tenant_id(tenant_id)
        chars = _validate_non_negative_int("chars_count", chars_count)
        prov = (provider or "unknown").strip() or "unknown"
        current_period = period or _utc_period()

        if chars == 0:
            return UsageLogResult(
                tenant_id=tid,
                period=current_period,
                event_type="tts_characters",
                quantity=0,
                redis_key=_redis_summary_key(tid, current_period),
                metadata={"provider": prov, "chars_count": 0},
            )

        summary_key = _redis_summary_key(tid, current_period)
        provider_key = _redis_tts_provider_key(tid, current_period, prov)

        await self._incr_redis(summary_key, {FIELD_TTS_CHARACTERS: chars})
        await self._incr_redis(provider_key, {FIELD_TTS_CHARACTERS: chars})

        metadata = {"provider": prov, "chars_count": chars}
        await self._schedule_persistence(
            tenant_id=tid,
            period=current_period,
            event_type="tts_characters",
            quantity=chars,
            unit="characters",
            metadata=metadata,
            monthly_updates=[("tts_characters", prov, chars)],
        )

        return UsageLogResult(
            tenant_id=tid,
            period=current_period,
            event_type="tts_characters",
            quantity=chars,
            redis_key=summary_key,
            metadata=metadata,
        )

    async def log_telephony_seconds(
        self,
        tenant_id: int,
        seconds: int,
        *,
        period: str | None = None,
    ) -> UsageLogResult:
        tid = _validate_tenant_id(tenant_id)
        secs = _validate_non_negative_int("seconds", seconds)
        current_period = period or _utc_period()

        if secs == 0:
            return UsageLogResult(
                tenant_id=tid,
                period=current_period,
                event_type="telephony_seconds",
                quantity=0,
                redis_key=_redis_summary_key(tid, current_period),
                metadata={"seconds": 0},
            )

        summary_key = _redis_summary_key(tid, current_period)
        await self._incr_redis(summary_key, {FIELD_TELEPHONY_SECONDS: secs})

        metadata = {"seconds": secs}
        await self._schedule_persistence(
            tenant_id=tid,
            period=current_period,
            event_type="telephony_seconds",
            quantity=secs,
            unit="seconds",
            metadata=metadata,
            monthly_updates=[("telephony_seconds", "", secs)],
        )

        return UsageLogResult(
            tenant_id=tid,
            period=current_period,
            event_type="telephony_seconds",
            quantity=secs,
            redis_key=summary_key,
            metadata=metadata,
        )

    async def get_current_usage(
        self,
        tenant_id: int,
        *,
        period: str | None = None,
    ) -> TenantUsageSnapshot:
        """Lee contadores acumulados del mes desde Redis (fuente para hard limits)."""
        tid = _validate_tenant_id(tenant_id)
        current_period = period or _utc_period()
        redis = await get_redis()

        summary_key = _redis_summary_key(tid, current_period)
        summary_raw = await redis.hgetall(summary_key)

        llm_by_model: dict[str, dict[str, int]] = {}
        pattern = f"{BILLING_PREFIX}:tenant:{tid}:{current_period}:llm:*"
        async for key in redis.scan_iter(match=pattern):
            model = key.rsplit(":", 1)[-1]
            model_raw = await redis.hgetall(key)
            llm_by_model[model] = {
                "prompt_tokens": int(model_raw.get(FIELD_LLM_PROMPT, 0) or 0),
                "completion_tokens": int(model_raw.get(FIELD_LLM_COMPLETION, 0) or 0),
            }

        tts_by_provider: dict[str, int] = {}
        tts_pattern = f"{BILLING_PREFIX}:tenant:{tid}:{current_period}:tts:*"
        async for key in redis.scan_iter(match=tts_pattern):
            prov = key.rsplit(":", 1)[-1]
            prov_raw = await redis.hgetall(key)
            tts_by_provider[prov] = int(prov_raw.get(FIELD_TTS_CHARACTERS, 0) or 0)

        return TenantUsageSnapshot(
            tenant_id=tid,
            period=current_period,
            llm_prompt_tokens=int(summary_raw.get(FIELD_LLM_PROMPT, 0) or 0),
            llm_completion_tokens=int(summary_raw.get(FIELD_LLM_COMPLETION, 0) or 0),
            tts_characters=int(summary_raw.get(FIELD_TTS_CHARACTERS, 0) or 0),
            telephony_seconds=int(summary_raw.get(FIELD_TELEPHONY_SECONDS, 0) or 0),
            llm_by_model=llm_by_model,
            tts_by_provider=tts_by_provider,
        )

    async def _incr_redis(self, key: str, deltas: dict[str, int]) -> None:
        filtered = {field: int(delta) for field, delta in deltas.items() if int(delta) != 0}
        if not filtered:
            return

        redis = await get_redis()
        args: list[str] = [str(BILLING_TTL_SECONDS)]
        for field, delta in filtered.items():
            args.extend([field, str(delta)])

        await redis.eval(_INCR_HASH_SCRIPT, 1, key, *args)

    async def _schedule_persistence(
        self,
        *,
        tenant_id: int,
        period: str,
        event_type: UsageEventType,
        quantity: int,
        unit: str,
        metadata: dict[str, Any],
        monthly_updates: list[tuple[MonthlyCategory, str, int]],
    ) -> None:
        if not supabase:
            logger.debug("[billing] Supabase no configurado; solo Redis para tenant=%s", tenant_id)
            return

        coro = self._persist_usage(
            tenant_id=tenant_id,
            period=period,
            event_type=event_type,
            quantity=quantity,
            unit=unit,
            metadata=metadata,
            monthly_updates=monthly_updates,
        )

        if self._defer_persistence:
            task = asyncio.create_task(coro)
            self._pending_tasks.add(task)
            task.add_done_callback(self._pending_tasks.discard)
            return

        await coro

    async def _persist_usage(
        self,
        *,
        tenant_id: int,
        period: str,
        event_type: UsageEventType,
        quantity: int,
        unit: str,
        metadata: dict[str, Any],
        monthly_updates: list[tuple[MonthlyCategory, str, int]],
    ) -> None:
        try:
            await sb_query(
                lambda: supabase.table("tenant_usage_events")
                .insert(
                    {
                        "empresa_id": tenant_id,
                        "event_type": event_type,
                        "period": period,
                        "quantity": str(Decimal(quantity)),
                        "unit": unit,
                        "metadata": metadata,
                    }
                )
                .execute()
            )

            for category, sub_key, delta in monthly_updates:
                if delta <= 0:
                    continue
                await sb_query(
                    lambda cat=category, sk=sub_key, d=delta: supabase.rpc(
                        "upsert_tenant_usage_monthly",
                        {
                            "p_empresa_id": tenant_id,
                            "p_period": period,
                            "p_category": cat,
                            "p_sub_key": sk,
                            "p_quantity": float(d),
                        },
                    ).execute()
                )
        except Exception:
            logger.exception(
                "[billing] Error persistiendo uso tenant=%s period=%s event=%s",
                tenant_id,
                period,
                event_type,
            )


_billing_service: BillingService | None = None


def get_billing_service() -> BillingService:
    global _billing_service
    if _billing_service is None:
        _billing_service = BillingService(defer_persistence=True)
    return _billing_service
