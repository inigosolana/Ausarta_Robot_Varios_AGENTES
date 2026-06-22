"""Tests del Customer Anger Score (Groq 8B post-llamada)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.customer_anger_service import (
    CustomerAngerResult,
    analyze_customer_anger,
    merge_anger_into_datos_extra,
)


@pytest.mark.asyncio
async def test_analyze_customer_anger_empty_transcript():
    result = await analyze_customer_anger("")
    assert result.skipped is True
    assert result.customer_anger_score == 1
    assert result.requires_urgent_human_attention is False


@pytest.mark.asyncio
async def test_analyze_customer_anger_disabled(monkeypatch):
    monkeypatch.setenv("CUSTOMER_ANGER_ANALYSIS_ENABLED", "false")
    result = await analyze_customer_anger("Cliente muy enfadado")
    assert result.skipped is True
    assert result.reason == "disabled"


@pytest.mark.asyncio
async def test_analyze_customer_anger_groq_success(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("CUSTOMER_ANGER_ANALYSIS_ENABLED", "true")

    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.text = AsyncMock(return_value="")
    mock_resp.json = AsyncMock(
        return_value={
            "choices": [
                {
                    "message": {
                        "content": (
                            '{"customer_anger_score": 9, '
                            '"requires_urgent_human_attention": true, '
                            '"anger_signals": ["amenaza de baja"]}'
                        )
                    }
                }
            ]
        }
    )
    mock_resp.__aenter__ = AsyncMock(return_value=mock_resp)
    mock_resp.__aexit__ = AsyncMock(return_value=False)

    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_resp)
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)

    breaker = MagicMock()
    breaker.is_open = AsyncMock(return_value=False)
    breaker.record_success = AsyncMock()
    breaker.record_failure = AsyncMock()

    @asynccontextmanager
    async def _noop_span(*_args, **_kwargs):
        yield None

    with (
        patch("services.customer_anger_service.aiohttp.ClientSession", return_value=mock_session),
        patch("services.provider_circuit_service.groq_llm_breaker", AsyncMock(return_value=breaker)),
        patch("utils.tracing.traced_span", _noop_span),
    ):
        result = await analyze_customer_anger("Voy a denunciaros si no me solucionáis esto ya")

    assert result.skipped is False
    assert result.customer_anger_score == 9
    assert result.requires_urgent_human_attention is True
    assert "amenaza" in result.anger_signals[0]
    breaker.record_success.assert_awaited_once()


def test_merge_anger_into_datos_extra():
    anger = CustomerAngerResult(
        customer_anger_score=8,
        requires_urgent_human_attention=True,
        anger_signals=("tono agresivo",),
    )
    merged = merge_anger_into_datos_extra({"idioma": "es"}, anger)
    assert merged["idioma"] == "es"
    assert merged["customer_anger_score"] == 8
    assert merged["requires_urgent_human_attention"] is True
    assert merged["anger_signals"] == ["tono agresivo"]


@pytest.mark.asyncio
async def test_maybe_enqueue_urgent_anger_alert(monkeypatch):
    monkeypatch.setenv("CUSTOMER_ANGER_TELEGRAM_ALERTS", "true")
    enqueue = AsyncMock(return_value="job-tg")
    anger = CustomerAngerResult(
        customer_anger_score=9,
        requires_urgent_human_attention=True,
    )

    with patch("services.queue_service.enqueue_telegram_alert", enqueue):
        from services.customer_anger_service import maybe_enqueue_urgent_anger_alert

        await maybe_enqueue_urgent_anger_alert(
            empresa_id=3,
            encuesta_id=99,
            anger=anger,
            telefono="+34600",
        )

    enqueue.assert_awaited_once()
    assert "score=9" in enqueue.await_args.args[0]
