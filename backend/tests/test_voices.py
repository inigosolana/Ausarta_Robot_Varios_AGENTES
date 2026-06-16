import pytest

from services.cartesia_voices_service import (
    CURATED_VOICES,
    filter_voices_by_language,
    merge_voices,
    normalize_cartesia_voice,
)


def test_normalize_cartesia_voice_uses_curated_label():
    voice = normalize_cartesia_voice({"id": CURATED_VOICES[0]["id"], "name": "Ines"})
    assert voice["label"] == CURATED_VOICES[0]["label"]
    assert voice["language"] == "es"


def test_normalize_cartesia_voice_from_api():
    voice = normalize_cartesia_voice(
        {
            "id": "00000000-0000-0000-0000-000000000099",
            "name": "Test Voice",
            "language": "en",
            "gender": "masculine",
        }
    )
    assert voice["id"].endswith("99")
    assert voice["group"] == "Inglés"
    assert voice["source"] == "cartesia"


def test_merge_voices_keeps_curated():
    merged = merge_voices([])
    ids = {v["id"] for v in merged}
    assert CURATED_VOICES[0]["id"] in ids
    assert len(merged) >= len(CURATED_VOICES)


def test_filter_voices_by_language():
    voices = [
        {"id": "1", "language": "es", "label": "A"},
        {"id": "2", "language": "en", "label": "B"},
    ]
    filtered = filter_voices_by_language(voices, "es")
    assert len(filtered) == 1
    assert filtered[0]["id"] == "1"


@pytest.mark.asyncio
async def test_list_voices_fallback_without_api_key(monkeypatch):
    from services import cartesia_voices_service

    monkeypatch.delenv("CARTESIA_API_KEY", raising=False)

    async def no_cache():
        return None

    monkeypatch.setattr(cartesia_voices_service, "_read_cache", no_cache)

    result = await cartesia_voices_service.list_voices()
    assert result["source"] == "fallback"
    assert result["count"] >= len(CURATED_VOICES)
    assert result["default_voice_id"]
