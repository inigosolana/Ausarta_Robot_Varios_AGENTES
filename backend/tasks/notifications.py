"""
notifications.py — Tareas ARQ para notificaciones y webhooks externos.

Agrupa: Telegram, n8n webhooks, alertas de sistema, webhooks Yeastar.
Extraído de worker.py para mantener WorkerSettings limpio.
"""
from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger("arq-worker")


async def send_telegram_alert_task(ctx: dict[str, Any], message: str) -> None:
    """Tarea ARQ para enviar alertas Telegram sin bloquear el flujo principal."""
    from services.telegram_service import send_telegram_alert

    _ = ctx
    await send_telegram_alert(message)


async def process_n8n_webhook(ctx: dict[str, Any], payload: dict) -> None:
    """
    Tarea ARQ: POST persistente a un webhook de n8n (p.ej. classify-agent).
    Reemplaza asyncio.create_task() en routers para no perder peticiones al
    reiniciar la API.
    """
    import aiohttp

    url = (payload or {}).get("url")
    body = (payload or {}).get("body") or {}
    if not url:
        logger.warning("[ARQ] process_n8n_webhook: payload sin URL, ignorando")
        return

    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.post(url, json=body, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                if resp.status >= 400:
                    text = await resp.text()
                    logger.warning(
                        "[ARQ] Webhook n8n respondió HTTP %s para %s: %s",
                        resp.status, url, text[:200],
                    )
                else:
                    logger.info("[ARQ] Webhook n8n OK (%s): %s", resp.status, url)
    except Exception as e:
        logger.warning("[ARQ] Webhook n8n falló para %s: %s", url, e)


async def process_system_alert(ctx: dict[str, Any], message: str, details: dict | None = None) -> None:
    """
    Registra una alerta de sistema en logs y, si la tabla existe, en Supabase.
    """
    logger.error("🚨 ALERTA DEL SISTEMA: %s | Detalles: %s", message, json.dumps(details or {}))
    from services.supabase_service import supabase, sb_query

    if not supabase:
        return
    try:
        await sb_query(
            lambda: supabase.table("system_logs").insert({
                "level": "error",
                "message": message,
                "metadata": details or {},
            }).execute()
        )
    except Exception:
        pass  # Silenciamos si la tabla no existe en este proyecto


async def process_yeastar_webhook(ctx: dict[str, Any], payload: dict) -> None:
    """
    Procesa webhooks de Yeastar desde ARQ para que sobrevivan a reinicios HTTP.
    """
    from services.yeastar_webhook_service import process_yeastar_webhook_payload

    _ = ctx
    await process_yeastar_webhook_payload(payload)
