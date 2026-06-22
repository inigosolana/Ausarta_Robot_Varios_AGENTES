from unittest.mock import AsyncMock, patch

import pytest

from services.auth import _resolve_api_key


@pytest.mark.asyncio
async def test_resolve_api_key_legacy_env(monkeypatch):
    monkeypatch.setenv("AUSARTA_API_KEY", "legacy-test-key")
    monkeypatch.setenv("AUSARTA_API_KEY_LEGACY", "true")

    with patch("services.auth.validate_api_key_from_db", AsyncMock(return_value=None)):
        resolved = await _resolve_api_key("legacy-test-key")

    assert resolved is not None
    assert resolved.source == "legacy_env"


@pytest.mark.asyncio
async def test_resolve_api_key_unknown(monkeypatch):
    monkeypatch.setenv("AUSARTA_API_KEY_LEGACY", "false")

    with patch("services.auth.validate_api_key_from_db", AsyncMock(return_value=None)):
        resolved = await _resolve_api_key("unknown-key")

    assert resolved is None
