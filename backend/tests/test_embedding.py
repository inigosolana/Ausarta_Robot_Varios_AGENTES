"""
Tests de embedding_service:

- Cache hit Redis: si la clave existe, devuelve el embedding sin llamar a OpenAI.
- Cache miss: llama a OpenAI y guarda en Redis.
- Sin OPENAI_API_KEY: devuelve None inmediatamente.
- Texto vacío: devuelve None.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


MOCK_EMBEDDING = [0.1] * 1536


# ──────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_empty_text_returns_none():
    from services.embedding_service import get_embedding

    assert await get_embedding("") is None
    assert await get_embedding("   ") is None


@pytest.mark.asyncio
async def test_no_api_key_returns_none(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "")
    from services.embedding_service import get_embedding

    result = await get_embedding("hola mundo")
    assert result is None


@pytest.mark.asyncio
async def test_cache_hit_skips_openai(monkeypatch):
    """Si Redis tiene el embedding cacheado, OpenAI NO se llama."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=json.dumps(MOCK_EMBEDDING))

    with (
        patch("services.embedding_service.get_redis", AsyncMock(return_value=mock_redis)),
        patch("aiohttp.ClientSession") as mock_session_cls,
    ):
        from services.embedding_service import get_embedding
        result = await get_embedding("tarifa móvil")

    assert result == MOCK_EMBEDDING
    # Nunca debió abrirse la sesión HTTP hacia OpenAI
    mock_session_cls.assert_not_called()


@pytest.mark.asyncio
async def test_cache_miss_calls_openai_and_stores(monkeypatch):
    """Cache miss → llama OpenAI → guarda en Redis."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)  # cache miss
    mock_redis.set = AsyncMock()

    openai_response = {"data": [{"embedding": MOCK_EMBEDDING}]}
    mock_http_resp = MagicMock()
    mock_http_resp.status = 200
    mock_http_resp.json = AsyncMock(return_value=openai_response)
    mock_http_resp.__aenter__ = AsyncMock(return_value=mock_http_resp)
    mock_http_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_http_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("services.embedding_service.get_redis", AsyncMock(return_value=mock_redis)),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        from services.embedding_service import get_embedding
        result = await get_embedding("tarifa fibra")

    assert result == MOCK_EMBEDDING
    mock_redis.set.assert_called_once()


@pytest.mark.asyncio
async def test_openai_error_returns_none(monkeypatch):
    """Si OpenAI falla en todos los intentos, devuelve None sin propagar."""
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")

    mock_redis = AsyncMock()
    mock_redis.get = AsyncMock(return_value=None)

    mock_http_resp = MagicMock()
    mock_http_resp.status = 429
    mock_http_resp.text = AsyncMock(return_value="rate limit")
    mock_http_resp.__aenter__ = AsyncMock(return_value=mock_http_resp)
    mock_http_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_http_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("services.embedding_service.get_redis", AsyncMock(return_value=mock_redis)),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        from services.embedding_service import get_embedding
        result = await get_embedding("consulta")

    assert result is None
