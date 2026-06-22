"""
Cortafuegos financiero: bloquea nuevas llamadas si el tenant supera su tope mensual.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import HTTPException

from services.billing_pricing import calculate_usage_cost_breakdown
from services.billing_service import get_billing_service, _utc_period
from services.supabase_service import sb_query, supabase

logger = logging.getLogger("billing")

_SPEND_LIMITS_ENABLED = os.getenv("BILLING_SPEND_LIMITS_ENABLED", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)


@dataclass(frozen=True)
class TenantSpendStatus:
    empresa_id: int
    period: str
    limit_eur: float | None
    spent_eur: float
    remaining_eur: float | None
    limit_exceeded: bool
    limits_enabled: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "empresa_id": self.empresa_id,
            "period": self.period,
            "limit_eur": self.limit_eur,
            "spent_eur": self.spent_eur,
            "remaining_eur": self.remaining_eur,
            "limit_exceeded": self.limit_exceeded,
            "limits_enabled": self.limits_enabled,
        }


class TenantSpendingLimitExceeded(Exception):
    """Lanzada en workers cuando no aplica HTTPException."""

    def __init__(self, message: str, status: TenantSpendStatus) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


async def _load_monthly_spend_limit(empresa_id: int) -> float | None:
    if not supabase:
        return None

    result = await sb_query(
        lambda: supabase.table("empresas")
        .select("monthly_spend_limit_eur")
        .eq("id", empresa_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        return None

    raw = result.data[0].get("monthly_spend_limit_eur")
    if raw is None:
        return None

    limit = Decimal(str(raw))
    if limit <= 0:
        return None
    return float(limit)


async def evaluate_tenant_spending(
    empresa_id: int,
    *,
    period: str | None = None,
) -> TenantSpendStatus:
    """Calcula gasto acumulado del mes vs límite configurado en empresas."""
    current_period = period or _utc_period()

    if empresa_id <= 0 or not _SPEND_LIMITS_ENABLED:
        return TenantSpendStatus(
            empresa_id=empresa_id,
            period=current_period,
            limit_eur=None,
            spent_eur=0.0,
            remaining_eur=None,
            limit_exceeded=False,
            limits_enabled=False,
        )

    limit_eur = await _load_monthly_spend_limit(empresa_id)
    billing = get_billing_service()
    usage = await billing.get_tenant_usage_summary(empresa_id, period=current_period)
    costs = calculate_usage_cost_breakdown(usage)
    spent_eur = float(costs["total_eur"])

    if limit_eur is None:
        return TenantSpendStatus(
            empresa_id=empresa_id,
            period=current_period,
            limit_eur=None,
            spent_eur=spent_eur,
            remaining_eur=None,
            limit_exceeded=False,
            limits_enabled=True,
        )

    spent_dec = Decimal(str(spent_eur))
    limit_dec = Decimal(str(limit_eur))
    remaining = float(max(limit_dec - spent_dec, Decimal("0")))
    exceeded = spent_dec >= limit_dec

    return TenantSpendStatus(
        empresa_id=empresa_id,
        period=current_period,
        limit_eur=limit_eur,
        spent_eur=spent_eur,
        remaining_eur=remaining,
        limit_exceeded=exceeded,
        limits_enabled=True,
    )


def _build_limit_message(status: TenantSpendStatus) -> str:
    return (
        f"Límite de gasto mensual alcanzado para la empresa {status.empresa_id}. "
        f"Periodo {status.period}: gastado €{status.spent_eur:.4f} "
        f"de €{status.limit_eur:.4f} permitidos. "
        "Contacta con Ausarta para ampliar tu plan o espera al próximo ciclo."
    )


async def enforce_tenant_spending_limit(
    empresa_id: int,
    *,
    period: str | None = None,
    raise_http: bool = True,
) -> TenantSpendStatus:
    """
    Verifica el tope de gasto. Si se supera:
      - raise_http=True  → HTTPException 402 (API FastAPI)
      - raise_http=False → TenantSpendingLimitExceeded (workers ARQ)
    """
    status = await evaluate_tenant_spending(empresa_id, period=period)
    if not status.limit_exceeded:
        return status

    message = _build_limit_message(status)
    logger.warning(
        "[billing-limit] Empresa %s bloqueada: spent=%.4f limit=%.4f period=%s",
        empresa_id,
        status.spent_eur,
        status.limit_eur or 0,
        status.period,
    )

    if raise_http:
        raise HTTPException(
            status_code=402,
            detail={
                "message": message,
                **status.to_dict(),
            },
        )

    raise TenantSpendingLimitExceeded(message, status)
