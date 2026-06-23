from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("arq-worker")

def _agent_bridge_url() -> str:
    url = (
        os.getenv("BRIDGE_SERVER_URL_INTERNAL")
        or os.getenv("BRIDGE_SERVER_URL")
        or "http://backend:8001"
    )
    return url.strip().rstrip("/")


async def agent_post_guardar_encuesta(ctx: dict[str, Any], payload: dict) -> None:
    """POST /guardar-encuesta desde el worker ARQ."""
    import aiohttp
    from services.supabase_service import supabase, sb_query

    url = f"{_agent_bridge_url()}/guardar-encuesta"
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json=payload, timeout=15) as resp:
            logger.info("[agent_bridge] guardar-encuesta HTTP %s encuesta=%s", resp.status, payload.get("id_encuesta"))

    if not supabase:
        return

    encuesta_id = int(payload.get("id_encuesta") or 0)
    if not encuesta_id:
        return

    try:
        encuesta_res = await sb_query(
            lambda: supabase.table("encuestas")
            .select("id, empresa_id, campaign_id, status, retry_count, scheduled_at")
            .eq("id", encuesta_id)
            .limit(1)
            .execute()
        )
        if not encuesta_res.data:
            return
        encuesta = encuesta_res.data[0]
        empresa_id = int(encuesta.get("empresa_id") or 0)
        status = (encuesta.get("status") or payload.get("status") or "").strip().lower()

        if status == "failed":
            from tasks.transcription_processor import _schedule_failed_survey_retry

            await _schedule_failed_survey_retry(encuesta)

        if empresa_id:
            now = datetime.now(timezone.utc)
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            empresa_res = await sb_query(
                lambda: supabase.table("empresas")
                .select("id, nombre, max_llamadas_mes")
                .eq("id", empresa_id)
                .limit(1)
                .execute()
            )
            if empresa_res.data:
                empresa = empresa_res.data[0]
                max_llamadas_mes = int(empresa.get("max_llamadas_mes") or 0)
                if max_llamadas_mes > 0:
                    count_res = await sb_query(
                        lambda: supabase.table("encuestas")
                        .select("id", count="exact")
                        .eq("empresa_id", empresa_id)
                        .gte("fecha", month_start.isoformat())
                        .execute()
                    )
                    consumed = int(count_res.count or 0)
                    from services.tenant_quota_alerts import maybe_alert_call_quota_threshold

                    await maybe_alert_call_quota_threshold(
                        empresa_id,
                        consumed=consumed,
                        max_calls=max_llamadas_mes,
                        empresa_nombre=empresa.get("nombre"),
                        redis=ctx.get("redis"),
                    )

            streak_key = f"ausarta:failed_streak:{empresa_id}"
            if status == "failed":
                failed_streak = await ctx["redis"].incr(streak_key)
                await ctx["redis"].expire(streak_key, 86400)
                if failed_streak >= 3:
                    await ctx["redis"].enqueue_job(
                        "send_telegram_alert_task",
                        f"[AUSARTA] La empresa {empresa_id} acumula {failed_streak} llamadas consecutivas con status='failed'.",
                    )
            elif status:
                await ctx["redis"].delete(streak_key)
    except Exception as exc:
        logger.warning("⚠️ [worker] Post-procesado de guardar_encuesta falló: %s", exc)


async def agent_post_colgar(ctx: dict[str, Any], room_name: str) -> None:
    """POST /colgar desde el worker ARQ."""
    import aiohttp

    url = f"{_agent_bridge_url()}/colgar"
    async with aiohttp.ClientSession() as sess:
        async with sess.post(url, json={"nombre_sala": room_name}, timeout=10) as resp:
            logger.info("[agent_bridge] colgar HTTP %s room=%s", resp.status, room_name)


async def agent_post_transfer(ctx: dict[str, Any], payload: dict) -> None:
    """Persiste estado transferred y llama a /api/calls/transfer."""
    import aiohttp

    base = _agent_bridge_url()
    guardar_payload = payload.get("guardar_payload") or {}
    transfer_payload = payload.get("transfer_payload") or {}

    async with aiohttp.ClientSession() as sess:
        if guardar_payload:
            async with sess.post(
                f"{base}/guardar-encuesta",
                json=guardar_payload,
                timeout=10,
            ) as resp:
                logger.info("[agent_bridge] transfer→guardar HTTP %s", resp.status)

        if transfer_payload:
            async with sess.post(
                f"{base}/api/calls/transfer",
                json=transfer_payload,
                timeout=20,
            ) as resp:
                body = await resp.text()
                logger.info(
                    "[agent_bridge] transfer HTTP %s room=%s body=%s",
                    resp.status,
                    transfer_payload.get("room_name"),
                    body[:200],
                )
