"""
Análisis de ira del cliente (Customer Anger Score) vía LLM rápido (Groq 8B).

Se ejecuta al finalizar la llamada, sobre la transcripción completa y ANTES
de persistir en Supabase (PII sanitize ocurre después en post_call_processor).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from typing import Any, Final

import aiohttp

from config import settings

logger = logging.getLogger("customer-anger")

_GROQ_CHAT_URL: Final[str] = "https://api.groq.com/openai/v1/chat/completions"

_SYSTEM_PROMPT: Final[str] = (
    "Eres un analista de experiencia de cliente en llamadas telefónicas B2B. "
    "Evalúa el nivel de enfado/frustración del CLIENTE (no del agente). "
    "Responde ÚNICAMENTE con JSON válido sin markdown.\n\n"
    "Schema:\n"
    "{\n"
    '  "customer_anger_score": <entero 1-10>,\n'
    '  "requires_urgent_human_attention": <boolean>,\n'
    '  "anger_signals": <array de strings, máx 5, citas breves o señales detectadas>\n'
    "}\n\n"
    "Escala customer_anger_score:\n"
    "  1-2: tranquilo, colaborativo\n"
    "  3-4: leve molestia\n"
    "  5-6: frustración clara\n"
    "  7-8: enfado alto, tono agresivo o amenazas de baja\n"
    "  9-10: furia extrema, insultos, amenazas legales o exige supervisor YA\n\n"
    "requires_urgent_human_attention=true si:\n"
    "  - customer_anger_score >= 8, O\n"
    "  - amenaza explícita de denuncia/cancelación inmediata/supervisor, O\n"
    "  - el cliente dice que no volverá a llamar por mala experiencia\n"
)


@dataclass(frozen=True, slots=True)
class CustomerAngerResult:
    customer_anger_score: int
    requires_urgent_human_attention: bool
    anger_signals: tuple[str, ...] = ()
    model: str = ""
    latency_ms: float = 0.0
    skipped: bool = False
    reason: str | None = None

    def to_datos_extra_fields(self) -> dict[str, Any]:
        return {
            "customer_anger_score": self.customer_anger_score,
            "requires_urgent_human_attention": self.requires_urgent_human_attention,
            "anger_signals": list(self.anger_signals),
        }

    def to_agent_results_analysis(self) -> dict[str, Any]:
        return {
            "customer_anger_score": self.customer_anger_score,
            "requires_urgent_human_attention": self.requires_urgent_human_attention,
            "anger_signals": list(self.anger_signals),
        }


def _is_enabled() -> bool:
    return os.getenv("CUSTOMER_ANGER_ANALYSIS_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _urgent_threshold() -> int:
    try:
        return max(1, min(10, int(os.getenv("CUSTOMER_ANGER_URGENT_THRESHOLD", "8"))))
    except (TypeError, ValueError):
        return 8


def _default_neutral() -> CustomerAngerResult:
    return CustomerAngerResult(
        customer_anger_score=1,
        requires_urgent_human_attention=False,
        anger_signals=(),
        skipped=True,
        reason="no_transcript",
    )


def _parse_anger_json(raw: str) -> CustomerAngerResult | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None

    try:
        score = int(payload.get("customer_anger_score", 1))
    except (TypeError, ValueError):
        score = 1
    score = max(1, min(10, score))

    urgent_raw = payload.get("requires_urgent_human_attention", False)
    requires_urgent = bool(urgent_raw) if not isinstance(urgent_raw, str) else urgent_raw.lower() in (
        "1",
        "true",
        "yes",
    )

    threshold = _urgent_threshold()
    if score >= threshold:
        requires_urgent = True

    signals_raw = payload.get("anger_signals") or []
    signals: list[str] = []
    if isinstance(signals_raw, list):
        for item in signals_raw[:5]:
            text = str(item or "").strip()
            if text:
                signals.append(text[:200])

    return CustomerAngerResult(
        customer_anger_score=score,
        requires_urgent_human_attention=requires_urgent,
        anger_signals=tuple(signals),
    )


def merge_anger_into_datos_extra(
    datos_extra: dict[str, Any] | None,
    anger: CustomerAngerResult | None,
) -> dict[str, Any]:
    """Fusiona campos de ira en datos_extra para persistencia y agent_results."""
    out: dict[str, Any] = dict(datos_extra or {})
    if anger is None:
        return out
    out.update(anger.to_datos_extra_fields())
    return out


async def analyze_customer_anger(transcript: str) -> CustomerAngerResult:
    """
    Clasifica enfado del cliente. Devuelve resultado neutro si está desactivado
    o no hay API key (no bloquea el post-procesado).
    """
    import time

    text = (transcript or "").strip()
    if not text:
        return _default_neutral()

    if not _is_enabled():
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="disabled",
        )

    groq_api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not groq_api_key:
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="no_groq_key",
        )

    from services.provider_circuit_service import groq_llm_breaker

    breaker = await groq_llm_breaker()
    if await breaker.is_open():
        logger.info("Análisis de ira omitido: circuit %s abierto", breaker.name)
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="circuit_open",
        )

    model = os.getenv("CUSTOMER_ANGER_MODEL", settings.semantic_router_model).strip()
    timeout_s = float(os.getenv("CUSTOMER_ANGER_TIMEOUT_MS", "400")) / 1000.0
    max_chars = int(os.getenv("CUSTOMER_ANGER_MAX_TRANSCRIPT_CHARS", "12000"))
    snippet = text if len(text) <= max_chars else text[-max_chars:]

    payload = {
        "model": model,
        "temperature": 0.0,
        "max_tokens": 128,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": f"Transcripción de la llamada:\n{snippet}"},
        ],
    }
    headers = {
        "Authorization": f"Bearer {groq_api_key}",
        "Content-Type": "application/json",
    }

    started = time.perf_counter()
    try:
        from utils.tracing import traced_span

        async with traced_span(
            "llm.groq.customer_anger",
            {"llm.model": model, "llm.provider": "groq"},
            kind="client",
        ):
            async with aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=timeout_s)
            ) as session:
                async with session.post(_GROQ_CHAT_URL, headers=headers, json=payload) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        logger.warning(
                            "Customer anger HTTP %s: %s",
                            resp.status,
                            body[:200],
                        )
                        await breaker.record_failure(RuntimeError(f"HTTP {resp.status}"))
                        return CustomerAngerResult(
                            customer_anger_score=1,
                            requires_urgent_human_attention=False,
                            skipped=True,
                            reason=f"http_{resp.status}",
                        )
                    data = await resp.json()
    except asyncio.TimeoutError as exc:
        logger.debug("Customer anger timeout (%.0f ms)", timeout_s * 1000)
        await breaker.record_failure(exc, extreme=True)
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="timeout",
        )
    except aiohttp.ClientError as exc:
        logger.warning("Customer anger network error: %s", exc)
        await breaker.record_failure(exc)
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="network",
        )
    except Exception as exc:
        logger.warning("Customer anger unexpected error: %s", exc)
        await breaker.record_failure(exc)
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="error",
        )

    await breaker.record_success()
    latency_ms = (time.perf_counter() - started) * 1000.0

    try:
        raw = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="bad_response",
            latency_ms=latency_ms,
        )

    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(raw or "").strip(), flags=re.IGNORECASE)
    parsed = _parse_anger_json(cleaned)
    if parsed is None:
        logger.debug("Customer anger JSON inválido: %s", cleaned[:120])
        return CustomerAngerResult(
            customer_anger_score=1,
            requires_urgent_human_attention=False,
            skipped=True,
            reason="invalid_json",
            latency_ms=latency_ms,
            model=model,
        )

    result = CustomerAngerResult(
        customer_anger_score=parsed.customer_anger_score,
        requires_urgent_human_attention=parsed.requires_urgent_human_attention,
        anger_signals=parsed.anger_signals,
        model=model,
        latency_ms=latency_ms,
    )
    logger.info(
        "Customer anger score=%s urgent=%s signals=%s latency_ms=%.0f",
        result.customer_anger_score,
        result.requires_urgent_human_attention,
        len(result.anger_signals),
        result.latency_ms,
    )
    return result


async def maybe_enqueue_urgent_anger_alert(
    *,
    empresa_id: int,
    encuesta_id: int,
    anger: CustomerAngerResult,
    telefono: str = "",
) -> None:
    """Alerta opcional vía Telegram cuando requires_urgent_human_attention."""
    if not anger.requires_urgent_human_attention:
        return
    if os.getenv("CUSTOMER_ANGER_TELEGRAM_ALERTS", "true").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return

    try:
        from services.queue_service import enqueue_telegram_alert

        phone = (telefono or "?")[:20]
        msg = (
            f"[AUSARTA][IRA CLIENTE] Empresa {empresa_id} encuesta {encuesta_id} "
            f"tel={phone} score={anger.customer_anger_score}/10 — requiere atención humana urgente."
        )
        await enqueue_telegram_alert(msg)
    except Exception as exc:
        logger.warning("No se pudo encolar alerta de ira: %s", exc)
