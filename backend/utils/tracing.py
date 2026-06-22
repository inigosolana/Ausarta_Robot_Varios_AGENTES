"""
OpenTelemetry — trazabilidad distribuida Ausarta Voice Agent API v2.

Flujo:
  FastAPI request → trace root (FastAPIInstrumentor)
       ↓ metadata traceparent / otel_carrier
  LiveKit agent entrypoint → span voice.call (STT / LLM / TTS hijos)
       ↓ otel_carrier en kwargs ARQ
  Worker ARQ → span arq.<task>

Variables de entorno:
  OTEL_ENABLED=true|false
  OTEL_SERVICE_NAME=ausarta-voice-api
  OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
  OTEL_EXPORTER_OTLP_PROTOCOL=grpc|http
  OTEL_TRACES_SAMPLER_ARG=1.0
"""
from __future__ import annotations

import contextlib
import contextvars
import logging
import os
from typing import Any, AsyncIterator, Awaitable, Callable, Iterator, TypeVar

logger = logging.getLogger("tracing")

OTEL_CARRIER_KEY = "_otel_carrier"
TRACEPARENT_METADATA_KEY = "traceparent"
OTEL_CARRIER_METADATA_KEY = "otel_carrier"

_tracer_provider: Any | None = None
_fastapi_instrumented = False
_aiohttp_instrumented = False

# Contexto de llamada activa (agente LiveKit / logs JSON)
current_call_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_call_id", default=None
)
current_room_name: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "current_room_name", default=None
)

T = TypeVar("T")


def is_tracing_enabled() -> bool:
    return os.getenv("OTEL_ENABLED", "false").strip().lower() in ("1", "true", "yes")


def _service_name() -> str:
    return (
        os.getenv("OTEL_SERVICE_NAME", "").strip()
        or os.getenv("SERVICE_NAME", "").strip()
        or "ausarta-voice-api"
    )


def _parse_headers_env() -> dict[str, str]:
    raw = os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "").strip()
    if not raw:
        return {}
    headers: dict[str, str] = {}
    for part in raw.split(","):
        piece = part.strip()
        if not piece or "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        headers[key.strip()] = value.strip()
    return headers


def init_tracing(*, service_name: str | None = None) -> bool:
    """
    Inicializa TracerProvider + exportador OTLP.
    Idempotente. Devuelve True si el tracing quedó activo.
    """
    global _tracer_provider

    if not is_tracing_enabled():
        logger.info("OpenTelemetry desactivado (OTEL_ENABLED=false)")
        return False

    if _tracer_provider is not None:
        return True

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter as GrpcExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter as HttpExporter,
        )
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import ParentBasedTraceIdRatio
    except ImportError as exc:
        logger.warning("OpenTelemetry no instalado — tracing omitido: %s", exc)
        return False

    name = service_name or _service_name()
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://localhost:4317").strip()
    protocol = os.getenv("OTEL_EXPORTER_OTLP_PROTOCOL", "grpc").strip().lower()
    sample_ratio = float(os.getenv("OTEL_TRACES_SAMPLER_ARG", "1.0"))

    resource = Resource.create(
        {
            "service.name": name,
            "service.version": os.getenv("OTEL_SERVICE_VERSION", "2.0.0"),
            "deployment.environment": os.getenv("ENVIRONMENT", "production"),
        }
    )
    provider = TracerProvider(
        resource=resource,
        sampler=ParentBasedTraceIdRatio(sample_ratio),
    )

    headers = _parse_headers_env()
    if protocol == "http":
        exporter = HttpExporter(endpoint=endpoint, headers=headers or None)
    else:
        insecure = os.getenv("OTEL_EXPORTER_OTLP_INSECURE", "true").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        exporter = GrpcExporter(endpoint=endpoint, headers=headers or None, insecure=insecure)

    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _tracer_provider = provider
    logger.info(
        "OpenTelemetry activo | service=%s endpoint=%s protocol=%s sample=%.2f",
        name,
        endpoint,
        protocol,
        sample_ratio,
    )
    return True


