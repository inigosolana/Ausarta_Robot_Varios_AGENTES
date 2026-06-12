"""
usage.py — Endpoint de consumo por empresa ("Mi consumo").

GET /api/usage/mi-consumo
  → Devuelve el consumo del mes en curso para la empresa del usuario logueado.
  → Filtrado automáticamente por empresa_id del JWT (no se puede pedir otra empresa).
  → Superadmin puede pasar ?empresa_id= para ver cualquier empresa.

Campos devueltos:
  total_calls     — total de llamadas registradas en encuestas
  completed_calls — llamadas completadas
  total_minutes   — minutos de voz (seconds_used / 60)
  total_tokens    — tokens LLM estimados (seconds_used * 15 tokens/s)
  estimated_cost  — coste estimado en EUR (0.0 si no hay config de precio)
  per_model_stats — desglose por modelo LLM
  period          — mes en formato "YYYY-MM"
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse

from services.auth import CurrentUser, get_current_user
from services.supabase_service import supabase, sb_query

logger = logging.getLogger("api-backend")

router = APIRouter(prefix="/api/usage", tags=["usage"])

# Coste estimado por minuto de voz en EUR (configurable)
_COST_PER_MINUTE_EUR = 0.02  # 2 céntimos por minuto (valor referencial, ajustar por empresa)


@router.get("/mi-consumo")
async def mi_consumo(
    empresa_id: Optional[int] = Query(None, description="Superadmin solo: empresa_id a consultar"),
    year_month: Optional[str] = Query(None, description="Periodo YYYY-MM (default: mes actual)"),
    current_user: CurrentUser = Depends(get_current_user),
) -> Any:
    """
    Devuelve el consumo del mes para la empresa del usuario autenticado.

    - Usuarios normales y admins solo ven su propia empresa.
    - Superadmins pueden pasar `?empresa_id=N` para ver cualquier empresa.
    - `?year_month=2026-05` permite consultar meses anteriores.
    """
    # ── Resolución del empresa_id efectivo ───────────────────────────────
    if current_user.role == "superadmin" and empresa_id is not None:
        effective_empresa_id: Optional[int] = empresa_id
    else:
        effective_empresa_id = current_user.empresa_id

    if not effective_empresa_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "No se puede determinar la empresa. Asegúrese de estar autenticado."}
        )

    # ── Rango del periodo ─────────────────────────────────────────────────
    now = datetime.now(tz=timezone.utc)
    if year_month:
        try:
            year, month = map(int, year_month.split("-"))
        except Exception:
            return JSONResponse(status_code=400, content={"detail": "Formato de year_month inválido. Use YYYY-MM."})
    else:
        year, month = now.year, now.month

    period_str = f"{year:04d}-{month:02d}"
    start_date = f"{year:04d}-{month:02d}-01"
    if month == 12:
        end_date = f"{year + 1:04d}-01-01"
    else:
        end_date = f"{year:04d}-{month + 1:02d}-01"

    if not supabase:
        return {"empresa_id": effective_empresa_id, "period": period_str, "total_calls": 0,
                "completed_calls": 0, "total_minutes": 0.0, "total_tokens": 0,
                "estimated_cost_eur": 0.0, "per_model_stats": [], "error": "DB no disponible"}

    try:
        res = await sb_query(
            lambda eid=effective_empresa_id, sd=start_date, ed=end_date: supabase.table("encuestas")
            .select("llm_model, seconds_used, completada, status")
            .eq("empresa_id", eid)
            .gte("fecha", sd)
            .lt("fecha", ed)
            .execute()
        )

        rows = res.data if res and res.data else []

        total_calls = len(rows)
        completed_calls = sum(1 for r in rows if r.get("completada") == 1)
        total_seconds = sum(r.get("seconds_used") or 0 for r in rows)

        model_stats: dict[str, dict] = {}
        for r in rows:
            model = r.get("llm_model") or "Standard"
            if model not in model_stats:
                model_stats[model] = {"llm_model": model, "calls": 0, "tokens": 0, "seconds": 0}
            model_stats[model]["calls"] += 1
            secs = r.get("seconds_used") or 0
            model_stats[model]["seconds"] += secs
            model_stats[model]["tokens"] += secs * 15  # ~15 tokens/segundo estimado

        total_tokens = sum(s["tokens"] for s in model_stats.values())
        total_minutes = round(total_seconds / 60, 2)
        estimated_cost = round(total_minutes * _COST_PER_MINUTE_EUR, 4)

        return {
            "empresa_id": effective_empresa_id,
            "period": period_str,
            "total_calls": total_calls,
            "completed_calls": completed_calls,
            "total_minutes": total_minutes,
            "total_tokens": total_tokens,
            "estimated_cost_eur": estimated_cost,
            "cost_note": "Coste estimado basado en duración. Revise facturación real de proveedores.",
            "per_model_stats": list(model_stats.values()),
        }

    except Exception as exc:
        logger.warning("[mi_consumo] Error empresa %s: %s", effective_empresa_id, exc)
        return JSONResponse(status_code=500, content={"detail": "Error calculando consumo"})
