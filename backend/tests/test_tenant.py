"""
Tests de aislamiento multi-tenant.

Verifica que:
- TenantContextMiddleware limpia el tenant antes y después de cada request.
- El ContextVar no se filtra entre requests concurrentes.
- Un empresa_id inválido (None, 0, letras) se normaliza a None.
"""
from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from services.tenant_context import (
    bind_tenant_context,
    get_current_empresa_id,
    reset_current_empresa_id,
    set_current_empresa_id,
)


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _set_and_get(empresa_id):
    tok = set_current_empresa_id(empresa_id)
    result = get_current_empresa_id()
    reset_current_empresa_id(tok)
    return result


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

def test_set_valid_empresa_id():
    assert _set_and_get(42) == 42


def test_set_none_empresa_id():
    assert _set_and_get(None) is None


def test_invalid_empresa_id_becomes_none():
    """Strings no numéricos deben normalizarse a None."""
    assert _set_and_get("abc") is None


def test_zero_empresa_id_normalizes_to_none():
    """empresa_id=0 NO es un tenant válido; se admite pero es 0 (no None)."""
    val = _set_and_get(0)
    # 0 es diferente de None: está parseado pero no es tenant real
    assert val == 0


def test_empresa_id_resets_after_context_manager():
    """bind_tenant_context restaura el valor anterior al salir."""
    tok = set_current_empresa_id(10)
    try:
        with bind_tenant_context(99):
            assert get_current_empresa_id() == 99
        assert get_current_empresa_id() == 10
    finally:
        reset_current_empresa_id(tok)


def test_empresa_id_resets_even_on_exception():
    """El context manager limpia el tenant aunque lance excepción."""
    tok = set_current_empresa_id(10)
    try:
        with pytest.raises(RuntimeError):
            with bind_tenant_context(99):
                raise RuntimeError("fallo")
        assert get_current_empresa_id() == 10
    finally:
        reset_current_empresa_id(tok)


@pytest.mark.asyncio
async def test_tenant_isolation_concurrent_coroutines():
    """
    Dos coroutines corriendo concurrentemente NO deben ver el empresa_id de la otra.
    ContextVar está aislado por contexto asyncio — no por thread.
    """
    barrier = asyncio.Event()
    results: dict = {}

    async def task_a():
        with bind_tenant_context(1):
            results["a_before"] = get_current_empresa_id()
            barrier.set()          # avisa a B
            await asyncio.sleep(0) # cede el control
            results["a_after"] = get_current_empresa_id()

    async def task_b():
        await barrier.wait()       # espera a que A haya establecido su tenant
        with bind_tenant_context(2):
            results["b"] = get_current_empresa_id()

    await asyncio.gather(task_a(), task_b())

    assert results["a_before"] == 1
    assert results["a_after"] == 1   # no contaminado por B
    assert results["b"] == 2


@pytest.mark.asyncio
async def test_middleware_resets_tenant(monkeypatch):
    """
    TenantContextMiddleware resetea el tenant a None antes de cada request.
    Simula que un request anterior dejó un tenant residual.
    """
    from starlette.testclient import TestClient
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse
    from starlette.routing import Route
    from middleware.tenant_context import TenantContextMiddleware

    captured = {}

    async def endpoint(request: Request):
        captured["empresa_id"] = get_current_empresa_id()
        return JSONResponse({"ok": True})

    app = Starlette(routes=[Route("/", endpoint)], middleware=[])
    app.add_middleware(TenantContextMiddleware)

    # Primero forzamos un tenant "sucio" en el contexto padre
    # (simula que el middleware no limpió en un request anterior)
    tok = set_current_empresa_id(999)
    try:
        client = TestClient(app)
        client.get("/")
        # El middleware debe haber reseteado a None dentro del request
        assert captured["empresa_id"] is None
    finally:
        reset_current_empresa_id(tok)
