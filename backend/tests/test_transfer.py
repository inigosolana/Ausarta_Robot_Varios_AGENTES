"""
Tests de transferencia de llamada: extensión interna vs número externo.

Casos cubiertos:
1. Extensión interna IDLE     → llama transfer_call, devuelve 200 ok.
2. Extensión interna OCUPADA  → devuelve 409, NO llama transfer_call.
3. Número externo VÁLIDO      → salta check de estado, llama transfer_call normalizado.
4. Número externo INVÁLIDO    → devuelve 400, NO llama transfer_call.
5. normalize_external_number  → pruebas unitarias de normalización.
6. is_internal_extension      → pruebas de clasificación con BD mockeada.
"""
from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ──────────────────────────────────────────────────────────────────────────────
# Tests unitarios: normalize_external_number
# ──────────────────────────────────────────────────────────────────────────────

def test_normalize_valid_national():
    from services.telephony_transfer_service import normalize_external_number
    assert normalize_external_number("612 345 678") == "612345678"


def test_normalize_valid_e164():
    from services.telephony_transfer_service import normalize_external_number
    assert normalize_external_number("+34 612-34-56-78") == "+34612345678"


def test_normalize_strips_parens_dashes():
    from services.telephony_transfer_service import normalize_external_number
    assert normalize_external_number("(912) 34-56-78") == "912345678"


def test_normalize_too_short_returns_none():
    from services.telephony_transfer_service import normalize_external_number
    assert normalize_external_number("123") is None


def test_normalize_letters_returns_none():
    from services.telephony_transfer_service import normalize_external_number
    assert normalize_external_number("abc123") is None


def test_normalize_empty_returns_none():
    from services.telephony_transfer_service import normalize_external_number
    assert normalize_external_number("") is None


# ──────────────────────────────────────────────────────────────────────────────
# Tests unitarios: is_internal_extension
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_is_internal_short_number_with_db_record():
    """Extensión de 4 dígitos presente en yeastar_extensions → es interna."""
    mock_res = MagicMock()
    mock_res.data = [{"id": 1}]
    mock_sb = MagicMock()
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = mock_res

    with (
        patch("services.telephony_transfer_service.supabase", mock_sb),
        patch("services.telephony_transfer_service.sb_query", side_effect=lambda fn: fn()),
    ):
        from services.telephony_transfer_service import is_internal_extension
        result = await is_internal_extension(1, "1001")

    assert result is True


@pytest.mark.asyncio
async def test_is_external_long_number():
    """Número de 9 dígitos → es externo sin necesidad de consultar la BD."""
    from services.telephony_transfer_service import is_internal_extension
    result = await is_internal_extension(1, "612345678")
    assert result is False


@pytest.mark.asyncio
async def test_is_external_e164():
    """Número E.164 con + → es externo directamente."""
    from services.telephony_transfer_service import is_internal_extension
    result = await is_internal_extension(1, "+34912345678")
    assert result is False


@pytest.mark.asyncio
async def test_is_external_short_not_in_db():
    """Extensión de 4 dígitos NO presente en la tabla con registros → es externa."""
    mock_sb = MagicMock()
    call_count = {"n": 0}

    def mock_execute():
        call_count["n"] += 1
        if call_count["n"] == 1:
            r = MagicMock()
            r.data = []
            return r
        r = MagicMock()
        r.data = []
        r.count = 5
        return r

    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute = mock_execute
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute = mock_execute

    with (
        patch("services.telephony_transfer_service.supabase", mock_sb),
        patch("services.telephony_transfer_service.sb_query", side_effect=lambda fn: fn()),
    ):
        from services.telephony_transfer_service import is_internal_extension
        result = await is_internal_extension(1, "1099")

    assert result is False


# ──────────────────────────────────────────────────────────────────────────────
# Tests de integración: transfer_call_to_human (endpoint)
# ──────────────────────────────────────────────────────────────────────────────

