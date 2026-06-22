"""Tests unitarios para agents.post_call_processor."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.post_call_processor import finalize_call_session


@pytest.fixture(autouse=True)
def _suppress_background_tasks(monkeypatch):
    """Evita tareas fire-and-forget (upsert contacto) en tests unitarios."""
    def _fake_create_task(coro):
        if hasattr(coro, "close"):
            coro.close()
        return MagicMock()

    monkeypatch.setattr("agents.post_call_processor.asyncio.create_task", _fake_create_task)


def _make_call_session(
    *,
    transcript: str = "",
    data_saved: bool = False,
    survey_id: str = "123",
    agent_type: str = "ENCUESTA_NUMERICA",
    inbound: bool = False,
) -> SimpleNamespace:
    agent_config: dict = {
        "agent_type": agent_type,
        "empresa_id": 1,
        "name": "Test Agent",
    }
    if inbound:
        agent_config["call_direction"] = "inbound"

    return SimpleNamespace(
        job_id="job-test",
        survey_id=survey_id,
        room_name="llamada_ausarta_123",
        language="es",
        call_start_time=time.time() - 30,
        session=object(),
        agent_config=agent_config,
        agent_instance=SimpleNamespace(data_saved=data_saved, _detected_customer_name=""),
        lang_state={"active_lang": "es"},
        transcript_snapshot={"transcript": "", "raw": []},
        _build_transcript_from_event_buffer=lambda: ([], transcript),
    )


@pytest.mark.asyncio
async def test_finalize_no_transcript_enqueues_fallback(monkeypatch):
    cs = _make_call_session(transcript="", data_saved=False)
    enqueue_mock = AsyncMock(return_value="job-1")
    monkeypatch.setattr(
        "agents.post_call_processor.enqueue_guardar_encuesta",
        enqueue_mock,
    )
    monkeypatch.setattr(
        "agents.post_call_processor._extract_transcript_from_session",
        lambda _session: ([], ""),
    )

    await finalize_call_session(cs)

    enqueue_mock.assert_awaited_once()
    payload = enqueue_mock.await_args.args[0]
    assert payload["id_encuesta"] == 123
    assert payload["status"] == "no_contesta"
    assert payload["datos_extra"]["sentimiento_cliente"] == "Neutral"
    assert payload["datos_extra"]["idioma"] == "es"


@pytest.mark.asyncio
async def test_finalize_with_transcript_and_data_saved_enqueues_extras(monkeypatch):
    cs = _make_call_session(transcript="Cliente: Hola\nAgente: Buenas", data_saved=True)
    enqueue_mock = AsyncMock(return_value="job-2")
    analyze_mock = AsyncMock(
        return_value=(
            "completada",
            {"sentimiento_cliente": "Positivo", "idioma": "es", "telefono": "+34600111222"},
        )
    )
    monkeypatch.setattr("agents.post_call_processor.enqueue_guardar_encuesta", enqueue_mock)
    monkeypatch.setattr("agents.post_call_processor.analyze_call_disposition", analyze_mock)
    monkeypatch.setattr(
        "agents.post_call_processor._extract_transcript_from_session",
        lambda _session: ([{"role": "user", "content": "Hola"}], "Cliente: Hola"),
    )

    await finalize_call_session(cs)

    analyze_mock.assert_awaited_once()
    enqueue_mock.assert_awaited_once()
    payload = enqueue_mock.await_args.args[0]
    assert payload["id_encuesta"] == 123
    assert payload["transcription"] == "Cliente: Hola"
    assert payload["datos_extra"]["sentimiento_cliente"] == "Positivo"
    assert "status" not in payload


@pytest.mark.asyncio
async def test_finalize_without_data_saved_uses_analyzer_disposition(monkeypatch):
    cs = _make_call_session(transcript="Cliente: Adiós", data_saved=False)
    enqueue_mock = AsyncMock(return_value="job-3")
    analyze_mock = AsyncMock(
        return_value=(
            "parcial",
            {"sentimiento_cliente": "Neutral", "idioma": "es"},
        )
    )
    monkeypatch.setattr("agents.post_call_processor.enqueue_guardar_encuesta", enqueue_mock)
    monkeypatch.setattr("agents.post_call_processor.analyze_call_disposition", analyze_mock)
    monkeypatch.setattr(
        "agents.post_call_processor._extract_transcript_from_session",
        lambda _session: ([], "Cliente: Adiós"),
    )

    await finalize_call_session(cs)

    payload = enqueue_mock.await_args.args[0]
    assert payload["status"] == "parcial"
    assert payload["comentarios"] == "Llamada parcial via post-call"


@pytest.mark.asyncio
async def test_finalize_uses_transcript_snapshot_when_session_empty(monkeypatch):
    cs = _make_call_session(transcript="", data_saved=False)
    cs.transcript_snapshot = {
        "transcript": "Cliente: desde snapshot\n",
        "raw": [{"role": "user", "content": "desde snapshot"}],
    }
    enqueue_mock = AsyncMock(return_value="job-4")
    analyze_mock = AsyncMock(return_value=("completada", {"sentimiento_cliente": "Positivo", "idioma": "es"}))
    monkeypatch.setattr("agents.post_call_processor.enqueue_guardar_encuesta", enqueue_mock)
    monkeypatch.setattr("agents.post_call_processor.analyze_call_disposition", analyze_mock)
    monkeypatch.setattr(
        "agents.post_call_processor._extract_transcript_from_session",
        lambda _session: ([], ""),
    )

    await finalize_call_session(cs)

    analyze_mock.assert_awaited_once()
    assert "snapshot" in enqueue_mock.await_args.args[0]["transcription"]


@pytest.mark.asyncio
async def test_finalize_inbound_applies_inbound_datos_extra(monkeypatch):
    cs = _make_call_session(transcript="", data_saved=False, inbound=True)
    enqueue_mock = AsyncMock(return_value="job-5")
    monkeypatch.setattr("agents.post_call_processor.enqueue_guardar_encuesta", enqueue_mock)
    monkeypatch.setattr(
        "agents.post_call_processor._extract_transcript_from_session",
        lambda _session: ([], ""),
    )
    monkeypatch.setattr(
        "agents.post_call_processor._build_inbound_datos_extra",
        lambda _cfg, _room, extra: {**(extra or {}), "telefono": "+34999999999"},
    )
    monkeypatch.setattr(
        "utils.inbound_call.normalize_inbound_disposition",
        lambda disposition, *_args: disposition,
    )
    monkeypatch.setattr(
        "utils.inbound_call.build_inbound_fallback_comentarios",
        lambda *_args, **_kwargs: "Comentario inbound",
    )

    await finalize_call_session(cs)

    payload = enqueue_mock.await_args.args[0]
    assert payload["datos_extra"]["telefono"] == "+34999999999"
    assert payload["comentarios"] == "Comentario inbound"


@pytest.mark.asyncio
async def test_finalize_with_transcript_sanitizes_pii_before_persist(monkeypatch):
    cs = _make_call_session(
        transcript="Cliente: mi email es cliente@empresa.com y DNI 12345678Z",
        data_saved=True,
    )
    enqueue_mock = AsyncMock(return_value="job-pii")
    analyze_mock = AsyncMock(
        return_value=("completada", {"sentimiento_cliente": "Positivo", "idioma": "es"}),
    )
    monkeypatch.setattr("agents.post_call_processor.enqueue_guardar_encuesta", enqueue_mock)
    monkeypatch.setattr("agents.post_call_processor.analyze_call_disposition", analyze_mock)
    monkeypatch.setattr(
        "agents.post_call_processor._extract_transcript_from_session",
        lambda _session: ([], cs._build_transcript_from_event_buffer()[1]),
    )

    await finalize_call_session(cs)

    payload = enqueue_mock.await_args.args[0]
    assert "cliente@empresa.com" not in payload["transcription"]
    assert "12345678Z" not in payload["transcription"]
    assert "[REDACTED_EMAIL]" in payload["transcription"]
    analyze_mock.assert_awaited_once()
    assert "cliente@empresa.com" in analyze_mock.await_args.args[0]
