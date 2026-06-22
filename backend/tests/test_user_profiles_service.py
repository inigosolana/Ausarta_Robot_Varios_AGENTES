"""Tests para list_user_profiles_with_empresa (batch 2-query)."""

from unittest.mock import MagicMock, patch

import pytest

from services.user_profiles_service import list_user_profiles_with_empresa


@pytest.mark.asyncio
async def test_list_user_profiles_with_empresa_batches_empresas():
    users = [
        {"id": "u1", "email": "a@x.com", "empresa_id": 1},
        {"id": "u2", "email": "b@x.com", "empresa_id": 2},
        {"id": "u3", "email": "c@x.com", "empresa_id": 1},
    ]
    empresas = [
        {"id": 1, "nombre": "Acme", "plan": "pro"},
        {"id": 2, "nombre": "Beta", "plan": "basico"},
    ]

    users_res = MagicMock(data=users)
    empresas_res = MagicMock(data=empresas)

    profiles_chain = MagicMock()
    profiles_chain.select.return_value = profiles_chain
    profiles_chain.order.return_value = profiles_chain
    profiles_chain.eq.return_value = profiles_chain
    profiles_chain.execute.return_value = users_res

    empresas_chain = MagicMock()
    empresas_chain.select.return_value = empresas_chain
    empresas_chain.in_.return_value = empresas_chain
    empresas_chain.execute.return_value = empresas_res

    def table_side_effect(name):
        if name == "user_profiles":
            return profiles_chain
        if name == "empresas":
            return empresas_chain
        raise AssertionError(f"unexpected table {name}")

    with patch("services.user_profiles_service.supabase") as sb, patch(
        "services.user_profiles_service.sb_query",
        side_effect=lambda fn: fn(),
    ):
        sb.table = MagicMock(side_effect=table_side_effect)
        result = await list_user_profiles_with_empresa(empresa_id=1)

    assert len(result) == 3
    assert result[0]["empresas"] == empresas[0]
    assert result[1]["empresas"] == empresas[1]
    empresas_chain.in_.assert_called_once_with("id", [1, 2])


@pytest.mark.asyncio
async def test_list_user_profiles_empty_when_no_supabase():
    with patch("services.user_profiles_service.supabase", None):
        assert await list_user_profiles_with_empresa() == []
