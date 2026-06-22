import pytest

from utils.sip_edge_config import (
    normalize_e164,
    validate_outbound_destination,
)


def test_normalize_e164_spanish_mobile():
    assert normalize_e164("612345678") == "+612345678"
    assert normalize_e164("+34612345678") == "+34612345678"
    assert normalize_e164("0034612345678") == "+34612345678"


def test_validate_blocks_premium_prefix(monkeypatch):
    monkeypatch.setenv("SIP_OUTBOUND_BLOCK_PREMIUM", "true")
    with pytest.raises(ValueError, match="tarificación"):
        validate_outbound_destination("+34903123456")


def test_validate_allowed_country(monkeypatch):
    monkeypatch.setenv("SIP_OUTBOUND_ALLOWED_COUNTRY_CODES", "34")
    assert validate_outbound_destination("+34612345678") == "+34612345678"
    with pytest.raises(ValueError, match="País no permitido"):
        validate_outbound_destination("+14155552671")