def shutdown_tracing() -> None:
    """Flush y cierre del TracerProvider."""
    global _tracer_provider
    if _tracer_provider is None:
        return
    try:
        _tracer_provider.shutdown()
    except Exception as exc:
        logger.debug("shutdown tracing: %s", exc)
    finally:
        _tracer_provider = None


def instrument_fastapi(app: Any) -> None:
    """Instrumenta FastAPI (spans HTTP + propagación W3C)."""
    global _fastapi_instrumented
    if _fastapi_instrumented or not is_tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

        excluded = os.getenv("OTEL_FASTAPI_EXCLUDED_URLS", "/health,/")
        FastAPIInstrumentor.instrument_app(
            app,
            excluded_urls=excluded,
        )
        _fastapi_instrumented = True
        logger.info("FastAPI instrumentado (excluded=%s)", excluded)
    except ImportError as exc:
        logger.warning("FastAPI instrumentation no disponible: %s", exc)


def instrument_aiohttp_client() -> None:
    """Spans automáticos en cliente aiohttp (Groq, webhooks, etc.)."""
    global _aiohttp_instrumented
    if _aiohttp_instrumented or not is_tracing_enabled():
        return
    try:
        from opentelemetry.instrumentation.aiohttp_client import AioHttpClientInstrumentor

        AioHttpClientInstrumentor().instrument()
        _aiohttp_instrumented = True
        logger.info("aiohttp client instrumentado")
    except ImportError as exc:
        logger.warning("aiohttp instrumentation no disponible: %s", exc)


def get_tracer(name: str = "ausarta") -> Any:
    if not is_tracing_enabled():
        return _NoOpTracer()
    from opentelemetry import trace

    return trace.get_tracer(name)


def current_trace_id() -> str | None:
    """Trace-ID hex (32 chars) del span activo, o None."""
    if not is_tracing_enabled():
        return None
    from opentelemetry import trace

    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.trace_id, "032x")


def current_span_id() -> str | None:
    if not is_tracing_enabled():
        return None
    from opentelemetry import trace

    span = trace.get_current_span()
    ctx = span.get_span_context()
    if not ctx or not ctx.is_valid:
        return None
    return format(ctx.span_id, "016x")


def inject_context_carrier() -> dict[str, str]:
    """Serializa el contexto OTEL activo para ARQ / metadata LiveKit."""
    if not is_tracing_enabled():
        return {}
    from opentelemetry.propagate import inject

    carrier: dict[str, str] = {}
    inject(carrier)
    return carrier


def extract_context_carrier(carrier: dict[str, str] | None) -> Any:
    """Devuelve OTEL Context desde carrier W3C (o None)."""
    if not carrier or not is_tracing_enabled():
        return None
    from opentelemetry.propagate import extract

    return extract(carrier)


