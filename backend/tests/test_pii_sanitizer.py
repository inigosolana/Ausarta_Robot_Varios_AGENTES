"""Tests de sanitización PII en transcripciones."""

from __future__ import annotations

from config import clear_settings_cache
from services.call_results_service import (
    prepare_narrative_text_for_storage,
    prepare_transcription_for_storage,
)
from utils.pii_sanitizer import sanitize_transcription_pii


def setup_function() -> None:
    clear_settings_cache()


def teardown_function() -> None:
    clear_settings_cache()


def test_sanitize_dni_and_email():
    raw = "Cliente: mi DNI es 12345678Z y mi email cliente@empresa.com"
    result = sanitize_transcription_pii(raw)
    assert "12345678Z" not in result.text
    assert "cliente@empresa.com" not in result.text
    assert "[REDACTED_DNI_NIE]" in result.text
    assert "[REDACTED_EMAIL]" in result.text
    assert result.redaction_count >= 2


def test_sanitize_credit_card_and_iban():
    raw = "Tarjeta 4532 1234 5678 9010 y cuenta ES7620770024003102575766"
    result = sanitize_transcription_pii(raw)
    assert "4532" not in result.text
    assert "ES7620770024003102575766" not in result.text
    assert "[REDACTED_CREDIT_CARD]" in result.text
    assert "[REDACTED_IBAN]" in result.text


def test_sanitize_spanish_phone():
    raw = "Llámeme al +34 612 345 678 cuando pueda"
    result = sanitize_transcription_pii(raw)
    assert "612" not in result.text or "[REDACTED_PHONE]" in result.text
    assert result.redaction_count >= 1


def test_sanitize_preserves_non_pii_survey_content():
    raw = "Cliente: Hola\nAgente: ¿Del 1 al 10, qué nota da?\nCliente: Un 8"
    result = sanitize_transcription_pii(raw)
    assert "Un 8" in result.text
    assert result.redaction_count == 0


def test_prepare_transcription_for_storage_none():
    assert prepare_transcription_for_storage(None) is None


def test_prepare_narrative_text_for_storage():
    text = "El cliente dio su email soporte@cliente.es en la llamada"
    sanitized = prepare_narrative_text_for_storage(text)
    assert sanitized is not None
    assert "soporte@cliente.es" not in sanitized
    assert "[REDACTED_EMAIL]" in sanitized


def test_sanitize_disabled_via_flag(monkeypatch):
    monkeypatch.setenv("PII_SANITIZATION_ENABLED", "false")
    clear_settings_cache()
    raw = "email secreto@correo.com"
    result = sanitize_transcription_pii(raw)
    assert result.text == raw
    assert result.redaction_count == 0
