"""
worker.py — ARQ Worker para el motor de campañas Ausarta.

PROCESO SEPARADO a la API FastAPI. Consume tareas de Redis de forma
persistente: si el servidor se reinicia, los jobs pendientes sobreviven.

Arranque (imagen Docker, WORKDIR /app = raíz del backend):
    arq worker.WorkerSettings

Este archivo solo contiene WorkerSettings, startup/shutdown y los imports
de las tasks. La lógica de negocio vive en backend/tasks/.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

from arq import cron
from arq.connections import ArqRedis, RedisSettings

logger = logging.getLogger("arq-worker")

# ── Tasks ──────────────────────────────────────────────────────────────────────
from tasks.campaign_scheduler import campaign_scheduler_task
from tasks.lead_dispatcher import dispatch_lead_drip_task
from tasks.call_actions import (
    agent_post_colgar,
    agent_post_guardar_encuesta,
    agent_post_transfer,
)
from tasks.transcription_processor import process_transcription_ai
from tasks.transfer_briefing import generate_transfer_briefing_task
from tasks.campaign_orchestrator import campaign_orchestrator, process_campaign_empresa
from tasks.notifications import (
    send_telegram_alert_task,
    process_n8n_webhook,
    process_system_alert,
    process_yeastar_webhook,
)


# ──────────────────────────────────────────────────────────────────────────────
# Redis
# ──────────────────────────────────────────────────────────────────────────────

def _build_redis_settings() -> RedisSettings:
    """
    Parsea REDIS_URL y construye RedisSettings para ARQ.

    Formato soportado: redis://[:password@]host[:port][/db]
    Ejemplo:           redis://redis:6379/0
                       redis://:mysecret@redis:6379/1
    """
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")
    try:
        return RedisSettings.from_dsn(url)
    except AttributeError:
        m = re.match(r"redis://(?::([^@]*)@)?([^:/]+)(?::(\d+))?(?:/(\d+))?", url)
        if m:
            password = m.group(1) or None
            host = m.group(2) or "redis"
            port = int(m.group(3) or 6379)
            database = int(m.group(4) or 0)
        else:
            logger.warning("No se pudo parsear REDIS_URL='%s'. Usando redis://redis:6379/0", url)
            host, port, database, password = "redis", 6379, 0, None
        return RedisSettings(host=host, port=port, database=database, password=password)


# ──────────────────────────────────────────────────────────────────────────────
# Lifecycle
# ──────────────────────────────────────────────────────────────────────────────

async def startup(ctx: dict[str, Any]) -> None:
    """Inicialización del worker: conexiones compartidas entre tareas."""
    logger.info("🚀 [ARQ Worker] Arrancando...")
    redis: ArqRedis = ctx["redis"]
    await redis.set("ausarta:arq:worker_started", "1", ex=300)
    logger.info("✅ [ARQ Worker] Redis OK. Listo para consumir tareas.")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Limpieza al apagar el worker."""
    logger.info("🌙 [ARQ Worker] Apagando...")


# ──────────────────────────────────────────────────────────────────────────────
# WorkerSettings — clase leída por `arq` CLI
# ──────────────────────────────────────────────────────────────────────────────

class WorkerSettings:
    """
    Configuración del worker ARQ leída por el CLI de arq:

        arq worker.WorkerSettings

    Variables de entorno reconocidas:
        REDIS_URL          — URL de Redis (default: redis://redis:6379/0)
        ARQ_MAX_JOBS       — Máx. tareas concurrentes (default: 10)
        ARQ_JOB_TIMEOUT    — Timeout por tarea en segundos (default: 660)
    """

    redis_settings: RedisSettings = _build_redis_settings()
    on_startup = startup
    on_shutdown = shutdown

    functions = [
        # Campañas
        campaign_scheduler_task,
        dispatch_lead_drip_task,
        campaign_orchestrator,
        process_campaign_empresa,
        # Llamadas
        agent_post_guardar_encuesta,
        agent_post_colgar,
        agent_post_transfer,
        # IA
        process_transcription_ai,
        generate_transfer_briefing_task,
        # Notificaciones / webhooks
        process_n8n_webhook,
        process_system_alert,
        send_telegram_alert_task,
        process_yeastar_webhook,
    ]

    cron_jobs = [
        cron(
            campaign_scheduler_task,
            second={0, 30},
            unique=True,
            timeout=25,
        ),
        cron(
            campaign_orchestrator,
            minute=None,   # cada minuto
            unique=True,
            timeout=55,
        ),
    ]

    max_jobs: int = int(os.getenv("ARQ_MAX_JOBS", "10"))
    job_timeout: int = int(os.getenv("ARQ_JOB_TIMEOUT", "660"))
    keep_result: int = 300
    max_tries: int = 1
    health_check_interval: int = 60
    health_check_key: str = "ausarta:arq:health"
