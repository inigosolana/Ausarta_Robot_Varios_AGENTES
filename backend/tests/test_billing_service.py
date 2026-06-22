"""Tests del servicio de billing / unit economics (Punto 1)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.billing_service import (
    FIELD_LLM_COMPLETION,
    FIELD_LLM_PROMPT,
    FIELD_TELEPHONY_SECONDS,
    FIELD_TTS_CHARACTERS,
    BillingService,
    _redis_llm_model_key,
    _redis_summary_key,
    _sanitize_sub_key,
)


@pytest.fixture
def mock_redis() -> AsyncMock:
    store: dict[str, dict[str, int]] = {}

    async def _eval(script, numkeys, key, *args):
        ttl = int(args[0])
        assert ttl > 0
        bucket = store.setdefault(key, {})
        for i in range(1, len(args), 2):
            field = args[i]
            delta = int(args[i + 1])
            bucket[field] = bucket.get(field, 0) + delta
        return 1

    async def _hgetall(key):
        return {k: str(v) for k, v in store.get(key, {}).items()}

    async def _scan_iter(match=None):
        prefix = (match or "").replace("*", "")
        for key in list(store.keys()):
            if key.startswith(prefix.rstrip(":")):
                yield key

    redis = AsyncMock()
    redis.eval = AsyncMock(side_effect=_eval)
    redis.hgetall = AsyncMock(side_effect=_hgetall)
    redis.scan_iter = _scan_iter
    redis._store = store
    return redis


@pytest.fixture
def billing(mock_redis: AsyncMock) -> BillingService:
    with patch("services.billing_service.get_redis", new=AsyncMock(return_value=mock_redis)):
        yield BillingService(defer_persistence=False)


def test_sanitize_sub_key():
    assert _sanitize_sub_key("Llama-3.3 70B") == "llama-3.3_70b"


@pytest.mark.asyncio
async def test_log_llm_tokens_increments_redis_summary_and_model_hash(
    billing: BillingService,
    mock_redis: AsyncMock,
):
    result = await billing.log_llm_tokens(
        tenant_id=7,
        prompt_tokens=120,
        completion_tokens=80,
        model_name="llama-3.3-70b-versatile",
        period="2026-06",
    )

    assert result.quantity == 200
    assert result.event_type == "llm_tokens"

    summary_key = _redis_summary_key(7, "2026-06")
    model_key = _redis_llm_model_key(7, "2026-06", "llama-3.3-70b-versatile")

    assert mock_redis._store[summary_key][FIELD_LLM_PROMPT] == 120
    assert mock_redis._store[summary_key][FIELD_LLM_COMPLETION] == 80
    assert mock_redis._store[model_key][FIELD_LLM_PROMPT] == 120
    assert mock_redis.eval.await_count == 2


@pytest.mark.asyncio
async def test_log_tts_characters_increments_redis(billing: BillingService, mock_redis: AsyncMock):
    await billing.log_tts_characters(
        tenant_id=3,
        chars_count=450,
        provider="cartesia",
        period="2026-06",
    )

    summary_key = _redis_summary_key(3, "2026-06")
    assert mock_redis._store[summary_key][FIELD_TTS_CHARACTERS] == 450


@pytest.mark.asyncio
async def test_log_telephony_seconds_increments_redis(billing: BillingService, mock_redis: AsyncMock):
    await billing.log_telephony_seconds(tenant_id=5, seconds=187, period="2026-06")

    summary_key = _redis_summary_key(5, "2026-06")
    assert mock_redis._store[summary_key][FIELD_TELEPHONY_SECONDS] == 187


@pytest.mark.asyncio
async def test_get_current_usage_reads_redis_aggregates(billing: BillingService):
    await billing.log_llm_tokens(9, 50, 25, "groq-8b", period="2026-06")
    await billing.log_tts_characters(9, 300, "cartesia", period="2026-06")
    await billing.log_telephony_seconds(9, 90, period="2026-06")

    snapshot = await billing.get_current_usage(9, period="2026-06")

    assert snapshot.llm_prompt_tokens == 50
    assert snapshot.llm_completion_tokens == 25
    assert snapshot.llm_total_tokens == 75
    assert snapshot.tts_characters == 300
    assert snapshot.telephony_seconds == 90
    assert "groq-8b" in snapshot.llm_by_model
    assert snapshot.tts_by_provider.get("cartesia") == 300


@pytest.mark.asyncio
async def test_zero_quantity_skips_redis_writes(billing: BillingService, mock_redis: AsyncMock):
    await billing.log_llm_tokens(1, 0, 0, "model", period="2026-06")
    await billing.log_tts_characters(1, 0, "cartesia", period="2026-06")
    await billing.log_telephony_seconds(1, 0, period="2026-06")

    assert mock_redis.eval.await_count == 0


@pytest.mark.asyncio
async def test_invalid_tenant_id_raises(billing: BillingService):
    with pytest.raises(ValueError, match="tenant_id"):
        await billing.log_llm_tokens(0, 10, 10, "model")


@pytest.mark.asyncio
async def test_persist_usage_writes_event_and_monthly_rpc(billing: BillingService):
    mock_table = MagicMock()
    mock_insert = MagicMock()
    mock_insert.execute.return_value = MagicMock(data=[{"id": 1}])
    mock_table.insert.return_value = mock_insert

    mock_rpc = MagicMock()
    mock_rpc.execute.return_value = MagicMock(data=None)

    mock_client = MagicMock()
    mock_client.table.return_value = mock_table
    mock_client.rpc.return_value = mock_rpc

    with (
        patch("services.billing_service.supabase", mock_client),
        patch("services.billing_service.sb_query", new=AsyncMock(side_effect=lambda fn: fn())),
    ):
        await billing._persist_usage(
            tenant_id=4,
            period="2026-06",
            event_type="llm_tokens",
            quantity=150,
            unit="tokens",
            metadata={"model_name": "llama", "prompt_tokens": 100, "completion_tokens": 50},
            monthly_updates=[
                ("llm_prompt_tokens", "llama", 100),
                ("llm_completion_tokens", "llama", 50),
            ],
        )

    mock_table.insert.assert_called_once()
    assert mock_client.rpc.call_count == 2
    mock_client.rpc.assert_any_call(
        "upsert_tenant_usage_monthly",
        {
            "p_empresa_id": 4,
            "p_period": "2026-06",
            "p_category": "llm_prompt_tokens",
            "p_sub_key": "llama",
            "p_quantity": 100.0,
        },
    )


@pytest.mark.asyncio
async def test_defer_persistence_schedules_background_task(mock_redis: AsyncMock):
    billing = BillingService(defer_persistence=True)
    scheduled: list = []

    def _capture_task(coro):
        scheduled.append(coro)
        coro.close()
        return MagicMock()

    with (
        patch("services.billing_service.get_redis", new=AsyncMock(return_value=mock_redis)),
        patch("services.billing_service.asyncio.create_task", side_effect=_capture_task),
        patch("services.billing_service.supabase", MagicMock()),
    ):
        await billing.log_telephony_seconds(2, 30, period="2026-06")

    assert len(scheduled) == 1
