"""
Tests de autenticación de endpoints críticos.

Verifica que los endpoints protegidos devuelven 401/403
cuando no se envía JWT válido.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient, ASGITransport


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

_PROTECTED_ENDPOINTS = [
    ("GET", "/api/agents"),
    ("GET", "/api/knowledge/"),
    ("GET", "/api/admin/api-credits"),
    ("GET", "/api/campaigns"),
    ("GET", "/api/contacts"),
]

_ADMIN_ONLY_ENDPOINTS = [
    ("POST", "/api/knowledge/upload"),
    ("POST", "/api/agents"),
]


@pytest.fixture
def mock_supabase():
    """Evita hits reales a Supabase durante los tests de auth."""
    mock_sb = AsyncMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    with (
        patch("services.supabase_service.supabase", mock_sb),
        patch("services.auth.supabase", mock_sb),
    ):
        yield mock_sb


# ──────────────────────────────────────────────────────────────────
# Tests: sin token → 401 / 403
# ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _PROTECTED_ENDPOINTS)
async def test_protected_endpoint_without_token_returns_401_or_403(
    method, path, mock_supabase
):
    from api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await getattr(ac, method.lower())(path)

    assert response.status_code in (401, 403), (
        f"{method} {path} devolvió {response.status_code}, esperado 401 o 403"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("method,path", _ADMIN_ONLY_ENDPOINTS)
async def test_admin_endpoint_without_token_returns_401_or_403(
    method, path, mock_supabase
):
    from api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await getattr(ac, method.lower())(path)

    assert response.status_code in (401, 403), (
        f"{method} {path} devolvió {response.status_code}, esperado 401 o 403"
    )


@pytest.mark.asyncio
async def test_root_endpoint_is_public():
    """El endpoint raíz / es público y no requiere autenticación."""
    from api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/")

    assert response.status_code == 200
    assert response.json().get("status") == "ok"


@pytest.mark.asyncio
async def test_health_endpoint_is_public():
    """GET /health no requiere autenticación."""
    from api import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")

    # 200 (todo ok) o 503 (deps no disponibles en CI) — ambos son válidos
    assert response.status_code in (200, 503)
    data = response.json()
    assert "status" in data
    assert "dependencies" in data
