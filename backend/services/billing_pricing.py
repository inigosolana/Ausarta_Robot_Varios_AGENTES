"""Tarifas unitarias y cálculo de costes para unit economics (FinOps)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from services.billing_service import TenantUsageSnapshot


@dataclass(frozen=True)
class BillingRates:
    llm_input_eur_per_1m: float
    llm_output_eur_per_1m: float
    tts_eur_per_1k_chars: float
    stt_eur_per_minute: float
    telephony_eur_per_minute: float

    @classmethod
    def from_env(cls) -> "BillingRates":
        return cls(
            llm_input_eur_per_1m=float(os.getenv("BILLING_LLM_INPUT_EUR_PER_1M", "0.59")),
            llm_output_eur_per_1m=float(os.getenv("BILLING_LLM_OUTPUT_EUR_PER_1M", "0.79")),
            tts_eur_per_1k_chars=float(os.getenv("BILLING_TTS_EUR_PER_1K_CHARS", "0.015")),
            stt_eur_per_minute=float(os.getenv("BILLING_STT_EUR_PER_MINUTE", "0.0043")),
            telephony_eur_per_minute=float(os.getenv("BILLING_TELEPHONY_EUR_PER_MINUTE", "0.02")),
        )


def _round_eur(value: float) -> float:
    return round(max(0.0, value), 4)


def calculate_llm_cost_eur(
    prompt_tokens: int,
    completion_tokens: int,
    *,
    rates: BillingRates | None = None,
) -> float:
    r = rates or BillingRates.from_env()
    input_cost = (prompt_tokens / 1_000_000) * r.llm_input_eur_per_1m
    output_cost = (completion_tokens / 1_000_000) * r.llm_output_eur_per_1m
    return _round_eur(input_cost + output_cost)


def calculate_tts_cost_eur(chars: int, *, rates: BillingRates | None = None) -> float:
    r = rates or BillingRates.from_env()
    return _round_eur((chars / 1000) * r.tts_eur_per_1k_chars)


def calculate_stt_cost_eur(audio_seconds: int, *, rates: BillingRates | None = None) -> float:
    """STT estimado a partir de segundos de audio (duración de llamada)."""
    r = rates or BillingRates.from_env()
    return _round_eur((audio_seconds / 60) * r.stt_eur_per_minute)


def calculate_telephony_cost_eur(seconds: int, *, rates: BillingRates | None = None) -> float:
    r = rates or BillingRates.from_env()
    return _round_eur((seconds / 60) * r.telephony_eur_per_minute)


def calculate_usage_cost_breakdown(
    usage: TenantUsageSnapshot,
    *,
    rates: BillingRates | None = None,
) -> dict[str, Any]:
    """
    Devuelve costes EUR desglosados: LLM, Voz (TTS+STT) y Telefonía.
    """
    r = rates or BillingRates.from_env()

    llm_cost = calculate_llm_cost_eur(
        usage.llm_prompt_tokens,
        usage.llm_completion_tokens,
        rates=r,
    )
    tts_cost = calculate_tts_cost_eur(usage.tts_characters, rates=r)
    stt_cost = calculate_stt_cost_eur(usage.telephony_seconds, rates=r)
    voice_cost = _round_eur(tts_cost + stt_cost)
    telephony_cost = calculate_telephony_cost_eur(usage.telephony_seconds, rates=r)
    total_cost = _round_eur(llm_cost + voice_cost + telephony_cost)

    llm_by_model: list[dict[str, Any]] = []
    for model, counts in sorted(usage.llm_by_model.items()):
        prompt = int(counts.get("prompt_tokens", 0) or 0)
        completion = int(counts.get("completion_tokens", 0) or 0)
        llm_by_model.append(
            {
                "model": model,
                "prompt_tokens": prompt,
                "completion_tokens": completion,
                "total_tokens": prompt + completion,
                "cost_eur": calculate_llm_cost_eur(prompt, completion, rates=r),
            }
        )

    tts_by_provider: list[dict[str, Any]] = []
    for provider, chars in sorted(usage.tts_by_provider.items()):
        tts_by_provider.append(
            {
                "provider": provider,
                "characters": int(chars),
                "cost_eur": calculate_tts_cost_eur(int(chars), rates=r),
            }
        )

    return {
        "currency": "EUR",
        "llm_eur": llm_cost,
        "voice_eur": voice_cost,
        "voice_tts_eur": tts_cost,
        "voice_stt_eur": stt_cost,
        "telephony_eur": telephony_cost,
        "total_eur": total_cost,
        "breakdown": [
            {"category": "llm", "label": "LLM (Groq/OpenAI)", "amount_eur": llm_cost},
            {"category": "voice", "label": "Voz (TTS/STT)", "amount_eur": voice_cost},
            {"category": "telephony", "label": "Telefonía (SIP/trunk)", "amount_eur": telephony_cost},
        ],
        "llm_by_model": llm_by_model,
        "tts_by_provider": tts_by_provider,
        "rates": {
            "llm_input_eur_per_1m": r.llm_input_eur_per_1m,
            "llm_output_eur_per_1m": r.llm_output_eur_per_1m,
            "tts_eur_per_1k_chars": r.tts_eur_per_1k_chars,
            "stt_eur_per_minute": r.stt_eur_per_minute,
            "telephony_eur_per_minute": r.telephony_eur_per_minute,
        },
    }
