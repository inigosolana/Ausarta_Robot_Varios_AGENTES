"""
Tests de seguridad: whitelist de queries en external_db_service.

Verifica que:
- Un query_name no registrado en empresa_external_db.queries devuelve None.
- Nunca se ejecuta SQL libre (la función solo acepta queries predefinidos).
- Si no hay config para la empresa, devuelve None.
- Si la empresa no está activa, devuelve None.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _make_config(
    db_type="rest",
    queries: dict | None = None,
    activo: bool = True,
    api_url: str = "http://crm.example.com",
):
    return {
        "db_type": db_type,
        "connection_url": None,
        "api_url": api_url,
        "api_key_enc": None,
        "api_key_header": "Authorization",
        "queries": queries or {},
        "activo": activo,
    }


def _mock_supabase_with_config(config: dict | None):
    """Devuelve un mock de supabase cuya respuesta de empresa_external_db tiene los datos dados."""
    sb = MagicMock()
    if config is None:
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    else:
        sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value.data = [config]
    return sb


# ──────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_not_in_whitelist_returns_none():
    """Un query_name desconocido nunca llega a ejecutarse; devuelve None."""
    cfg = _make_config(queries={"cliente_por_telefono": "SELECT * FROM clientes WHERE tel=$1"})
    sb = _mock_supabase_with_config(cfg)

    with (
        patch("services.external_db_service.supabase", sb),
        patch("services.external_db_service.sb_query", side_effect=lambda fn: fn()),
    ):
        from services.external_db_service import query_external_db
        result = await query_external_db(1, "DROP TABLE clientes", [])
        assert result is None


@pytest.mark.asyncio
async def test_empty_whitelist_returns_none_for_any_query():
    """Si queries está vacío, ningún query_name puede ejecutarse."""
    cfg = _make_config(queries={})
    sb = _mock_supabase_with_config(cfg)

    with (
        patch("services.external_db_service.supabase", sb),
        patch("services.external_db_service.sb_query", side_effect=lambda fn: fn()),
    ):
        from services.external_db_service import query_external_db
        result = await query_external_db(1, "cliente_por_telefono", ["123"])
        assert result is None


@pytest.mark.asyncio
async def test_no_config_returns_none():
    """Sin config de BD externa para la empresa, devuelve None."""
    sb = _mock_supabase_with_config(None)

    with (
        patch("services.external_db_service.supabase", sb),
        patch("services.external_db_service.sb_query", side_effect=lambda fn: fn()),
    ):
        from services.external_db_service import query_external_db
        result = await query_external_db(99, "cliente_por_telefono", ["123"])
        assert result is None


@pytest.mark.asyncio
async def test_valid_query_in_whitelist_calls_rest():
    """Un query_name registrado en la whitelist llega al cliente REST (mock)."""
    cfg = _make_config(
        db_type="rest",
        queries={"cliente_por_telefono": "endpoint"},
        api_url="http://crm.example.com",
    )
    sb = _mock_supabase_with_config(cfg)
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.json = AsyncMock(return_value=[{"nombre": "Test"}])
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.get = MagicMock(return_value=mock_response)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("services.external_db_service.supabase", sb),
        patch("services.external_db_service.sb_query", side_effect=lambda fn: fn()),
        patch("aiohttp.ClientSession", return_value=mock_session),
    ):
        from services.external_db_service import query_external_db
        result = await query_external_db(1, "cliente_por_telefono", ["600000000"])
        assert result is not None
        assert isinstance(result, list)


@pytest.mark.asyncio
async def test_supabase_none_returns_none():
    """Si supabase no está inicializado, devuelve None sin lanzar excepción."""
    with patch("services.external_db_service.supabase", None):
        from services.external_db_service import query_external_db
        result = await query_external_db(1, "any_query", [])
        assert result is None