def _make_encuesta_row(survey_id: int = 1, channel_id: str = "SIP/ch001") -> dict:
    return {
        "id": survey_id,
        "empresa_id": 42,
        "telefono": "600000000",
        "datos_extra": {
            "yeastar_callid": "callid-123",
            "yeastar_call_id": "callid-123",
            "yeastar_channel_id": channel_id,
        },
        "status": "active",
    }


def _make_yeastar_config() -> dict:
    return {
        "id": 1,
        "empresa_id": 42,
        "api_url": "https://pbx.test.com",
        "api_port": 443,
        "api_mode": "pseries",
        "api_username": "admin",
        "api_password": "encrypted_pass",
        "is_active": True,
        "enabled_capabilities": [],
        "outbound_prefix": "",
    }


@pytest.fixture
def _common_patches():
    """Patches comunes para todos los tests de transferencia."""
    enc_row = _make_encuesta_row()
    config = _make_yeastar_config()

    mock_sb = MagicMock()

    def _make_sb_res(data):
        r = MagicMock()
        r.data = data
        r.count = len(data)
        return r

    enc_res = _make_sb_res([enc_row])
    mock_sb.table.return_value.select.return_value.eq.return_value.eq.return_value.limit.return_value.execute.return_value = enc_res
    mock_sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = enc_res
    mock_sb.table.return_value.update.return_value.eq.return_value.execute.return_value = MagicMock()

    with (
        patch("routers.telephony_transfer.supabase", mock_sb),
        patch("services.supabase_service.supabase", mock_sb),
        patch("routers.telephony_transfer.sb_query", side_effect=lambda fn: fn()),
        patch("routers.telephony_transfer.load_yeastar_tenant_config", AsyncMock(return_value=config)),
    ):
        yield mock_sb


@pytest.mark.asyncio
async def test_internal_extension_idle_transfers(_common_patches):
    """Extensión interna idle → llama transfer_call, devuelve ok."""
    mock_client = AsyncMock()
    mock_client.get_extension_status = AsyncMock(return_value="idle")
    mock_client.transfer_call = AsyncMock(return_value={"errcode": 0})
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("routers.telephony_transfer.is_internal_extension", AsyncMock(return_value=True)),
        patch("routers.telephony_transfer.yeastar_client_from_config", return_value=mock_client),
    ):
        from routers.telephony_transfer import transfer_call_to_human
        from models.schemas import CallTransferRequest

        req = CallTransferRequest(
            room_name="empresa_42_encuesta_1",
            empresa_id=42,
            call_id="callid-123",
            extension="1001",
            survey_id=1,
        )
        result = await transfer_call_to_human(req)

    assert result["status"] == "ok"
    assert result["transfer_type"] == "internal"
    mock_client.transfer_call.assert_called_once()
    call_args = mock_client.transfer_call.call_args
    assert call_args[0][1] == "1001"


@pytest.mark.asyncio
async def test_internal_extension_busy_returns_409(_common_patches):
    """Extensión interna ocupada → 409, NO llama transfer_call."""
    mock_client = AsyncMock()
    mock_client.get_extension_status = AsyncMock(return_value="Busy")
    mock_client.transfer_call = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("routers.telephony_transfer.is_internal_extension", AsyncMock(return_value=True)),
        patch("routers.telephony_transfer.yeastar_client_from_config", return_value=mock_client),
    ):
        from routers.telephony_transfer import transfer_call_to_human
        from models.schemas import CallTransferRequest
        from fastapi.responses import JSONResponse

        req = CallTransferRequest(
            room_name="empresa_42_encuesta_1",
            empresa_id=42,
            call_id="callid-123",
            extension="1001",
            survey_id=1,
        )
        result = await transfer_call_to_human(req)

    assert isinstance(result, JSONResponse)
    assert result.status_code == 409
    mock_client.transfer_call.assert_not_called()


