"""Clasificador híbrido de baja latencia: regex (Tier 0) + Groq 8B (Tier 1)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Final, Literal, Sequence

import aiohttp

from agents.agent_common import _normalize_message_text
from agents.semantic_routes import (
    DEFAULT_TRANSFER_PHRASES,
    NEGATIVE_TRANSFER_CUES,
    TRANSFER_HUMAN_REGEXES,
)
from config import settings

logger = logging.getLogger("semantic-router")

SemanticIntent = Literal["transfer_human", "continue"]
SemanticTier = Literal["tier0", "tier1", "fallback"]

_GROQ_CHAT_URL: Final[str] = "https://api.groq.com/openai/v1/chat/completions"

_CLASSIFIER_SYSTEM_PROMPT: Final[str] = (
    "Clasificador de intención en llamadas telefónicas B2B. "
    "Responde SOLO JSON válido sin markdown.\n"
    'Schema: {"intent":"transfer_human"|"continue","confidence":0.0-1.0}\n'
    "transfer_human = el cliente pide EXPLÍCITAMENTE hablar con una persona humana, "
    "operador o agente real.\n"
    "continue = cualquier otro caso, incluido rechazo a hablar con humano."
)


@dataclass(frozen=True, slots=True)
class SemanticRouteResult:
    intent: SemanticIntent
    confidence: float
    tier: SemanticTier
    latency_ms: float


def _has_negative_transfer_cue(text: str) -> bool:
    lowered = text.lower()
    return any(cue in lowered for cue in NEGATIVE_TRANSFER_CUES)


def _match_tier0(text: str, extra_phrases: Sequence[str] = ()) -> bool:
    if _has_negative_transfer_cue(text):
        return False
    normalized = " ".join(text.lower().split())
    for pattern in TRANSFER_HUMAN_REGEXES:
        if pattern.search(normalized):
            return True
    for phrase in (*DEFAULT_TRANSFER_PHRASES, *extra_phrases):
        cleaned = " ".join(phrase.strip().lower().split())
        if cleaned and cleaned in normalized:
            return True
    return False


def _parse_classifier_json(raw: str) -> SemanticRouteResult | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    intent_raw = str(payload.get("intent") or "").strip().lower()
    if intent_raw not in ("transfer_human", "continue"):
        return None
    try:
        confidence = float(payload.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    confidence = max(0.0, min(confidence, 1.0))
    intent: SemanticIntent = "transfer_human" if intent_raw == "transfer_human" else "continue"
    return SemanticRouteResult(intent=intent, confidence=confidence, tier="tier1", latency_ms=0.0)


class SemanticRouterService:
    """Router semántico async con timeout estricto en Tier 1."""

    def __init__(
        self,
        *,
        custom_phrases: Sequence[str] | None = None,
        model: str | None = None,
        timeout_ms: int | None = None,
        min_confidence: float | None = None,
        tier0_only: bool | None = None,
    ) -> None:
        self._custom_phrases: tuple[str, ...] = tuple(custom_phrases or ())
        self._model = model or settings.semantic_router_model
        self._timeout_s = (timeout_ms or settings.semantic_router_timeout_ms) / 1000.0
        self._min_confidence = (
            min_confidence
            if min_confidence is not None
            else settings.semantic_router_min_confidence
        )
        self._tier0_only = (
            tier0_only if tier0_only is not None else settings.semantic_router_tier0_only
        )
        self._groq_api_key = os.getenv("GROQ_API_KEY", "").strip()

    async def classify(self, user_text: str) -> SemanticRouteResult:
        started = time.perf_counter()
        text = _normalize_message_text(user_text)
        if not text:
            return self._result("continue", 0.0, "fallback", started)

        if _match_tier0(text, self._custom_phrases):
            return self._result("transfer_human", 1.0, "tier0", started)

        if self._tier0_only or not self._groq_api_key:
            return self._result("continue", 0.0, "fallback", started)

        tier1 = await self._classify_with_groq(text)
        if tier1 is None:
            return self._result("continue", 0.0, "fallback", started)

        latency_ms = (time.perf_counter() - started) * 1000.0
        return SemanticRouteResult(
            intent=tier1.intent,
            confidence=tier1.confidence,
            tier="tier1",
            latency_ms=latency_ms,
        )

    def is_actionable(self, result: SemanticRouteResult) -> bool:
        return (
            result.intent == "transfer_human"
            and result.confidence >= self._min_confidence
        )

    async def _classify_with_groq(self, text: str) -> SemanticRouteResult | None:
        from services.provider_circuit_service import groq_llm_breaker
        from utils.tracing import traced_span

        breaker = await groq_llm_breaker()
        if await breaker.is_open():
            logger.info("Groq classifier omitido: circuit %s abierto", breaker.name)
            return None

        payload = {
            "model": self._model,
            "temperature": 0.0,
            "max_tokens": 32,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _CLASSIFIER_SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
        }
        headers = {
            "Authorization": f"Bearer {self._groq_api_key}",
            "Content-Type": "application/json",
        }
        try:
            timeout = aiohttp.ClientTimeout(total=self._timeout_s)
            async with traced_span(
                "llm.groq.classify",
                {"llm.model": self._model, "llm.provider": "groq"},
                kind="client",
            ):
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(_GROQ_CHAT_URL, headers=headers, json=payload) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            logger.warning(
                                "Groq classifier HTTP %s: %s",
                                resp.status,
                                body[:200],
                            )
                            await breaker.record_failure(RuntimeError(f"HTTP {resp.status}"))
                            return None
                        data = await resp.json()
        except asyncio.TimeoutError as exc:
            logger.debug("Groq classifier timeout (%.0f ms)", self._timeout_s * 1000)
            await breaker.record_failure(exc, extreme=True)
            return None
        except aiohttp.ClientError as exc:
            logger.warning("Groq classifier network error: %s", exc)
            await breaker.record_failure(exc)
            return None
        except Exception as exc:
            logger.warning("Groq classifier unexpected error: %s", exc)
            await breaker.record_failure(exc)
            return None

        await breaker.record_success()

        try:
            raw = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError):
            return None

        parsed = _parse_classifier_json(str(raw or ""))
        if parsed is None:
            logger.debug("Groq classifier JSON inválido: %s", str(raw)[:120])
        return parsed

    @staticmethod
    def _result(
        intent: SemanticIntent,
        confidence: float,
        tier: SemanticTier,
        started: float,
    ) -> SemanticRouteResult:
        return SemanticRouteResult(
            intent=intent,
            confidence=confidence,
            tier=tier,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )
