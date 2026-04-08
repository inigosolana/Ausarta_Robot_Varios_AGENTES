"""
worker.py — ARQ Worker para el motor de campañas Ausarta.

PROCESO SEPARADO a la API FastAPI. Consume tareas de Redis de forma
persistente: si el servidor se reinicia, los jobs pendientes sobreviven.

Arranque:
    arq backend.worker.WorkerSettings

    (desde /backend, con REDIS_URL definido en el entorno)

Fases:
    Fase 1 (este archivo): Configuración base + stubs de tareas.
    Fase 2: Implementación real de campaign_scheduler_task y dispatch_lead_drip_task.
    Fase 3: Eliminación del asyncio.create_task() en api.py; endpoints usan arq.enqueue_job().

Flujo de datos:
    [API FastAPI]  →  enqueue_job("dispatch_lead_drip_task", lead_id, campaign_id)  →  [Redis]
    [ARQ Worker]   ←  consume job  →  _dispatch_single_lead_drip(lead, campaign)
    
    Cron cada 30s: campaign_scheduler_task escanea campañas activas y
    encola dispatch_lead_drip_task por cada empresa sin lock activo.
"""
import os
import logging
from typing import Any

from arq import cron
from arq.connections import ArqRedis, RedisSettings

logger = logging.getLogger("arq-worker")


# ──────────────────────────────────────────────
# Configuración Redis
# Reutiliza REDIS_URL del mismo .env que la API.
# ──────────────────────────────────────────────

def _build_redis_settings() -> RedisSettings:
    """
    Parsea REDIS_URL y construye RedisSettings para ARQ.

    Formato soportado: redis://[:password@]host[:port][/db]
    Ejemplo:           redis://redis:6379/0
                       redis://:mysecret@redis:6379/1
    """
    url = os.getenv("REDIS_URL", "redis://redis:6379/0")

    try:
        # ARQ >= 0.25 expone from_dsn directamente
        return RedisSettings.from_dsn(url)
    except AttributeError:
        # Fallback manual para versiones más antiguas
        import re
        m = re.match(r"redis://(?::([^@]*)@)?([^:/]+)(?::(\d+))?(?:/(\d+))?", url)
        if m:
            password = m.group(1) or None
            host     = m.group(2) or "redis"
            port     = int(m.group(3) or 6379)
            database = int(m.group(4) or 0)
        else:
            logger.warning(f"No se pudo parsear REDIS_URL='{url}'. Usando redis://redis:6379/0")
            host, port, database, password = "redis", 6379, 0, None
        return RedisSettings(host=host, port=port, database=database, password=password)


# ──────────────────────────────────────────────
# Lifecycle del Worker
# ──────────────────────────────────────────────

async def startup(ctx: dict[str, Any]) -> None:
    """
    Inicialización del worker: conexiones compartidas entre tareas.

    ctx es el diccionario compartido que ARQ inyecta en cada tarea.
    Aquí inicializamos Supabase, LiveKit, y Redis (para locks) una
    sola vez y los reutilizamos en todas las tareas del worker.

    Fase 2 completará este bloque. Por ahora verifica conectividad.
    """
    logger.info("🚀 [ARQ Worker] Arrancando...")

    # Verificar que Redis responde (la conexión ARQ ya está establecida en ctx['redis'])
    redis: ArqRedis = ctx["redis"]
    await redis.set("ausarta:arq:worker_started", "1", ex=300)
    logger.info("✅ [ARQ Worker] Redis OK.")

    # Fase 2 añadirá aquí:
    # from services.supabase_service import supabase
    # from services.livekit_service import lkapi
    # ctx['supabase'] = supabase
    # ctx['lkapi']    = lkapi
    logger.info("✅ [ARQ Worker] Listo para consumir tareas.")


async def shutdown(ctx: dict[str, Any]) -> None:
    """Limpieza al apagar el worker."""
    logger.info("🌙 [ARQ Worker] Apagando...")


# ──────────────────────────────────────────────
# Tareas (stubs — Fase 2 implementa el cuerpo)
# ──────────────────────────────────────────────

async def campaign_scheduler_task(ctx: dict[str, Any]) -> None:
    """
    Cron: se ejecuta cada 30s (segundos :00 y :30 de cada minuto).

    Reemplaza campaign_scheduler_loop() de campaigns.py.
    Escanea campañas activas en Supabase y encola dispatch_lead_drip_task
    por cada empresa sin lock activo, usando ctx['redis'].enqueue_job().

    Ventaja frente al while-True en memoria: si el worker se reinicia,
    el siguiente ciclo de 30s retoma el trabajo sin pérdida de estado.
    """
    logger.info("[ARQ] campaign_scheduler_task — stub Fase 1 (sin implementación aún)")
    # Fase 2 reemplazará este cuerpo con la lógica de campaign_scheduler_loop()


async def dispatch_lead_drip_task(ctx: dict[str, Any], lead_id: int, campaign_id: int) -> None:
    """
    Tarea persistida en Redis: ejecuta UNA llamada SIP para un lead.

    Reemplaza asyncio.create_task(_dispatch_single_lead_drip()) del scheduler.
    Al ser un job ARQ, su ejecución sobrevive reinicios del proceso API.

    Argumentos recibidos del job:
        lead_id:     ID del lead en campaign_leads.
        campaign_id: ID de la campaña padre.
    """
    logger.info(
        f"[ARQ] dispatch_lead_drip_task — lead={lead_id} camp={campaign_id} "
        f"(stub Fase 1, sin implementación aún)"
    )
    # Fase 2 cargará lead + campaign de Supabase y llamará a:
    # from routers.campaigns import _dispatch_single_lead_drip
    # await _dispatch_single_lead_drip(lead, campaign)


# ──────────────────────────────────────────────
# WorkerSettings — clase leída por `arq` CLI
# ──────────────────────────────────────────────

class WorkerSettings:
    """
    Configuración del worker ARQ. La clase es leída por el CLI de arq:

        arq backend.worker.WorkerSettings

    Variables de entorno reconocidas:
        REDIS_URL              — URL de Redis (default: redis://redis:6379/0)
        ARQ_MAX_JOBS           — Máx. tareas concurrentes (default: 10)
        ARQ_JOB_TIMEOUT        — Timeout por tarea en segundos (default: 660)
                                 Debe ser > max_call_time (300s) + max_cooldown (180s) + margen
    """

    # Conexión Redis
    redis_settings: RedisSettings = _build_redis_settings()

    # Lifecycle
    on_startup  = startup
    on_shutdown = shutdown

    # Tareas disponibles para enqueue_job()
    functions = [
        dispatch_lead_drip_task,
    ]

    # Cron: scanner de campañas cada 30 segundos
    # second={0, 30} → dispara en el segundo :00 y :30 de cada minuto
    cron_jobs = [
        cron(
            campaign_scheduler_task,
            second={0, 30},
            unique=True,   # no encolar si la instancia anterior no ha terminado
            timeout=25,    # debe terminar antes del siguiente tick (30s)
        )
    ]

    # Concurrencia: 1 tarea de goteo activa por empresa (el lock Redis lo garantiza),
    # pero múltiples empresas pueden tener su goteo simultáneo.
    max_jobs: int = int(os.getenv("ARQ_MAX_JOBS", "10"))

    # Timeout: llamada SIP (max 300s) + cooldown (max 180s) + margen de seguridad
    job_timeout: int = int(os.getenv("ARQ_JOB_TIMEOUT", "660"))

    # Conservar resultado de cada job 5 minutos (útil para debugging)
    keep_result: int = 300

    # No reintentar automáticamente: el drip gestiona sus propios reintentos
    # vía _apply_retry_after_failure(). Evita llamadas duplicadas.
    max_tries: int = 1

    # Health check en Redis cada 60s
    health_check_interval: int = 60
    health_check_key: str      = "ausarta:arq:health"
