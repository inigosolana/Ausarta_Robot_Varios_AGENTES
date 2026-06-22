"""Registro de webhooks entrantes para auditoría y replay."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any

from services.supabase_service import sb_query, supabase

logger = logging.getLogger("api-backend")


async def log_webhook_event(
    *,
    source: str,
    event_type: str,
    payload: dict[str, Any] | list[Any] | None,
    status: str = "pending",
) -> str | None:
    """Persiste evento webhook. Devuelve id UUID o None si BD no disponible."""
    if not supabase:
        return None
    try:
        body = payload if isinstance(payload, (dict, list)) else {}
        row = {
            "source": source[:64],
            "event_type": event_type[:128],
            "payload": body,
            "status": status[:32],
            "attempts": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        def _insert():
            return supabase.table("webhook_events").insert(row).execute()

        res = await sb_query(_insert)
        if res.data:
            return str(res.data[0].get("id"))
    except Exception as exc:
        logger.warning("[webhook_events] No se pudo registrar evento %s/%s: %s", source, event_type, exc)
    return None


async def mark_webhook_event_processed(event_id: str, *, failed: bool = False) -> None:
    if not supabase or not event_id:
        return
    status = "failed" if failed else "processed"
    now = datetime.now(timezone.utc).isoformat()

    def _update():
        return (
            supabase.table("webhook_events")
            .update({"status": status, "processed_at": now})
            .eq("id", event_id)
            .execute()
        )

    try:
        await sb_query(_update)
    except Exception as exc:
        logger.debug("[webhook_events] mark processed %s: %s", event_id, exc)


async def increment_webhook_attempts(event_id: str) -> None:
    if not supabase or not event_id:
        return

    def _bump():
        cur = (
            supabase.table("webhook_events")
            .select("attempts")
            .eq("id", event_id)
            .limit(1)
            .execute()
        )
        attempts = int((cur.data or [{}])[0].get("attempts") or 0) + 1
        return (
            supabase.table("webhook_events")
            .update({"attempts": attempts, "status": "pending"})
            .eq("id", event_id)
            .execute()
        )

    try:
        await sb_query(_bump)
    except Exception as exc:
        logger.debug("[webhook_events] bump attempts %s: %s", event_id, exc)
