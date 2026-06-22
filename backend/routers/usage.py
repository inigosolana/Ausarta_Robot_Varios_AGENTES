"""
usage.py — Endpoints de consumo y unit economics por empresa (dashboard B2B).

GET /api/usage/mi-consumo
  → Consumo del mes con costes desglosados (LLM, Voz, Telefonía).

GET /api/usage/unit-economics
  → Alias enfocado en FinOps con el mismo payload de costes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.auth import CurrentUser, get_current_user
from services.billing_pricing import calculate_usage_cost_breakdown
from services.billing_service import TenantUsageSnapshot, get_billing_service
from services.supabase_service import supabase, sb_query

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/usage", tags=["usage"])


def _resolve_effective_empresa_id(
    current_user: CurrentUser,
    empresa_id: Optional[int],
) -> tuple[int | None, JSONResponse | None]:
    if current_user.role == "superadmin" and empresa_id is not None:
        effective = empresa_id
    else:
        effective = current_user.empresa_id

    if not effective:
        return None, JSONResponse(
            status_code=400,
            content={"detail": "No se puede determinar la empresa. Asegúrese de estar autenticado."},
        )
    return effective, None


def _parse_period(year_month: Optional[str]) -> tuple[str, int, int, str, str, JSONResponse | None]:
    now = datetime.now(tz=timezone.utc)
    if year_month:
        try:
            year, month = map(int, year_month.split("-"))
        except Exception:
            return "", 0, 0, "", "", JSONResponse(
                status_code=400,
                content={"detail": "Formato de year_month inválido. Use YYYY-MM."},
            )
    else:
        year, month = now.year, now.month

    period_str = f"{year:04d}-{month:02d}"
    start_date = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1:04d}-01-01"
    else:
        end_date = f"{year:04d}-{month + 1:02d}-01"
    return period_str, year, month, start_date, end_date, None


async def _fetch_call_stats(
    empresa_id: int,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    if not supabase:
        return {
            "total_calls": 0,
            "completed_calls": 0,
            "total_seconds": 0,
            "per_model_stats": [],
        }

    res = await sb_query(
        lambda: supabase.table("encuestas")
        .select("llm_model, seconds_used, completada, status")
        .eq("empresa_id", empresa_id)
        .gte("fecha", start_date)
        .lt("fecha", end_date)
        .execute()
    )
    rows = res.data if res and res.data else []

    total_calls = len(rows)
    completed_calls = sum(1 for r in rows if r.get("completada") == 1)
    total_seconds = sum(r.get("seconds_used") or 0 for r in rows)

    model_stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        model = row.get("llm_model") or "Standard"
        if model not in model_stats:
            model_stats[model] = {
                "llm_model": model,
                "calls": 0,
                "tokens": 0,
                "seconds": 0,
            }
        model_stats[model]["calls"] += 1
        secs = row.get("seconds_used") or 0
        model_stats[model]["seconds"] += secs
        model_stats[model]["tokens"] += secs * 15

    return {
        "total_calls": total_calls,
        "completed_calls": completed_calls,
        "total_seconds": total_seconds,
        "per_model_stats": list(model_stats.values()),
    }


def _usage_payload(
    *,
    empresa_id: int,
    period: str,
    usage: TenantUsageSnapshot,
    call_stats: dict[str, Any],
) -> dict[str, Any]:
    costs = calculate_usage_cost_breakdown(usage)
    total_minutes = round(usage.telephony_seconds / 60, 2)
    legacy_tokens = usage.llm_total_tokens or sum(
        s.get("tokens", 0) for s in call_stats.get("per_model_stats", [])
    )

    return {
        "empresa_id": empresa_id,
        "period": period,
        "usage": {
            "llm_prompt_tokens": usage.llm_prompt_tokens,
            "llm_completion_tokens": usage.llm_completion_tokens,
            "llm_total_tokens": usage.llm_total_tokens,
            "tts_characters": usage.tts_characters,
            "telephony_seconds": usage.telephony_seconds,
            "telephony_minutes": total_minutes,
        },
        "costs_eur": {
            "llm": costs["llm_eur"],
            "voice": costs["voice_eur"],
            "voice_tts": costs["voice_tts_eur"],
            "voice_stt": costs["voice_stt_eur"],
            "telephony": costs["telephony_eur"],
            "total": costs["total_eur"],
        },
        "costs_breakdown": costs["breakdown"],
        "llm_by_model": costs["llm_by_model"],
        "tts_by_provider": costs["tts_by_provider"],
        "rates": costs["rates"],
        "currency": costs["currency"],
        # Campos legacy para UsageView.tsx
        "total_calls": call_stats["total_calls"],
        "completed_calls": call_stats["completed_calls"],
        "total_minutes": total_minutes,
        "total_tokens": legacy_tokens,
        "estimated_cost_eur": costs["total_eur"],
        "per_model_stats": call_stats["per_model_stats"],
        "cost_note": (
            "Costes calculados desde métricas reales de billing (LLM, TTS/STT, telefonía). "
            "Tarifas configurables vía BILLING_* en .env."
        ),
    }


async def _build_unit_economics_response(
    empresa_id: int,
    period: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    billing = get_billing_service()
    usage = await billing.get_tenant_usage_summary(empresa_id, period=period)
    call_stats = await _fetch_call_stats(empresa_id, start_date, end_date)
    return _usage_payload(
        empresa_id=empresa_id,
        period=period,
        usage=usage,
        call_stats=call_stats,
    )


@router.get("/mi-consumo")
async def mi_consumo(
    empresa_id: Optional[int] = Query(None, description="Superadmin solo: empresa_id a consultar"),
    year_month: Optional[str] = Query(None, description="Periodo YYYY-MM (default: mes actual)"),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """Consumo y costes del mes para la empresa del usuario autenticado."""
    effective_empresa_id, error = _resolve_effective_empresa_id(current_user, empresa_id)
    if error:
        return error

    period_str, _year, _month, start_date, end_date, period_error = _parse_period(year_month)
    if period_error:
        return period_error

    try:
        return await _build_unit_economics_response(
            effective_empresa_id,
            period_str,
            start_date,
            end_date,
        )
    except Exception as exc:
        logger.warning("[mi_consumo] Error empresa %s: %s", effective_empresa_id, exc)
        return JSONResponse(status_code=500, content={"detail": "Error calculando consumo"})


@router.get("/unit-economics")
async def unit_economics(
    empresa_id: Optional[int] = Query(None, description="Superadmin solo: empresa_id a consultar"),
    year_month: Optional[str] = Query(None, description="Periodo YYYY-MM (default: mes actual)"),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """
    Dashboard B2B FinOps: consumo acumulado del mes con coste desglosado
    (LLM, Voz TTS/STT, Telefonía).
    """
    return await mi_consumo(
        empresa_id=empresa_id,
        year_month=year_month,
        current_user=current_user,
    )
