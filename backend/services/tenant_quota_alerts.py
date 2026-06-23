"""Alertas Telegram al acercarse o superar cuotas de tenant (llamadas y gasto EUR)."""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("api-backend")

_ALERTS_ENABLED = os.getenv("TENANT_QUOTA_TELEGRAM_ALERTS", "true").strip().lower() in (
    "1",
    "true",
    "yes",
)
_DEDUP_TTL_SECONDS = 35 * 24 * 3600


def _current_period() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


async def _enqueue_deduped_alert(redis: Any | None, dedup_key: str, message: str) -> None:
    if not _ALERTS_ENABLED:
        return
    try:
        if redis is not None:
            inserted = await redis.set(dedup_key, "1", nx=True, ex=_DEDUP_TTL_SECONDS)
            if not inserted:
                return
        from services.queue_service import enqueue_telegram_alert

        await enqueue_telegram_alert(message)
    except Exception as exc:
        logger.warning("No se pudo encolar alerta de cuota tenant: %s", exc)


async def maybe_alert_call_quota_threshold(
    empresa_id: int,
    *,
    consumed: int,
    max_calls: int,
    empresa_nombre: str | None = None,
    redis: Any | None = None,
) -> None:
    """Alerta al 80% y al 100% de max_llamadas_mes (una vez por umbral y mes)."""
    if max_calls <= 0:
        return

    period = _current_period()
    name = empresa_nombre or f"empresa {empresa_id}"
    ratio = consumed / max_calls

    if ratio >= 1.0:
        key = f"ausarta:quota_alert:{empresa_id}:calls:100:{period}"
        msg = (
            f"[AUSARTA] {name} ha alcanzado el 100% de su cuota mensual de llamadas "
            f"({consumed}/{max_calls}). Nuevas llamadas pueden bloquearse."
        )
        await _enqueue_deduped_alert(redis, key, msg)
        return

    if ratio >= 0.8:
        key = f"ausarta:quota_alert:{empresa_id}:calls:80:{period}"
        msg = (
            f"[AUSARTA] {name} ha superado el 80% de su cuota mensual de llamadas "
            f"({consumed}/{max_calls})."
        )
        await _enqueue_deduped_alert(redis, key, msg)


async def maybe_alert_spend_quota_threshold(
    empresa_id: int,
    *,
    spent_eur: float,
    limit_eur: float,
    empresa_nombre: str | None = None,
    period: str | None = None,
    redis: Any | None = None,
) -> None:
    """Alerta al 80% y al 100% del tope monthly_spend_limit_eur."""
    if limit_eur <= 0:
        return

    current_period = period or _current_period()
    name = empresa_nombre or f"empresa {empresa_id}"
    ratio = spent_eur / limit_eur

    if ratio >= 1.0:
        key = f"ausarta:quota_alert:{empresa_id}:spend:100:{current_period}"
        msg = (
            f"[AUSARTA] {name} ha alcanzado el 100% de su tope de gasto mensual "
            f"(€{spent_eur:.2f}/€{limit_eur:.2f}). Nuevas llamadas bloqueadas."
        )
        await _enqueue_deduped_alert(redis, key, msg)
        return

    if ratio >= 0.8:
        key = f"ausarta:quota_alert:{empresa_id}:spend:80:{current_period}"
        msg = (
            f"[AUSARTA] {name} ha superado el 80% de su tope de gasto mensual "
            f"(€{spent_eur:.2f}/€{limit_eur:.2f})."
        )
        await _enqueue_deduped_alert(redis, key, msg)
