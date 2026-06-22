"""Tests para profile_cache (L1/L2, singleflight, invalidación)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

import services.profile_cache as pc


@pytest.fixture(autouse=True)
def _reset_profile_cache():
    pc._MEM_PROFILE_CACHE.clear()
    pc._CACHE_GEN.clear()
    pc._IN_FLIGHT.clear()
    yield
    pc._MEM_PROFILE_CACHE.clear()
    pc._CACHE_GEN.clear()
    pc._IN_FLIGHT.clear()


def test_profile_row_cache_blob_roundtrip():
    row = {
        "id": "u1",
        "email": "a@b.com",
        "role": "admin",
        "empresa_id": 3,
        "is_active": True,
    }
    blob = pc._profile_row_cache_blob(row)
    assert pc._profile_from_cache_blob(blob) == row


def test_decode_redis_value_handles_bytes():
    assert pc._decode_redis_value(b'{"id":"u1"}') == '{"id":"u1"}'
    assert pc._decode_redis_value(None) is None


@pytest.mark.asyncio
async def test_mem_cache_hit_avoids_db():
    user_id = "user-1"
    row = {"id": user_id, "email": "x@y.com", "role": "user", "empresa_id": 1, "is_active": True}
    now = pc.time.monotonic()
    pc._mem_cache_set(user_id, row, now)

    with patch.object(pc, "_redis_get_profile", new=AsyncMock()) as redis_mock, patch.object(
        pc, "_singleflight_load", new=AsyncMock()
    ) as sf_mock:
        result = await pc.get_user_profile_cached(user_id)

    assert result == row
    redis_mock.assert_not_called()
    sf_mock.assert_not_called()


@pytest.mark.asyncio
async def test_redis_hit_warms_mem_cache():
    user_id = "user-2"
    row = {"id": user_id, "email": "x@y.com", "role": "admin", "empresa_id": 2, "is_active": True}

    with patch.object(pc, "_redis_get_profile", new=AsyncMock(return_value=row)):
        first = await pc.get_user_profile_cached(user_id)
        second = await pc.get_user_profile_cached(user_id)

    assert first == row
    assert second == row
    assert user_id in pc._MEM_PROFILE_CACHE


@pytest.mark.asyncio
async def test_singleflight_coalesces_concurrent_db_loads():
    user_id = "user-3"
    row = {"id": user_id, "email": "z@y.com", "role": "user", "empresa_id": 1, "is_active": True}
    calls = {"n": 0}

    async def slow_load(uid: str) -> dict:
        calls["n"] += 1
        await asyncio.sleep(0.05)
        return row

    with patch.object(pc, "_load_profile_from_db", side_effect=slow_load):
        results = await asyncio.gather(
            pc.get_user_profile_cached(user_id),
            pc.get_user_profile_cached(user_id),
            pc.get_user_profile_cached(user_id),
        )

    assert results == [row, row, row]
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_load_skips_cache_when_invalidated_during_fetch():
    user_id = "user-4"
    row = {"id": user_id, "role": "admin", "empresa_id": 1, "is_active": True}

    def fetch_and_invalidate(uid: str) -> dict:
        pc._CACHE_GEN[user_id] = pc._CACHE_GEN.get(user_id, 0) + 1
        return row

    with patch.object(pc, "_fetch_user_profile_row", side_effect=fetch_and_invalidate), patch.object(
        pc, "_redis_set_profile", new=AsyncMock()
    ) as redis_set:
        result = await pc._load_profile_from_db(user_id)

    assert result == row
    redis_set.assert_not_called()
    assert user_id not in pc._MEM_PROFILE_CACHE


@pytest.mark.asyncio
async def test_invalidate_clears_mem_and_bumps_generation():
    user_id = "user-5"
    now = pc.time.monotonic()
    pc._mem_cache_set(user_id, {"id": user_id}, now)
    gen_before = pc._CACHE_GEN.get(user_id, 0)

    with patch("services.redis_service.get_redis", new=AsyncMock(return_value=MagicMock(delete=AsyncMock(return_value=1)))):
        await pc.invalidate_user_profile_cache(user_id)

    assert user_id not in pc._MEM_PROFILE_CACHE
    assert pc._CACHE_GEN[user_id] == gen_before + 1


@pytest.mark.asyncio
async def test_fetch_user_profile_row_raises_when_missing():
    mock_supabase = MagicMock()
    mock_supabase.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = MagicMock(
        data=[]
    )
    with patch.object(pc, "supabase", mock_supabase):
        with pytest.raises(HTTPException) as exc:
            pc._fetch_user_profile_row("missing")
    assert exc.value.status_code == 403
