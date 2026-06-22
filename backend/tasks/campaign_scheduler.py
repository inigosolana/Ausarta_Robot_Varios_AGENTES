from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any

from arq.connections import ArqRedis
from utils.call_schedule import is_call_allowed

logger = logging.getLogger("arq-worker")

async def campaign_scheduler_task(ctx: dict[str, Any]) -> None:
    """
    Cron: se ejecuta cada 30s (segundos :00 y :30 de cada minuto).

    Reemplaza campaign_scheduler_loop() de campaigns.py.
    Escanea campañas activas en Supabase y encola dispatch_lead_drip_task
    por cada empresa sin lock activo, usando ctx['redis'].enqueue_job().

    Ventaja frente al while-True en memoria: si el worker se reinicia,
    el siguiente ciclo de 30s retoma el trabajo sin pérdida de estado.
    """
    from services.supabase_service import supabase
    from routers.campaigns import (
        _is_empresa_locked, _acquire_empresa_lock, _check_campaign_completion,
        _get_active_call_count, _get_active_call_count_for_empresa,
    )

    if not supabase:
        logger.warning("[ARQ] Supabase no disponible en scheduler")
        return

    redis: ArqRedis = ctx["redis"]
    now_iso = datetime.utcnow().isoformat()
    max_concurrent_calls = int(os.getenv("MAX_CONCURRENT_CALLS", "10"))

    try:
        campaigns_res = await asyncio.to_thread(
            supabase.table("campaigns").select("*").in_("status", ["active", "running"]).execute
        )
        campaigns = campaigns_res.data or []
    except Exception as e:
        logger.error(f"[ARQ] Error leyendo campañas activas: {e}")
        return

    if campaigns:
        logger.info(f"[ARQ] Scheduler: {len(campaigns)} campañas activas.")

    active_count = await _get_active_call_count()
    if active_count >= max_concurrent_calls:
        logger.warning(f"[ARQ] Límite global de canales SIP alcanzado ({max_concurrent_calls}).")
        return

    # Rate limit por empresa: máximo de llamadas concurrentes por tenant
    from services.empresa_limits_service import get_empresa_max_concurrent_calls

    for camp in campaigns:
        campaign_id = camp["id"]
        empresa_id = camp.get("empresa_id") or 0
        max_calls_per_empresa = await get_empresa_max_concurrent_calls(int(empresa_id or 0))
        campaign_type = (camp.get("type") or "").strip().lower()
        use_orchestrator = bool(camp.get("use_orchestrator"))

        # FIX A — evitar doble despacho con orquestador.
        if campaign_type == "orchestrated" or use_orchestrator:
            logger.debug(
                f"[ARQ] Scheduler salta campaña {campaign_id} "
                f"(type={campaign_type}, use_orchestrator={use_orchestrator})"
            )
            continue

        cancel_key = f"ausarta:campaign:cancel:{campaign_id}"
        try:
            if await redis.exists(cancel_key):
                continue
        except Exception:
            pass

        if await _is_empresa_locked(empresa_id):
            continue

        # FIX G — cumplimiento horario por campaña.
        now_utc = datetime.now(timezone.utc)
        allowed_hours = (
            int(camp.get("call_start_hour") or 9),
            int(camp.get("call_end_hour") or 21),
        )
        tz_name = camp.get("call_timezone") or "Europe/Madrid"
        forbidden_days = set(camp.get("forbidden_weekdays") or {6})
        can_call, reason = is_call_allowed(
            now=now_utc,
            timezone_str=tz_name,
            allowed_hours=allowed_hours,
            forbidden_weekdays=forbidden_days,
        )
        if not can_call:
            logger.info(
                f"[ARQ] Scheduler salta campaña {campaign_id} por horario: {reason}"
            )
            continue

        # Per-empresa concurrent call rate limit
        empresa_active = await _get_active_call_count_for_empresa(empresa_id)
        if empresa_active >= max_calls_per_empresa:
            logger.info(
                f"[ARQ] Rate limit empresa {empresa_id}: "
                f"{empresa_active}/{max_calls_per_empresa} llamadas activas. "
                f"Skipping campaña {campaign_id}."
            )
            continue

        try:
            leads_res = await asyncio.to_thread(
                supabase.table("campaign_leads")
                .select("*")
                .eq("campaign_id", campaign_id)
                .in_("status", ["pending", "pending_retry"])
                .or_(f"next_retry_at.is.null,next_retry_at.lte.{now_iso}")
                .order("next_retry_at", desc=False, nullsfirst=True)
                .limit(1)
                .execute
            )
        except Exception as fetch_err:
            logger.error(f"[ARQ] Error leyendo leads campaña {campaign_id}: {fetch_err}")
            continue

        if not leads_res.data:
            is_done = await _check_campaign_completion(campaign_id)
            if is_done:
                try:
                    await asyncio.to_thread(
                        supabase.table("campaigns").update({"status": "completed"}).eq("id", campaign_id).execute
                    )
                    logger.info(f"[ARQ] Campaña {campaign_id} completada.")
                except Exception as done_err:
                    logger.error(f"[ARQ] Error marcando campaña {campaign_id} como completada: {done_err}")
            continue

        lead = leads_res.data[0]

        lock_token = await _acquire_empresa_lock(empresa_id)
        if not lock_token:
            continue

        job_id = f"dispatch:{campaign_id}:{lead['id']}"
        await redis.enqueue_job(
            "dispatch_lead_drip_task",
            lead["id"],
            campaign_id,
            lock_token,
            _job_id=job_id,
        )

