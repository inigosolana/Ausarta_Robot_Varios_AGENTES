import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.api_key_service import (
    CACHE_INVALID,
    generate_api_key,
    hash_api_key,
    has_scope,
    validate_api_key_from_db,
    _normalize_scopes,
)


def test_hash_api_key_deterministic():
    raw = generate_api_key()
    assert hash_api_key(raw) == hash_api_key(raw)
    assert len(hash_api_key(raw)) == 64


def test_has_scope_admin_wildcard():
    assert has_scope(["admin"], "webhook")
    assert has_scope(["outbound_call"], "outbound_call")
    assert not has_scope(["read"], "webhook")


def test_normalize_scopes_rejects_invalid():
    with pytest.raises(ValueError):
        _normalize_scopes(["invalid_scope"])


@pytest.mark.asyncio
async def test_validate_api_key_cache_hit():
    raw = generate_api_key()
    key_hash = hash_api_key(raw)
    payload = json.dumps({"key_id": "id-1", "empresa_id": 42, "scopes": ["outbound_call"]})

    with patch("services.api_key_service._cache_get", AsyncMock(return_value=payload)):
        result = await validate_api_key_from_db(raw)

    assert result is not None
    assert result.empresa_id == 42
    assert result.scopes == ("outbound_call",)


@pytest.mark.asyncio
async def test_validate_api_key_cache_invalid():
    raw = generate_api_key()
    with patch("services.api_key_service._cache_get", AsyncMock(return_value=CACHE_INVALID)):
        result = await validate_api_key_from_db(raw)
    assert result is None


@pytest.mark.asyncio
async def test_validate_api_key_db_miss():
    raw = generate_api_key()

    mock_res = MagicMock()
    mock_res.data = []

    with (
        patch("services.api_key_service._cache_get", AsyncMock(return_value=None)),
        patch("services.api_key_service._cache_set", AsyncMock()),
        patch("services.api_key_service.sb_query", AsyncMock(return_value=mock_res)),
        patch("services.api_key_service.supabase", MagicMock()),
    ):
        result = await validate_api_key_from_db(raw)

    assert result is None


@pytest.mark.asyncio
async def test_validate_api_key_expired():
    raw = generate_api_key()
    expired = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    mock_res = MagicMock()
    mock_res.data = [
        {
            "id": "k1",
            "empresa_id": 7,
            "scopes": ["outbound_call"],
            "is_active": True,
            "expires_at": expired,
        }
    ]

    with (
        patch("services.api_key_service._cache_get", AsyncMock(return_value=None)),
        patch("services.api_key_service._cache_set", AsyncMock()),
        patch("services.api_key_service.sb_query", AsyncMock(return_value=mock_res)),
        patch("services.api_key_service.supabase", MagicMock()),
    ):
        result = await validate_api_key_from_db(raw)

    assert result is None
