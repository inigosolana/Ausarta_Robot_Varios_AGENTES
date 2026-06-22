"""Alertas Telegram cuando el saldo de un proveedor cae bajo umbral."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger("api-backend")


async def maybe_alert_low_balances(providers: list[dict[str, Any]]) -> None:
    if os.getenv("API_CREDITS_TELEGRAM_ALERTS", "false").strip().lower() not in (
        "1",
        "true",
        "yes",
    ):
        return

    from services.queue_service import enqueue_telegram_alert

    for provider in providers:
        if not provider.get("supported") or not provider.get("key_configured"):
            continue
        balance = provider.get("balance")
        if balance is None:
            continue
        try:
            balance_f = float(balance)
        except (TypeError, ValueError):
            continue

        name = str(provider.get("provider") or "provider").upper().replace(" ", "_")
        threshold_raw = os.getenv(f"{name}_ALERT_THRESHOLD", os.getenv("API_CREDITS_ALERT_THRESHOLD", "10"))
        try:
            threshold = float(threshold_raw)
        except (TypeError, ValueError):
            threshold = 10.0

        if balance_f >= threshold:
            continue

        unit = provider.get("balance_unit") or ""
        msg = (
            f"[AUSARTA][API Credits] {provider.get('provider')} saldo bajo: "
            f"{balance_f} {unit} (umbral {threshold})"
        )
        try:
            await enqueue_telegram_alert(msg)
        except Exception as exc:
            logger.warning("No se pudo encolar alerta api-credits: %s", exc)