def enrich_metadata_with_trace(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """Añade traceparent + otel_carrier al metadata de sala LiveKit."""
    out = dict(metadata or {})
    carrier = inject_context_carrier()
    if not carrier:
        return out
    out[OTEL_CARRIER_METADATA_KEY] = dict(carrier)
    if carrier.get("traceparent"):
        out[TRACEPARENT_METADATA_KEY] = carrier["traceparent"]
    if carrier.get("tracestate"):
        out["tracestate"] = carrier["tracestate"]
    trace_id = current_trace_id()
    if trace_id:
        out["trace_id"] = trace_id
    return out


def extract_carrier_from_metadata(metadata: dict[str, Any] | None) -> dict[str, str]:
    """Reconstruye carrier desde metadata de job LiveKit."""
    if not metadata:
        return {}
    carrier: dict[str, str] = {}
    nested = metadata.get(OTEL_CARRIER_METADATA_KEY)
    if isinstance(nested, dict):
        carrier.update({str(k): str(v) for k, v in nested.items()})
    tp = metadata.get(TRACEPARENT_METADATA_KEY) or metadata.get("traceparent")
    if tp:
        carrier["traceparent"] = str(tp)
    ts = metadata.get("tracestate")
    if ts:
        carrier["tracestate"] = str(ts)
    return carrier


def inject_carrier_into_kwargs(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Inyecta carrier OTEL en kwargs de enqueue ARQ (sin sobrescribir)."""
    out = dict(kwargs)
    if OTEL_CARRIER_KEY not in out:
        carrier = inject_context_carrier()
        if carrier:
            out[OTEL_CARRIER_KEY] = carrier
    return out


@contextlib.contextmanager
def attach_context(carrier: dict[str, str] | None) -> Iterator[None]:
    """Context manager: adjunta contexto OTEL propagado."""
    if not carrier or not is_tracing_enabled():
        yield
        return
    from opentelemetry import context

    token = context.attach(extract_context_carrier(carrier))
    try:
        yield
    finally:
        context.detach(token)


@contextlib.asynccontextmanager
async def traced_span(
    name: str,
    attributes: dict[str, Any] | None = None,
    *,
    kind: str = "internal",
) -> AsyncIterator[Any]:
    """Span async manual (STT/LLM/TTS/voice.call)."""
    if not is_tracing_enabled():
        yield _NoOpSpan()
        return

    from opentelemetry import trace
    from opentelemetry.trace import SpanKind

    kind_map = {
        "internal": SpanKind.INTERNAL,
        "client": SpanKind.CLIENT,
        "server": SpanKind.SERVER,
        "producer": SpanKind.PRODUCER,
        "consumer": SpanKind.CONSUMER,
    }
    tracer = get_tracer("ausarta.voice")
    with tracer.start_as_current_span(
        name,
        kind=kind_map.get(kind, SpanKind.INTERNAL),
        attributes=_safe_attributes(attributes),
    ) as span:
        yield span


@contextlib.asynccontextmanager
async def voice_call_context(
    *,
    job_id: str,
    room_name: str,
    empresa_id: str | int | None = None,
    survey_id: str | int | None = None,
    carrier: dict[str, str] | None = None,
) -> AsyncIterator[Any]:
    """
    Span raíz del ciclo de vida de una llamada LiveKit.
    Propaga call_id / room_name a ContextVars para logs.
    """
    call_token = current_call_id.set(str(job_id))
    room_token = current_room_name.set(str(room_name))
    attrs = {
        "call.job_id": str(job_id),
        "call.room_name": str(room_name),
        "call.empresa_id": str(empresa_id or ""),
        "call.survey_id": str(survey_id or ""),
    }
    try:
        with attach_context(carrier):
            async with traced_span("voice.call", attrs, kind="server") as span:
                trace_id = current_trace_id()
                if trace_id and hasattr(span, "set_attribute"):
                    span.set_attribute("call.trace_id", trace_id)
                logger.info(
                    "trace voice.call start job=%s room=%s trace_id=%s",
                    job_id,
                    room_name,
                    trace_id or "n/a",
                )
                yield span
    finally:
        current_call_id.reset(call_token)
        current_room_name.reset(room_token)


def wrap_arq_task(
    fn: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    """Decorador/wrapper: restaura contexto OTEL desde kwargs ARQ."""

    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> T:
        carrier = kwargs.pop(OTEL_CARRIER_KEY, None)
        job_id = str(ctx.get("job_id", ""))
        fn_name = getattr(fn, "__name__", "task")
        attrs = {"arq.job_id": job_id, "arq.function": fn_name}
        with attach_context(carrier if isinstance(carrier, dict) else None):
            async with traced_span(f"arq.{fn_name}", attrs, kind="consumer"):
                return await fn(ctx, *args, **kwargs)

    wrapper.__name__ = getattr(fn, "__name__", "arq_task")
    wrapper.__qualname__ = getattr(fn, "__qualname__", wrapper.__name__)
    wrapper.__doc__ = fn.__doc__
    return wrapper


def _safe_attributes(attributes: dict[str, Any] | None) -> dict[str, str | int | float | bool]:
    if not attributes:
        return {}
    safe: dict[str, str | int | float | bool] = {}
    for key, value in attributes.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            safe[str(key)] = value
        else:
            safe[str(key)] = str(value)
    return safe


class _NoOpSpan:
    def set_attribute(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def add_event(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    def record_exception(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _NoOpTracer:
    @contextlib.contextmanager
    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> Iterator[_NoOpSpan]:
        yield _NoOpSpan()
