"""Tests OpenTelemetry tracing utilities."""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _reset_tracing(monkeypatch):
    import utils.tracing as tracing

    tracing.shutdown_tracing()
    monkeypatch.setenv("OTEL_ENABLED", "false")
    tracing._tracer_provider = None
    tracing._fastapi_instrumented = False
    tracing._aiohttp_instrumented = False
    yield
    tracing.shutdown_tracing()


def test_disabled_tracing_is_noop():
    from utils.tracing import (
        current_trace_id,
        get_tracer,
        inject_context_carrier,
        is_tracing_enabled,
    )

    assert is_tracing_enabled() is False
    assert inject_context_carrier() == {}
    assert current_trace_id() is None
    tracer = get_tracer()
    with tracer.start_as_current_span("test"):
        assert current_trace_id() is None


def test_tracing_enabled_integration(monkeypatch):
    """Un solo init_tracing por proceso de test (limitación OTEL global)."""
    monkeypatch.setenv("OTEL_ENABLED", "true")
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    import utils.tracing as tracing_mod
    from utils.tracing import (
        current_trace_id,
        enrich_metadata_with_trace,
        extract_carrier_from_metadata,
        get_tracer,
        init_tracing,
        inject_context_carrier,
        shutdown_tracing,
        voice_call_context,
        wrap_arq_task,
    )

    exporter = InMemorySpanExporter()
    assert init_tracing(service_name="test-tracing") is True
    tracing_mod._tracer_provider.add_span_processor(SimpleSpanProcessor(exporter))

    tracer = get_tracer()
    with tracer.start_as_current_span("http.request"):
        enriched = enrich_metadata_with_trace({"survey_id": "42", "empresa_id": "7"})
        assert "otel_carrier" in enriched
        assert enriched.get("traceparent")
        carrier = extract_carrier_from_metadata(enriched)
        assert carrier.get("traceparent") == enriched["traceparent"]

        async def _voice():
            async with voice_call_context(
                job_id="job-1",
                room_name="room-abc",
                empresa_id=9,
                survey_id=100,
                carrier=carrier,
            ):
                return current_trace_id()

        trace_id = asyncio.run(_voice())
        assert trace_id is not None
        assert len(trace_id) == 32

        seen: dict[str, str | None] = {"trace_id": None}

        async def sample_task(ctx, value: int, **kwargs):
            seen["trace_id"] = current_trace_id()
            return value * 2

        wrapped = wrap_arq_task(sample_task)
        job_carrier = inject_context_carrier()

        async def _arq():
            return await wrapped({"job_id": "j1"}, 3, _otel_carrier=job_carrier)

        assert asyncio.run(_arq()) == 6
        assert seen["trace_id"] is not None

    shutdown_tracing()
    span_names = {span.name for span in exporter.get_finished_spans()}
    assert "voice.call" in span_names
    assert any(name.startswith("arq.") for name in span_names)
