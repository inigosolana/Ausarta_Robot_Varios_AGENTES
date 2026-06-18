"""Tests de carga de Settings tras renombrar campos."""

import os

import pytest


def test_settings_field_names_and_env_aliases(monkeypatch):
    monkeypatch.setenv("BRIDGE_SERVER_URL_INTERNAL", "http://localhost:8001")
    monkeypatch.setenv("AGENT_GREETING_DELAY_SECONDS", "0.42")
    monkeypatch.setenv("DEFAULT_CARTESIA_VOICE_ID", "voice-test-id")
    monkeypatch.setenv("DRIP_COOLDOWN_MIN_SECONDS", "90")
    monkeypatch.setenv("DRIP_COOLDOWN_MAX_SECONDS", "150")

    from config import clear_settings_cache, get_settings

    clear_settings_cache()
    settings = get_settings()

    assert settings.agent_greeting_delay == 0.42
    assert settings.default_cartesia_voice == "voice-test-id"
    assert settings.drip_cooldown_min == 90
    assert settings.drip_cooldown_max == 150
    assert settings.bridge_server_url_internal == "http://localhost:8001"

    clear_settings_cache()
