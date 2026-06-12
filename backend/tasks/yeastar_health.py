"""
yeastar_health.py — Cron ARQ: health-check Yeastar por empresa.

Detecta PBX caídos, pausa campañas automáticamente y avisa por Telegram.
Reanuda campañas cuando el PBX vuelve a responder.
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("arq-worker")


async def check_yeastar_health_task(ctx: dict[str, Any]) -> None:
    """
    Tarea cron: comprueba salud del Yeastar de cada empresa activa.

    Frecuencia configurada en worker.py vía YEASTAR_HEALTH_CHECK_INTERVAL_SECONDS.
    """
    _ = ctx
    from services.yeastar_health_service import run_yeastar_health_checks

    try:
        summary = await run_yeastar_health_checks()
        logger.info(
            "[yeastar_health] Ciclo completado: %s empresa(s) comprobadas",
            summary.get("checked", 0),
        )
    except Exception as exc:
        logger.error("[yeastar_health] Error en ciclo de health-check: %s", exc)