@pytest.mark.asyncio
async def test_external_number_valid_skips_status_check(_common_patches):
    """Número externo válido → salta check de estado, llama transfer_call normalizado."""
    mock_client = AsyncMock()
    mock_client.get_extension_status = AsyncMock()
    mock_client.transfer_call = AsyncMock(return_value={"errcode": 0})
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("routers.telephony_transfer.is_internal_extension", AsyncMock(return_value=False)),
        patch("routers.telephony_transfer.yeastar_client_from_config", return_value=mock_client),
    ):
        from routers.telephony_transfer import transfer_call_to_human
        from models.schemas import CallTransferRequest

        req = CallTransferRequest(
            room_name="empresa_42_encuesta_1",
            empresa_id=42,
            call_id="callid-123",
            extension="+34 612-34 56 78",
            survey_id=1,
        )
        result = await transfer_call_to_human(req)

    assert result["status"] == "ok"
    assert result["transfer_type"] == "external"
    assert result["extension_status"] == "skipped_external"
    assert result["target_extension"] == "+34612345678"
    mock_client.get_extension_status.assert_not_called()
    mock_client.transfer_call.assert_called_once()
    call_args = mock_client.transfer_call.call_args
    assert call_args[0][1] == "+34612345678"


@pytest.mark.asyncio
async def test_external_number_invalid_returns_400(_common_patches):
    """Número externo inválido → 400, NO llama transfer_call."""
    mock_client = AsyncMock()
    mock_client.transfer_call = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("routers.telephony_transfer.is_internal_extension", AsyncMock(return_value=False)),
        patch("routers.telephony_transfer.yeastar_client_from_config", return_value=mock_client),
    ):
        from routers.telephony_transfer import transfer_call_to_human
        from models.schemas import CallTransferRequest
        from fastapi import HTTPException as _HTTPException
        import pytest as _pytest

        req = CallTransferRequest(
            room_name="empresa_42_encuesta_1",
            empresa_id=42,
            call_id="callid-123",
            extension="abc",
            survey_id=1,
        )
        with _pytest.raises(_HTTPException) as exc_info:
            await transfer_call_to_human(req)

    assert exc_info.value.status_code == 400
    mock_client.transfer_call.assert_not_called()


@pytest.mark.asyncio
async def test_external_number_too_short_returns_400(_common_patches):
    """Número externo demasiado corto (< 6 dígitos) → 400."""
    mock_client = AsyncMock()
    mock_client.transfer_call = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("routers.telephony_transfer.is_internal_extension", AsyncMock(return_value=False)),
        patch("routers.telephony_transfer.yeastar_client_from_config", return_value=mock_client),
    ):
        from routers.telephony_transfer import transfer_call_to_human
        from models.schemas import CallTransferRequest
        from fastapi import HTTPException as _HTTPException
        import pytest as _pytest

        req = CallTransferRequest(
            room_name="empresa_42_encuesta_1",
            empresa_id=42,
            call_id="callid-123",
            extension="123",
            survey_id=1,
        )
        with _pytest.raises(_HTTPException) as exc_info:
            await transfer_call_to_human(req)

    assert exc_info.value.status_code == 400
    mock_client.transfer_call.assert_not_called()


@pytest.mark.asyncio
async def test_external_number_with_outbound_prefix(_common_patches):
    """Número externo con outbound_prefix → se antepone el prefijo al número."""
    mock_client = AsyncMock()
    mock_client.transfer_call = AsyncMock(return_value={"errcode": 0})
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("routers.telephony_transfer.is_internal_extension", AsyncMock(return_value=False)),
        patch("routers.telephony_transfer.yeastar_client_from_config", return_value=mock_client),
    ):
        from routers.telephony_transfer import transfer_call_to_human
        from models.schemas import CallTransferRequest

        req = CallTransferRequest(
            room_name="empresa_42_encuesta_1",
            empresa_id=42,
            call_id="callid-123",
            extension="612345678",
            survey_id=1,
            outbound_prefix="0",
        )
        result = await transfer_call_to_human(req)

    assert result["status"] == "ok"
    call_args = mock_client.transfer_call.call_args
    assert call_args[1]["outbound_prefix"] == "0"
